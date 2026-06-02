"""Stable runtime contract helpers for AGILAB workflow/DAG state."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


WORKFLOW_RUNTIME_CONTRACT_SCHEMA = "agilab.workflow_runtime_contract.v1"

PLANNED_PHASE = "planned"
RUNNING_PHASE = "running"
WAITING_PHASE = "waiting"
PAUSED_PHASE = "paused"
NEEDS_HELP_PHASE = "needs_help"
COMPLETED_PHASE = "completed"
FAILED_PHASE = "failed"
STOPPED_PHASE = "stopped"
UNKNOWN_PHASE = "unknown"

SUPPORTED_WORKFLOW_PHASES = {
    PLANNED_PHASE,
    RUNNING_PHASE,
    WAITING_PHASE,
    PAUSED_PHASE,
    NEEDS_HELP_PHASE,
    COMPLETED_PHASE,
    FAILED_PHASE,
    STOPPED_PHASE,
    UNKNOWN_PHASE,
}
TERMINAL_PHASES = {COMPLETED_PHASE, FAILED_PHASE, STOPPED_PHASE}

RUNNABLE_STATUS = "runnable"
BLOCKED_STATUS = "blocked"
RUNNING_STATUS = "running"
COMPLETED_STATUS = "completed"
FAILED_STATUS = "failed"
PAUSED_STATUS = "paused"
WAITING_STATUS = "waiting"
NEEDS_HELP_STATUS = "needs_help"
STOPPED_STATUS = "stopped"


def build_workflow_runtime_contract(
    state: Mapping[str, Any],
    *,
    max_recent_events: int = 12,
) -> dict[str, Any]:
    """Build a compact, UI-safe runtime contract from persisted workflow state."""
    units = _unit_rows(state)
    events = _event_rows(state)
    phase = workflow_phase(state, units=units)
    unit_ids = _unit_ids_by_status(units)
    controls = workflow_control_contract(phase, unit_ids)
    return {
        "schema": WORKFLOW_RUNTIME_CONTRACT_SCHEMA,
        "phase": phase,
        "run_status": str(state.get("run_status", "") or ""),
        "unit_counts": {
            "total": len(units),
            "runnable": len(unit_ids[RUNNABLE_STATUS]),
            "blocked": len(unit_ids[BLOCKED_STATUS]),
            "running": len(unit_ids[RUNNING_STATUS]),
            "completed": len(unit_ids[COMPLETED_STATUS]),
            "failed": len(unit_ids[FAILED_STATUS]),
        },
        "unit_ids": {
            "runnable": unit_ids[RUNNABLE_STATUS],
            "blocked": unit_ids[BLOCKED_STATUS],
            "running": unit_ids[RUNNING_STATUS],
            "completed": unit_ids[COMPLETED_STATUS],
            "failed": unit_ids[FAILED_STATUS],
        },
        "event_count": len(events),
        "last_event": events[-1] if events else {},
        "recent_events": events[-max(1, int(max_recent_events or 1)) :],
        "controls": controls,
    }


def workflow_phase(
    state: Mapping[str, Any],
    *,
    units: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    """Return the stable high-level workflow phase for UI and evidence."""
    unit_rows = list(units) if units is not None else _unit_rows(state)
    run_status = str(state.get("run_status", "") or "").strip().lower()
    statuses = {str(unit.get("dispatch_status", "") or "").strip().lower() for unit in unit_rows}

    if run_status in {COMPLETED_PHASE, FAILED_PHASE, STOPPED_PHASE, PAUSED_PHASE, NEEDS_HELP_PHASE}:
        return run_status
    if FAILED_STATUS in statuses:
        return FAILED_PHASE
    if NEEDS_HELP_STATUS in statuses:
        return NEEDS_HELP_PHASE
    if PAUSED_STATUS in statuses:
        return PAUSED_PHASE
    if RUNNING_STATUS in statuses:
        return RUNNING_PHASE
    if unit_rows and statuses == {COMPLETED_STATUS}:
        return COMPLETED_PHASE
    if WAITING_STATUS in statuses or (BLOCKED_STATUS in statuses and RUNNABLE_STATUS not in statuses):
        return WAITING_PHASE
    if RUNNABLE_STATUS in statuses or run_status in {"not_started", "not_executed", "ready_for_operator_review"}:
        return PLANNED_PHASE
    if run_status == RUNNING_PHASE:
        return RUNNING_PHASE
    return UNKNOWN_PHASE


def workflow_control_contract(
    phase: str,
    unit_ids: Mapping[str, Sequence[str]],
) -> list[dict[str, Any]]:
    """Return supported workflow controls with deterministic enabled/disabled reasons."""
    runnable_count = len(unit_ids.get(RUNNABLE_STATUS, ()))
    running_count = len(unit_ids.get(RUNNING_STATUS, ()))
    terminal = phase in TERMINAL_PHASES
    paused = phase in {PAUSED_PHASE, NEEDS_HELP_PHASE}
    runnable_reason = "" if runnable_count else "no ready workflow stage"
    terminal_reason = f"workflow is {phase}" if terminal else ""
    paused_reason = f"workflow is {phase}" if paused else ""
    return [
        _control(
            "run_next_stage",
            "Run next stage",
            bool(runnable_count) and not terminal and not paused,
            paused_reason or terminal_reason or runnable_reason,
        ),
        _control(
            "run_ready_stages",
            "Run ready stages",
            bool(runnable_count) and not terminal and not paused,
            paused_reason or terminal_reason or runnable_reason,
        ),
        _control(
            "pause",
            "Pause",
            phase in {PLANNED_PHASE, RUNNING_PHASE} and (bool(runnable_count) or bool(running_count)),
            "nothing is active or ready" if not runnable_count and not running_count else terminal_reason,
        ),
        _control(
            "resume",
            "Resume",
            phase in {PAUSED_PHASE, NEEDS_HELP_PHASE},
            "" if phase in {PAUSED_PHASE, NEEDS_HELP_PHASE} else "workflow is not paused",
        ),
        _control(
            "wake",
            "Wake",
            phase == WAITING_PHASE,
            "" if phase == WAITING_PHASE else "workflow is not waiting",
        ),
        _control(
            "stop",
            "Stop",
            not terminal and phase != UNKNOWN_PHASE,
            terminal_reason or "workflow state is unknown",
        ),
    ]


def validate_workflow_runtime_contract(contract: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate the public runtime-contract shape without requiring runtime imports."""
    issues: list[str] = []
    if str(contract.get("schema", "")) != WORKFLOW_RUNTIME_CONTRACT_SCHEMA:
        issues.append("runtime contract schema is unsupported")
    phase = str(contract.get("phase", "") or "")
    if phase not in SUPPORTED_WORKFLOW_PHASES:
        issues.append(f"runtime phase is unsupported: {phase!r}")
    controls = contract.get("controls", [])
    if not isinstance(controls, list):
        issues.append("runtime controls must be a list")
    else:
        for index, control in enumerate(controls):
            if not isinstance(control, Mapping):
                issues.append(f"runtime control #{index} must be an object")
                continue
            if not str(control.get("id", "") or "").strip():
                issues.append(f"runtime control #{index} id is missing")
            if not str(control.get("label", "") or "").strip():
                issues.append(f"runtime control #{index} label is missing")
            if not isinstance(control.get("enabled"), bool):
                issues.append(f"runtime control #{index} enabled flag must be boolean")
    try:
        event_count = int(contract.get("event_count", 0) or 0)
        if event_count < 0:
            issues.append("runtime event_count must be non-negative")
    except (TypeError, ValueError):
        issues.append("runtime event_count must be an integer")
    return tuple(issues)


