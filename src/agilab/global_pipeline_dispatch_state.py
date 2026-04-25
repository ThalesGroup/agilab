# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Persistent dispatch-state helpers for AGILAB global pipeline DAGs."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from agilab.global_pipeline_execution_plan import build_execution_plan
from agilab.global_pipeline_runner_state import build_runner_state


SCHEMA = "agilab.global_pipeline_dispatch_state.v1"
DEFAULT_RUN_ID = "global-dag-dispatch-proof"
PERSISTENCE_FORMAT = "json"
SIMULATED_CREATED_AT = "2026-04-25T00:00:00Z"
SIMULATED_QUEUE_COMPLETED_AT = "2026-04-25T00:00:01Z"
SIMULATED_RELAY_RUNNABLE_AT = "2026-04-25T00:00:02Z"
SIMULATED_PERSISTED_AT = "2026-04-25T00:00:03Z"


@dataclass(frozen=True)
class DispatchStateIssue:
    level: str
    location: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "level": self.level,
            "location": self.location,
            "message": self.message,
        }


@dataclass(frozen=True)
class DispatchStateProof:
    ok: bool
    issues: tuple[DispatchStateIssue, ...]
    path: str
    dispatch_state: dict[str, Any]
    reloaded_state: dict[str, Any]

    @property
    def round_trip_ok(self) -> bool:
        return self.dispatch_state == self.reloaded_state

    @property
    def unit_count(self) -> int:
        return len(self.dispatch_state.get("units", []))

    @property
    def completed_unit_ids(self) -> tuple[str, ...]:
        return _unit_ids_for_status(self.dispatch_state, "completed")

    @property
    def runnable_unit_ids(self) -> tuple[str, ...]:
        return _unit_ids_for_status(self.dispatch_state, "runnable")

    @property
    def blocked_unit_ids(self) -> tuple[str, ...]:
        return _unit_ids_for_status(self.dispatch_state, "blocked")

    @property
    def event_count(self) -> int:
        events = self.dispatch_state.get("events", [])
        return len(events) if isinstance(events, list) else 0

    @property
    def available_artifact_ids(self) -> tuple[str, ...]:
        artifacts = self.dispatch_state.get("artifacts", [])
        if not isinstance(artifacts, list):
            return ()
        return tuple(
            str(artifact.get("artifact", ""))
            for artifact in artifacts
            if isinstance(artifact, dict) and artifact.get("status") == "available"
        )

    @property
    def retry_counter_count(self) -> int:
        return sum(1 for unit in _unit_rows(self.dispatch_state) if "retry" in unit)

    @property
    def partial_rerun_flag_count(self) -> int:
        return sum(1 for unit in _unit_rows(self.dispatch_state) if "partial_rerun" in unit)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [issue.as_dict() for issue in self.issues],
            "path": self.path,
            "round_trip_ok": self.round_trip_ok,
            "unit_count": self.unit_count,
            "completed_unit_ids": list(self.completed_unit_ids),
            "runnable_unit_ids": list(self.runnable_unit_ids),
            "blocked_unit_ids": list(self.blocked_unit_ids),
            "available_artifact_ids": list(self.available_artifact_ids),
            "event_count": self.event_count,
            "retry_counter_count": self.retry_counter_count,
            "partial_rerun_flag_count": self.partial_rerun_flag_count,
            "dispatch_state": self.dispatch_state,
            "reloaded_state": self.reloaded_state,
        }


def _issue(location: str, message: str) -> DispatchStateIssue:
    return DispatchStateIssue(level="error", location=location, message=message)


