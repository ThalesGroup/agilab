from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Protocol

from .dag_execution_registry import (
    CONTROLLED_CONTRACT_RUNNER_STATUS,
    FLIGHT_CONTEXT_UNIT_ID,
    FLIGHT_REDUCE_SUMMARY_ARTIFACT_ID,
    FLIGHT_TO_METEO_ADAPTER,
    FORECAST_METRICS_ARTIFACT_ID,
    METEO_FORECAST_REVIEW_UNIT_ID,
    QUEUE_UNIT_ID,
    RELAY_UNIT_ID,
    UAV_QUEUE_ADAPTER,
)
from .global_pipeline_app_dispatch_smoke import (
    run_queue_baseline_app,
    run_relay_followup_app,
)

GLOBAL_DAG_REAL_RUN_DIRNAME = "global_dag_real_runs"
GLOBAL_DAG_REAL_EXECUTION_SCOPE = "controlled_uav_queue_to_relay_stage"
GLOBAL_DAG_CONTRACT_EXECUTION_SCOPE = "controlled_flight_to_meteo_stage"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class DagStageExecutionResult:
    ok: bool
    message: str
    state: dict[str, Any]
    executed_unit_id: str = ""


@dataclass(frozen=True)
class DagExecutionContext:
    repo_root: Path
    lab_dir: Path
    run_queue_fn: Callable[..., Mapping[str, Any]] | None = None
    run_relay_fn: Callable[..., Mapping[str, Any]] | None = None
    stage_run_fns: Mapping[str, Callable[..., Mapping[str, Any]]] | None = None
    now_fn: Callable[[], str] = _now_iso


class DagExecutionAdapter(Protocol):
    adapter_id: str

    def run_next(
        self,
        state: Mapping[str, Any],
        context: DagExecutionContext,
    ) -> DagStageExecutionResult:
        ...


class UavQueueToRelayExecutionAdapter:
    adapter_id = UAV_QUEUE_ADAPTER

    def run_next(
        self,
        state: Mapping[str, Any],
        context: DagExecutionContext,
    ) -> DagStageExecutionResult:
        return _run_next_uav_queue_to_relay_stage(state, context=context)


class FlightToMeteoExecutionAdapter:
    adapter_id = FLIGHT_TO_METEO_ADAPTER

    def run_next(
        self,
        state: Mapping[str, Any],
        context: DagExecutionContext,
    ) -> DagStageExecutionResult:
        return _run_next_flight_to_meteo_stage(state, context=context)


DAG_EXECUTION_ADAPTERS_BY_ID: Mapping[str, DagExecutionAdapter] = {
    UavQueueToRelayExecutionAdapter.adapter_id: UavQueueToRelayExecutionAdapter(),
    FlightToMeteoExecutionAdapter.adapter_id: FlightToMeteoExecutionAdapter(),
}


def registered_execution_adapter_ids() -> tuple[str, ...]:
    return tuple(sorted(DAG_EXECUTION_ADAPTERS_BY_ID))


def run_next_adapter_stage(
    adapter_id: str,
    state: Mapping[str, Any],
    context: DagExecutionContext,
) -> DagStageExecutionResult:
    adapter = DAG_EXECUTION_ADAPTERS_BY_ID.get(adapter_id)
    if adapter is None:
        return DagStageExecutionResult(
            ok=False,
            message=f"No DAG execution adapter is registered for `{adapter_id}`.",
            state=dict(state),
        )
    return adapter.run_next(state, context)


