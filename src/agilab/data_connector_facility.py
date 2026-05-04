# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Data connector catalog validation for AGILAB evidence reports."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import tomllib
from typing import Any, Mapping

from agilab.data_connector_cloud import (
    ACCEPTED_OBJECT_STORAGE_PROVIDERS,
    object_storage_provider,
)
from agilab.data_connector_search import (
    ACCEPTED_SEARCH_INDEX_PROVIDERS,
    search_index_provider,
)


SCHEMA = "agilab.data_connector_facility.v1"
DEFAULT_RUN_ID = "data-connector-facility-proof"
DEFAULT_CONNECTORS_RELATIVE_PATH = Path("docs/source/data/data_connectors_sample.toml")
SUPPORTED_KINDS = ("sql", "opensearch", "object_storage")
CREATED_AT = "2026-04-25T00:00:22Z"
UPDATED_AT = "2026-04-25T00:00:22Z"


@dataclass(frozen=True)
class DataConnectorIssue:
    level: str
    location: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "level": self.level,
            "location": self.location,
            "message": self.message,
        }


def _issue(location: str, message: str) -> DataConnectorIssue:
    return DataConnectorIssue(level="error", location=location, message=message)


def load_connector_catalog(path: Path) -> dict[str, Any]:
    payload = tomllib.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("connector catalog must be a TOML table")
    return payload


def _connector_rows(catalog: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = catalog.get("connectors", [])
    if not isinstance(rows, list):
        raise ValueError("connector catalog must define [[connectors]] entries")
    return [row for row in rows if isinstance(row, dict)]


def _has_raw_secret(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.lower()
    if value.startswith("env:"):
        return False
    return bool(re.search(r"(password|secret|token|access_key|api_key)=", lowered))


def _required_fields(kind: str) -> tuple[str, ...]:
    if kind == "sql":
        return ("id", "kind", "label", "uri", "driver", "query_mode")
    if kind == "opensearch":
        return ("id", "kind", "label", "index", "auth_ref")
    if kind == "object_storage":
        return ("id", "kind", "label", "provider", "bucket", "prefix", "auth_ref")
    return ("id", "kind", "label")


def _optional_fields(kind: str) -> tuple[str, ...]:
    if kind == "object_storage":
        return ("account", "storage_account", "container", "region", "endpoint_url")
    if kind == "opensearch":
        return ("provider", "url", "cluster_uri", "endpoint", "scheme")
    return ()


def _validate_connector(row: Mapping[str, Any], index: int) -> list[DataConnectorIssue]:
    issues: list[DataConnectorIssue] = []
    kind = str(row.get("kind", "") or "")
    connector_id = str(row.get("id", "") or f"connector[{index}]")
    if kind not in SUPPORTED_KINDS:
        issues.append(_issue(connector_id, f"unsupported connector kind: {kind}"))
        return issues
    for field in _required_fields(kind):
        if not str(row.get(field, "") or "").strip():
            issues.append(_issue(connector_id, f"missing required field: {field}"))
    if kind == "sql" and str(row.get("query_mode", "") or "") != "read_only":
        issues.append(_issue(connector_id, "SQL connector must be read_only"))
    if kind == "opensearch":
        provider = str(row.get("provider", "") or "opensearch")
        if search_index_provider(provider) is None:
            issues.append(
                _issue(
                    connector_id,
                    "unsupported opensearch provider: "
                    f"{provider or '(missing)'}; supported providers: "
                    f"{', '.join(ACCEPTED_SEARCH_INDEX_PROVIDERS)}",
                )
            )
        if not str(
            row.get("url", "")
            or row.get("cluster_uri", "")
            or row.get("endpoint", "")
            or ""
        ).strip():
            issues.append(_issue(connector_id, "missing required field: url or cluster_uri"))
    if kind == "object_storage":
        provider = str(row.get("provider", "") or "")
        if object_storage_provider(provider) is None:
            issues.append(
                _issue(
                    connector_id,
                    "unsupported object_storage provider: "
                    f"{provider or '(missing)'}; supported providers: "
                    f"{', '.join(ACCEPTED_OBJECT_STORAGE_PROVIDERS)}",
                )
            )
    auth_ref = str(row.get("auth_ref", "") or "")
    if kind in {"opensearch", "object_storage"} and not auth_ref.startswith("env:"):
        issues.append(_issue(connector_id, "remote connector auth_ref must use env:"))
    for key, value in row.items():
        if _has_raw_secret(value):
            issues.append(_issue(f"{connector_id}.{key}", "raw secret-like value found"))
    return issues


def _normalized_connector(row: Mapping[str, Any]) -> dict[str, Any]:
    kind = str(row.get("kind", "") or "")
    result = {
        "id": str(row.get("id", "") or ""),
        "kind": kind,
        "label": str(row.get("label", "") or ""),
        "description": str(row.get("description", "") or ""),
        "auth_ref": str(row.get("auth_ref", "") or ""),
        "network_probe": "not_executed_contract_validation",
    }
    for field in (*_required_fields(kind), *_optional_fields(kind)):
        if field not in result and field in row:
            result[field] = row.get(field)
    return result


def build_data_connector_facility(
    catalog: Mapping[str, Any],
    *,
    source_path: Path | str,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    rows = _connector_rows(catalog)
    issues: list[DataConnectorIssue] = []
    ids: set[str] = set()
    connectors: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        connector_id = str(row.get("id", "") or "")
        if connector_id in ids:
            issues.append(_issue(connector_id, "duplicate connector id"))
        ids.add(connector_id)
        issues.extend(_validate_connector(row, index))
        connectors.append(_normalized_connector(row))

    kinds = sorted({connector.get("kind", "") for connector in connectors})
    missing_kinds = [kind for kind in SUPPORTED_KINDS if kind not in kinds]
    if missing_kinds:
        issues.append(_issue("connectors", f"missing connector kinds: {missing_kinds}"))

    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "run_status": "validated" if not issues else "invalid",
        "execution_mode": "contract_validation_only",
        "source": {
            "catalog_path": str(source_path),
            "catalog_format": "toml",
        },
        "summary": {
            "connector_count": len(connectors),
            "supported_kind_count": len(kinds),
            "supported_kinds": kinds,
            "required_kinds": list(SUPPORTED_KINDS),
            "missing_kinds": missing_kinds,
            "issue_count": len(issues),
            "network_probe_count": 0,
            "raw_secret_count": sum(
                1
                for issue in issues
                if "secret" in issue.message
            ),
        },
        "connectors": connectors,
        "issues": [issue.as_dict() for issue in issues],
        "provenance": {
            "executes_network_probe": False,
            "plain_text_catalog": True,
            "supports_app_settings_references": True,
            "first_class_targets": list(SUPPORTED_KINDS),
        },
    }


def write_data_connector_facility(path: Path, state: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_data_connector_facility(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def persist_data_connector_facility(
    *,
    repo_root: Path,
    output_path: Path,
    catalog_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    catalog_path = catalog_path or (repo_root / DEFAULT_CONNECTORS_RELATIVE_PATH)
    if not catalog_path.is_absolute():
        catalog_path = repo_root / catalog_path
    catalog = load_connector_catalog(catalog_path)
    state = build_data_connector_facility(catalog, source_path=catalog_path)
    path = write_data_connector_facility(output_path, state)
    reloaded = load_data_connector_facility(path)
    return {
        "ok": state == reloaded and state.get("run_status") == "validated",
        "path": str(path),
        "catalog_path": str(catalog_path),
        "state": state,
        "reloaded_state": reloaded,
        "round_trip_ok": state == reloaded,
    }