def enabled_workflow_control_labels(contract: Mapping[str, Any]) -> tuple[str, ...]:
    """Return labels for enabled controls in display order."""
    controls = contract.get("controls", [])
    if not isinstance(controls, list):
        return ()
    return tuple(
        str(control.get("label", "") or "")
        for control in controls
        if isinstance(control, Mapping) and bool(control.get("enabled")) and str(control.get("label", "") or "")
    )


def _control(control_id: str, label: str, enabled: bool, reason: str = "") -> dict[str, Any]:
    return {
        "id": control_id,
        "label": label,
        "enabled": bool(enabled),
        "reason": "" if enabled else reason,
    }


def _unit_rows(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = state.get("units", state.get("state_units", []))
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _unit_ids_by_status(units: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    buckets = {
        RUNNABLE_STATUS: [],
        BLOCKED_STATUS: [],
        RUNNING_STATUS: [],
        COMPLETED_STATUS: [],
        FAILED_STATUS: [],
    }
    for unit in units:
        unit_id = str(unit.get("id", "") or "")
        status = str(unit.get("dispatch_status", "") or "").strip().lower()
        if unit_id and status in buckets:
            buckets[status].append(unit_id)
    for values in buckets.values():
        values.sort()
    return buckets


def _event_rows(state: Mapping[str, Any]) -> list[dict[str, str]]:
    events = state.get("events", [])
    if not isinstance(events, list):
        return []
    rows: list[dict[str, str]] = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        rows.append(
            {
                "timestamp": str(event.get("timestamp", "") or ""),
                "kind": str(event.get("kind", "") or ""),
                "unit_id": str(event.get("unit_id", "") or ""),
                "from_status": str(event.get("from_status", "") or ""),
                "to_status": str(event.get("to_status", "") or ""),
                "detail": str(event.get("detail", "") or ""),
            }
        )
    rows.sort(key=lambda row: row["timestamp"])
    return rows


__all__ = [
    "WORKFLOW_RUNTIME_CONTRACT_SCHEMA",
    "SUPPORTED_WORKFLOW_PHASES",
    "build_workflow_runtime_contract",
    "enabled_workflow_control_labels",
    "validate_workflow_runtime_contract",
    "workflow_control_contract",
    "workflow_phase",
]
