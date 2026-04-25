# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Real first-unit dispatch smoke for AGILAB global pipeline DAGs."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, Mapping

from agilab.global_pipeline_dispatch_state import (
    PERSISTENCE_FORMAT,
    SCHEMA as DISPATCH_STATE_SCHEMA,
    load_dispatch_state,
    write_dispatch_state,
)
from agilab.global_pipeline_execution_plan import build_execution_plan
from agilab.global_pipeline_runner_state import build_runner_state


SCHEMA = "agilab.global_pipeline_app_dispatch_smoke.v1"
DEFAULT_RUN_ID = "global-dag-real-dispatch-smoke"
REAL_UNIT_ID = "queue_baseline"
READY_ONLY_UNIT_ID = "relay_followup"
CREATED_AT = "2026-04-25T00:00:00Z"
QUEUE_STARTED_AT = "2026-04-25T00:00:01Z"
QUEUE_COMPLETED_AT = "2026-04-25T00:00:02Z"
RELAY_RUNNABLE_AT = "2026-04-25T00:00:03Z"
PERSISTED_AT = "2026-04-25T00:00:04Z"


@dataclass(frozen=True)
class AppDispatchSmokeIssue:
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
class AppDispatchSmokeProof:
    ok: bool
    issues: tuple[AppDispatchSmokeIssue, ...]
    path: str
    dispatch_state: dict[str, Any]
    reloaded_state: dict[str, Any]

    @property
    def round_trip_ok(self) -> bool:
        return self.dispatch_state == self.reloaded_state

    @property
    def completed_unit_ids(self) -> tuple[str, ...]:
        return _unit_ids_for_status(self.dispatch_state, "completed")

    @property
    def runnable_unit_ids(self) -> tuple[str, ...]:
        return _unit_ids_for_status(self.dispatch_state, "runnable")

    @property
    def real_executed_unit_ids(self) -> tuple[str, ...]:
        summary = self.dispatch_state.get("summary", {})
        values = summary.get("real_executed_unit_ids", [])
        return tuple(str(value) for value in values if str(value))

    @property
    def readiness_only_unit_ids(self) -> tuple[str, ...]:
        summary = self.dispatch_state.get("summary", {})
        values = summary.get("readiness_only_unit_ids", [])
        return tuple(str(value) for value in values if str(value))

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
    def event_count(self) -> int:
        events = self.dispatch_state.get("events", [])
        return len(events) if isinstance(events, list) else 0

    @property
    def packet_count(self) -> int:
        metrics = _queue_metrics(self.dispatch_state)
        return int(metrics.get("packets_generated", 0) or 0)

    @property
    def summary_metric_paths(self) -> tuple[str, ...]:
        artifacts = self.dispatch_state.get("artifacts", [])
        if not isinstance(artifacts, list):
            return ()
        return tuple(
            str(artifact.get("path", ""))
            for artifact in artifacts
            if isinstance(artifact, dict) and artifact.get("artifact") == "queue_metrics"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [issue.as_dict() for issue in self.issues],
            "path": self.path,
            "round_trip_ok": self.round_trip_ok,
            "completed_unit_ids": list(self.completed_unit_ids),
            "runnable_unit_ids": list(self.runnable_unit_ids),
            "real_executed_unit_ids": list(self.real_executed_unit_ids),
            "readiness_only_unit_ids": list(self.readiness_only_unit_ids),
            "available_artifact_ids": list(self.available_artifact_ids),
            "event_count": self.event_count,
            "packet_count": self.packet_count,
            "summary_metric_paths": list(self.summary_metric_paths),
            "dispatch_state": self.dispatch_state,
            "reloaded_state": self.reloaded_state,
        }


def _issue(location: str, message: str) -> AppDispatchSmokeIssue:
    return AppDispatchSmokeIssue(level="error", location=location, message=message)


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


def _queue_metrics(state: Mapping[str, Any]) -> dict[str, Any]:
    for unit in _unit_rows(state):
        if unit.get("id") == REAL_UNIT_ID:
            metrics = unit.get("real_execution", {}).get("summary_metrics", {})
            return metrics if isinstance(metrics, dict) else {}
    return {}


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _ensure_queue_project_on_path(repo_root: Path) -> Path:
    src_root = repo_root / "src" / "agilab" / "apps" / "builtin" / "uav_queue_project" / "src"
    src_text = str(src_root)
    if src_text not in sys.path:
        sys.path.insert(0, src_text)
    return src_root


