# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Read-only runner-state helpers for AGILAB global pipeline DAGs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Mapping

_src_root = Path(__file__).resolve().parents[1]
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))
_agilab_pkg = sys.modules.get("agilab")
if _agilab_pkg is not None:
    package_path = str(_src_root / "agilab")
    package_paths = list(getattr(_agilab_pkg, "__path__", []) or [])
    if package_path not in package_paths:
        _agilab_pkg.__path__ = [*package_paths, package_path]

from agilab.global_pipeline_execution_plan import ExecutionPlan, build_execution_plan


SCHEMA = "agilab.global_pipeline_runner_state.v1"
RUNNER_MODE = "read_only_preview"
RUN_STATUS = "not_started"
RUNNABLE_STATUS = "runnable"
BLOCKED_STATUS = "blocked"
RUNNING_STATUS = "running"
COMPLETED_STATUS = "completed"
FAILED_STATUS = "failed"
PLANNED_STATUS = "planned"
PERSISTENCE_FORMAT = "json"
DEFAULT_RUN_ID = "global-dag-runner-state"


@dataclass(frozen=True)
class RunnerStateIssue:
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
class RunnerState:
    ok: bool
    issues: tuple[RunnerStateIssue, ...]
    schema: str
    runner_mode: str
    run_status: str
    dag_path: str
    plan_schema: str
    plan_runner_status: str
    execution_order: tuple[str, ...]
    state_units: tuple[dict[str, Any], ...]

    @property
    def unit_count(self) -> int:
        return len(self.state_units)

    @property
    def runnable_count(self) -> int:
        return sum(1 for unit in self.state_units if unit.get("dispatch_status") == RUNNABLE_STATUS)

    @property
    def blocked_count(self) -> int:
        return sum(1 for unit in self.state_units if unit.get("dispatch_status") == BLOCKED_STATUS)

    @property
    def completed_count(self) -> int:
        return sum(1 for unit in self.state_units if unit.get("dispatch_status") == "completed")

    @property
    def failed_count(self) -> int:
        return sum(1 for unit in self.state_units if unit.get("dispatch_status") == "failed")

    @property
    def runnable_unit_ids(self) -> tuple[str, ...]:
        return tuple(
            str(unit["id"])
            for unit in self.state_units
            if unit.get("dispatch_status") == RUNNABLE_STATUS
        )

    @property
    def blocked_unit_ids(self) -> tuple[str, ...]:
        return tuple(
            str(unit["id"])
            for unit in self.state_units
            if unit.get("dispatch_status") == BLOCKED_STATUS
        )

    @property
    def transition_count(self) -> int:
        return sum(len(unit.get("transitions", [])) for unit in self.state_units)

    @property
    def retry_policy_count(self) -> int:
        return sum(1 for unit in self.state_units if "retry" in unit)

    @property
    def partial_rerun_record_count(self) -> int:
        return sum(1 for unit in self.state_units if "partial_rerun" in unit)

    @property
    def operator_state_count(self) -> int:
        return sum(1 for unit in self.state_units if "operator_ui" in unit)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [issue.as_dict() for issue in self.issues],
            "schema": self.schema,
            "runner_mode": self.runner_mode,
            "run_status": self.run_status,
            "dag_path": self.dag_path,
            "plan_schema": self.plan_schema,
            "plan_runner_status": self.plan_runner_status,
            "execution_order": list(self.execution_order),
            "unit_count": self.unit_count,
            "runnable_count": self.runnable_count,
            "blocked_count": self.blocked_count,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "runnable_unit_ids": list(self.runnable_unit_ids),
            "blocked_unit_ids": list(self.blocked_unit_ids),
            "transition_count": self.transition_count,
            "retry_policy_count": self.retry_policy_count,
            "partial_rerun_record_count": self.partial_rerun_record_count,
            "operator_state_count": self.operator_state_count,
            "state_units": list(self.state_units),
        }


@dataclass(frozen=True)
class RunnerStatePersistenceProof:
    ok: bool
    issues: tuple[RunnerStateIssue, ...]
    path: str
    runner_state: dict[str, Any]
    reloaded_state: dict[str, Any]

    @property
    def round_trip_ok(self) -> bool:
        return self.runner_state == self.reloaded_state

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [issue.as_dict() for issue in self.issues],
            "path": self.path,
            "round_trip_ok": self.round_trip_ok,
            "runner_state": self.runner_state,
            "reloaded_state": self.reloaded_state,
        }


