# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Operator-triggered connector health action contract for AGILAB evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from agilab.data_connector_facility import (
    DEFAULT_CONNECTORS_RELATIVE_PATH,
    load_connector_catalog,
)
from agilab.data_connector_health import build_data_connector_health


SCHEMA = "agilab.data_connector_health_actions.v1"
DEFAULT_RUN_ID = "data-connector-health-actions-proof"
CREATED_AT = "2026-04-25T00:00:28Z"
UPDATED_AT = "2026-04-25T00:00:28Z"


def _action_row(probe: Mapping[str, Any]) -> dict[str, Any]:
    connector_id = str(probe.get("connector_id", "") or "")
    probe_type = str(probe.get("probe_type", "") or "")
    label = str(probe.get("label", "") or "")
    credential_source = str(probe.get("credential_source", "") or "none_required")
    return {
        "action_id": f"{connector_id}:health_probe",
        "connector_id": connector_id,
        "kind": str(probe.get("kind", "") or ""),
        "label": label,
        "probe_type": probe_type,
        "target": str(probe.get("target", "") or ""),
        "trigger_mode": "operator_explicit_opt_in",
        "ui_control": "button",
        "button_label": f"Run health probe: {label or connector_id}",
        "requires_operator_context": True,
        "operator_context_required": True,
        "requires_credentials": credential_source != "none_required",
        "credential_source": credential_source,
        "default_status": "unknown_not_probed",
        "execution_status": "not_executed_awaiting_operator",
        "result_status": "unknown_not_probed",
        "network_probe_executed": False,
        "safe_for_public_evidence": True,
    }


def build_data_connector_health_actions(
    catalog: Mapping[str, Any],
    *,
    source_path: Path | str,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    health_state = build_data_connector_health(catalog, source_path=source_path)
    probes = [probe for probe in health_state.get("probes", []) if isinstance(probe, dict)]
    actions = [_action_row(probe) for probe in probes]
    credential_gated_count = sum(
        1 for action in actions if action["requires_credentials"] is True
    )
    no_credential_required_count = sum(
        1 for action in actions if action["requires_credentials"] is False
    )
    issues = []
    if health_state.get("run_status") != "planned":
        issues.append(
            {
                "level": "error",
                "location": "health_plan",
                "message": f"health plan is not ready: {health_state.get('run_status')}",
            }
        )
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "run_status": "ready_for_operator_trigger" if not issues else "invalid",
        "execution_mode": "operator_trigger_contract_only",
        "source": {
            "catalog_path": str(source_path),
            "health_schema": health_state.get("schema", ""),
            "health_run_status": health_state.get("run_status", ""),
        },
        "summary": {
            "action_count": len(actions),
            "connector_count": len({action["connector_id"] for action in actions}),
            "operator_trigger_count": len(actions),
            "pending_action_count": len(actions),
            "pending_operator_trigger_count": len(actions),
            "executed_probe_count": 0,
            "network_probe_count": 0,
            "operator_context_required_count": len(actions),
            "credential_gated_count": credential_gated_count,
            "no_credential_required_count": no_credential_required_count,
            "probe_types": sorted({action["probe_type"] for action in actions}),
            "default_status_values": sorted(
                {action["default_status"] for action in actions}
            ),
            "result_status_values": sorted({action["result_status"] for action in actions}),
        },
        "actions": actions,
        "issues": issues,
        "provenance": {
            "executes_network_probe": False,
            "supports_operator_trigger": True,
            "requires_operator_opt_in": True,
            "requires_runtime_credentials": True,
            "safe_for_public_evidence": True,
        },
    }


def write_data_connector_health_actions(path: Path, state: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_data_connector_health_actions(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def persist_data_connector_health_actions(
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
    state = build_data_connector_health_actions(catalog, source_path=catalog_path)
    path = write_data_connector_health_actions(output_path, state)
    reloaded = load_data_connector_health_actions(path)
    return {
        "ok": state == reloaded
        and state.get("run_status") == "ready_for_operator_trigger",
        "path": str(path),
        "catalog_path": str(catalog_path),
        "state": state,
        "reloaded_state": reloaded,
        "round_trip_ok": state == reloaded,
    }