def _make_env(run_root: Path) -> SimpleNamespace:
    share_root = run_root / "share"
    export_root = run_root / "export"
    share_root.mkdir(parents=True, exist_ok=True)
    export_root.mkdir(parents=True, exist_ok=True)

    def _resolve_share_path(path: str | Path) -> Path:
        candidate = Path(path)
        return candidate if candidate.is_absolute() else share_root / candidate

    return SimpleNamespace(
        verbose=0,
        resolve_share_path=_resolve_share_path,
        home_abs=run_root,
        _is_managed_pc=False,
        AGI_LOCAL_SHARE=str(share_root),
        AGILAB_EXPORT_ABS=export_root,
        target="global_dag_dispatch_smoke",
    )


def run_queue_baseline_app(
    *,
    repo_root: Path,
    run_root: Path,
) -> dict[str, Any]:
    _ensure_queue_project_on_path(repo_root)
    uav_queue = importlib.import_module("uav_queue")
    uav_queue_worker = importlib.import_module("uav_queue_worker")

    env = _make_env(run_root)
    args = uav_queue.UavQueueArgs(
        routing_policy="queue_aware",
        sim_time_s=2.0,
        sampling_interval_s=0.5,
        source_rate_pps=4.0,
        random_seed=2026,
        reset_target=True,
    )
    manager = uav_queue.UavQueue(env, args=args)
    source = sorted(manager.args.data_in.glob("*.json"))[0]

    worker = uav_queue_worker.UavQueueWorker()
    worker.env = env
    worker.args = manager.args.model_dump(mode="json")
    worker._worker_id = 0
    worker.worker_id = 0
    worker.verbose = 0
    worker.start()

    result = worker.work_pool(str(source))
    worker.work_done(result)

    metrics = dict(result["summary_metrics"])
    stem = str(metrics["artifact_stem"])
    export_root = env.AGILAB_EXPORT_ABS / env.target / "queue_analysis" / stem
    result_root = Path(worker.data_out) / stem
    summary_path = export_root / f"{stem}_summary_metrics.json"
    reduce_path = export_root / "reduce_summary_worker_0.json"
    if not summary_path.is_file():
        raise FileNotFoundError(f"UAV queue summary metrics were not written: {summary_path}")
    if not reduce_path.is_file():
        raise FileNotFoundError(f"UAV queue reduce artifact was not written: {reduce_path}")

    return {
        "app_entry": "uav_queue.UavQueue + uav_queue_worker.UavQueueWorker",
        "source_scenario": _relative(source, run_root),
        "workspace": str(run_root),
        "export_root": _relative(export_root, run_root),
        "result_root": _relative(result_root, run_root),
        "summary_metrics_path": _relative(summary_path, run_root),
        "reduce_artifact_path": _relative(reduce_path, run_root),
        "summary_metrics": metrics,
    }


def _produces_by_id(plan_units: tuple[dict[str, Any], ...]) -> dict[str, list[dict[str, str]]]:
    rows: dict[str, list[dict[str, str]]] = {}
    for unit in plan_units:
        rows[str(unit.get("id", ""))] = [
            {
                "artifact": str(artifact.get("artifact", "")),
                "kind": str(artifact.get("kind", "")),
                "path": str(artifact.get("path", "")),
            }
            for artifact in unit.get("produces", [])
            if isinstance(artifact, dict) and artifact.get("artifact")
        ]
    return rows


