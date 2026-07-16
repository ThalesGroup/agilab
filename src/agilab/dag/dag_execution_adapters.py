from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any, Callable, Mapping, Protocol

from .dag_idempotency import (
    DagExternalExecutionUncertainError,
    execute_idempotently as _execute_idempotently,
    fsync_directory,
    write_json_atomic,
)
from .dag_execution_registry import (
    CONTROLLED_CONTRACT_ADAPTER,
    CONTROLLED_CONTRACT_RUNNER_STATUS,
    QUEUE_UNIT_ID,
    RELAY_UNIT_ID,
    UAV_QUEUE_ADAPTER,
)
from agilab.global_pipeline.global_pipeline_app_dispatch_smoke import (
    run_queue_baseline_app,
    run_relay_followup_app,
)

GLOBAL_DAG_REAL_RUN_DIRNAME = "multi_app_dag_real_runs"
GLOBAL_DAG_REAL_EXECUTION_SCOPE = "controlled_uav_queue_to_relay_stage"
GLOBAL_DAG_CONTRACT_EXECUTION_SCOPE = "controlled_contract_dag_stage"
GLOBAL_DAG_DISTRIBUTED_EXECUTION_SCOPE = "controlled_contract_dag_stage_distributed"
DAG_STAGE_BACKEND_LOCAL = "local"
DAG_STAGE_BACKEND_DISTRIBUTED = "distributed"
_DURABLE_CLAIM_RECEIPT = object()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class DagStageExecutionResult:
    ok: bool
    message: str
    state: dict[str, Any]
    executed_unit_id: str = ""


@dataclass(frozen=True)
class DagBatchExecutionResult:
    ok: bool
    message: str
    state: dict[str, Any]
    executed_unit_ids: tuple[str, ...] = ()
    failed_unit_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DagExecutionContext:
    repo_root: Path
    lab_dir: Path
    run_queue_fn: Callable[..., Mapping[str, Any]] | None = None
    run_relay_fn: Callable[..., Mapping[str, Any]] | None = None
    stage_run_fns: Mapping[str, Callable[..., Mapping[str, Any]]] | None = None
    stage_submit_fn: Callable[..., Mapping[str, Any]] | None = None
    now_fn: Callable[[], str] = _now_iso
    execution_attempt_id: str = ""
    persist_execution_claim_fn: Callable[[Mapping[str, Any]], object] | None = None


def _persist_execution_claim(context: DagExecutionContext, state: dict[str, Any]) -> None:
    """Persist the running claim before invoking any external execution boundary."""

    _refresh_summary(state)
    if context.persist_execution_claim_fn is None:
        raise RuntimeError(
            "Controlled DAG execution requires a durable claim persistence callback; "
            "use the runner-state transaction API."
        )
    receipt = context.persist_execution_claim_fn(state)
    if receipt is not _DURABLE_CLAIM_RECEIPT:
        raise RuntimeError(
            "Controlled DAG execution did not receive a durable claim receipt; "
            "use the runner-state transaction API."
        )


def _unit_idempotency_token(context: DagExecutionContext, unit_id: str) -> str:
    attempt_id = str(context.execution_attempt_id).strip()
    if not attempt_id:
        raise RuntimeError(
            f"Controlled DAG stage `{unit_id}` requires a durable execution attempt and idempotency token."
        )
    return f"{attempt_id}:{unit_id}"


def _unit_persisted_idempotency_token(unit: Mapping[str, Any]) -> str:
    attempt = unit.get("execution_attempt")
    token = str(attempt.get("idempotency_token", "")).strip() if isinstance(attempt, Mapping) else ""
    if not token:
        unit_id = str(unit.get("id", "")).strip() or "stage"
        raise RuntimeError(f"Controlled DAG stage `{unit_id}` is missing its persisted idempotency token.")
    return token


class _DagExecutionAdapter(Protocol):
    adapter_id: str

    def _run_next_uncommitted(
        self,
        state: Mapping[str, Any],
        context: DagExecutionContext,
    ) -> DagStageExecutionResult:
        ...


class _UavQueueToRelayExecutionAdapter:
    adapter_id = UAV_QUEUE_ADAPTER

    def _run_next_uncommitted(
        self,
        state: Mapping[str, Any],
        context: DagExecutionContext,
    ) -> DagStageExecutionResult:
        return _run_next_uav_queue_to_relay_stage(state, context=context)


class _ControlledContractDagExecutionAdapter:
    adapter_id = CONTROLLED_CONTRACT_ADAPTER

    def _run_next_uncommitted(
        self,
        state: Mapping[str, Any],
        context: DagExecutionContext,
    ) -> DagStageExecutionResult:
        return _run_next_controlled_contract_dag_stage(state, context=context)


_DAG_EXECUTION_ADAPTERS_BY_ID: Mapping[str, _DagExecutionAdapter] = {
    _UavQueueToRelayExecutionAdapter.adapter_id: _UavQueueToRelayExecutionAdapter(),
    _ControlledContractDagExecutionAdapter.adapter_id: _ControlledContractDagExecutionAdapter(),
}