@dataclass(frozen=True)
class RunnerDispatchResult:
    ok: bool
    message: str
    dispatched_unit_id: str
    state: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "dispatched_unit_id": self.dispatched_unit_id,
            "state": self.state,
        }


def _issue(location: str, message: str) -> RunnerStateIssue:
    return RunnerStateIssue(level="error", location=location, message=message)


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _artifact_names(dependencies: list[dict[str, str]]) -> list[str]:
    return [
        dependency["artifact"]
        for dependency in dependencies
        if dependency.get("artifact")
    ]


def _transition(from_status: str, to_status: str, condition: str) -> dict[str, str]:
    return {
        "from": from_status,
        "to": to_status,
        "condition": condition,
    }


def _dependency_summary(dependencies: list[dict[str, str]]) -> str:
    if not dependencies:
        return "all artifact dependencies satisfied"
    parts = [
        f"{dependency.get('artifact', 'artifact')} from {dependency.get('from', 'upstream')}"
        for dependency in dependencies
    ]
    return "waiting for " + ", ".join(parts)


def _transitions_for_unit(dependencies: list[dict[str, str]]) -> list[dict[str, str]]:
    runnable_condition = "all artifact dependencies are available"
    transitions = [
        _transition(RUNNABLE_STATUS, "completed", "app runner records successful completion"),
        _transition(RUNNABLE_STATUS, "failed", "app runner records failure"),
        _transition("failed", RUNNABLE_STATUS, "retry requested and retry budget remains"),
        _transition("completed", RUNNABLE_STATUS, "operator requests a partial rerun"),
    ]
    if dependencies:
        return [
            _transition("pending", BLOCKED_STATUS, _dependency_summary(dependencies)),
            _transition(BLOCKED_STATUS, RUNNABLE_STATUS, runnable_condition),
            *transitions,
        ]
    return [
        _transition("pending", RUNNABLE_STATUS, runnable_condition),
        *transitions,
    ]


def _operator_ui_state(unit_id: str, dependencies: list[dict[str, str]]) -> dict[str, Any]:
    artifacts = _artifact_names(dependencies)
    if dependencies:
        return {
            "state": "waiting_for_artifacts",
            "severity": "info",
            "message": f"{unit_id} is blocked until {', '.join(artifacts)} is available.",
            "blocked_by_artifacts": artifacts,
        }
    return {
        "state": "ready_to_dispatch",
        "severity": "info",
        "message": f"{unit_id} is ready for dispatch; no upstream artifacts are pending.",
        "blocked_by_artifacts": [],
    }


def _retry_metadata(unit_id: str) -> dict[str, Any]:
    return {
        "policy": "metadata_only",
        "attempt": 0,
        "max_attempts": 0,
        "status": "not_scheduled",
        "last_error": "",
        "next_action": f"configure retry policy before dispatching {unit_id}",
    }


def _partial_rerun_metadata(unit: dict[str, Any]) -> dict[str, Any]:
    produced = unit.get("produces", [])
    artifact_scope = [
        artifact.get("artifact", "")
        for artifact in produced
        if isinstance(artifact, dict) and artifact.get("artifact")
    ]
    return {
        "policy": "metadata_only",
        "requested": False,
        "eligible_after_completion": True,
        "requires_completed_dependencies": _as_str_list(unit.get("depends_on")),
        "artifact_scope": artifact_scope,
    }