def _base_unit(unit: dict[str, Any], produces: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "id": str(unit.get("id", "")),
        "app": str(unit.get("app", "")),
        "order_index": unit.get("order_index"),
        "depends_on": list(unit.get("depends_on", [])),
        "artifact_dependencies": list(unit.get("artifact_dependencies", [])),
        "produces": produces,
        "dispatch_status": str(unit.get("dispatch_status", "")),
        "execution_mode": "readiness_only",
        "retry": {
            "attempt": 0,
            "retry_count": 0,
            "max_attempts": 0,
            "last_error": "",
        },
        "partial_rerun": dict(unit.get("partial_rerun", {})),
        "timestamps": {
            "created_at": CREATED_AT,
            "updated_at": CREATED_AT,
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


def build_app_dispatch_smoke_state(
    *,
    repo_root: Path,
    run_root: Path,
    dag_path: Path | None = None,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    run_root = run_root.resolve()
    plan = build_execution_plan(repo_root=repo_root, dag_path=dag_path)
    runner_state = build_runner_state(repo_root=repo_root, dag_path=dag_path)
    real_result = run_queue_baseline_app(repo_root=repo_root, run_root=run_root)
    produces_by_id = _produces_by_id(plan.runnable_units)

    units = [
        _base_unit(unit, produces_by_id.get(str(unit.get("id", "")), []))
        for unit in runner_state.state_units
    ]
    by_id = {unit["id"]: unit for unit in units}
    queue = by_id[REAL_UNIT_ID]
    relay = by_id[READY_ONLY_UNIT_ID]

    previous_queue_status = str(queue.get("dispatch_status", ""))
    queue["dispatch_status"] = "completed"
    queue["execution_mode"] = "real_app_entry"
    queue["retry"]["attempt"] = 1
    queue["timestamps"]["started_at"] = QUEUE_STARTED_AT
    queue["timestamps"]["completed_at"] = QUEUE_COMPLETED_AT
    queue["timestamps"]["updated_at"] = QUEUE_COMPLETED_AT
    queue["operator_ui"] = {
        "state": "completed",
        "severity": "success",
        "message": "queue_baseline executed via the real UAV queue app entry.",
        "blocked_by_artifacts": [],
    }
    queue["produces"] = [
        {
            **artifact,
            "kind": "summary_metrics",
            "path": real_result["summary_metrics_path"],
        }
        if artifact.get("artifact") == "queue_metrics"
        else artifact
        for artifact in queue["produces"]
    ]
    queue["real_execution"] = real_result

    previous_relay_status = str(relay.get("dispatch_status", ""))
    relay["dispatch_status"] = "runnable"
    relay["execution_mode"] = "readiness_only"
    relay["unblocked_by"] = ["queue_metrics"]
    relay["timestamps"]["unblocked_at"] = RELAY_RUNNABLE_AT
    relay["timestamps"]["updated_at"] = RELAY_RUNNABLE_AT
    relay["operator_ui"] = {
        "state": "ready_to_dispatch",
        "severity": "info",
        "message": "relay_followup is runnable after the real queue_metrics artifact was produced.",
        "blocked_by_artifacts": [],
    }

    metrics = real_result["summary_metrics"]
    artifacts = [
        {
            "artifact": "queue_metrics",
            "kind": "summary_metrics",
            "path": real_result["summary_metrics_path"],
            "producer": REAL_UNIT_ID,
            "status": "available",
            "available_at": QUEUE_COMPLETED_AT,
            "execution_mode": "real_app_entry",
            "packets_generated": int(metrics.get("packets_generated", 0) or 0),
            "packets_delivered": int(metrics.get("packets_delivered", 0) or 0),
        },
        {
            "artifact": "queue_reduce_summary",
            "kind": "reduce_artifact",
            "path": real_result["reduce_artifact_path"],
            "producer": REAL_UNIT_ID,
            "status": "available",
            "available_at": QUEUE_COMPLETED_AT,
            "execution_mode": "real_app_entry",
        },
    ]
    events = [
        _event(
            timestamp=CREATED_AT,
            kind="run_created",
            unit_id="",
            from_status="",
            to_status="created",
            detail="real first-unit global DAG dispatch smoke created",
        ),
        _event(
            timestamp=QUEUE_STARTED_AT,
            kind="unit_started",
            unit_id=REAL_UNIT_ID,
            from_status=previous_queue_status,
            to_status="running",
            detail="started real UAV queue app entry",
        ),
        _event(
            timestamp=QUEUE_COMPLETED_AT,
            kind="unit_completed",
            unit_id=REAL_UNIT_ID,
            from_status="running",
            to_status="completed",
            detail="real UAV queue app entry completed",
        ),
        _event(
            timestamp=QUEUE_COMPLETED_AT,
            kind="artifact_available",
            unit_id=REAL_UNIT_ID,
            from_status="missing",
            to_status="available",
            detail="real queue_metrics artifact became available",
        ),
        _event(
            timestamp=RELAY_RUNNABLE_AT,
            kind="unit_unblocked",
            unit_id=READY_ONLY_UNIT_ID,
            from_status=previous_relay_status,
            to_status="runnable",
            detail="relay_followup readiness satisfied by the real queue_metrics artifact",
        ),
        _event(
            timestamp=PERSISTED_AT,
            kind="state_persisted",
            unit_id="",
            from_status="memory",
            to_status="disk",
            detail="real first-unit dispatch smoke state JSON written and read back",
        ),
    ]

    return {
        "schema": DISPATCH_STATE_SCHEMA,
        "run_id": run_id,
        "persistence_format": PERSISTENCE_FORMAT,
        "run_status": "in_progress",
        "created_at": CREATED_AT,
        "updated_at": PERSISTED_AT,
        "source": {
            "dag_path": runner_state.dag_path,
            "execution_order": list(runner_state.execution_order),
            "plan_schema": runner_state.plan_schema,
            "runner_state_schema": runner_state.schema,
            "runner_state_mode": runner_state.runner_mode,
            "smoke_schema": SCHEMA,
        },
        "summary": {
            "unit_count": len(units),
            "completed_unit_ids": [REAL_UNIT_ID],
            "runnable_unit_ids": [READY_ONLY_UNIT_ID],
            "blocked_unit_ids": [],
            "available_artifact_ids": [artifact["artifact"] for artifact in artifacts],
            "real_executed_unit_ids": [REAL_UNIT_ID],
            "readiness_only_unit_ids": [READY_ONLY_UNIT_ID],
            "real_execution_scope": "first_unit_only",
            "event_count": len(events),
            "packets_generated": int(metrics.get("packets_generated", 0) or 0),
            "packets_delivered": int(metrics.get("packets_delivered", 0) or 0),
        },
        "units": units,
        "artifacts": artifacts,
        "events": events,
        "provenance": {
            "source_dag": runner_state.dag_path,
            "source_plan_schema": runner_state.plan_schema,
            "source_runner_state_schema": runner_state.schema,
            "dispatch_mode": "real_first_unit_dispatch_smoke",
            "real_app_execution": True,
            "real_execution_scope": "first_unit_only",
            "real_executed_unit_ids": [REAL_UNIT_ID],
            "readiness_only_unit_ids": [READY_ONLY_UNIT_ID],
        },
    }


def persist_app_dispatch_smoke(
    *,
    repo_root: Path,
    output_path: Path,
    run_root: Path | None = None,
    dag_path: Path | None = None,
    run_id: str = DEFAULT_RUN_ID,
) -> AppDispatchSmokeProof:
    output_path = output_path.expanduser()
    run_root = (run_root or (output_path.parent / "global_pipeline_app_dispatch_smoke")).expanduser()
    issues: list[AppDispatchSmokeIssue] = []
    state = build_app_dispatch_smoke_state(
        repo_root=repo_root,
        run_root=run_root,
        dag_path=dag_path,
        run_id=run_id,
    )
    path = write_dispatch_state(output_path, state)
    reloaded = load_dispatch_state(path)
    if state != reloaded:
        issues.append(_issue("persistence.round_trip", "app dispatch smoke state changed after JSON write/read"))
    return AppDispatchSmokeProof(
        ok=not issues,
        issues=tuple(issues),
        path=str(path),
        dispatch_state=state,
        reloaded_state=reloaded,
    )


__all__ = [
    "DEFAULT_RUN_ID",
    "READY_ONLY_UNIT_ID",
    "REAL_UNIT_ID",
    "SCHEMA",
    "AppDispatchSmokeIssue",
    "AppDispatchSmokeProof",
    "build_app_dispatch_smoke_state",
    "persist_app_dispatch_smoke",
    "run_queue_baseline_app",
]