def registered_execution_adapter_ids() -> tuple[str, ...]:
    return tuple(sorted(_DAG_EXECUTION_ADAPTERS_BY_ID))


def run_next_adapter_stage(
    adapter_id: str,
    state: Mapping[str, Any],
    context: DagExecutionContext,
) -> DagStageExecutionResult:
    """Reject public execution that cannot own the runner-state transaction."""

    del adapter_id, state, context
    raise RuntimeError(
        "Direct DAG adapter execution is disabled; use "
        "DagRunEngine.run_next_controlled_stage() so the durable claim and "
        "CAS finalization cannot be bypassed."
    )


def _run_next_adapter_stage_uncommitted(
    adapter_id: str,
    state: Mapping[str, Any],
    context: DagExecutionContext,
) -> DagStageExecutionResult:
    adapter = _DAG_EXECUTION_ADAPTERS_BY_ID.get(adapter_id)
    if adapter is None:
        return DagStageExecutionResult(
            ok=False,
            message=f"No DAG execution adapter is registered for `{adapter_id}`.",
            state=dict(state),
        )
    return adapter._run_next_uncommitted(state, context)


def run_ready_adapter_stages(
    adapter_id: str,
    state: Mapping[str, Any],
    context: DagExecutionContext,
    *,
    max_workers: int | None = None,
    execution_backend: str = DAG_STAGE_BACKEND_LOCAL,
) -> DagBatchExecutionResult:
    """Reject public batch execution that cannot own the state transaction."""

    del adapter_id, state, context, max_workers, execution_backend
    raise RuntimeError(
        "Direct DAG adapter batch execution is disabled; use "
        "DagRunEngine.run_ready_controlled_stages() so the durable claim and "
        "CAS finalization cannot be bypassed."
    )


def _run_ready_adapter_stages_uncommitted(
    adapter_id: str,
    state: Mapping[str, Any],
    context: DagExecutionContext,
    *,
    max_workers: int | None = None,
    execution_backend: str = DAG_STAGE_BACKEND_LOCAL,
) -> DagBatchExecutionResult:
    if adapter_id == CONTROLLED_CONTRACT_ADAPTER:
        return _run_ready_controlled_contract_dag_stages(
            state,
            context=context,
            max_workers=max_workers,
            execution_backend=execution_backend,
        )

    result = _run_next_adapter_stage_uncommitted(adapter_id, state, context)
    if result.ok:
        return DagBatchExecutionResult(
            ok=True,
            message=result.message,
            state=result.state,
            executed_unit_ids=(result.executed_unit_id,) if result.executed_unit_id else (),
        )
    return DagBatchExecutionResult(
        ok=False,
        message=result.message,
        state=result.state,
    )


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


def _next_runnable_unit(state: Mapping[str, Any]) -> dict[str, Any] | None:
    for unit in dag_units(state):
        if str(unit.get("dispatch_status", "")) == "runnable":
            return unit
    return None


def _runnable_units(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        unit
        for unit in dag_units(state)
        if str(unit.get("dispatch_status", "")) == "runnable"
    ]


def _unblock_ready_units(state: dict[str, Any], *, timestamp: str) -> None:
    for unit in dag_units(state):
        _unblock_unit_when_artifacts_available(state, unit, timestamp=timestamp)


def _primary_contract_artifact(state: Mapping[str, Any], unit: Mapping[str, Any]) -> dict[str, str]:
    unit_id = str(unit.get("id", "")).strip() or "stage"
    produces = unit.get("produces", [])
    if isinstance(produces, list):
        for artifact in produces:
            if not isinstance(artifact, Mapping):
                continue
            artifact_id = str(artifact.get("artifact", "") or artifact.get("id", "")).strip()
            if not artifact_id:
                continue
            return {
                "artifact": artifact_id,
                "kind": _contract_artifact_kind(artifact_id, str(artifact.get("kind", "")).strip()),
                "path": str(artifact.get("path", "")).strip(),
            }

    for downstream in dag_units(state):
        dependencies = downstream.get("artifact_dependencies", [])
        if not isinstance(dependencies, list):
            continue
        for dependency in dependencies:
            if not isinstance(dependency, Mapping):
                continue
            if str(dependency.get("from", "")).strip() != unit_id:
                continue
            artifact_id = str(dependency.get("artifact", "")).strip()
            if not artifact_id:
                continue
            return {
                "artifact": artifact_id,
                "kind": _contract_artifact_kind(artifact_id, ""),
                "path": str(dependency.get("source_path", "")).strip(),
            }

    fallback_artifact = f"{unit_id}_contract_artifact"
    return {
        "artifact": fallback_artifact,
        "kind": "contract_artifact",
        "path": "",
    }


