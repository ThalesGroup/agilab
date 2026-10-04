"""Prepare explicit operator retries without discarding unrelated DAG results."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .dag_execution_adapters import (
    _contract_artifact_kind,
    _refresh_summary,
    _unblock_unit_when_artifacts_available,
    dag_units,
)


def replay_unit_ids(state: Mapping[str, Any], unit_id: str) -> tuple[str, ...]:
    """Return the selected stage and every downstream consumer, in plan order."""
    units = dag_units(state)
    if not any(str(unit.get("id", "")) == unit_id for unit in units):
        raise ValueError(f"Unknown workflow stage: {unit_id}")
    affected = {unit_id}
    while True:
        previous = set(affected)
        for unit in units:
            dependencies = set(str(value) for value in unit.get("depends_on", []))
            dependencies.update(
                str(row.get("from", ""))
                for row in unit.get("artifact_dependencies", [])
                if isinstance(row, Mapping)
            )
            if dependencies & affected:
                affected.add(str(unit.get("id", "")))
        if affected == previous:
            return tuple(str(unit["id"]) for unit in units if str(unit["id"]) in affected)


def _contract_signature(unit: Mapping[str, Any]) -> dict[str, Any]:
    signature = {
        key: unit.get(key)
        for key in (
            "id", "app", "depends_on", "artifact_dependencies",
            "execution", "execution_contract", "command", "runtime",
        )
    }
    # Dispatch replaces paths and infers optional kinds. Compare the same
    # canonical kind the execution adapter uses, rather than its input spelling.
    signature["produces"] = [
        {
            "artifact": row.get("artifact"),
            "kind": _contract_artifact_kind(
                str(row.get("artifact", "")), str(row.get("kind", "") or "").strip(),
            ),
        }
        for row in unit.get("produces", []) if isinstance(row, Mapping)
    ]
    return signature


def prepare_operator_replay(
    state: Mapping[str, Any],
    *,
    baseline: Mapping[str, Any],
    unit_id: str,
    action: str,
    timestamp: str,
) -> dict[str, Any]:
    """Invalidate a branch; execution remains owned by the durable run engine.

    The engine calls this inside its revision-checked state transaction. Repeated
    requests cannot replay a now-pending unit, and changed source contracts require
    a full explicit reset rather than mixing old results with a new DAG.
    """
    expected_status = {"retry": "failed", "partial_rerun": "completed"}.get(action)
    if expected_status is None:
        raise ValueError("Operator action must be retry or partial_rerun.")
    units = dag_units(state)
    if any(unit.get("dispatch_status") == "running" for unit in units):
        raise ValueError("A running workflow stage must finish or be recovered before replay.")
    original = {str(unit["id"]): unit for unit in units}
    fresh = {str(unit["id"]): unit for unit in dag_units(baseline)}
    source = state.get("source", {})
    expected_source = baseline.get("source", {})
    expected_digest = expected_source.get("dag_sha256") if isinstance(expected_source, Mapping) else None
    if expected_digest and (not isinstance(source, Mapping) or source.get("dag_sha256") != expected_digest):
        raise ValueError("The saved workflow source fingerprint is missing or changed. Reset the plan explicitly before replay.")
    if not baseline.get("ok", False) or original.keys() != fresh.keys() or any(
        _contract_signature(unit) != _contract_signature(fresh[key])
        for key, unit in original.items()
    ):
        raise ValueError("The workflow contract changed. Reset the plan explicitly before replay.")
    if unit_id not in original:
        raise ValueError(f"Unknown workflow stage: {unit_id}")
    if original[unit_id].get("dispatch_status") != expected_status:
        raise ValueError(f"{action} requires a {expected_status} stage: {unit_id}")

    affected = replay_unit_ids(state, unit_id)
    invalidated_artifacts = {
        str(row.get("artifact", ""))
        for key in affected
        for row in original[key].get("produces", [])
        if isinstance(row, Mapping)
    }
    invalidated_artifacts.update(
        str(row.get("artifact", "")) for row in state.get("artifacts", [])
        if isinstance(row, Mapping) and str(row.get("producer", "")) in affected
    )
    updated = deepcopy(dict(state))
    updated["units"] = [
        deepcopy(fresh[str(unit["id"])]) if str(unit["id"]) in affected else unit
        for unit in dag_units(updated)
    ]
    updated["artifacts"] = [
        row for row in updated.get("artifacts", [])
        if isinstance(row, Mapping)
        and str(row.get("artifact", "")) not in invalidated_artifacts
        and str(row.get("producer", "")) not in affected
    ]
    for unit in dag_units(updated):
        key = str(unit["id"])
        if key not in affected:
            continue
        prior_retry = original[key].get("retry", {})
        retry_count = int(prior_retry.get("attempt", 0) or 0) if isinstance(prior_retry, Mapping) else 0
        unit["retry"] = {
            "policy": "operator_requested", "attempt": retry_count + int(action == "retry" and key == unit_id),
            "status": "prepared", "last_error": "", "next_action": "run the ready stage explicitly",
        }
        unit["partial_rerun"] = {
            "policy": "operator_requested", "requested": action == "partial_rerun" and key == unit_id,
            "requested_at": timestamp, "source_unit_id": unit_id,
            "invalidated_unit_ids": list(affected),
        }
        unit.setdefault("timestamps", {})["updated_at"] = timestamp
    updated.setdefault("events", []).append({
        "timestamp": timestamp, "kind": f"operator_{action}_prepared", "unit_id": unit_id,
        "from_status": expected_status, "to_status": str(fresh[unit_id].get("dispatch_status", "")),
        "detail": f"Explicit {action}; invalidated stages: {', '.join(affected)}. Existing files remain historical.",
        "invalidated_unit_ids": list(affected), "invalidated_artifact_ids": sorted(invalidated_artifacts),
    })
    provenance = updated.get("provenance", {})
    if isinstance(provenance, dict):
        for key in ("real_executed_unit_ids", "controlled_executed_unit_ids"):
            if isinstance(provenance.get(key), list):
                provenance[key] = [value for value in provenance[key] if str(value) not in affected]
    updated["updated_at"] = timestamp
    completed = {
        str(unit["id"]) for unit in dag_units(updated)
        if unit.get("dispatch_status") == "completed"
    }
    for unit in dag_units(updated):
        if str(unit["id"]) in affected and set(unit.get("depends_on", [])) <= completed:
            _unblock_unit_when_artifacts_available(updated, unit, timestamp=timestamp)
    return _refresh_summary(updated)
