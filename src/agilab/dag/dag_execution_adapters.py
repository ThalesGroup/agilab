from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any, Callable, Mapping, Protocol

from .dag_artifact_contracts import (
    ArtifactOutputSnapshot,
    bind_artifact_identities,
    require_artifact_location,
    artifact_result_path_key as _artifact_path_result_key,
    is_contract_receipt_artifact,
    reported_artifact_paths,
    verified_submission_artifacts,
)
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
    _read_queue_context,
    _require_owned_output_tree,
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
    backend = _normalize_stage_backend(execution_backend)
    if adapter_id == CONTROLLED_CONTRACT_ADAPTER or (
        adapter_id == UAV_QUEUE_ADAPTER and backend == DAG_STAGE_BACKEND_DISTRIBUTED
    ):
        return _run_ready_controlled_contract_dag_stages(
            state,
            context=context,
            max_workers=max_workers,
            execution_backend=backend,
        )

    result = _run_next_adapter_stage_uncommitted(adapter_id, state, context)
    if result.ok:
        return DagBatchExecutionResult(
            ok=True,
            message=result.message,
            state=result.state,
            executed_unit_ids=(result.executed_unit_id,)
            if result.executed_unit_id
            else (),
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


def _artifact_dependency_available(
    state: Mapping[str, Any], dependency: Mapping[str, Any]
) -> bool:
    artifact_id = str(dependency.get("artifact", "")).strip()
    producer = str(dependency.get("from", "")).strip()
    if not artifact_id:
        return False
    if producer:
        producer_unit = _dag_unit(state, producer)
        if producer_unit is None or producer_unit.get("dispatch_status") != "completed":
            return False
    artifacts = state.get("artifacts", [])
    return isinstance(artifacts, list) and any(
        isinstance(artifact, Mapping)
        and str(artifact.get("artifact", "")).strip() == artifact_id
        and artifact.get("status") == "available"
        and (not producer or str(artifact.get("producer", "")).strip() == producer)
        and _persisted_artifact_available(artifact)
        for artifact in artifacts
    )


def _persisted_artifact_available(artifact: Mapping[str, Any]) -> bool:
    path_value = artifact.get("path")
    if not isinstance(path_value, (str, Path)) or not str(path_value).strip():
        return False
    path = Path(path_value)
    kind = str(artifact.get("kind", ""))
    if not path.exists() or (
        kind in {"contract_artifact", "summary_metrics", "reduce_summary"}
        and not path.is_file()
    ):
        return False
    return kind == "contract_artifact" or not is_contract_receipt_artifact(path)


def _distributed_input_artifacts(
    state: Mapping[str, Any],
    *,
    unit: Mapping[str, Any],
    context: DagExecutionContext,
) -> list[dict[str, Any]]:
    """Forward original producer bindings; never baseline an existing input again."""
    dependencies = unit.get("artifact_dependencies", [])
    if not isinstance(dependencies, list):
        raise ValueError("Declared upstream artifacts must be a list.")
    artifacts = state.get("artifacts", [])
    artifacts = artifacts if isinstance(artifacts, list) else []
    inputs = []
    identity_fields = (
        "resolved_path",
        "size_bytes",
        "sha256",
        "identity_kind",
        "entry_count",
        "producer_run_root",
    )
    for dependency in dependencies:
        if not isinstance(dependency, Mapping):
            raise ValueError("Declared upstream artifact dependency must be a mapping.")
        artifact_id = str(dependency.get("artifact", "")).strip()
        producer = str(dependency.get("from", "")).strip()
        matches = [
            artifact
            for artifact in artifacts
            if isinstance(artifact, Mapping)
            and str(artifact.get("artifact", "") or artifact.get("id", "")).strip()
            == artifact_id
            and artifact.get("status") == "available"
            and (not producer or str(artifact.get("producer", "")).strip() == producer)
        ]
        if not artifact_id or len(matches) != 1:
            raise ValueError(
                f"Declared upstream artifact `{artifact_id}` is missing or ambiguous."
            )
        original = dict(matches[0])
        producer = str(original.get("producer", "")).strip()
        producer_unit = _dag_unit(state, producer)
        if (
            not producer
            or producer_unit is None
            or producer_unit.get("dispatch_status") != "completed"
        ):
            raise ValueError(
                f"Declared upstream artifact `{artifact_id}` has no completed producer."
            )
        outputs = producer_unit.get("produces", [])
        outputs = outputs if isinstance(outputs, list) else []
        bound = [
            output
            for output in outputs
            if isinstance(output, Mapping)
            and str(output.get("artifact", "") or output.get("id", "")).strip()
            == artifact_id
            and str(output.get("kind", "")).strip()
            == str(original.get("kind", "")).strip()
            and str(output.get("path", "")).strip()
            == str(original.get("path", "")).strip()
        ]
        if len(bound) != 1:
            raise ValueError(
                f"Declared upstream artifact `{artifact_id}` has no unique original producer binding."
            )
        for key in identity_fields:
            if key in original and key in bound[0] and original[key] != bound[0][key]:
                raise ValueError(
                    f"Declared upstream artifact `{artifact_id}` has conflicting original identity."
                )
            if key in bound[0]:
                original[key] = bound[0][key]
        if any(
            key not in original for key in ("resolved_path", "size_bytes", "sha256")
        ):
            raise ValueError(
                f"Declared upstream artifact `{artifact_id}` is missing its original identity."
            )
        original.update(
            artifact=artifact_id,
            producer=producer,
        )
        original.setdefault(
            "producer_run_root", str(_real_run_root(context.lab_dir, producer))
        )
        inputs.append(original)
    return inputs


def _unit_dependencies_available(
    state: Mapping[str, Any], unit: Mapping[str, Any]
) -> bool:
    dependencies = unit.get("artifact_dependencies", [])
    upstream_ids = unit.get("depends_on", [])
    if not isinstance(upstream_ids, list):
        return False
    policy = unit.get("dispatch_policy", {})
    policy_upstream = (
        policy.get("requires_completed_dependencies", [])
        if isinstance(policy, Mapping)
        else []
    )
    if not isinstance(policy_upstream, list):
        return False
    for producer in [*upstream_ids, *policy_upstream]:
        producer_unit = _dag_unit(state, str(producer))
        if producer_unit is None or producer_unit.get("dispatch_status") != "completed":
            return False
    return isinstance(dependencies, list) and all(
        isinstance(dependency, Mapping)
        and _artifact_dependency_available(state, dependency)
        for dependency in dependencies
    )


def _next_runnable_unit(state: Mapping[str, Any]) -> dict[str, Any] | None:
    return next(iter(_runnable_units(state)), None)


def planned_stage_ids(
    adapter_id: str, state: Mapping[str, Any], *, batch: bool = False
) -> tuple[str, ...]:
    """Preview the adapter's next targets without claims, writes or execution."""
    if adapter_id == CONTROLLED_CONTRACT_ADAPTER:
        projected = deepcopy(dict(state))
        _unblock_ready_units(projected, timestamp="")
        ready = _runnable_units(projected)
        return tuple(str(unit["id"]) for unit in (ready if batch else ready[:1]))
    if adapter_id == UAV_QUEUE_ADAPTER:
        next_id = _next_uav_queue_to_relay_unit_id(state)
        return (next_id,) if next_id else ()
    raise ValueError(f"No execution target preview is available for adapter `{adapter_id}`.")


def _next_uav_queue_to_relay_unit_id(state: Mapping[str, Any]) -> str | None:
    queue = _dag_unit(state, QUEUE_UNIT_ID)
    relay = _dag_unit(state, RELAY_UNIT_ID)
    if not isinstance(queue, dict) or not isinstance(relay, dict):
        return None
    if str(
        queue.get("dispatch_status", "")
    ) == "runnable" and _unit_dependencies_available(state, queue):
        return QUEUE_UNIT_ID
    if (
        str(relay.get("dispatch_status", "")) in {"runnable", "blocked"}
        and _artifact_dependency_available(
            state, {"artifact": "queue_metrics", "from": QUEUE_UNIT_ID}
        )
        and _unit_dependencies_available(state, relay)
    ):
        return RELAY_UNIT_ID
    return None


def _runnable_units(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        unit
        for unit in dag_units(state)
        if str(unit.get("dispatch_status", "")) == "runnable"
        and _unit_dependencies_available(state, unit)
    ]


def _unblock_ready_units(state: dict[str, Any], *, timestamp: str) -> None:
    for unit in dag_units(state):
        if unit.get(
            "dispatch_status"
        ) == "runnable" and not _unit_dependencies_available(state, unit):
            unit["dispatch_status"] = "blocked"
            _append_event(
                state,
                timestamp=timestamp,
                kind="unit_blocked",
                unit_id=str(unit.get("id", "")),
                from_status="runnable",
                to_status="blocked",
                detail="Declared producer artifacts are not available after completion.",
            )
            timestamps = unit.get("timestamps")
            if isinstance(timestamps, dict):
                timestamps["updated_at"] = timestamp
            unit["operator_ui"] = {
                "state": "waiting_for_artifacts",
                "severity": "warning",
                "message": "Waiting for artifacts from the declared completed producers.",
                "blocked_by_artifacts": [
                    str(dependency.get("artifact", ""))
                    for dependency in unit.get("artifact_dependencies", [])
                    if isinstance(dependency, Mapping)
                    and not _artifact_dependency_available(state, dependency)
                ],
            }
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



def _invoke_uav_stage_runner(
    runner: Callable[..., Mapping[str, Any]],
    unit: Mapping[str, Any],
    *,
    input_artifacts: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> Mapping[str, Any]:
    # Adapt injected legacy callbacks before execution; never retry a body error.
    try:
        signature = inspect.signature(runner)
    except (TypeError, ValueError):
        return runner(**kwargs)
    authored_contract = _unit_execution_contract(unit) or None
    runtime_contract = authored_contract
    if "execution_contract" in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    ):
        if authored_contract:
            from .dag_distributed_submitter import (
                _bind_distributed_worker_params,
                _queue_trace_requested,
            )

            app_name = str(unit.get("app", ""))
            params = authored_contract.get("params") or authored_contract.get("run_params") or {}
            if _queue_trace_requested(app_name, params):
                parameter_key = "params" if "params" in authored_contract else "run_params"
                runtime_contract = {
                    **authored_contract,
                    parameter_key: _bind_distributed_worker_params(
                        app_name, params, input_artifacts or []
                    ),
                }
        kwargs["execution_contract"] = runtime_contract
    signature.bind(**kwargs)
    result = runner(**kwargs)
    if runtime_contract is not authored_contract:
        # The binding is a runtime derivative; keep the author's plan unchanged.
        return {**result, "execution_contract": authored_contract}
    return result


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

    next_unit_id = _next_uav_queue_to_relay_unit_id(mutable_state)
    relay_status = str(relay.get("dispatch_status", ""))
    timestamp = context.now_fn()
    if next_unit_id == QUEUE_UNIT_ID:
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
            callback=lambda: _run_uav_stage_callback_once(
                queue,
                run_root=run_root,
                prefix="queue",
                callback=lambda: _invoke_uav_stage_runner(
                    run_queue_fn,
                    queue,
                    repo_root=context.repo_root,
                    run_root=run_root,
                    idempotency_token=idempotency_token,
                ),
            ),
        )
        try:
            result = _validated_uav_stage_result(
                queue, run_root=run_root, result=result, prefix="queue"
            )
        except Exception as exc:
            _mark_controlled_stage_failure(
                mutable_state, queue, timestamp=timestamp, message=str(exc)
            )
            _refresh_summary(mutable_state)
            return DagStageExecutionResult(
                ok=False,
                message=str(exc),
                state=mutable_state,
                executed_unit_id=QUEUE_UNIT_ID,
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

    if next_unit_id == RELAY_UNIT_ID:
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
        from .dag_distributed_submitter import _queue_trace_requested

        contract = _unit_execution_contract(relay)
        params = contract.get("params") or contract.get("run_params") or {}
        exact_trace = _queue_trace_requested(str(relay.get("app", "")), params)
        input_artifacts = (
            _distributed_input_artifacts(mutable_state, unit=relay, context=context)
            if exact_trace else []
        )
        result = _execute_idempotently(
            run_root=run_root,
            unit_id=RELAY_UNIT_ID,
            idempotency_token=idempotency_token,
            callback=lambda: _run_uav_stage_callback_once(
                relay,
                run_root=run_root,
                prefix="relay",
                input_artifacts=input_artifacts,
                queue_result=queue_result,
                callback=lambda: _invoke_uav_stage_runner(
                    run_relay_fn,
                    relay,
                    input_artifacts=input_artifacts,
                    repo_root=context.repo_root,
                    run_root=run_root,
                    queue_result=queue_result,
                    idempotency_token=idempotency_token,
                ),
            ),
        )
        try:
            if not exact_trace and "app_entry" in result and not any(
                isinstance(consumed, Mapping)
                and consumed.get("role") == "upstream_context"
                for consumed in result.get("consumed_artifacts", [])
            ):
                raise ValueError(
                    "Cached relay execution has no loaded queue_metrics context."
                )
            for consumed in result.get("consumed_artifacts", []):
                if (
                    not exact_trace and isinstance(consumed, Mapping)
                    and consumed.get("role") == "upstream_context"
                ):
                    if dict(consumed) != _read_queue_context(queue_result):
                        raise ValueError(
                            "Cached relay execution is bound to different queue_metrics context."
                        )
            result = _validated_uav_stage_result(
                relay, run_root=run_root, result=result, prefix="relay"
            )
            if exact_trace:
                result = _validated_uav_packet_handoff_result(
                    relay, result=result, input_artifacts=input_artifacts,
                    queue_result=queue_result,
                )
        except Exception as exc:
            _mark_controlled_stage_failure(
                mutable_state, relay, timestamp=timestamp, message=str(exc)
            )
            _refresh_summary(mutable_state)
            return DagStageExecutionResult(
                ok=False,
                message=str(exc),
                state=mutable_state,
                executed_unit_id=RELAY_UNIT_ID,
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
        contract_issue = _controlled_contract_unit_issue(unit, context=context)
        if contract_issue:
            _mark_controlled_stage_failure(
                mutable_state, unit, timestamp=timestamp, message=contract_issue
            )
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
            message=(
                f"Recorded contract receipt for `{unit_id}` as `{artifact_id}`."
                if result.get("receipt_only")
                else f"Executed `{unit_id}` and published `{artifact_id}`."
            ),
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
    inputs_by_unit_id: dict[str, list[dict[str, Any]]] = {}
    failed_unit_ids: list[str] = []
    failure_messages_by_unit_id: dict[str, str] = {}
    for unit in runnable_units:
        unit_id = str(unit.get("id", ""))
        contract_issue = _controlled_contract_unit_issue(
            unit, context=context, execution_backend=backend
        )
        if not contract_issue and backend == DAG_STAGE_BACKEND_DISTRIBUTED:
            try:
                inputs_by_unit_id[unit_id] = _distributed_input_artifacts(
                    mutable_state, unit=unit, context=context
                )
            except ValueError as exc:
                contract_issue = str(exc)
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
                    input_artifacts=inputs_by_unit_id.get(str(unit.get("id", ""))),
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
    backend = str(value).strip().lower()
    if backend not in {DAG_STAGE_BACKEND_LOCAL, DAG_STAGE_BACKEND_DISTRIBUTED}:
        raise ValueError(f"Unsupported DAG stage execution backend: {value!r}.")
    return backend


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
    input_artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if execution_backend == DAG_STAGE_BACKEND_DISTRIBUTED:
        return _distributed_stage_result(
            context,
            unit=unit,
            artifact=artifact,
            timestamp=timestamp,
            input_artifacts=input_artifacts,
        )
    return _contract_stage_result(context, unit=unit, artifact=artifact, timestamp=timestamp)


def _distributed_stage_result(
    context: DagExecutionContext,
    *,
    unit: Mapping[str, Any],
    artifact: Mapping[str, str],
    timestamp: str,
    input_artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from .dag_distributed_submitter import (
        require_distributed_input_receipts,
        validate_distributed_stage_inputs,
    )

    submitter = context.stage_submit_fn
    if submitter is None:
        raise RuntimeError(
            "Distributed DAG stage backend is not configured. "
            "Use the local contract backend or provide a stage submitter."
        )
    inputs = validate_distributed_stage_inputs(unit, input_artifacts)
    unit_id = str(unit.get("id", "")).strip() or "stage"
    idempotency_token = _unit_persisted_idempotency_token(unit)
    contract = _unit_execution_contract(unit)
    run_root = _real_run_root(context.lab_dir, unit_id)
    result = _execute_idempotently(
        run_root=run_root,
        unit_id=unit_id,
        idempotency_token=idempotency_token,
        callback=lambda: _run_distributed_stage_callback_once(
            context,
            unit=unit,
            artifact=artifact,
            contract=contract,
            run_root=run_root,
            timestamp=timestamp,
            idempotency_token=idempotency_token,
            input_artifacts=inputs,
        ),
    )
    result.setdefault("execution_contract", contract)
    result.setdefault("stage_backend", DAG_STAGE_BACKEND_DISTRIBUTED)
    require_distributed_input_receipts(
        result, inputs, app_name=str(unit.get("app", "")),
        params=contract.get("params") or contract.get("run_params") or {},
    )
    return _validated_contract_stage_result(
        unit, artifact, run_root=run_root, result=result, bind_output_identity=False
    )


def _run_distributed_stage_callback_once(
    context: DagExecutionContext,
    *,
    unit: Mapping[str, Any],
    artifact: Mapping[str, str],
    contract: Mapping[str, Any],
    run_root: Path,
    timestamp: str,
    idempotency_token: str,
    input_artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from .dag_distributed_submitter import require_distributed_input_receipts

    freshness = _callback_output_snapshot(unit, run_root=run_root)
    submitter = context.stage_submit_fn
    assert submitter is not None
    kwargs = dict(
        repo_root=context.repo_root,
        lab_dir=context.lab_dir,
        run_root=run_root,
        unit=dict(unit),
        artifact=dict(artifact),
        execution_contract=dict(contract),
        timestamp=timestamp,
        idempotency_token=idempotency_token,
    )
    try:
        signature = inspect.signature(submitter)
    except (TypeError, ValueError):
        if input_artifacts:
            kwargs["input_artifacts"] = input_artifacts
    else:
        if "input_artifacts" in signature.parameters or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        ):
            kwargs["input_artifacts"] = input_artifacts or []
        elif input_artifacts:
            raise RuntimeError(
                "Distributed submitter cannot accept declared upstream artifacts."
            )
        signature.bind(**kwargs)
    result = dict(submitter(**kwargs))
    require_distributed_input_receipts(
        result, input_artifacts or [], app_name=str(unit.get("app", "")),
        params=contract.get("params") or contract.get("run_params") or {},
    )
    validated = _validated_contract_stage_result(
        unit, artifact, run_root=run_root, result=result, bind_output_identity=True
    )
    submitted = verified_submission_artifacts(
        validated,
        run_root=run_root,
        unit_id=str(unit.get("id", "stage")),
        idempotency_token=idempotency_token,
    )
    for output in validated["produced_artifacts"]:
        if output["kind"] == "contract_artifact":
            continue
        path = Path(output["path"])
        if (output["artifact"], output["kind"], path.resolve()) not in submitted:
            freshness.require_fresh(path, artifact_id=output["artifact"])
    return validated


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
    result = _execute_idempotently(
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
    return _validated_contract_stage_result(
        unit, artifact, run_root=run_root, result=result, bind_output_identity=False
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
    receipt_only = _contract_receipt_allowed(unit, artifact)
    command = _contract_command(contract)
    if runner is None and not command and not receipt_only:
        raise RuntimeError(
            f"Controlled DAG stage `{unit_id}` has no registered executor for its entrypoint."
        )
    if runner is not None:
        freshness = _callback_output_snapshot(unit, run_root=run_root)
        result = dict(
            runner(
                repo_root=context.repo_root,
                run_root=run_root,
                idempotency_token=idempotency_token,
            )
        )
        result.setdefault("execution_contract", contract)
        result.setdefault("idempotency_token", idempotency_token)
        validated = _validated_contract_stage_result(
            unit, artifact, run_root=run_root, result=result, bind_output_identity=True
        )
        _require_fresh_stage_outputs(validated, freshness)
        return validated

    run_root.mkdir(parents=True, exist_ok=True)
    output_path = _contract_artifact_path(run_root, artifact_id=artifact_id, declared_path=artifact_path)
    command_result: dict[str, Any] = {}
    if command:
        declared_paths = {output_path}
        for declared_output in unit.get("produces", []):
            if isinstance(declared_output, Mapping):
                output_id = str(
                    declared_output.get("artifact", "") or declared_output.get("id", "")
                ).strip()
                if output_id:
                    declared_paths.add(
                        _contract_artifact_path(
                            run_root,
                            artifact_id=output_id,
                            declared_path=str(declared_output.get("path", "")).strip(),
                        )
                    )
        for declared_path in declared_paths:
            if declared_path.is_dir():
                raise RuntimeError(
                    f"Controlled contract artifact path is a directory: {declared_path}"
                )
            try:
                declared_path.unlink()
            except FileNotFoundError:
                pass
            else:
                # Every declared command output must belong to this attempt.
                fsync_directory(declared_path.parent)
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
        if not receipt_only:
            raise RuntimeError(
                f"Controlled DAG stage `{unit_id}` did not produce its declared artifact `{artifact_id}`."
            )
        # A receipt is permitted only by an explicit contract_artifact declaration.
        # Scientific outputs must come from the executor, never this metadata.
        artifact_payload["receipt_only"] = True
        write_json_atomic(output_path, artifact_payload)
        for declared_output in unit.get("produces", []):
            if not isinstance(declared_output, Mapping):
                continue
            output_id = str(
                declared_output.get("artifact", "") or declared_output.get("id", "")
            ).strip()
            if output_id and output_id != artifact_id:
                receipt_path = _contract_artifact_path(
                    run_root,
                    artifact_id=output_id,
                    declared_path=str(declared_output.get("path", "")).strip(),
                )
                write_json_atomic(
                    receipt_path,
                    {
                        **artifact_payload,
                        "artifact": output_id,
                        "artifact_kind": "contract_artifact",
                    },
                )
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
    result["receipt_only"] = not command or bool(artifact_payload.get("receipt_only"))
    return _validated_contract_stage_result(
        unit, artifact, run_root=run_root, result=result, bind_output_identity=True
    )


def _contract_receipt_allowed(
    unit: Mapping[str, Any], artifact: Mapping[str, Any]
) -> bool:
    produces = unit.get("produces")
    if not isinstance(produces, list):
        return artifact.get("kind") == "contract_artifact"
    artifact_id = str(artifact.get("artifact", "")).strip()
    return (
        bool(produces)
        and all(
            isinstance(output, Mapping) and output.get("kind") == "contract_artifact"
            for output in produces
        )
        and any(
            str(output.get("artifact", "") or output.get("id", "")).strip()
            == artifact_id
            for output in produces
        )
    )


def _validated_contract_stage_result(
    unit: Mapping[str, Any],
    artifact: Mapping[str, str],
    *,
    run_root: Path,
    result: dict[str, Any],
    bind_output_identity: bool | None = None,
) -> dict[str, Any]:
    unit_id = str(unit.get("id", "stage"))[:160]
    if (
        result.get("status") == "error"
        or result.get("command_returncode", 0)
        or result.get("returncode", 0)
    ):
        raise RuntimeError(
            f"Controlled DAG stage `{unit_id}` executor reported a failed result."
        )
    primary_id = str(artifact.get("artifact", "")).strip()
    primary_kind = str(artifact.get("kind", "contract_artifact"))
    primary_key = _artifact_path_result_key(primary_kind)
    declared_outputs = unit.get("produces")
    outputs = declared_outputs if isinstance(declared_outputs, list) else [artifact]
    reported_paths = reported_artifact_paths(result)
    original_outputs = {
        str(output.get("artifact", "") or output.get("id", "")).strip(): output
        for output in result.get("produced_artifacts", [])
    }
    primary_reported = (
        reported_paths.get(primary_id, "")
        or str(
            result.get(primary_key, "")
            or result.get("summary_metrics_path", "")
            or result.get("reduce_artifact_path", "")
            or result.get("contract_artifact_path", "")
        ).strip()
    )
    primary_path = (
        Path(primary_reported)
        if primary_reported
        else _contract_artifact_path(
            run_root,
            artifact_id=primary_id,
            declared_path=str(artifact.get("path", "")).strip(),
        )
    )
    if primary_reported and not primary_path.is_absolute():
        primary_path = run_root / primary_path
    validated: list[dict[str, Any]] = []
    for output in outputs:
        if not isinstance(output, Mapping):
            continue
        artifact_id = str(output.get("artifact", "") or output.get("id", "")).strip()
        if not artifact_id:
            continue
        kind = _contract_artifact_kind(artifact_id, str(output.get("kind", "")).strip())
        key = _artifact_path_result_key(kind)
        path_value = reported_paths.get(artifact_id, "")
        if not path_value:
            if artifact_id == primary_id:
                path_value = str(
                    result.get(primary_key, "")
                    or result.get("summary_metrics_path", "")
                    or result.get("reduce_artifact_path", "")
                    or result.get("contract_artifact_path", "")
                ).strip()
            elif key != primary_key:
                path_value = str(result.get(key, "")).strip()
                if path_value:
                    reported_path = Path(path_value)
                    if not reported_path.is_absolute():
                        reported_path = run_root / reported_path
                    if reported_path.resolve() == primary_path.resolve():
                        # Legacy kind aliases describe the primary output. They
                        # cannot prove another artifact with its own declaration.
                        path_value = ""
        path = (
            Path(path_value)
            if path_value
            else _contract_artifact_path(
                run_root,
                artifact_id=artifact_id,
                declared_path=str(output.get("path", "")).strip(),
            )
        )
        if path_value and not path.is_absolute():
            path = run_root / path
        original = original_outputs.get(artifact_id, {})
        if bind_output_identity is not None:
            require_artifact_location(
                path,
                artifact_id=artifact_id,
                expected=original,
                bind_new=bind_output_identity,
            )
        if not path.exists() or (
            kind in {"contract_artifact", "summary_metrics", "reduce_summary"}
            and not path.is_file()
        ):
            raise RuntimeError(
                f"Controlled DAG stage `{unit_id}` did not produce its declared artifact `{artifact_id}`."
            )
        if kind != "contract_artifact" and is_contract_receipt_artifact(path):
            raise RuntimeError(
                f"Contract receipt cannot satisfy scientific artifact `{artifact_id}`."
            )
        evidence_path = str(result.get("submission_evidence_path", "")).strip()
        if (
            kind != "contract_artifact"
            and evidence_path
            and path.resolve() == Path(evidence_path).resolve()
        ):
            raise RuntimeError(
                f"Distributed DAG stage `{unit_id}` returned a submission receipt instead of `{artifact_id}`."
            )
        if result.get("receipt_only") and kind != "contract_artifact":
            raise RuntimeError(
                f"A contract receipt cannot satisfy scientific artifact `{artifact_id}`."
            )
        original = original_outputs.get(artifact_id, {})
        validated.append(
            {
                **{
                    key: original[key]
                    for key in (
                        "size_bytes",
                        "sha256",
                        "identity_kind",
                        "entry_count",
                        "resolved_path",
                    )
                    if key in original
                },
                "artifact": artifact_id,
                "kind": kind,
                "path": str(path),
            }
        )
        if artifact_id == primary_id:
            result[primary_key] = str(path)
    if not validated or not any(
        output["artifact"] == primary_id for output in validated
    ):
        raise RuntimeError(
            f"Controlled DAG stage `{unit_id}` has no validated primary artifact."
        )
    if bind_output_identity is not None:
        bind_artifact_identities(
            validated, run_root=run_root, bind_new=bind_output_identity
        )
    result["produced_artifacts"] = validated
    return result


def _validated_uav_stage_result(
    unit: Mapping[str, Any],
    *,
    run_root: Path,
    result: dict[str, Any],
    prefix: str,
    bind_output_identity: bool = False,
) -> dict[str, Any]:
    if "execution_inputs_sha256" in result or "app_entry" in result:
        _require_owned_output_tree(
            run_root, run_root.resolve() / "export", label="export"
        )
        effective_args = result.get("effective_args", {})
        if isinstance(effective_args, Mapping) and effective_args.get("data_out"):
            _require_owned_output_tree(
                run_root, Path(effective_args["data_out"]), label="data_out"
            )
        if result.get("execution_contract") != (_unit_execution_contract(unit) or None):
            raise ValueError(
                "Cached UAV execution is bound to a different execution contract."
            )
    if result.get("source_scenario_sha256"):
        source = Path(str(result["source_scenario"]))
        source = source if source.is_absolute() else run_root / source
        if (
            hashlib.sha256(source.read_bytes()).hexdigest()
            != result["source_scenario_sha256"]
        ):
            raise ValueError(
                "Cached UAV execution is bound to different scenario bytes."
            )
    if result.get("artifact_validation_error"):
        raise RuntimeError(str(result["artifact_validation_error"]))
    metrics_id = f"{prefix}_metrics"
    reduce_id = f"{prefix}_reduce_summary"
    outputs = [
        dict(output)
        for output in unit.get("produces", [])
        if isinstance(output, Mapping)
    ]
    by_id = {
        str(output.get("artifact", "") or output.get("id", "")): output
        for output in outputs
    }
    for artifact_id, kind in (
        (metrics_id, "summary_metrics"),
        (reduce_id, "reduce_summary"),
    ):
        if artifact_id not in by_id:
            output = {"artifact": artifact_id, "kind": kind}
            outputs.append(output)
            by_id[artifact_id] = output
        else:
            by_id[artifact_id]["kind"] = kind
    validated = _validated_contract_stage_result(
        {**unit, "produces": outputs},
        {**by_id[metrics_id], "artifact": metrics_id},
        run_root=run_root,
        result=result,
        bind_output_identity=bind_output_identity,
    )
    for output in validated["produced_artifacts"]:
        if output["artifact"] in {metrics_id, reduce_id}:
            validated[_artifact_path_result_key(output["kind"])] = output["path"]
    return validated


def _validated_uav_packet_handoff_result(
    unit: Mapping[str, Any], *, result: Mapping[str, Any],
    input_artifacts: list[dict[str, Any]], queue_result: Mapping[str, Any],
) -> dict[str, Any]:
    from .dag_distributed_submitter import _queue_trace_requested, _validated_worker_packet_summary

    validated = dict(result)
    contract = _unit_execution_contract(unit)
    params = contract.get("params") or contract.get("run_params") or {}
    if not _queue_trace_requested(str(unit.get("app", "")), params):
        return validated
    metrics, receipt = _validated_worker_packet_summary(validated, input_artifacts)
    if json.dumps(validated.get("summary_metrics"), sort_keys=True, allow_nan=False) != json.dumps(
        metrics, sort_keys=True, allow_nan=False
    ):
        raise ValueError("Local worker summary metrics differ from the actual worker artifact.")
    original = next(
        item for item in input_artifacts
        if item["artifact"] == "queue_metrics" and item["producer"] == QUEUE_UNIT_ID
    )
    validated["consumed_artifacts"] = [{
        **original, **_read_queue_context(queue_result), **receipt, "role": "upstream_context",
    }]
    validated["relay_numerically_conditioned_on_queue_metrics"] = True
    return validated


def _callback_output_snapshot(
    unit: Mapping[str, Any], *, run_root: Path
) -> ArtifactOutputSnapshot:
    declared_paths: list[Path] = []
    for output in unit.get("produces", []):
        if not isinstance(output, Mapping):
            continue
        value = str(output.get("path", "")).strip()
        if value:
            path = Path(value).expanduser()
            declared_paths.append(path if path.is_absolute() else run_root / path)
    return ArtifactOutputSnapshot(workspaces=[run_root], declared_paths=declared_paths)


def _require_fresh_stage_outputs(
    result: Mapping[str, Any], freshness: ArtifactOutputSnapshot
) -> None:
    for output in result.get("produced_artifacts", []):
        if output.get("kind") != "contract_artifact":
            freshness.require_fresh(
                Path(output["path"]), artifact_id=output["artifact"]
            )


def _run_uav_stage_callback_once(
    unit: Mapping[str, Any],
    *,
    run_root: Path,
    prefix: str,
    callback: Callable[[], Mapping[str, Any]],
    input_artifacts: list[dict[str, Any]] | None = None,
    queue_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    freshness = _callback_output_snapshot(unit, run_root=run_root)
    result = dict(callback())
    try:
        validated = _validated_uav_stage_result(
            unit,
            run_root=run_root,
            result=result,
            prefix=prefix,
            bind_output_identity=True,
        )
        _require_fresh_stage_outputs(validated, freshness)
        if queue_result is not None:
            validated = _validated_uav_packet_handoff_result(
                unit, result=validated, input_artifacts=input_artifacts or [],
                queue_result=queue_result,
            )
        return validated
    except Exception as exc:
        # The callback returned, so its output validation is a known failure.
        # Persist that result before idempotent replay can bypass this check.
        return {**result, "status": "error", "artifact_validation_error": str(exc)}


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


def _controlled_contract_unit_issue(
    unit: Mapping[str, Any],
    *,
    context: DagExecutionContext | None = None,
    execution_backend: str = DAG_STAGE_BACKEND_LOCAL,
) -> str:
    unit_id = str(unit.get("id", "")).strip() or "stage"
    produces = unit.get("produces")
    if not isinstance(produces, list) or not any(_has_declared_contract_artifact(artifact) for artifact in produces):
        return f"Controlled contract stage `{unit_id}` must declare at least one produced artifact."
    contract = _unit_execution_contract(unit)
    if not contract.get("entrypoint") and not _contract_command(contract):
        return f"Controlled contract stage `{unit_id}` must declare `execution.entrypoint` or `execution.command`."
    if context is not None and execution_backend == DAG_STAGE_BACKEND_LOCAL:
        artifact = _primary_contract_artifact({}, unit)
        if (
            not _contract_command(contract)
            and _stage_contract_runner(context, unit_id=unit_id, contract=contract)
            is None
        ):
            if not _contract_receipt_allowed(unit, artifact):
                return f"Controlled DAG stage `{unit_id}` has no registered executor for its entrypoint."
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
        if not isinstance(row, dict)
        or (str(row.get("artifact", "")).strip(), str(row.get("producer", "")).strip())
        != (artifact_id, str(artifact.get("producer", "")).strip())
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
    validated_outputs = result.get("produced_artifacts", [])
    if isinstance(validated_outputs, list):
        output_by_id = {
            str(output.get("artifact", "")): output
            for output in validated_outputs
            if isinstance(output, Mapping)
        }
        produces = [
            {
                **output,
                **output_by_id.get(
                    str(output.get("artifact", "") or output.get("id", "")), {}
                ),
            }
            for output in produces
        ]
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
    if isinstance(validated_outputs, list):
        for output in validated_outputs:
            if not isinstance(output, Mapping) or output.get("artifact") == artifact_id:
                continue
            _replace_artifact(
                state,
                {
                    **dict(output),
                    "producer": unit_id,
                    "status": "available",
                    "available_at": timestamp,
                    "execution_mode": execution_mode,
                },
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
    if not _unit_dependencies_available(state, unit):
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
    if not _artifact_dependency_available(
        state, {"artifact": "queue_metrics", "from": QUEUE_UNIT_ID}
    ):
        return
    if not _unit_dependencies_available(state, relay):
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
            and artifact.get("producer") == QUEUE_UNIT_ID
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