def _contract_artifact_kind(artifact_id: str, declared_kind: str) -> str:
    if declared_kind:
        return declared_kind
    artifact_id_lower = artifact_id.lower()
    if "reduce" in artifact_id_lower:
        return "reduce_summary"
    if "metric" in artifact_id_lower:
        return "summary_metrics"
    return "contract_artifact"


def _artifact_path_result_key(artifact_kind: str) -> str:
    if artifact_kind == "reduce_summary":
        return "reduce_artifact_path"
    if artifact_kind == "summary_metrics":
        return "summary_metrics_path"
    return "contract_artifact_path"


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
        idempotency_token = _unit_idempotency_token(context, QUEUE_UNIT_ID)
        _mark_controlled_stage_running(
            mutable_state,
            queue,
            timestamp=timestamp,
            execution_mode="real_app_entry",
            operator_message=f"{QUEUE_UNIT_ID} is running through the controlled AGILAB app entrypoint.",
            event_detail=f"{QUEUE_UNIT_ID} claimed before controlled AGILAB app execution",
            execution_attempt_id=context.execution_attempt_id,
            idempotency_token=idempotency_token,
        )
        _persist_execution_claim(context, mutable_state)
        run_root = _real_run_root(context.lab_dir, QUEUE_UNIT_ID)
        result = _execute_idempotently(
            run_root=run_root,
            unit_id=QUEUE_UNIT_ID,
            idempotency_token=idempotency_token,
            callback=lambda: run_queue_fn(
                repo_root=context.repo_root,
                run_root=run_root,
                idempotency_token=idempotency_token,
            ),
        )
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
        idempotency_token = _unit_idempotency_token(context, RELAY_UNIT_ID)
        _mark_controlled_stage_running(
            mutable_state,
            relay,
            timestamp=timestamp,
            execution_mode="real_app_entry",
            operator_message=f"{RELAY_UNIT_ID} is running through the controlled AGILAB app entrypoint.",
            event_detail=f"{RELAY_UNIT_ID} claimed before controlled AGILAB app execution",
            execution_attempt_id=context.execution_attempt_id,
            idempotency_token=idempotency_token,
        )
        _persist_execution_claim(context, mutable_state)
        run_root = _real_run_root(context.lab_dir, RELAY_UNIT_ID)
        queue_result = _queue_result_for_relay(mutable_state)
        result = _execute_idempotently(
            run_root=run_root,
            unit_id=RELAY_UNIT_ID,
            idempotency_token=idempotency_token,
            callback=lambda: run_relay_fn(
                repo_root=context.repo_root,
                run_root=run_root,
                queue_result=queue_result,
                idempotency_token=idempotency_token,
            ),
        )
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


def _run_next_controlled_contract_dag_stage(
    state: Mapping[str, Any],
    *,
    context: DagExecutionContext,
) -> DagStageExecutionResult:
    mutable_state = deepcopy(dict(state))
    timestamp = context.now_fn()
    _unblock_ready_units(mutable_state, timestamp=timestamp)
    unit = _next_runnable_unit(mutable_state)
    if unit is not None:
        unit_id = str(unit.get("id", ""))
        contract_issue = _controlled_contract_unit_issue(unit)
        if contract_issue:
            _refresh_summary(mutable_state)
            return DagStageExecutionResult(
                ok=False,
                message=contract_issue,
                state=mutable_state,
                executed_unit_id=unit_id,
            )
        artifact = _primary_contract_artifact(mutable_state, unit)
        artifact_id = artifact["artifact"]
        artifact_kind = artifact["kind"]
        artifact_path_key = _artifact_path_result_key(artifact_kind)
        idempotency_token = _unit_idempotency_token(context, unit_id)
        _mark_controlled_stage_running(
            mutable_state,
            unit,
            timestamp=timestamp,
            execution_attempt_id=context.execution_attempt_id,
            idempotency_token=idempotency_token,
        )
        _persist_execution_claim(context, mutable_state)
        try:
            result = _contract_stage_result(
                context,
                unit=unit,
                artifact=artifact,
                timestamp=timestamp,
            )
        except DagExternalExecutionUncertainError:
            raise
        except RuntimeError as exc:
            _mark_controlled_stage_failure(
                mutable_state,
                unit,
                timestamp=timestamp,
                message=str(exc),
            )
            _refresh_summary(mutable_state)
            return DagStageExecutionResult(
                ok=False,
                message=str(exc),
                state=mutable_state,
                executed_unit_id=unit_id,
            )
        _mark_controlled_stage_execution(
            mutable_state,
            unit,
            result=result,
            timestamp=timestamp,
            artifact_id=artifact_id,
            reduce_artifact_id=None,
            artifact_kind=artifact_kind,
            artifact_path_key=artifact_path_key,
            execution_mode="contract_adapter",
            execution_payload_key="contract_execution",
            operator_message=f"{unit_id} completed through the controlled DAG contract adapter.",
            artifact_available_detail=f"{artifact_id} became available after controlled contract execution",
        )
        _unblock_ready_units(mutable_state, timestamp=timestamp)
        _update_real_execution_provenance(
            mutable_state,
            executed_unit_id=unit_id,
            timestamp=timestamp,
            dispatch_mode=CONTROLLED_CONTRACT_RUNNER_STATUS,
            real_app_execution=False,
            execution_scope=GLOBAL_DAG_CONTRACT_EXECUTION_SCOPE,
        )
        _refresh_summary(mutable_state)
        return DagStageExecutionResult(
            ok=True,
            message=f"Executed `{unit_id}` and published `{artifact_id}`.",
            state=mutable_state,
            executed_unit_id=unit_id,
        )

    _refresh_summary(mutable_state)
    return DagStageExecutionResult(
        ok=False,
        message="No controlled contract DAG stage is ready to run.",
        state=mutable_state,
    )


