# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Opt-in live endpoint smoke evidence for AGILAB data connectors."""

from __future__ import annotations

from functools import partial
import json
import os
from pathlib import Path, PurePath
import socket
import sqlite3
from typing import Any, Mapping, Sequence
from urllib import request
from urllib.parse import urlparse
import ipaddress

from agilab.data_connectors.data_connector_cloud import object_storage_target
from agilab.data_connectors.data_connector_facility import (
    DEFAULT_CONNECTORS_RELATIVE_PATH,
    build_data_connector_facility,
    load_connector_catalog,
)
from agilab.data_connectors.data_connector_search import search_index_provider, search_index_target
from agilab.security.llm_endpoint_policy import (
    _PinnedHTTPConnection,
    _PinnedHTTPSConnection,
)
from agilab.security.secret_uri import credential_env_name, is_secret_uri


SCHEMA = "agilab.data_connector_live_endpoint_smoke.v1"
DEFAULT_RUN_ID = "data-connector-live-endpoint-smoke-proof"
CREATED_AT = "2026-04-25T00:00:34Z"
UPDATED_AT = "2026-04-25T00:00:34Z"
LOCAL_HTTP_OPT_IN_ENV = "AGILAB_CONNECTOR_LIVE_SMOKE_ALLOW_LOCAL_HTTP"
BLOCKED_LINK_LOCAL_METADATA_IPS = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("fd00:ec2::254"),
}


def _connector_target(connector: Mapping[str, Any]) -> str:
    kind = str(connector.get("kind", "") or "")
    if kind == "sql":
        return str(connector.get("uri", "") or "")
    if kind == "opensearch":
        return search_index_target(connector)
    if kind == "object_storage":
        return object_storage_target(connector)
    return ""


def _credential_env_name(auth_ref: str) -> str:
    return credential_env_name(auth_ref)


def _credential_status(connector: Mapping[str, Any]) -> tuple[str, str]:
    auth_ref = str(connector.get("auth_ref", "") or "")
    env_name = _credential_env_name(auth_ref)
    if env_name:
        return ("available", env_name) if os.getenv(env_name) else ("missing", env_name)
    if is_secret_uri(auth_ref):
        return "operator_runtime_required", ""
    if not auth_ref:
        return "none_required", ""
    return "invalid", ""


def _sqlite_target(uri: str) -> str:
    if uri == "sqlite:///:memory:":
        return ":memory:"
    if uri.startswith("sqlite:///"):
        return uri.removeprefix("sqlite:///")
    return ""


def _sqlite_read_only_uri(path: PurePath) -> str:
    """Encode absolute file paths with SQLite's required empty URI authority."""
    parsed = urlparse(path.as_uri())
    filename = f"//{parsed.netloc}{parsed.path}" if parsed.netloc else parsed.path
    return f"file://{filename}?mode=ro"


def _probe_sqlite(uri: str) -> tuple[str, str]:
    target = _sqlite_target(uri)
    if not target:
        return (
            "skipped_unsupported_driver",
            "only sqlite:/// targets execute in public smoke",
        )
    # File probes must not create a database when an operator mistypes its path.
    # as_uri escapes filename characters such as ?, # and % before adding mode.
    database = (
        target
        if target == ":memory:"
        else _sqlite_read_only_uri(Path(target).resolve())
    )
    with sqlite3.connect(database, uri=target != ":memory:") as connection:
        connection.execute("select 1").fetchone()
    return "healthy", "sqlite connectivity check passed"


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(url)
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port


def _local_http_allowed() -> bool:
    return os.getenv(LOCAL_HTTP_OPT_IN_ENV, "").strip().lower() in {"1", "true", "yes"}


def _address_is_blocked(address: ipaddress._BaseAddress, *, allow_local_http: bool) -> str:
    if address in BLOCKED_LINK_LOCAL_METADATA_IPS:
        return "metadata-service target is blocked"
    if address.is_loopback:
        return "" if allow_local_http else "loopback targets require local emulator opt-in"
    if address.is_private or address.is_link_local or address.is_unspecified or address.is_multicast:
        return "non-public IP targets are blocked"
    return ""