def dag_units(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    units = state.get("units", [])
    if not isinstance(units, list):
        return []
    return [unit for unit in units if isinstance(unit, dict)]


def available_artifact_ids(state: Mapping[str, Any]) -> set[str]:
    artifacts = state.get("artifacts", [])
    if not isinstance(artifacts, list):
        return set()
    return {
        str(artifact.get("artifact", ""))
        for artifact in artifacts
        if isinstance(artifact, dict)
        and artifact.get("status") == "available"
        and str(artifact.get("artifact", ""))
    }


def _run_next_uav_queue_to_relay_stage(
    state: Mapping[str, Any],
    *,
    context: DagExecutionContext,
) -> DagStageExecutionResult:
    mutable_state = deepcopy(dict(state))
    run_queue_fn = context.run_queue_fn or run_queue_baseline_app
    run_relay_fn = context.run_relay_fn or run_relay_followup_app

    queue = _dag_unit(mutable_state, QUEUE_UNIT_ID)
    relay = _dag_unit(mutable_state, RELAY_UNIT_ID)
    if not isinstance(queue, dict) or not isinstance(relay, dict):
        return DagStageExecutionResult(
            ok=False,
            message="The controlled DAG state is missing the expected queue or relay stage.",
            state=mutable_state,
        )

    queue_status = str(queue.get("dispatch_status", ""))
    relay_status = str(relay.get("dispatch_status", ""))
    timestamp = context.now_fn()
    if queue_status == "runnable":
        run_root = _real_run_root(context.lab_dir, QUEUE_UNIT_ID)
        result = dict(run_queue_fn(repo_root=context.repo_root, run_root=run_root))
        _mark_controlled_stage_execution(
            mutable_state,
            queue,
            result=result,
            timestamp=timestamp,
            artifact_id="queue_metrics",
            reduce_artifact_id="queue_reduce_summary",
        )
        _unblock_relay_after_queue(mutable_state, timestamp=timestamp)
        _update_real_execution_provenance(
            mutable_state,
            executed_unit_id=QUEUE_UNIT_ID,
            timestamp=timestamp,
        )
        _refresh_summary(mutable_state)
        return DagStageExecutionResult(
            ok=True,
            message=f"Executed `{QUEUE_UNIT_ID}` and published `queue_metrics`.",
            state=mutable_state,
            executed_unit_id=QUEUE_UNIT_ID,
        )

    if relay_status in {"runnable", "blocked"} and "queue_metrics" in available_artifact_ids(mutable_state):
        if relay_status == "blocked":
            _unblock_relay_after_queue(mutable_state, timestamp=timestamp)
        run_root = _real_run_root(context.lab_dir, RELAY_UNIT_ID)
        queue_result = _queue_result_for_relay(mutable_state)
        result = dict(run_relay_fn(repo_root=context.repo_root, run_root=run_root, queue_result=queue_result))
        _mark_controlled_stage_execution(
            mutable_state,
            relay,
            result=result,
            timestamp=timestamp,
            artifact_id="relay_metrics",
            reduce_artifact_id="relay_reduce_summary",
        )
        _update_real_execution_provenance(
            mutable_state,
            executed_unit_id=RELAY_UNIT_ID,
            timestamp=timestamp,
        )
        _refresh_summary(mutable_state)
        return DagStageExecutionResult(
            ok=True,
            message=f"Executed `{RELAY_UNIT_ID}` and published `relay_metrics`.",
            state=mutable_state,
            executed_unit_id=RELAY_UNIT_ID,
        )

    _refresh_summary(mutable_state)
    return DagStageExecutionResult(
        ok=False,
        message="No controlled real DAG stage is ready to run.",
        state=mutable_state,
    )


def _run_next_flight_to_meteo_stage(
    state: Mapping[str, Any],
    *,
    context: DagExecutionContext,
) -> DagStageExecutionResult:
    mutable_state = deepcopy(dict(state))
    flight = _dag_unit(mutable_state, FLIGHT_CONTEXT_UNIT_ID)
    meteo = _dag_unit(mutable_state, METEO_FORECAST_REVIEW_UNIT_ID)
    if not isinstance(flight, dict) or not isinstance(meteo, dict):
        return DagStageExecutionResult(
            ok=False,
            message="The controlled DAG state is missing the expected flight or meteo stage.",
            state=mutable_state,
        )

    timestamp = context.now_fn()
    flight_status = str(flight.get("dispatch_status", ""))
    meteo_status = str(meteo.get("dispatch_status", ""))
    if flight_status == "runnable":
        result = _contract_stage_result(
            context,
            unit_id=FLIGHT_CONTEXT_UNIT_ID,
            artifact_id=FLIGHT_REDUCE_SUMMARY_ARTIFACT_ID,
            artifact_kind="reduce_summary",
            timestamp=timestamp,
        )
        _mark_controlled_stage_execution(
            mutable_state,
            flight,
            result=result,
            timestamp=timestamp,
            artifact_id=FLIGHT_REDUCE_SUMMARY_ARTIFACT_ID,
            reduce_artifact_id=None,
            artifact_kind="reduce_summary",
            artifact_path_key="reduce_artifact_path",
            execution_mode="contract_adapter",
            execution_payload_key="contract_execution",
            operator_message=(
                f"{FLIGHT_CONTEXT_UNIT_ID} completed through the controlled DAG contract adapter."
            ),
            artifact_available_detail=(
                f"{FLIGHT_REDUCE_SUMMARY_ARTIFACT_ID} became available after controlled contract execution"
            ),
        )
        _unblock_unit_when_artifacts_available(mutable_state, meteo, timestamp=timestamp)
        _update_real_execution_provenance(
            mutable_state,
            executed_unit_id=FLIGHT_CONTEXT_UNIT_ID,
            timestamp=timestamp,
            dispatch_mode=CONTROLLED_CONTRACT_RUNNER_STATUS,
            real_app_execution=False,
            execution_scope=GLOBAL_DAG_CONTRACT_EXECUTION_SCOPE,
        )
        _refresh_summary(mutable_state)
        return DagStageExecutionResult(
            ok=True,
            message=f"Executed `{FLIGHT_CONTEXT_UNIT_ID}` and published `{FLIGHT_REDUCE_SUMMARY_ARTIFACT_ID}`.",
            state=mutable_state,
            executed_unit_id=FLIGHT_CONTEXT_UNIT_ID,
        )

    if meteo_status == "blocked":
        _unblock_unit_when_artifacts_available(mutable_state, meteo, timestamp=timestamp)
        meteo_status = str(meteo.get("dispatch_status", ""))
    if meteo_status == "runnable":
        result = _contract_stage_result(
            context,
            unit_id=METEO_FORECAST_REVIEW_UNIT_ID,
            artifact_id=FORECAST_METRICS_ARTIFACT_ID,
            artifact_kind="summary_metrics",
            timestamp=timestamp,
        )
        _mark_controlled_stage_execution(
            mutable_state,
            meteo,
            result=result,
            timestamp=timestamp,
            artifact_id=FORECAST_METRICS_ARTIFACT_ID,
            reduce_artifact_id=None,
            artifact_kind="summary_metrics",
            artifact_path_key="summary_metrics_path",
            execution_mode="contract_adapter",
            execution_payload_key="contract_execution",
            operator_message=(
                f"{METEO_FORECAST_REVIEW_UNIT_ID} completed through the controlled DAG contract adapter."
            ),
            artifact_available_detail=(
                f"{FORECAST_METRICS_ARTIFACT_ID} became available after controlled contract execution"
            ),
        )
        _update_real_execution_provenance(
            mutable_state,
            executed_unit_id=METEO_FORECAST_REVIEW_UNIT_ID,
            timestamp=timestamp,
            dispatch_mode=CONTROLLED_CONTRACT_RUNNER_STATUS,
            real_app_execution=False,
            execution_scope=GLOBAL_DAG_CONTRACT_EXECUTION_SCOPE,
        )
        _refresh_summary(mutable_state)
        return DagStageExecutionResult(
            ok=True,
            message=f"Executed `{METEO_FORECAST_REVIEW_UNIT_ID}` and published `{FORECAST_METRICS_ARTIFACT_ID}`.",
            state=mutable_state,
            executed_unit_id=METEO_FORECAST_REVIEW_UNIT_ID,
        )

    _refresh_summary(mutable_state)
    return DagStageExecutionResult(
        ok=False,
        message="No controlled contract DAG stage is ready to run.",
        state=mutable_state,
    )


def _contract_stage_result(
    context: DagExecutionContext,
    *,
    unit_id: str,
    artifact_id: str,
    artifact_kind: str,
    timestamp: str,
) -> dict[str, Any]:
    run_root = _real_run_root(context.lab_dir, unit_id)
    runner = (context.stage_run_fns or {}).get(unit_id)
    if runner is not None:
        return dict(runner(repo_root=context.repo_root, run_root=run_root))

    run_root.mkdir(parents=True, exist_ok=True)
    artifact_path = run_root / f"{artifact_id}.json"
    artifact_payload = {
        "schema": "agilab.dag_contract_stage_result.v1",
        "unit_id": unit_id,
        "artifact": artifact_id,
        "artifact_kind": artifact_kind,
        "created_at": timestamp,
        "execution_mode": "controlled_contract_stage_execution",
    }
    artifact_path.write_text(json.dumps(artifact_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = {
        "contract_artifact_path": str(artifact_path),
        "reduce_artifact_path": str(artifact_path),
        "summary_metrics_path": str(artifact_path),
        "summary_metrics": {
            "contract_artifacts": 1,
            "stage_completed": 1,
        },
    }
    return result


def _real_run_root(lab_dir: Path, unit_id: str) -> Path:
    safe_unit_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", unit_id).strip("-") or "stage"
    return lab_dir / ".agilab" / GLOBAL_DAG_REAL_RUN_DIRNAME / safe_unit_id


def _dag_unit(state: Mapping[str, Any], unit_id: str) -> dict[str, Any] | None:
    for unit in dag_units(state):
        if str(unit.get("id", "")) == unit_id:
            return unit
    return None


def _events(state: dict[str, Any]) -> list[dict[str, Any]]:
    events = state.get("events")
    if not isinstance(events, list):
        events = []
        state["events"] = events
    return events


def _append_event(
    state: dict[str, Any],
    *,
    timestamp: str,
    kind: str,
    unit_id: str,
    from_status: str,
    to_status: str,
    detail: str,
) -> None:
    _events(state).append(
        {
            "timestamp": timestamp,
            "kind": kind,
            "unit_id": unit_id,
            "from_status": from_status,
            "to_status": to_status,
            "detail": detail,
        }
    )


def _replace_artifact(state: dict[str, Any], artifact: dict[str, Any]) -> None:
    artifact_id = str(artifact.get("artifact", "")).strip()
    if not artifact_id:
        return
    artifacts = state.get("artifacts")
    if not isinstance(artifacts, list):
        artifacts = []
        state["artifacts"] = artifacts
    artifacts[:] = [
        row
        for row in artifacts
        if not isinstance(row, dict) or str(row.get("artifact", "")).strip() != artifact_id
    ]
    artifacts.append(artifact)


def _refresh_summary(state: dict[str, Any]) -> dict[str, Any]:
    units = dag_units(state)
    previous_summary = state.get("summary")
    previous_summary = previous_summary if isinstance(previous_summary, dict) else {}
    provenance = state.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    running_ids = [
        str(unit.get("id", ""))
        for unit in units
        if unit.get("dispatch_status") == "running" and str(unit.get("id", ""))
    ]
    completed_ids = [
        str(unit.get("id", ""))
        for unit in units
        if unit.get("dispatch_status") == "completed" and str(unit.get("id", ""))
    ]
    failed_ids = [
        str(unit.get("id", ""))
        for unit in units
        if unit.get("dispatch_status") == "failed" and str(unit.get("id", ""))
    ]
    runnable_ids = [
        str(unit.get("id", ""))
        for unit in units
        if unit.get("dispatch_status") == "runnable" and str(unit.get("id", ""))
    ]
    blocked_ids = [
        str(unit.get("id", ""))
        for unit in units
        if unit.get("dispatch_status") == "blocked" and str(unit.get("id", ""))
    ]
    planned_count = sum(
        1
        for unit in units
        if unit.get("dispatch_status") in {"runnable", "blocked", "pending", ""}
    )
    events = state.get("events", [])
    state["summary"] = {
        "unit_count": len(units),
        "planned_count": planned_count,
        "running_count": len(running_ids),
        "completed_count": len(completed_ids),
        "failed_count": len(failed_ids),
        "runnable_unit_ids": runnable_ids,
        "blocked_unit_ids": blocked_ids,
        "running_unit_ids": running_ids,
        "completed_unit_ids": completed_ids,
        "failed_unit_ids": failed_ids,
        "available_artifact_ids": sorted(available_artifact_ids(state)),
        "event_count": len(events) if isinstance(events, list) else 0,
    }
    real_executed_ids = provenance.get("real_executed_unit_ids", previous_summary.get("real_executed_unit_ids", []))
    if isinstance(real_executed_ids, list) and real_executed_ids:
        state["summary"]["real_executed_unit_ids"] = [str(unit_id) for unit_id in real_executed_ids if str(unit_id)]
    real_scope = provenance.get("real_execution_scope", previous_summary.get("real_execution_scope", ""))
    if real_scope:
        state["summary"]["real_execution_scope"] = str(real_scope)
    controlled_executed_ids = provenance.get(
        "controlled_executed_unit_ids",
        previous_summary.get("controlled_executed_unit_ids", []),
    )
    if isinstance(controlled_executed_ids, list) and controlled_executed_ids:
        state["summary"]["controlled_executed_unit_ids"] = [
            str(unit_id) for unit_id in controlled_executed_ids if str(unit_id)
        ]
    controlled_scope = provenance.get(
        "controlled_execution_scope",
        previous_summary.get("controlled_execution_scope", ""),
    )
    if controlled_scope:
        state["summary"]["controlled_execution_scope"] = str(controlled_scope)
    if failed_ids:
        state["run_status"] = "failed"
    elif units and len(completed_ids) == len(units):
        state["run_status"] = "completed"
    elif running_ids or completed_ids:
        state["run_status"] = "running"
    else:
        state["run_status"] = "planned"
    return state


def _mark_controlled_stage_execution(
    state: dict[str, Any],
    unit: dict[str, Any],
    *,
    result: dict[str, Any],
    timestamp: str,
    artifact_id: str,
    reduce_artifact_id: str | None,
    artifact_kind: str = "summary_metrics",
    artifact_path_key: str = "summary_metrics_path",
    execution_mode: str = "real_app_entry",
    execution_payload_key: str = "real_execution",
    operator_message: str | None = None,
    artifact_available_detail: str | None = None,
) -> None:
    unit_id = str(unit.get("id", ""))
    previous_status = str(unit.get("dispatch_status", ""))
    unit["dispatch_status"] = "completed"
    unit["execution_mode"] = execution_mode
    timestamps = unit.setdefault("timestamps", {})
    if isinstance(timestamps, dict):
        timestamps.setdefault("created_at", state.get("created_at", timestamp))
        timestamps["started_at"] = timestamp
        timestamps["completed_at"] = timestamp
        timestamps["updated_at"] = timestamp
    unit["operator_ui"] = {
        "state": "completed",
        "severity": "success",
        "message": operator_message or f"{unit_id} executed through the controlled AGILAB app entrypoint.",
        "blocked_by_artifacts": [],
    }
    unit[execution_payload_key] = result
    produces: list[dict[str, Any]] = []
    artifact_attached = False
    primary_path = str(
        result.get(artifact_path_key, "")
        or result.get("summary_metrics_path", "")
        or result.get("reduce_artifact_path", "")
    )
    for artifact in unit.get("produces", []):
        if not isinstance(artifact, dict):
            continue
        if str(artifact.get("artifact", "")) == artifact_id:
            artifact_attached = True
            produces.append(
                {
                    **artifact,
                    "kind": artifact_kind,
                    "path": primary_path,
                }
            )
        else:
            produces.append(artifact)
    if not artifact_attached:
        produces.append(
            {
                "artifact": artifact_id,
                "kind": artifact_kind,
                "path": primary_path,
            }
        )
    unit["produces"] = produces
    metrics = result.get("summary_metrics", {})
    metrics = metrics if isinstance(metrics, dict) else {}
    artifact_record: dict[str, Any] = {
        "artifact": artifact_id,
        "kind": artifact_kind,
        "path": primary_path,
        "producer": unit_id,
        "status": "available",
        "available_at": timestamp,
        "execution_mode": execution_mode,
    }
    if "packets_generated" in metrics:
        artifact_record["packets_generated"] = int(metrics.get("packets_generated", 0) or 0)
    if "packets_delivered" in metrics:
        artifact_record["packets_delivered"] = int(metrics.get("packets_delivered", 0) or 0)
    _replace_artifact(
        state,
        artifact_record,
    )
    if reduce_artifact_id:
        _replace_artifact(
            state,
            {
                "artifact": reduce_artifact_id,
                "kind": "reduce_artifact",
                "path": str(result.get("reduce_artifact_path", "")),
                "producer": unit_id,
                "status": "available",
                "available_at": timestamp,
                "execution_mode": execution_mode,
            },
        )
    _append_event(
        state,
        timestamp=timestamp,
        kind="unit_completed",
        unit_id=unit_id,
        from_status=previous_status,
        to_status="completed",
        detail=f"{unit_id} completed through the controlled AGILAB app entrypoint",
    )
    _append_event(
        state,
        timestamp=timestamp,
        kind="artifact_available",
        unit_id=unit_id,
        from_status="missing",
        to_status="available",
        detail=artifact_available_detail or f"{artifact_id} became available after real app execution",
    )


def _unblock_unit_when_artifacts_available(
    state: dict[str, Any],
    unit: dict[str, Any],
    *,
    timestamp: str,
) -> bool:
    if str(unit.get("dispatch_status", "")) != "blocked":
        return False
    dependencies = [
        str(dependency.get("artifact", "")).strip()
        for dependency in unit.get("artifact_dependencies", [])
        if isinstance(dependency, dict) and str(dependency.get("artifact", "")).strip()
    ]
    missing = [artifact for artifact in dependencies if artifact not in available_artifact_ids(state)]
    if missing:
        return False
    unit_id = str(unit.get("id", ""))
    previous_status = str(unit.get("dispatch_status", ""))
    unit["dispatch_status"] = "runnable"
    unit["unblocked_by"] = dependencies
    timestamps = unit.setdefault("timestamps", {})
    if isinstance(timestamps, dict):
        timestamps["unblocked_at"] = timestamp
        timestamps["updated_at"] = timestamp
    dependency_text = ", ".join(dependencies) if dependencies else "the DAG contract"
    unit["operator_ui"] = {
        "state": "ready_to_dispatch",
        "severity": "info",
        "message": f"{unit_id} is ready because {dependency_text} is available.",
        "blocked_by_artifacts": [],
    }
    _append_event(
        state,
        timestamp=timestamp,
        kind="unit_unblocked",
        unit_id=unit_id,
        from_status=previous_status,
        to_status="runnable",
        detail=f"{unit_id} readiness satisfied by {dependency_text}",
    )
    return True


def _unblock_relay_after_queue(state: dict[str, Any], *, timestamp: str) -> None:
    relay = _dag_unit(state, RELAY_UNIT_ID)
    if not isinstance(relay, dict) or str(relay.get("dispatch_status", "")) != "blocked":
        return
    previous_status = str(relay.get("dispatch_status", ""))
    relay["dispatch_status"] = "runnable"
    relay["unblocked_by"] = ["queue_metrics"]
    timestamps = relay.setdefault("timestamps", {})
    if isinstance(timestamps, dict):
        timestamps["unblocked_at"] = timestamp
        timestamps["updated_at"] = timestamp
    relay["operator_ui"] = {
        "state": "ready_to_dispatch",
        "severity": "info",
        "message": f"{RELAY_UNIT_ID} is ready because queue_metrics is available.",
        "blocked_by_artifacts": [],
    }
    _append_event(
        state,
        timestamp=timestamp,
        kind="unit_unblocked",
        unit_id=RELAY_UNIT_ID,
        from_status=previous_status,
        to_status="runnable",
        detail="relay_followup readiness satisfied by queue_metrics",
    )


def _queue_result_for_relay(state: Mapping[str, Any]) -> dict[str, Any]:
    queue = _dag_unit(state, QUEUE_UNIT_ID)
    real_execution = queue.get("real_execution") if isinstance(queue, dict) else None
    if isinstance(real_execution, dict) and real_execution.get("summary_metrics_path"):
        return real_execution
    for artifact in state.get("artifacts", []):
        if (
            isinstance(artifact, dict)
            and artifact.get("artifact") == "queue_metrics"
            and artifact.get("status") == "available"
        ):
            return {"summary_metrics_path": str(artifact.get("path", ""))}
    return {}


def _update_real_execution_provenance(
    state: dict[str, Any],
    *,
    executed_unit_id: str,
    timestamp: str,
    dispatch_mode: str = "controlled_real_stage_execution",
    real_app_execution: bool = True,
    execution_scope: str = GLOBAL_DAG_REAL_EXECUTION_SCOPE,
) -> None:
    provenance = state.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
        state["provenance"] = provenance
    executed = provenance.get("real_executed_unit_ids", [])
    if not isinstance(executed, list):
        executed = []
    if executed_unit_id not in executed:
        executed.append(executed_unit_id)
    controlled_executed = provenance.get("controlled_executed_unit_ids", [])
    if not isinstance(controlled_executed, list):
        controlled_executed = []
    if executed_unit_id not in controlled_executed:
        controlled_executed.append(executed_unit_id)
    update_payload: dict[str, Any] = {
        "dispatch_mode": dispatch_mode,
        "controlled_execution": True,
        "controlled_execution_scope": execution_scope,
        "controlled_executed_unit_ids": controlled_executed,
        "real_app_execution": real_app_execution,
    }
    if real_app_execution:
        update_payload.update(
            {
                "real_execution_scope": execution_scope,
                "real_executed_unit_ids": executed,
            }
        )
    provenance.update(
        update_payload,
    )
    state["updated_at"] = timestamp
    summary = state.get("summary")
    if isinstance(summary, dict):
        summary["controlled_executed_unit_ids"] = controlled_executed
        summary["controlled_execution_scope"] = execution_scope
        if real_app_execution:
            summary["real_executed_unit_ids"] = executed
            summary["real_execution_scope"] = execution_scope