def _run_ready_controlled_contract_dag_stages(
    state: Mapping[str, Any],
    *,
    context: DagExecutionContext,
    max_workers: int | None = None,
    execution_backend: str = DAG_STAGE_BACKEND_LOCAL,
) -> DagBatchExecutionResult:
    mutable_state = deepcopy(dict(state))
    timestamp = context.now_fn()
    backend = _normalize_stage_backend(execution_backend)
    _unblock_ready_units(mutable_state, timestamp=timestamp)
    runnable_units = _runnable_units(mutable_state)
    if not runnable_units:
        _refresh_summary(mutable_state)
        return DagBatchExecutionResult(
            ok=False,
            message="No controlled contract DAG stages are ready to run.",
            state=mutable_state,
        )

    jobs: list[tuple[dict[str, Any], dict[str, str], str, str]] = []
    failed_unit_ids: list[str] = []
    failure_messages_by_unit_id: dict[str, str] = {}
    for unit in runnable_units:
        unit_id = str(unit.get("id", ""))
        contract_issue = _controlled_contract_unit_issue(unit)
        if contract_issue:
            _mark_controlled_stage_failure(
                mutable_state,
                unit,
                timestamp=timestamp,
                message=contract_issue,
                execution_mode=_stage_backend_execution_mode(backend),
            )
            failed_unit_ids.append(unit_id)
            failure_messages_by_unit_id[unit_id] = contract_issue
            continue
        artifact = _primary_contract_artifact(mutable_state, unit)
        idempotency_token = _unit_idempotency_token(context, unit_id)
        _mark_controlled_stage_running(
            mutable_state,
            unit,
            timestamp=timestamp,
            execution_mode=_stage_backend_execution_mode(backend),
            operator_message=_stage_backend_running_message(unit_id, backend),
            event_detail=_stage_backend_dispatch_detail(unit_id, backend),
            execution_attempt_id=context.execution_attempt_id,
            idempotency_token=idempotency_token,
        )
        jobs.append(
            (
                unit,
                artifact,
                artifact["kind"],
                _artifact_path_result_key(artifact["kind"]),
            )
        )

    results_by_unit_id: dict[str, dict[str, Any]] = {}
    uncertain_errors: list[DagExternalExecutionUncertainError] = []
    if jobs:
        _persist_execution_claim(context, mutable_state)
        worker_count = max(1, min(max_workers or len(jobs), len(jobs)))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    _stage_execution_result,
                    context,
                    unit=deepcopy(unit),
                    artifact=artifact,
                    timestamp=timestamp,
                    execution_backend=backend,
                ): str(unit.get("id", ""))
                for unit, artifact, _artifact_kind, _artifact_path_key in jobs
            }
            for future, unit_id in futures.items():
                try:
                    results_by_unit_id[unit_id] = dict(future.result())
                except DagExternalExecutionUncertainError as exc:
                    uncertain_errors.append(exc)
                except Exception as exc:
                    failure_messages_by_unit_id[unit_id] = str(exc)

    if uncertain_errors:
        # Every batch unit remains under the durable top-level claim. Even units
        # whose callback returned cannot be finalized independently once one
        # sibling side effect has an unknown outcome.
        raise uncertain_errors[0]

    executed_unit_ids: list[str] = []
    for unit, artifact, artifact_kind, artifact_path_key in jobs:
        unit_id = str(unit.get("id", ""))
        result = results_by_unit_id.get(unit_id)
        if result is None:
            message = failure_messages_by_unit_id.get(unit_id, "Controlled contract stage failed.")
            _mark_controlled_stage_failure(
                mutable_state,
                unit,
                timestamp=timestamp,
                message=message,
                execution_mode=_stage_backend_execution_mode(backend),
            )
            failed_unit_ids.append(unit_id)
            continue
        _mark_controlled_stage_execution(
            mutable_state,
            unit,
            result=result,
            timestamp=timestamp,
            artifact_id=artifact["artifact"],
            reduce_artifact_id=None,
            artifact_kind=artifact_kind,
            artifact_path_key=artifact_path_key,
            execution_mode=_stage_backend_execution_mode(backend),
            execution_payload_key=_stage_backend_payload_key(backend),
            operator_message=_stage_backend_completed_message(unit_id, backend),
            artifact_available_detail=(
                f"{artifact['artifact']} became available after {_stage_backend_artifact_detail(backend)}"
            ),
            completion_detail=_stage_backend_completed_message(unit_id, backend),
        )
        _update_real_execution_provenance(
            mutable_state,
            executed_unit_id=unit_id,
            timestamp=timestamp,
            dispatch_mode=CONTROLLED_CONTRACT_RUNNER_STATUS,
            real_app_execution=False,
            execution_scope=_stage_backend_execution_scope(backend),
        )
        executed_unit_ids.append(unit_id)

    _unblock_ready_units(mutable_state, timestamp=timestamp)
    _refresh_summary(mutable_state)
    backend_label = _stage_backend_label(backend)
    if executed_unit_ids and not failed_unit_ids:
        stage_text = ", ".join(f"`{unit_id}`" for unit_id in executed_unit_ids)
        return DagBatchExecutionResult(
            ok=True,
            message=f"Executed {len(executed_unit_ids)} ready {backend_label} DAG stage(s): {stage_text}.",
            state=mutable_state,
            executed_unit_ids=tuple(executed_unit_ids),
        )
    if executed_unit_ids:
        stage_text = ", ".join(f"`{unit_id}`" for unit_id in executed_unit_ids)
        failed_text = _failed_stage_text(failed_unit_ids, failure_messages_by_unit_id)
        return DagBatchExecutionResult(
            ok=False,
            message=f"Executed {stage_text}; failed {failed_text}.",
            state=mutable_state,
            executed_unit_ids=tuple(executed_unit_ids),
            failed_unit_ids=tuple(failed_unit_ids),
        )
    failed_text = _failed_stage_text(failed_unit_ids, failure_messages_by_unit_id)
    return DagBatchExecutionResult(
        ok=False,
        message=f"No ready DAG stage completed. Failed {failed_text}.",
        state=mutable_state,
        failed_unit_ids=tuple(failed_unit_ids),
    )


