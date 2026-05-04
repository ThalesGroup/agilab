# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Connector health-probe planning for AGILAB evidence reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from agilab.data_connector_cloud import object_storage_target
from agilab.data_connector_facility import (
    DEFAULT_CONNECTORS_RELATIVE_PATH,
    build_data_connector_facility,
    load_connector_catalog,
)
from agilab.data_connector_search import search_index_target


SCHEMA = "agilab.data_connector_health.v1"
DEFAULT_RUN_ID = "data-connector-health-proof"
CREATED_AT = "2026-04-25T00:00:24Z"
UPDATED_AT = "2026-04-25T00:00:24Z"


def _connector_target(connector: Mapping[str, Any]) -> str:
    kind = str(connector.get("kind", "") or "")
    if kind == "sql":
        return str(connector.get("uri", "") or "")
    if kind == "opensearch":
        return search_index_target(connector)
    if kind == "object_storage":
        return object_storage_target(connector)
    return ""


def _probe_type(kind: str) -> str:
    if kind == "sql":
        return "driver_connectivity"
    if kind == "opensearch":
        return "index_head"
    if kind == "object_storage":
        return "bucket_prefix_list"
    return "unsupported"


def _health_probe_row(connector: Mapping[str, Any]) -> dict[str, Any]:
    auth_ref = str(connector.get("auth_ref", "") or "")
    return {
        "connector_id": str(connector.get("id", "") or ""),
        "kind": str(connector.get("kind", "") or ""),
        "label": str(connector.get("label", "") or ""),
        "probe_type": _probe_type(str(connector.get("kind", "") or "")),
        "target": _connector_target(connector),
        "status": "unknown_not_probed",
        "execution_status": "not_executed_opt_in_required",
        "network_probe_executed": False,
        "operator_context_required": True,
        "credential_source": auth_ref or "none_required",
        "reason": "public evidence plans the health probe but does not open networks",
    }


def build_data_connector_health(
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
    probes = [_health_probe_row(connector) for connector in connectors]
    issues = []
    if facility_state.get("run_status") != "validated":
        issues.append(
            {
                "level": "error",
                "location": "connector_catalog",
                "message": "connector catalog must validate before health planning",
            }
        )

    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "run_status": "planned" if not issues else "invalid",
        "execution_mode": "health_probe_plan_only",
        "source": {
            "catalog_path": str(source_path),
            "facility_schema": facility_state.get("schema", ""),
            "facility_run_status": facility_state.get("run_status", ""),
        },
        "summary": {
            "connector_count": len(connectors),
            "planned_probe_count": len(probes),
            "executed_probe_count": 0,
            "opt_in_required_count": len(probes),
            "network_probe_count": 0,
            "unknown_status_count": len(probes),
            "unhealthy_count": 0,
            "probe_types": sorted({str(probe.get("probe_type", "")) for probe in probes}),
            "status_values": sorted({str(probe.get("status", "")) for probe in probes}),
            "catalog_run_status": facility_state.get("run_status", ""),
        },
        "probes": probes,
        "issues": issues,
        "provenance": {
            "executes_network_probe": False,
            "requires_operator_opt_in": True,
            "safe_for_public_evidence": True,
        },
    }


def write_data_connector_health(path: Path, state: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_data_connector_health(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def persist_data_connector_health(
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
    state = build_data_connector_health(catalog, source_path=catalog_path)
    path = write_data_connector_health(output_path, state)
    reloaded = load_data_connector_health(path)
    return {
        "ok": state == reloaded and state.get("run_status") == "planned",
        "path": str(path),
        "catalog_path": str(catalog_path),
        "state": state,
        "reloaded_state": reloaded,
        "round_trip_ok": state == reloaded,
    }