def _resolve_host_addresses(host: str) -> list[ipaddress._BaseAddress]:
    addresses: list[ipaddress._BaseAddress] = []
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, OSError, UnicodeError):
        return addresses
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        try:
            addresses.append(ipaddress.ip_address(sockaddr[0]))
        except ValueError:
            continue
    return addresses


def _allowed_host_addresses(
    host: str, *, allow_local_http: bool
) -> tuple[tuple[str, ...], str]:
    if not host:
        return (), "missing host"
    lowered = host.lower().strip("[]")
    if (
        lowered == "localhost" or lowered.endswith(".localhost")
    ) and not allow_local_http:
        return (), "localhost targets require local emulator opt-in"
    try:
        addresses = [ipaddress.ip_address(lowered)]
    except ValueError:
        addresses = _resolve_host_addresses(lowered)
    if not addresses:
        return (), "hostname did not resolve to any address"
    for address in addresses:
        reason = _address_is_blocked(address, allow_local_http=allow_local_http)
        if reason:
            return (), reason
    return tuple(str(address) for address in addresses), ""


def _host_is_blocked(host: str, *, allow_local_http: bool) -> str:
    return _allowed_host_addresses(host, allow_local_http=allow_local_http)[1]


def _live_probe_addresses(
    url: str, *, allow_local_http: bool = False
) -> tuple[tuple[str, ...], str]:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme != "https" and not (scheme == "http" and allow_local_http):
        return (
            (),
            "live endpoint smoke requires https unless local HTTP emulator mode is enabled",
        )
    return _allowed_host_addresses(
        parsed.hostname or "", allow_local_http=allow_local_http
    )


def _validate_live_probe_url(
    url: str, *, allow_local_http: bool = False
) -> tuple[bool, str]:
    addresses, reason = _live_probe_addresses(url, allow_local_http=allow_local_http)
    return bool(addresses), reason or "live endpoint target passed URL safety policy"


class _SameOriginRedirectHandler(request.HTTPRedirectHandler):
    def __init__(self, *, allow_local_http: bool = False) -> None:
        super().__init__()
        self._allow_local_http = allow_local_http

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        if _origin(req.full_url) != _origin(newurl):
            raise RuntimeError("live endpoint smoke redirect changed origin")
        ok, reason = _validate_live_probe_url(
            newurl,
            allow_local_http=self._allow_local_http,
        )
        if not ok:
            raise RuntimeError(f"live endpoint smoke redirect target refused: {reason}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _DirectProbeProxyHandler(request.ProxyHandler):
    def proxy_open(self, req, proxy, type):  # type: ignore[override]
        # Honor the standard no_proxy bypass, but never delegate target DNS or
        # bearer credentials to a proxy. Pinning requires a direct connection.
        if req.host and request.proxy_bypass(req.host):
            return None
        raise RuntimeError(
            "live endpoint smoke requires a direct connection; configured proxies "
            "are unsupported because they bypass destination address validation"
        )


class _PinnedProbeHTTPHandler(request.HTTPHandler):
    def __init__(self, *, allow_local_http: bool) -> None:
        super().__init__()
        self._allow_local_http = allow_local_http
        self.network_probe_started = False

    def http_open(self, req):  # type: ignore[override]
        addresses, reason = _live_probe_addresses(
            req.full_url, allow_local_http=self._allow_local_http
        )
        if not addresses:
            raise RuntimeError(
                f"live endpoint smoke connection target refused: {reason}"
            )
        connection = partial(_PinnedHTTPConnection, pinned_addresses=addresses)
        self.network_probe_started = True
        return self.do_open(connection, req)


class _PinnedProbeHTTPSHandler(request.HTTPSHandler):
    def __init__(self, *, allow_local_http: bool) -> None:
        super().__init__()
        self._allow_local_http = allow_local_http
        self.network_probe_started = False

    def https_open(self, req):  # type: ignore[override]
        addresses, reason = _live_probe_addresses(
            req.full_url, allow_local_http=self._allow_local_http
        )
        if not addresses:
            raise RuntimeError(
                f"live endpoint smoke connection target refused: {reason}"
            )
        connection = partial(_PinnedHTTPSConnection, pinned_addresses=addresses)
        self.network_probe_started = True
        return self.do_open(connection, req, context=self._context)


def _live_probe_opener(*, allow_local_http: bool = False):
    """Pin direct connections; keep original Host/TLS identity and safe redirects."""
    return request.build_opener(
        _DirectProbeProxyHandler(),
        _SameOriginRedirectHandler(allow_local_http=allow_local_http),
        _PinnedProbeHTTPHandler(allow_local_http=allow_local_http),
        _PinnedProbeHTTPSHandler(allow_local_http=allow_local_http),
    )


def _probe_opensearch(
    connector: Mapping[str, Any], token: str
) -> tuple[str, str, bool]:
    opener = None
    try:
        url = _connector_target(connector)
        allow_local_http = _local_http_allowed()
        ok, reason = _validate_live_probe_url(url, allow_local_http=allow_local_http)
        if not ok:
            return "skipped", f"unsafe live endpoint target: {reason}", False
        provider = search_index_provider(
            str(connector.get("provider", "") or "opensearch")
        )
        label = provider.label if provider is not None else "Search index"
        req = request.Request(
            url,
            method="HEAD",
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "agilab-live-smoke/1",
            },
        )
        opener = _live_probe_opener(allow_local_http=allow_local_http)
        with opener.open(req, timeout=10) as response:
            status = getattr(response, "status", 200)
        return (
            ("healthy", f"{label} HEAD returned {status}")
            if int(status) < 500
            else ("unhealthy", f"{label} HEAD returned {status}")
        ) + (True,)
    except Exception as exc:
        # A redirect can be refused after a request; initial DNS/proxy refusals
        # happen before the transport starts. Preserve that distinction in proof.
        handlers = getattr(opener, "handlers", None)
        network_probe = opener is not None and (
            handlers is None  # Preserve the existing custom-opener seam.
            or any(
                getattr(handler, "network_probe_started", False) for handler in handlers
            )
        )
        return ("unhealthy" if network_probe else "skipped"), str(exc), network_probe