def _failed_stage_text(unit_ids: list[str], messages_by_unit_id: Mapping[str, str]) -> str:
    if not unit_ids:
        return "no stage"
    parts: list[str] = []
    for unit_id in unit_ids:
        message = str(messages_by_unit_id.get(unit_id, "")).strip()
        parts.append(f"`{unit_id}`: {message}" if message else f"`{unit_id}`")
    return "; ".join(parts)


def _normalize_stage_backend(value: str) -> str:
    if str(value).strip().lower() == DAG_STAGE_BACKEND_DISTRIBUTED:
        return DAG_STAGE_BACKEND_DISTRIBUTED
    return DAG_STAGE_BACKEND_LOCAL


def _stage_backend_label(backend: str) -> str:
    return "distributed" if backend == DAG_STAGE_BACKEND_DISTRIBUTED else "local"


def _stage_backend_execution_mode(backend: str) -> str:
    return "distributed_stage" if backend == DAG_STAGE_BACKEND_DISTRIBUTED else "contract_adapter"


def _stage_backend_payload_key(backend: str) -> str:
    return "distributed_execution" if backend == DAG_STAGE_BACKEND_DISTRIBUTED else "contract_execution"


def _stage_backend_execution_scope(backend: str) -> str:
    if backend == DAG_STAGE_BACKEND_DISTRIBUTED:
        return GLOBAL_DAG_DISTRIBUTED_EXECUTION_SCOPE
    return GLOBAL_DAG_CONTRACT_EXECUTION_SCOPE


def _stage_backend_running_message(unit_id: str, backend: str) -> str:
    if backend == DAG_STAGE_BACKEND_DISTRIBUTED:
        return f"{unit_id} is running through the distributed DAG stage backend."
    return f"{unit_id} is running through the controlled DAG contract adapter."


def _stage_backend_dispatch_detail(unit_id: str, backend: str) -> str:
    if backend == DAG_STAGE_BACKEND_DISTRIBUTED:
        return f"{unit_id} dispatched by the distributed DAG stage backend"
    return f"{unit_id} dispatched by the controlled DAG contract adapter"


def _stage_backend_completed_message(unit_id: str, backend: str) -> str:
    if backend == DAG_STAGE_BACKEND_DISTRIBUTED:
        return f"{unit_id} completed through the distributed DAG stage backend."
    return f"{unit_id} completed through the controlled DAG contract adapter."


def _stage_backend_artifact_detail(backend: str) -> str:
    if backend == DAG_STAGE_BACKEND_DISTRIBUTED:
        return "distributed stage execution"
    return "controlled contract execution"


