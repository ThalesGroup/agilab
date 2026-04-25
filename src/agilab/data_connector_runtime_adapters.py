# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Runtime adapter binding contract for AGILAB data connectors."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from agilab.data_connector_facility import (
    DEFAULT_CONNECTORS_RELATIVE_PATH,
    build_data_connector_facility,
    load_connector_catalog,
)


SCHEMA = "agilab.data_connector_runtime_adapters.v1"
DEFAULT_RUN_ID = "data-connector-runtime-adapters-proof"
CREATED_AT = "2026-04-25T00:00:29Z"
UPDATED_AT = "2026-04-25T00:00:29Z"


def _connector_target(connector: Mapping[str, Any]) -> str:
    kind = str(connector.get("kind", "") or "")
    if kind == "sql":
        return str(connector.get("uri", "") or "")
    if kind == "opensearch":
        return f"{connector.get('url', '')}/{connector.get('index', '')}"
    if kind == "object_storage":
        return (
            f"{connector.get('provider', '')}://"
            f"{connector.get('bucket', '')}/{connector.get('prefix', '')}"
        )
    return ""


def _credential_env_name(credential_source: str) -> str:
    if credential_source.startswith("env:"):
        return credential_source.removeprefix("env:")
    return ""


def _sql_dependency(connector: Mapping[str, Any]) -> str:
    driver = str(connector.get("driver", "") or "")
    if driver == "sqlite":
        return "python:sqlite3"
    if driver == "postgresql":
        return "package:psycopg"
    if driver == "mysql":
        return "package:pymysql"
    return f"driver:{driver or 'unspecified'}"


def _adapter_definition(connector: Mapping[str, Any]) -> dict[str, str]:
    kind = str(connector.get("kind", "") or "")
    if kind == "sql":
        return {
            "adapter_class": "SqlRuntimeAdapter",
            "operation": "read_only_connectivity_check",
            "runtime_dependency": _sql_dependency(connector),
        }
    if kind == "opensearch":
        return {
            "adapter_class": "OpenSearchRuntimeAdapter",
            "operation": "opensearch_index_head",
            "runtime_dependency": "python:urllib.request",
        }
    if kind == "object_storage":
        provider = str(connector.get("provider", "") or "")
        dependency = "package:boto3" if provider == "s3" else f"provider_sdk:{provider}"
        return {
            "adapter_class": "ObjectStorageRuntimeAdapter",
            "operation": "object_storage_prefix_list",
            "runtime_dependency": dependency,
        }
    return {
        "adapter_class": "UnsupportedRuntimeAdapter",
        "operation": "unsupported",
        "runtime_dependency": "unsupported",
    }


def _adapter_row(connector: Mapping[str, Any]) -> dict[str, Any]:
    connector_id = str(connector.get("id", "") or "")
    credential_source = str(connector.get("auth_ref", "") or "none_required")
    requires_credentials = credential_source != "none_required"
    definition = _adapter_definition(connector)
    return {
        "adapter_id": f"{connector_id}:runtime_adapter",
        "connector_id": connector_id,
        "kind": str(connector.get("kind", "") or ""),
        "label": str(connector.get("label", "") or ""),
        "target": _connector_target(connector),
        "adapter_class": definition["adapter_class"],
        "adapter_entrypoint": (
            "agilab.data_connector_runtime_adapters:"
            f"{definition['adapter_class']}.probe"
        ),
        "operation": definition["operation"],
        "runtime_dependency": definition["runtime_dependency"],
        "credential_source": credential_source,
        "credential_env_name": _credential_env_name(credential_source),
        "requires_credentials": requires_credentials,
        "credential_resolution": (
            "deferred_to_operator_runtime"
            if requires_credentials
            else "none_required"
        ),
        "operator_opt_in_required": True,
        "health_action_id": f"{connector_id}:health_probe",
        "supports_health_action": True,
        "runtime_binding_status": "ready_for_operator_runtime",
        "execution_status": "not_executed_operator_runtime_required",
        "network_probe_executed": False,
        "credential_value_materialized": False,
        "safe_for_public_evidence": True,
    }


def build_data_connector_runtime_adapters(
    catalog: Mapping[str, Any],
    *,
    source_path: Path | str,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    facility_state = build_data_connector_facility(catalog, source_path=source_path)
    connectors = [
        connector
        for connector in facility_state.get("connectors", [])
        if isinstance(connector, dict)
    ]
    adapters = [_adapter_row(connector) for connector in connectors]
    issues = []
    if facility_state.get("run_status") != "validated":
        issues.append(
            {
                "level": "error",
                "location": "connector_catalog",
                "message": "connector catalog must validate before adapter binding",
            }
        )
    credential_deferred_count = sum(
        1 for adapter in adapters if adapter["requires_credentials"] is True
    )
    no_credential_required_count = sum(
        1 for adapter in adapters if adapter["requires_credentials"] is False
    )

    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "run_status": "ready_for_runtime_binding" if not issues else "invalid",
        "execution_mode": "runtime_adapter_contract_only",
        "source": {
            "catalog_path": str(source_path),
            "facility_schema": facility_state.get("schema", ""),
            "facility_run_status": facility_state.get("run_status", ""),
        },
        "summary": {
            "connector_count": len(connectors),
            "adapter_count": len(adapters),
            "runtime_ready_count": len(adapters),
            "credential_deferred_count": credential_deferred_count,
            "no_credential_required_count": no_credential_required_count,
            "operator_opt_in_required_count": len(adapters),
            "health_action_binding_count": len(adapters),
            "executed_adapter_count": 0,
            "network_probe_count": 0,
            "credential_value_materialized_count": 0,
            "adapter_kinds": sorted({adapter["kind"] for adapter in adapters}),
            "operations": sorted({adapter["operation"] for adapter in adapters}),
            "runtime_dependencies": sorted(
                {adapter["runtime_dependency"] for adapter in adapters}
            ),
        },
        "adapters": adapters,
        "issues": issues,
        "provenance": {
            "executes_network_probe": False,
            "credential_values_materialized": False,
            "supports_runtime_adapters": True,
            "requires_operator_opt_in": True,
            "safe_for_public_evidence": True,
        },
    }


def write_data_connector_runtime_adapters(path: Path, state: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_data_connector_runtime_adapters(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def persist_data_connector_runtime_adapters(
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
    state = build_data_connector_runtime_adapters(catalog, source_path=catalog_path)
    path = write_data_connector_runtime_adapters(output_path, state)
    reloaded = load_data_connector_runtime_adapters(path)
    return {
        "ok": state == reloaded
        and state.get("run_status") == "ready_for_runtime_binding",
        "path": str(path),
        "catalog_path": str(catalog_path),
        "state": state,
        "reloaded_state": reloaded,
        "round_trip_ok": state == reloaded,
    }