def _smoke_row(
    connector: Mapping[str, Any],
    *,
    execute: bool,
    allowed_connector_ids: set[str],
) -> dict[str, Any]:
    connector_id = str(connector.get("id", "") or "")
    kind = str(connector.get("kind", "") or "")
    credential_status, credential_env_name = _credential_status(connector)
    target = _connector_target(connector)
    base = {
        "connector_id": connector_id,
        "kind": kind,
        "label": str(connector.get("label", "") or ""),
        "target": target,
        "credential_status": credential_status,
        "credential_env_name": credential_env_name,
        "operator_opt_in_required": True,
        "allowed_by_operator": connector_id in allowed_connector_ids,
        "network_probe_executed": False,
    }
    if not execute:
        return {
            **base,
            "status": "not_executed",
            "execution_status": "not_executed_opt_in_required",
            "message": "live endpoint smoke was not requested",
        }
    if connector_id not in allowed_connector_ids:
        return {
            **base,
            "status": "skipped",
            "execution_status": "skipped_not_allowed",
            "message": "connector was not included in the operator allow-list",
        }
    if credential_status == "missing":
        return {
            **base,
            "status": "skipped",
            "execution_status": "skipped_missing_credentials",
            "message": f"missing credential environment variable: {credential_env_name}",
        }
    if credential_status == "operator_runtime_required":
        return {
            **base,
            "status": "skipped",
            "execution_status": "skipped_operator_runtime_secret",
            "message": "secret URI requires an operator-provided runtime resolver",
        }
    if credential_status == "invalid":
        return {
            **base,
            "status": "skipped",
            "execution_status": "skipped_invalid_credentials",
            "message": "credential reference is invalid",
        }
    try:
        if kind == "sql":
            status, message = _probe_sqlite(str(connector.get("uri", "") or ""))
            network_probe = False
        elif kind == "opensearch" and credential_env_name:
            status, message, network_probe = _probe_opensearch(
                connector,
                str(os.environ[credential_env_name]),
            )
        else:
            status, message = "skipped", f"live smoke not implemented for {kind}"
            network_probe = False
    except Exception as exc:
        status, message = "unhealthy", str(exc)
        network_probe = kind == "opensearch"
    return {
        **base,
        "status": status,
        "execution_status": "executed" if status in {"healthy", "unhealthy"} else status,
        "message": message,
        "network_probe_executed": network_probe,
    }