def _provenance(plan: ExecutionPlan, unit: dict[str, Any]) -> dict[str, Any]:
    unit_provenance = unit.get("provenance", {})
    return {
        "source_plan_schema": plan.schema,
        "source_plan_runner_status": plan.runner_status,
        "source_dag": plan.dag_path,
        "source_unit_id": str(unit.get("id", "")),
        "source_app": str(unit.get("app", "")),
        "pipeline_view": str(unit_provenance.get("pipeline_view", "")),
        "runner_state_mode": RUNNER_MODE,
        "planning_mode": str(unit_provenance.get("planning_mode", "")),
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _unit_rows(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = state.get("units", state.get("state_units", []))
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _unit_ids_for_status(units: list[dict[str, Any]], status: str) -> list[str]:
    return [
        str(unit.get("id", ""))
        for unit in units
        if unit.get("dispatch_status") == status and str(unit.get("id", ""))
    ]


def _planned_count(units: list[dict[str, Any]]) -> int:
    return sum(
        1
        for unit in units
        if unit.get("dispatch_status") in {RUNNABLE_STATUS, BLOCKED_STATUS, "pending", ""}
    )


def _run_status_for_units(units: list[dict[str, Any]]) -> str:
    if any(unit.get("dispatch_status") == FAILED_STATUS for unit in units):
        return FAILED_STATUS
    if units and all(unit.get("dispatch_status") == COMPLETED_STATUS for unit in units):
        return COMPLETED_STATUS
    if any(unit.get("dispatch_status") == RUNNING_STATUS for unit in units):
        return RUNNING_STATUS
    if any(unit.get("dispatch_status") == COMPLETED_STATUS for unit in units):
        return RUNNING_STATUS
    return PLANNED_STATUS


def _refresh_persisted_summary(state: dict[str, Any]) -> dict[str, Any]:
    units = _unit_rows(state)
    events = state.get("events", [])
    event_count = len(events) if isinstance(events, list) else 0
    planned_count = _planned_count(units)
    running_ids = _unit_ids_for_status(units, RUNNING_STATUS)
    completed_ids = _unit_ids_for_status(units, COMPLETED_STATUS)
    failed_ids = _unit_ids_for_status(units, FAILED_STATUS)
    state["run_status"] = _run_status_for_units(units)
    state["summary"] = {
        "unit_count": len(units),
        "planned_count": planned_count,
        "running_count": len(running_ids),
        "completed_count": len(completed_ids),
        "failed_count": len(failed_ids),
        "runnable_unit_ids": _unit_ids_for_status(units, RUNNABLE_STATUS),
        "blocked_unit_ids": _unit_ids_for_status(units, BLOCKED_STATUS),
        "running_unit_ids": running_ids,
        "completed_unit_ids": completed_ids,
        "failed_unit_ids": failed_ids,
        "event_count": event_count,
    }
    return state


def build_persisted_runner_state(
    *,
    repo_root: Path,
    dag_path: Path | None = None,
    run_id: str = DEFAULT_RUN_ID,
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = now or _now_iso()
    runner_state = build_runner_state(repo_root=repo_root, dag_path=dag_path)
    units = deepcopy(list(runner_state.state_units))
    state = {
        "schema": SCHEMA,
        "run_id": run_id,
        "persistence_format": PERSISTENCE_FORMAT,
        "run_status": PLANNED_STATUS,
        "created_at": timestamp,
        "updated_at": timestamp,
        "ok": runner_state.ok,
        "issues": [issue.as_dict() for issue in runner_state.issues],
        "source": {
            "dag_path": runner_state.dag_path,
            "execution_order": list(runner_state.execution_order),
            "plan_schema": runner_state.plan_schema,
            "plan_runner_status": runner_state.plan_runner_status,
            "runner_state_mode": runner_state.runner_mode,
        },
        "units": units,
        "artifacts": [],
        "events": [
            {
                "timestamp": timestamp,
                "kind": "run_planned",
                "unit_id": "",
                "from_status": "",
                "to_status": PLANNED_STATUS,
                "detail": "persisted global DAG runner state created",
            }
        ],
        "provenance": {
            "source_dag": runner_state.dag_path,
            "source_plan_schema": runner_state.plan_schema,
            "source_runner_state_schema": runner_state.schema,
            "dispatch_mode": "operator_controlled_preview",
            "real_app_execution": False,
        },
    }
    return _refresh_persisted_summary(state)


def write_runner_state(path: Path, state: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_runner_state(path: Path) -> dict[str, Any]:
    state = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError(f"runner state must be a JSON object: {path}")
    return state


def persist_runner_state(
    *,
    repo_root: Path,
    output_path: Path,
    dag_path: Path | None = None,
    run_id: str = DEFAULT_RUN_ID,
    now: str | None = None,
) -> RunnerStatePersistenceProof:
    issues: list[RunnerStateIssue] = []
    state = build_persisted_runner_state(
        repo_root=repo_root,
        dag_path=dag_path,
        run_id=run_id,
        now=now,
    )
    path = write_runner_state(output_path, state)
    reloaded = load_runner_state(path)
    if state != reloaded:
        issues.append(_issue("persistence.round_trip", "runner state changed after JSON write/read"))
    return RunnerStatePersistenceProof(
        ok=not issues and bool(state.get("ok", False)),
        issues=tuple(issues),
        path=str(path),
        runner_state=state,
        reloaded_state=reloaded,
    )


def dispatch_next_runnable(
    state: Mapping[str, Any],
    *,
    now: str | None = None,
) -> RunnerDispatchResult:
    timestamp = now or _now_iso()
    mutable_state = deepcopy(dict(state))
    units = _unit_rows(mutable_state)
    if "units" not in mutable_state:
        mutable_state["units"] = units
    events = mutable_state.get("events")
    if not isinstance(events, list):
        events = []
        mutable_state["events"] = events

    for unit in units:
        if unit.get("dispatch_status") != RUNNABLE_STATUS:
            continue
        unit_id = str(unit.get("id", ""))
        unit["dispatch_status"] = RUNNING_STATUS
        timestamps = unit.setdefault("timestamps", {})
        if isinstance(timestamps, dict):
            timestamps.setdefault("created_at", mutable_state.get("created_at", timestamp))
            timestamps["started_at"] = timestamp
            timestamps["updated_at"] = timestamp
        unit["operator_ui"] = {
            "state": RUNNING_STATUS,
            "severity": "info",
            "message": f"{unit_id} was dispatched by the operator preview. No app execution has been claimed.",
            "blocked_by_artifacts": [],
        }
        mutable_state["updated_at"] = timestamp
        events.append(
            {
                "timestamp": timestamp,
                "kind": "unit_dispatched",
                "unit_id": unit_id,
                "from_status": RUNNABLE_STATUS,
                "to_status": RUNNING_STATUS,
                "detail": "operator dispatched the next runnable unit without executing the app",
            }
        )
        _refresh_persisted_summary(mutable_state)
        return RunnerDispatchResult(
            ok=True,
            message=f"Dispatched `{unit_id}` into running state.",
            dispatched_unit_id=unit_id,
            state=mutable_state,
        )

    _refresh_persisted_summary(mutable_state)
    return RunnerDispatchResult(
        ok=False,
        message="No runnable global DAG unit is available to dispatch.",
        dispatched_unit_id="",
        state=mutable_state,
    )


def build_runner_state(
    *,
    repo_root: Path,
    dag_path: Path | None = None,
) -> RunnerState:
    plan = build_execution_plan(repo_root=repo_root, dag_path=dag_path)
    issues = [
        _issue(f"execution_plan.{issue.location}", issue.message)
        for issue in plan.issues
    ]

    state_units: list[dict[str, Any]] = []
    for unit in plan.runnable_units:
        unit_id = str(unit.get("id", ""))
        dependencies = [
            dependency
            for dependency in unit.get("artifact_dependencies", [])
            if isinstance(dependency, dict)
        ]
        dispatch_status = RUNNABLE_STATUS if unit.get("ready") is True else BLOCKED_STATUS
        state_units.append(
            {
                "id": unit_id,
                "order_index": unit.get("order_index"),
                "app": str(unit.get("app", "")),
                "plan_status": str(unit.get("status", "")),
                "plan_runner_status": str(unit.get("runner_status", "")),
                "dispatch_status": dispatch_status,
                "depends_on": _as_str_list(unit.get("depends_on")),
                "artifact_dependencies": dependencies,
                "transitions": _transitions_for_unit(dependencies),
                "retry": _retry_metadata(unit_id),
                "partial_rerun": _partial_rerun_metadata(unit),
                "operator_ui": _operator_ui_state(unit_id, dependencies),
                "provenance": _provenance(plan, unit),
            }
        )

    return RunnerState(
        ok=plan.ok and not issues and bool(state_units),
        issues=tuple(issues),
        schema=SCHEMA,
        runner_mode=RUNNER_MODE,
        run_status=RUN_STATUS,
        dag_path=plan.dag_path,
        plan_schema=plan.schema,
        plan_runner_status=plan.runner_status,
        execution_order=plan.execution_order,
        state_units=tuple(state_units),
    )


__all__ = [
    "BLOCKED_STATUS",
    "COMPLETED_STATUS",
    "DEFAULT_RUN_ID",
    "FAILED_STATUS",
    "PERSISTENCE_FORMAT",
    "PLANNED_STATUS",
    "RUNNER_MODE",
    "RUNNING_STATUS",
    "RUNNABLE_STATUS",
    "RUN_STATUS",
    "RunnerDispatchResult",
    "RunnerState",
    "RunnerStateIssue",
    "RunnerStatePersistenceProof",
    "SCHEMA",
    "build_persisted_runner_state",
    "build_runner_state",
    "dispatch_next_runnable",
    "load_runner_state",
    "persist_runner_state",
    "write_runner_state",
]