def _unit_rows(state: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    rows = state.get("units", [])
    if not isinstance(rows, list):
        return ()
    return tuple(row for row in rows if isinstance(row, dict))


def _unit_ids_for_status(state: Mapping[str, Any], status: str) -> tuple[str, ...]:
    return tuple(
        str(unit.get("id", ""))
        for unit in _unit_rows(state)
        if unit.get("dispatch_status") == status
    )


def _plan_produces_by_id(plan_units: tuple[dict[str, Any], ...]) -> dict[str, list[dict[str, str]]]:
    produces_by_id: dict[str, list[dict[str, str]]] = {}
    for unit in plan_units:
        unit_id = str(unit.get("id", ""))
        produces = unit.get("produces", [])
        produces_by_id[unit_id] = [
            {
                "artifact": str(artifact.get("artifact", "")),
                "path": str(artifact.get("path", "")),
                "kind": str(artifact.get("kind", "")),
            }
            for artifact in produces
            if isinstance(artifact, dict) and artifact.get("artifact")
        ]
    return produces_by_id


def _base_unit(unit: dict[str, Any], produced_artifacts: list[dict[str, str]]) -> dict[str, Any]:
    retry = unit.get("retry", {})
    partial_rerun = unit.get("partial_rerun", {})
    return {
        "id": unit.get("id", ""),
        "app": unit.get("app", ""),
        "order_index": unit.get("order_index"),
        "depends_on": list(unit.get("depends_on", [])),
        "artifact_dependencies": list(unit.get("artifact_dependencies", [])),
        "produces": produced_artifacts,
        "dispatch_status": unit.get("dispatch_status", ""),
        "retry": {
            "attempt": retry.get("attempt", 0),
            "retry_count": 0,
            "max_attempts": retry.get("max_attempts", 0),
            "last_error": retry.get("last_error", ""),
        },
        "partial_rerun": {
            "requested": partial_rerun.get("requested", False),
            "eligible_after_completion": partial_rerun.get("eligible_after_completion", True),
            "requires_completed_dependencies": list(partial_rerun.get("requires_completed_dependencies", [])),
            "artifact_scope": list(partial_rerun.get("artifact_scope", [])),
        },
        "timestamps": {
            "created_at": SIMULATED_CREATED_AT,
            "updated_at": SIMULATED_CREATED_AT,
        },
        "operator_ui": dict(unit.get("operator_ui", {})),
        "provenance": dict(unit.get("provenance", {})),
    }


def _event(
    *,
    timestamp: str,
    kind: str,
    unit_id: str,
    from_status: str,
    to_status: str,
    detail: str,
) -> dict[str, str]:
    return {
        "timestamp": timestamp,
        "kind": kind,
        "unit_id": unit_id,
        "from_status": from_status,
        "to_status": to_status,
        "detail": detail,
    }


def _artifact_rows(unit: dict[str, Any]) -> list[dict[str, str]]:
    artifacts = []
    for artifact in unit.get("produces", []):
        if not isinstance(artifact, dict) or not artifact.get("artifact"):
            continue
        artifacts.append(
            {
                "artifact": str(artifact.get("artifact", "")),
                "kind": str(artifact.get("kind", "")),
                "path": str(artifact.get("path", "")),
                "producer": str(unit.get("id", "")),
                "status": "available",
                "available_at": SIMULATED_QUEUE_COMPLETED_AT,
            }
        )
    return artifacts


def build_dispatch_state(
    *,
    repo_root: Path,
    dag_path: Path | None = None,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    plan = build_execution_plan(repo_root=repo_root, dag_path=dag_path)
    runner_state = build_runner_state(repo_root=repo_root, dag_path=dag_path)
    produces_by_id = _plan_produces_by_id(plan.runnable_units)
    units = [
        _base_unit(unit, produces_by_id.get(str(unit.get("id", "")), []))
        for unit in runner_state.state_units
    ]
    by_id = {unit["id"]: unit for unit in units}
    queue = by_id.get("queue_baseline")
    relay = by_id.get("relay_followup")
    events = [
        {
            "timestamp": SIMULATED_CREATED_AT,
            "kind": "run_created",
            "unit_id": "",
            "from_status": "",
            "to_status": "created",
            "detail": "persistent global DAG dispatch state created",
        }
    ]
    artifacts: list[dict[str, str]] = []

    if queue:
        previous_status = str(queue.get("dispatch_status", ""))
        queue["dispatch_status"] = "completed"
        queue["retry"]["attempt"] = 1
        queue["timestamps"]["started_at"] = SIMULATED_QUEUE_COMPLETED_AT
        queue["timestamps"]["completed_at"] = SIMULATED_QUEUE_COMPLETED_AT
        queue["timestamps"]["updated_at"] = SIMULATED_QUEUE_COMPLETED_AT
        queue["operator_ui"] = {
            "state": "completed",
            "severity": "success",
            "message": "queue_baseline completed and published queue_metrics.",
            "blocked_by_artifacts": [],
        }
        events.append(
            _event(
                timestamp=SIMULATED_QUEUE_COMPLETED_AT,
                kind="unit_completed",
                unit_id="queue_baseline",
                from_status=previous_status,
                to_status="completed",
                detail="simulated dispatch completed successfully",
            )
        )
        artifacts.extend(_artifact_rows(queue))
        events.append(
            _event(
                timestamp=SIMULATED_QUEUE_COMPLETED_AT,
                kind="artifact_available",
                unit_id="queue_baseline",
                from_status="missing",
                to_status="available",
                detail="queue_metrics became available for downstream units",
            )
        )

    if relay:
        previous_status = str(relay.get("dispatch_status", ""))
        relay["dispatch_status"] = "runnable"
        relay["timestamps"]["unblocked_at"] = SIMULATED_RELAY_RUNNABLE_AT
        relay["timestamps"]["updated_at"] = SIMULATED_RELAY_RUNNABLE_AT
        relay["operator_ui"] = {
            "state": "ready_to_dispatch",
            "severity": "info",
            "message": "relay_followup is runnable after queue_metrics became available.",
            "blocked_by_artifacts": [],
        }
        events.append(
            _event(
                timestamp=SIMULATED_RELAY_RUNNABLE_AT,
                kind="unit_unblocked",
                unit_id="relay_followup",
                from_status=previous_status,
                to_status="runnable",
                detail="queue_metrics satisfied the artifact dependency",
            )
        )

    events.append(
        {
            "timestamp": SIMULATED_PERSISTED_AT,
            "kind": "state_persisted",
            "unit_id": "",
            "from_status": "memory",
            "to_status": "disk",
            "detail": "dispatch state JSON written and read back",
        }
    )

    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "persistence_format": PERSISTENCE_FORMAT,
        "run_status": "in_progress",
        "created_at": SIMULATED_CREATED_AT,
        "updated_at": SIMULATED_PERSISTED_AT,
        "source": {
            "dag_path": runner_state.dag_path,
            "execution_order": list(runner_state.execution_order),
            "plan_schema": runner_state.plan_schema,
            "runner_state_schema": runner_state.schema,
            "runner_state_mode": runner_state.runner_mode,
        },
        "summary": {
            "unit_count": len(units),
            "completed_unit_ids": list(_unit_ids_for_status({"units": units}, "completed")),
            "runnable_unit_ids": list(_unit_ids_for_status({"units": units}, "runnable")),
            "blocked_unit_ids": list(_unit_ids_for_status({"units": units}, "blocked")),
            "available_artifact_ids": [artifact["artifact"] for artifact in artifacts],
            "event_count": len(events),
        },
        "units": units,
        "artifacts": artifacts,
        "events": events,
        "provenance": {
            "source_dag": runner_state.dag_path,
            "source_plan_schema": runner_state.plan_schema,
            "source_runner_state_schema": runner_state.schema,
            "dispatch_mode": "simulated_persistent_state",
            "real_app_execution": False,
        },
    }


def write_dispatch_state(path: Path, state: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_dispatch_state(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def persist_dispatch_state(
    *,
    repo_root: Path,
    output_path: Path,
    dag_path: Path | None = None,
    run_id: str = DEFAULT_RUN_ID,
) -> DispatchStateProof:
    issues: list[DispatchStateIssue] = []
    state = build_dispatch_state(repo_root=repo_root, dag_path=dag_path, run_id=run_id)
    path = write_dispatch_state(output_path, state)
    reloaded = load_dispatch_state(path)
    if state != reloaded:
        issues.append(_issue("persistence.round_trip", "dispatch state changed after JSON write/read"))
    return DispatchStateProof(
        ok=not issues,
        issues=tuple(issues),
        path=str(path),
        dispatch_state=state,
        reloaded_state=reloaded,
    )


__all__ = [
    "DEFAULT_RUN_ID",
    "DispatchStateIssue",
    "DispatchStateProof",
    "PERSISTENCE_FORMAT",
    "SCHEMA",
    "build_dispatch_state",
    "load_dispatch_state",
    "persist_dispatch_state",
    "write_dispatch_state",
]