def build_data_connector_live_endpoint_smoke(
    catalog: Mapping[str, Any],
    *,
    source_path: Path | str,
    execute: bool = False,
    allowed_connector_ids: Sequence[str] = (),
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    facility_state = build_data_connector_facility(catalog, source_path=source_path)
    connectors = [
        connector
        for connector in facility_state.get("connectors", [])
        if isinstance(connector, dict)
    ]
    allowed = set(allowed_connector_ids)
    catalog_valid = facility_state.get("run_status") == "validated"
    issues = []
    if not catalog_valid:
        issues.append(
            {
                "level": "error",
                "location": "connector_catalog",
                "message": "connector catalog must validate before live endpoint smoke",
            }
        )
    rows = [
        _smoke_row(
            connector, execute=execute and catalog_valid, allowed_connector_ids=allowed
        )
        for connector in connectors
    ]
    if execute and not catalog_valid:
        for row in rows:
            row.update(
                status="skipped",
                execution_status="skipped_invalid_catalog",
                message="connector catalog must validate before live endpoint smoke",
            )
    status_values = sorted({str(row.get("status", "")) for row in rows})
    executed_rows = [row for row in rows if row.get("execution_status") == "executed"]
    network_probe_count = sum(1 for row in rows if row.get("network_probe_executed"))
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "run_status": "smoke_complete" if execute and not issues else "planned",
        "execution_mode": (
            "live_endpoint_smoke_opt_in" if execute else "live_endpoint_smoke_plan_only"
        ),
        "source": {
            "catalog_path": str(source_path),
            "facility_schema": facility_state.get("schema", ""),
            "facility_run_status": facility_state.get("run_status", ""),
        },
        "summary": {
            "connector_count": len(connectors),
            "planned_endpoint_count": len(rows),
            "executed_endpoint_count": len(executed_rows),
            "healthy_count": sum(1 for row in rows if row.get("status") == "healthy"),
            "unhealthy_count": sum(
                1 for row in rows if row.get("status") == "unhealthy"
            ),
            "skipped_count": sum(1 for row in rows if row.get("status") == "skipped"),
            "missing_credential_count": sum(
                1 for row in rows if row.get("credential_status") == "missing"
            ),
            "network_probe_count": network_probe_count,
            "command_execution_count": 0,
            "status_values": status_values,
            "connector_ids": sorted(str(row.get("connector_id", "")) for row in rows),
        },
        "endpoint_smokes": rows,
        "issues": issues,
        "provenance": {
            "executes_network_probe": network_probe_count > 0,
            "requires_operator_opt_in": True,
            "credential_values_logged": False,
            "safe_for_public_evidence": not execute or network_probe_count == 0,
        },
    }


def write_data_connector_live_endpoint_smoke(path: Path, state: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_data_connector_live_endpoint_smoke(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def persist_data_connector_live_endpoint_smoke(
    *,
    repo_root: Path,
    output_path: Path,
    catalog_path: Path | None = None,
    execute: bool = False,
    allowed_connector_ids: Sequence[str] = (),
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    catalog_path = catalog_path or (repo_root / DEFAULT_CONNECTORS_RELATIVE_PATH)
    if not catalog_path.is_absolute():
        catalog_path = repo_root / catalog_path
    catalog = load_connector_catalog(catalog_path)
    state = build_data_connector_live_endpoint_smoke(
        catalog,
        source_path=catalog_path,
        execute=execute,
        allowed_connector_ids=allowed_connector_ids,
    )
    path = write_data_connector_live_endpoint_smoke(output_path, state)
    reloaded = load_data_connector_live_endpoint_smoke(path)
    return {
        "ok": state == reloaded and state.get("run_status") in {"planned", "smoke_complete"},
        "path": str(path),
        "catalog_path": str(catalog_path),
        "state": state,
        "reloaded_state": reloaded,
        "round_trip_ok": state == reloaded,
    }