def _stage_execution_result(
    context: DagExecutionContext,
    *,
    unit: Mapping[str, Any],
    artifact: Mapping[str, str],
    timestamp: str,
    execution_backend: str,
) -> dict[str, Any]:
    if execution_backend == DAG_STAGE_BACKEND_DISTRIBUTED:
        return _distributed_stage_result(context, unit=unit, artifact=artifact, timestamp=timestamp)
    return _contract_stage_result(context, unit=unit, artifact=artifact, timestamp=timestamp)


def _distributed_stage_result(
    context: DagExecutionContext,
    *,
    unit: Mapping[str, Any],
    artifact: Mapping[str, str],
    timestamp: str,
) -> dict[str, Any]:
    submitter = context.stage_submit_fn
    if submitter is None:
        raise RuntimeError(
            "Distributed DAG stage backend is not configured. "
            "Use the local contract backend or provide a stage submitter."
        )
    unit_id = str(unit.get("id", "")).strip() or "stage"
    idempotency_token = _unit_persisted_idempotency_token(unit)
    contract = _unit_execution_contract(unit)
    run_root = _real_run_root(context.lab_dir, unit_id)
    result = _execute_idempotently(
        run_root=run_root,
        unit_id=unit_id,
        idempotency_token=idempotency_token,
        callback=lambda: submitter(
            repo_root=context.repo_root,
            lab_dir=context.lab_dir,
            run_root=run_root,
            unit=dict(unit),
            artifact=dict(artifact),
            execution_contract=contract,
            timestamp=timestamp,
            idempotency_token=idempotency_token,
        ),
    )
    result.setdefault("execution_contract", contract)
    result.setdefault("stage_backend", DAG_STAGE_BACKEND_DISTRIBUTED)
    return result


def _contract_stage_result(
    context: DagExecutionContext,
    *,
    unit: Mapping[str, Any],
    artifact: Mapping[str, str],
    timestamp: str,
) -> dict[str, Any]:
    unit_id = str(unit.get("id", "")).strip() or "stage"
    idempotency_token = _unit_persisted_idempotency_token(unit)
    run_root = _real_run_root(context.lab_dir, unit_id)
    return _execute_idempotently(
        run_root=run_root,
        unit_id=unit_id,
        idempotency_token=idempotency_token,
        callback=lambda: _contract_stage_result_once(
            context,
            unit=unit,
            artifact=artifact,
            timestamp=timestamp,
            idempotency_token=idempotency_token,
            run_root=run_root,
        ),
    )


def _contract_stage_result_once(
    context: DagExecutionContext,
    *,
    unit: Mapping[str, Any],
    artifact: Mapping[str, str],
    timestamp: str,
    idempotency_token: str,
    run_root: Path,
) -> dict[str, Any]:
    unit_id = str(unit.get("id", "")).strip() or "stage"
    artifact_id = str(artifact.get("artifact", "")).strip() or f"{unit_id}_contract_artifact"
    artifact_kind = str(artifact.get("kind", "")).strip() or _contract_artifact_kind(artifact_id, "")
    artifact_path = str(artifact.get("path", "")).strip()
    contract = _unit_execution_contract(unit)
    runner = _stage_contract_runner(context, unit_id=unit_id, contract=contract)
    if runner is not None:
        result = dict(
            runner(
                repo_root=context.repo_root,
                run_root=run_root,
                idempotency_token=idempotency_token,
            )
        )
        result.setdefault("execution_contract", contract)
        result.setdefault("idempotency_token", idempotency_token)
        return result

    run_root.mkdir(parents=True, exist_ok=True)
    output_path = _contract_artifact_path(run_root, artifact_id=artifact_id, declared_path=artifact_path)
    command = _contract_command(contract)
    command_result: dict[str, Any] = {}
    if command:
        if output_path.is_dir():
            raise RuntimeError(f"Controlled contract artifact path is a directory: {output_path}")
        try:
            output_path.unlink()
        except FileNotFoundError:
            pass
        else:
            # A retry must prove that its command produced the declared output;
            # retaining a prior attempt's file would make evidence/token state lie.
            fsync_directory(output_path.parent)
        command_result = _run_contract_command(
            command,
            run_root=run_root,
            idempotency_token=idempotency_token,
        )
    artifact_payload = {
        "schema": "agilab.dag_contract_stage_result.v1",
        "unit_id": unit_id,
        "artifact": artifact_id,
        "artifact_kind": artifact_kind,
        "created_at": timestamp,
        "execution_mode": "controlled_contract_stage_execution",
        "execution_contract": contract,
        "idempotency_token": idempotency_token,
        **command_result,
    }
    if not command or not output_path.exists():
        # Fallback evidence belongs to this attempt. Reset/retry reuses the run
        # root, so preserving a previous token would make state and evidence lie.
        write_json_atomic(output_path, artifact_payload)
    result = {
        "contract_artifact_path": str(output_path),
        "reduce_artifact_path": str(output_path),
        "summary_metrics_path": str(output_path),
        "execution_contract": contract,
        "idempotency_token": idempotency_token,
        "summary_metrics": {
            "contract_artifacts": 1,
            "stage_completed": 1,
        },
    }
    result.update(command_result)
    return result


