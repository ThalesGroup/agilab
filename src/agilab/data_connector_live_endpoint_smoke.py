# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Opt-in live endpoint smoke evidence for AGILAB data connectors."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence
from urllib import request

from agilab.data_connector_cloud import object_storage_target
from agilab.data_connector_facility import (
    DEFAULT_CONNECTORS_RELATIVE_PATH,
    build_data_connector_facility,
    load_connector_catalog,
)
from agilab.data_connector_search import search_index_provider, search_index_target
from agilab.secret_uri import credential_env_name, is_secret_uri


SCHEMA = "agilab.data_connector_live_endpoint_smoke.v1"
DEFAULT_RUN_ID = "data-connector-live-endpoint-smoke-proof"
CREATED_AT = "2026-04-25T00:00:34Z"
UPDATED_AT = "2026-04-25T00:00:34Z"


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


def _probe_sqlite(uri: str) -> tuple[str, str]:
    target = _sqlite_target(uri)
    if not target:
        return "skipped_unsupported_driver", "only sqlite:/// targets execute in public smoke"
    with sqlite3.connect(target) as connection:
        connection.execute("select 1").fetchone()
    return "healthy", "sqlite connectivity check passed"


def _probe_opensearch(connector: Mapping[str, Any], token: str) -> tuple[str, str]:
    url = _connector_target(connector)
    provider = search_index_provider(str(connector.get("provider", "") or "opensearch"))
    label = provider.label if provider is not None else "Search index"
    req = request.Request(
        url,
        method="HEAD",
        headers={"Authorization": f"Bearer {token}", "User-Agent": "agilab-live-smoke/1"},
    )
    with request.urlopen(req, timeout=10) as response:
        status = getattr(response, "status", 200)
    return (
        ("healthy", f"{label} HEAD returned {status}")
        if int(status) < 500
        else ("unhealthy", f"{label} HEAD returned {status}")
    )


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
            status, message = _probe_opensearch(
                connector,
                str(os.environ[credential_env_name]),
            )
            network_probe = True
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
    rows = [
        _smoke_row(connector, execute=execute, allowed_connector_ids=allowed)
        for connector in connectors
    ]
    issues = []
    if facility_state.get("run_status") != "validated":
        issues.append(
            {
                "level": "error",
                "location": "connector_catalog",
                "message": "connector catalog must validate before live endpoint smoke",
            }
        )
    status_values = sorted({str(row.get("status", "")) for row in rows})
    executed_rows = [
        row for row in rows if row.get("execution_status") == "executed"
    ]
    network_probe_count = sum(1 for row in rows if row.get("network_probe_executed"))
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "run_status": "smoke_complete" if execute and not issues else "planned",
        "execution_mode": (
            "live_endpoint_smoke_opt_in"
            if execute
            else "live_endpoint_smoke_plan_only"
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
            "unhealthy_count": sum(1 for row in rows if row.get("status") == "unhealthy"),
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