def _contract_artifact_path(run_root: Path, *, artifact_id: str, declared_path: str) -> Path:
    declared = Path(declared_path)
    if declared_path and not declared.is_absolute() and ".." not in declared.parts:
        return run_root / declared
    return run_root / f"{artifact_id}.json"


def _unit_execution_contract(unit: Mapping[str, Any]) -> dict[str, Any]:
    contract = unit.get("execution_contract")
    if not isinstance(contract, Mapping):
        return {}
    entrypoint = str(contract.get("entrypoint", "")).strip()
    command = _contract_command(contract)
    normalized: dict[str, Any] = {}
    if entrypoint:
        normalized["entrypoint"] = entrypoint
    if command:
        normalized["command"] = command
    params = contract.get("params")
    if not isinstance(params, Mapping):
        params = contract.get("run_params")
    if isinstance(params, Mapping):
        normalized["params"] = dict(params)
    if "steps" in contract or "run_steps" in contract:
        raise ValueError("Execution contracts must use 'stages'; legacy 'steps'/'run_steps' keys are not supported.")
    stages = contract.get("stages")
    if isinstance(stages, list):
        normalized["stages"] = list(stages)
    for key in ("data_in", "data_out", "reset_target"):
        if key in contract:
            normalized[key] = contract.get(key)
    for key in ("rapids_enabled", "benchmark_best_single_node"):
        if key in contract:
            normalized[key] = bool(contract.get(key))
    return normalized


def _contract_command(contract: Mapping[str, Any]) -> list[str]:
    value = contract.get("command")
    if isinstance(value, str):
        return [part for part in shlex.split(value) if part]
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def _stage_contract_runner(
    context: DagExecutionContext,
    *,
    unit_id: str,
    contract: Mapping[str, Any],
) -> Callable[..., Mapping[str, Any]] | None:
    stage_run_fns = context.stage_run_fns or {}
    runner = stage_run_fns.get(unit_id)
    if runner is not None:
        return runner
    entrypoint = str(contract.get("entrypoint", "")).strip()
    return stage_run_fns.get(entrypoint) if entrypoint else None


def _run_contract_command(
    command: list[str],
    *,
    run_root: Path,
    idempotency_token: str,
) -> dict[str, Any]:
    return _execute_idempotently(
        run_root=run_root,
        unit_id="contract-command",
        idempotency_token=idempotency_token,
        scope="contract-command",
        callback=lambda: _run_contract_command_once(
            command,
            run_root=run_root,
            idempotency_token=idempotency_token,
        ),
    )


def _run_contract_command_once(
    command: list[str],
    *,
    run_root: Path,
    idempotency_token: str,
) -> dict[str, Any]:
    try:
        command_env = os.environ.copy()
        command_env["AGILAB_IDEMPOTENCY_TOKEN"] = idempotency_token
        completed = subprocess.run(
            command,
            cwd=run_root,
            env=command_env,
            text=True,
            capture_output=True,
            check=False,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Controlled contract command timed out after 300 seconds.") from exc
    if completed.returncode:
        stderr = completed.stderr.strip()
        stdout = completed.stdout.strip()
        detail = stderr or stdout or f"command exited with status {completed.returncode}"
        raise RuntimeError(f"Controlled contract command failed ({completed.returncode}): {detail}")
    return {
        "command": command,
        "command_stdout": completed.stdout,
        "command_stderr": completed.stderr,
        "command_returncode": completed.returncode,
    }


def _controlled_contract_unit_issue(unit: Mapping[str, Any]) -> str:
    unit_id = str(unit.get("id", "")).strip() or "stage"
    produces = unit.get("produces")
    if not isinstance(produces, list) or not any(_has_declared_contract_artifact(artifact) for artifact in produces):
        return f"Controlled contract stage `{unit_id}` must declare at least one produced artifact."
    if not _unit_execution_contract(unit):
        return f"Controlled contract stage `{unit_id}` must declare `execution.entrypoint` or `execution.command`."
    return ""


def _has_declared_contract_artifact(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    artifact_id = str(value.get("artifact", "") or value.get("id", "")).strip()
    path = str(value.get("path", "")).strip()
    return bool(artifact_id and path)


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


def _mark_controlled_stage_running(
    state: dict[str, Any],
    unit: dict[str, Any],
    *,
    timestamp: str,
    execution_mode: str = "contract_adapter",
    operator_message: str | None = None,
    event_detail: str | None = None,
    execution_attempt_id: str = "",
    idempotency_token: str = "",
) -> None:
    unit_id = str(unit.get("id", ""))
    previous_status = str(unit.get("dispatch_status", ""))
    unit["dispatch_status"] = "running"
    unit["execution_mode"] = execution_mode
    state["updated_at"] = timestamp
    timestamps = unit.setdefault("timestamps", {})
    if isinstance(timestamps, dict):
        timestamps.setdefault("created_at", state.get("created_at", timestamp))
        timestamps["started_at"] = timestamp
        timestamps["updated_at"] = timestamp
    unit["operator_ui"] = {
        "state": "running",
        "severity": "info",
        "message": operator_message or f"{unit_id} is running through the controlled DAG contract adapter.",
        "blocked_by_artifacts": [],
    }
    if execution_attempt_id:
        unit["execution_attempt"] = {
            "id": execution_attempt_id,
            "idempotency_token": idempotency_token,
            "status": "running",
            "started_at": timestamp,
            "recovery_policy": "explicit_recovery_required_before_retry",
        }
    _append_event(
        state,
        timestamp=timestamp,
        kind="unit_dispatched",
        unit_id=unit_id,
        from_status=previous_status,
        to_status="running",
        detail=event_detail or f"{unit_id} dispatched by the controlled DAG contract adapter",
    )


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
    completion_detail: str | None = None,
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
    execution_attempt = unit.get("execution_attempt")
    if isinstance(execution_attempt, dict):
        execution_attempt["status"] = "completed"
        execution_attempt["completed_at"] = timestamp
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
        detail=completion_detail or f"{unit_id} completed through the controlled AGILAB app entrypoint",
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


def _mark_controlled_stage_failure(
    state: dict[str, Any],
    unit: dict[str, Any],
    *,
    timestamp: str,
    message: str,
    execution_mode: str = "contract_adapter",
) -> None:
    unit_id = str(unit.get("id", ""))
    previous_status = str(unit.get("dispatch_status", ""))
    unit["dispatch_status"] = "failed"
    unit["execution_mode"] = execution_mode
    timestamps = unit.setdefault("timestamps", {})
    if isinstance(timestamps, dict):
        timestamps.setdefault("created_at", state.get("created_at", timestamp))
        timestamps["started_at"] = timestamp
        timestamps["completed_at"] = timestamp
        timestamps["updated_at"] = timestamp
    unit["operator_ui"] = {
        "state": "failed",
        "severity": "error",
        "message": message,
        "blocked_by_artifacts": [],
    }
    execution_attempt = unit.get("execution_attempt")
    if isinstance(execution_attempt, dict):
        execution_attempt["status"] = "failed"
        execution_attempt["completed_at"] = timestamp
    _append_event(
        state,
        timestamp=timestamp,
        kind="unit_failed",
        unit_id=unit_id,
        from_status=previous_status,
        to_status="failed",
        detail=message,
    )


def recover_execution_attempt(
    state: Mapping[str, Any],
    *,
    unit_id: str,
    idempotency_token: str,
    timestamp: str,
) -> dict[str, Any]:
    """Mark one exact ambiguous unit claim failed after explicit operator recovery."""

    mutable_state = deepcopy(dict(state))
    active = mutable_state.get("active_execution")
    unit_tokens = active.get("unit_tokens") if isinstance(active, dict) else None
    recorded_token = (
        str(unit_tokens.get(unit_id, "")).strip()
        if isinstance(unit_tokens, Mapping)
        else ""
    )
    if not recorded_token or recorded_token != idempotency_token:
        raise ValueError(f"Active execution token does not match unit `{unit_id}`.")
    unit = _dag_unit(mutable_state, unit_id)
    if not isinstance(unit, dict):
        raise ValueError(f"Active execution unit `{unit_id}` is missing from runner state.")
    attempt = unit.get("execution_attempt")
    unit_token = str(attempt.get("idempotency_token", "")).strip() if isinstance(attempt, dict) else ""
    if unit.get("dispatch_status") != "running" or unit_token != idempotency_token:
        raise ValueError(f"Unit `{unit_id}` no longer has the claimed running token.")

    _mark_controlled_stage_failure(
        mutable_state,
        unit,
        timestamp=timestamp,
        message=(
            f"Execution attempt for {unit_id} was explicitly recovered with its exact "
            "idempotency token; reset is required before retry."
        ),
        execution_mode=str(unit.get("execution_mode", "contract_adapter")),
    )
    recovered_attempt = unit.get("execution_attempt")
    if isinstance(recovered_attempt, dict):
        recovered_attempt["status"] = "recovered_failed"
        recovered_attempt["recovered_at"] = timestamp
    remaining_tokens = dict(unit_tokens) if isinstance(unit_tokens, Mapping) else {}
    remaining_tokens.pop(unit_id, None)
    if remaining_tokens and isinstance(active, dict):
        active["unit_tokens"] = remaining_tokens
        active["status"] = "recovery_required"
    else:
        mutable_state.pop("active_execution", None)
    _append_event(
        mutable_state,
        timestamp=timestamp,
        kind="unit_recovered",
        unit_id=unit_id,
        from_status="running",
        to_status="failed",
        detail=f"operator recovered exact idempotency token {idempotency_token}",
    )
    _refresh_summary(mutable_state)
    return mutable_state


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
