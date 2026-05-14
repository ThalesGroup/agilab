from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .dag_execution_adapters import (
    DAG_STAGE_BACKEND_DISTRIBUTED,
    DAG_STAGE_BACKEND_LOCAL,
    GLOBAL_DAG_DISTRIBUTED_EXECUTION_SCOPE,
    GLOBAL_DAG_REAL_EXECUTION_SCOPE,
    GLOBAL_DAG_REAL_RUN_DIRNAME,
    DagBatchExecutionResult,
    DagExecutionContext,
    DagStageExecutionResult,
    available_artifact_ids,
    dag_units,
    registered_execution_adapter_ids,
    run_ready_adapter_stages,
    run_next_adapter_stage,
)
from .dag_execution_registry import (
    CONTROLLED_CONTRACT_ADAPTER,
    CONTROLLED_CONTRACT_RUNNER_STATUS,
    CONTROLLED_RUNNER_STATUS,
    DagRealRunSupport,
    FLIGHT_CONTEXT_UNIT_ID,
    FLIGHT_TO_WEATHER_ADAPTER,
    FLIGHT_TO_WEATHER_TEMPLATE_RELATIVE_PATH,
    GLOBAL_DAG_SAMPLE_RELATIVE_PATH,
    WEATHER_FORECAST_REVIEW_UNIT_ID,
    UAV_QUEUE_ADAPTER,
    UAV_QUEUE_TEMPLATE_RELATIVE_PATH,
    resolve_real_run_support,
)
from .global_pipeline_app_dispatch_smoke import (
    QUEUE_UNIT_ID,
    RELAY_UNIT_ID,
    run_queue_baseline_app,
    run_relay_followup_app,
)
from .global_pipeline_runner_state import (
    RunnerDispatchResult,
    dispatch_next_runnable as dispatch_next_runnable_state,
    load_runner_state,
    persist_runner_state,
    write_runner_state,
)
from .workflow_run_manifest import WorkflowEvidenceBundle, write_workflow_run_evidence

GLOBAL_RUNNER_STATE_FILENAME = "runner_state.json"
GLOBAL_DAG_UAV_QUEUE_TEMPLATE_RELATIVE_PATH = UAV_QUEUE_TEMPLATE_RELATIVE_PATH
GLOBAL_DAG_FLIGHT_TO_WEATHER_TEMPLATE_RELATIVE_PATH = FLIGHT_TO_WEATHER_TEMPLATE_RELATIVE_PATH
GLOBAL_DAG_CONTROLLED_ADAPTER = UAV_QUEUE_ADAPTER
GLOBAL_DAG_CONTROLLED_CONTRACT_ADAPTER = CONTROLLED_CONTRACT_ADAPTER
GLOBAL_DAG_FLIGHT_TO_WEATHER_ADAPTER = FLIGHT_TO_WEATHER_ADAPTER
GLOBAL_DAG_CONTROLLED_RUNNER_STATUS = CONTROLLED_RUNNER_STATUS
GLOBAL_DAG_CONTROLLED_CONTRACT_RUNNER_STATUS = CONTROLLED_CONTRACT_RUNNER_STATUS
GLOBAL_DAG_STAGE_BACKEND_LOCAL = DAG_STAGE_BACKEND_LOCAL
GLOBAL_DAG_STAGE_BACKEND_DISTRIBUTED = DAG_STAGE_BACKEND_DISTRIBUTED
GLOBAL_DAG_DISTRIBUTED_CONTRACT_EXECUTION_SCOPE = GLOBAL_DAG_DISTRIBUTED_EXECUTION_SCOPE
GLOBAL_DAG_QUEUE_UNIT_ID = QUEUE_UNIT_ID
GLOBAL_DAG_RELAY_UNIT_ID = RELAY_UNIT_ID
GLOBAL_DAG_FLIGHT_CONTEXT_UNIT_ID = FLIGHT_CONTEXT_UNIT_ID
GLOBAL_DAG_WEATHER_FORECAST_REVIEW_UNIT_ID = WEATHER_FORECAST_REVIEW_UNIT_ID
run_global_dag_queue_baseline_app = run_queue_baseline_app
run_global_dag_relay_followup_app = run_relay_followup_app
dispatch_next_runnable = dispatch_next_runnable_state
registered_dag_execution_adapter_ids = registered_execution_adapter_ids


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class DagRunEngine:
    repo_root: Path
    lab_dir: Path
    dag_path: Path | None
    state_filename: str = GLOBAL_RUNNER_STATE_FILENAME
    run_queue_fn: Callable[..., Mapping[str, Any]] | None = None
    run_relay_fn: Callable[..., Mapping[str, Any]] | None = None
    stage_run_fns: Mapping[str, Callable[..., Mapping[str, Any]]] | None = None
    stage_submit_fn: Callable[..., Mapping[str, Any]] | None = None
    now_fn: Callable[[], str] = lambda: _now_iso()

    @property
    def state_path(self) -> Path:
        return self.lab_dir / ".agilab" / self.state_filename

    def load_or_create_state(self, *, reset: bool = False) -> tuple[dict[str, Any], Path, Path | None]:
        if self.state_path.is_file() and not reset:
            state = load_runner_state(self.state_path)
            if runner_state_dag_matches(state, self.dag_path, self.repo_root):
                return state, self.state_path, self.dag_path
        proof = persist_runner_state(
            repo_root=self.repo_root,
            output_path=self.state_path,
            dag_path=self.dag_path,
        )
        self.write_evidence(
            proof.runner_state,
            state_path=self.state_path,
            trigger={"surface": "workflow", "action": "state_created"},
        )
        return proof.runner_state, self.state_path, self.dag_path

    def write_state(self, state: Mapping[str, Any]) -> Path:
        state_path = write_runner_state(self.state_path, state)
        self.write_evidence(
            state,
            state_path=state_path,
            trigger={"surface": "workflow", "action": "state_written"},
        )
        return state_path

    def write_evidence(
        self,
        state: Mapping[str, Any],
        *,
        state_path: Path | None = None,
        trigger: Mapping[str, Any] | None = None,
    ) -> WorkflowEvidenceBundle:
        return write_workflow_run_evidence(
            state=state,
            state_path=state_path or self.state_path,
            repo_root=self.repo_root,
            lab_dir=self.lab_dir,
            dag_path=self.dag_path,
            trigger=trigger,
        )

    def dispatch_next_runnable(self, state: Mapping[str, Any]) -> RunnerDispatchResult:
        return dispatch_next_runnable_state(state)

    def real_run_supported(self, state: Mapping[str, Any]) -> bool:
        return self.real_run_support(state).supported

    def real_run_support(self, state: Mapping[str, Any]) -> DagRealRunSupport:
        return controlled_real_run_support(state, self.dag_path, self.repo_root)

    def run_next_controlled_stage(self, state: Mapping[str, Any]) -> DagStageExecutionResult:
        return run_next_controlled_stage(
            state,
            repo_root=self.repo_root,
            dag_path=self.dag_path,
            lab_dir=self.lab_dir,
            run_queue_fn=self.run_queue_fn,
            run_relay_fn=self.run_relay_fn,
            stage_run_fns=self.stage_run_fns,
            now_fn=self.now_fn,
        )

    def run_ready_controlled_stages(
        self,
        state: Mapping[str, Any],
        *,
        max_workers: int | None = None,
        execution_backend: str = GLOBAL_DAG_STAGE_BACKEND_LOCAL,
    ) -> DagBatchExecutionResult:
        return run_ready_controlled_stages(
            state,
            repo_root=self.repo_root,
            dag_path=self.dag_path,
            lab_dir=self.lab_dir,
            run_queue_fn=self.run_queue_fn,
            run_relay_fn=self.run_relay_fn,
            stage_run_fns=self.stage_run_fns,
            stage_submit_fn=self.stage_submit_fn,
            now_fn=self.now_fn,
            max_workers=max_workers,
            execution_backend=execution_backend,
        )

    def distributed_stage_supported(self) -> bool:
        return self.stage_submit_fn is not None


def repo_relative_text(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(repo_root.resolve(strict=False)).as_posix()
    except ValueError:
        return str(path.expanduser())


def runner_state_dag_matches(
    state: Mapping[str, Any],
    dag_path: Path | None,
    repo_root: Path,
) -> bool:
    if dag_path is None:
        return True
    source = state.get("source", {})
    if not isinstance(source, dict):
        return False
    current = str(source.get("dag_path", "") or "").strip()
    expected = repo_relative_text(dag_path, repo_root)
    return current == expected or current == str(dag_path)


def execution_history_rows(state: Mapping[str, Any]) -> list[dict[str, str]]:
    events = state.get("events", [])
    if not isinstance(events, list):
        return []
    rows: list[dict[str, str]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        kind = str(event.get("kind", "")).strip()
        if not kind or kind == "run_planned":
            continue
        from_status = str(event.get("from_status", "")).strip()
        to_status = str(event.get("to_status", "")).strip()
        rows.append(
            {
                "Time": str(event.get("timestamp", "")),
                "Stage": str(event.get("unit_id", "")) or "-",
                "Event": kind.replace("_", " "),
                "Status": " -> ".join(part for part in [from_status, to_status] if part) or "-",
                "Detail": str(event.get("detail", "")),
            }
        )
    rows.sort(key=lambda row: row["Time"], reverse=True)
    return rows


def controlled_real_run_supported(
    state: Mapping[str, Any],
    dag_path: Path | None,
    repo_root: Path,
) -> bool:
    return controlled_real_run_support(state, dag_path, repo_root).supported


def controlled_real_run_support(
    state: Mapping[str, Any],
    dag_path: Path | None,
    repo_root: Path,
) -> DagRealRunSupport:
    return resolve_real_run_support(
        units=dag_units(state),
        dag_path=dag_path,
        repo_root=repo_root,
    )


def run_next_controlled_stage(
    state: Mapping[str, Any],
    *,
    repo_root: Path,
    dag_path: Path | None,
    lab_dir: Path,
    run_queue_fn: Callable[..., Mapping[str, Any]] | None = None,
    run_relay_fn: Callable[..., Mapping[str, Any]] | None = None,
    stage_run_fns: Mapping[str, Callable[..., Mapping[str, Any]]] | None = None,
    now_fn: Callable[[], str] = _now_iso,
) -> DagStageExecutionResult:
    support = controlled_real_run_support(state, dag_path, repo_root)
    if not support.supported:
        return DagStageExecutionResult(
            ok=False,
            message=support.message,
            state=dict(state),
        )

    return run_next_adapter_stage(
        support.adapter,
        state,
        DagExecutionContext(
            repo_root=repo_root,
            lab_dir=lab_dir,
            run_queue_fn=run_queue_fn or run_global_dag_queue_baseline_app,
            run_relay_fn=run_relay_fn or run_global_dag_relay_followup_app,
            stage_run_fns=stage_run_fns,
            now_fn=now_fn,
        ),
    )


def run_ready_controlled_stages(
    state: Mapping[str, Any],
    *,
    repo_root: Path,
    dag_path: Path | None,
    lab_dir: Path,
    run_queue_fn: Callable[..., Mapping[str, Any]] | None = None,
    run_relay_fn: Callable[..., Mapping[str, Any]] | None = None,
    stage_run_fns: Mapping[str, Callable[..., Mapping[str, Any]]] | None = None,
    stage_submit_fn: Callable[..., Mapping[str, Any]] | None = None,
    now_fn: Callable[[], str] = _now_iso,
    max_workers: int | None = None,
    execution_backend: str = GLOBAL_DAG_STAGE_BACKEND_LOCAL,
) -> DagBatchExecutionResult:
    support = controlled_real_run_support(state, dag_path, repo_root)
    if not support.supported:
        return DagBatchExecutionResult(
            ok=False,
            message=support.message,
            state=dict(state),
        )

    return run_ready_adapter_stages(
        support.adapter,
        state,
        DagExecutionContext(
            repo_root=repo_root,
            lab_dir=lab_dir,
            run_queue_fn=run_queue_fn or run_global_dag_queue_baseline_app,
            run_relay_fn=run_relay_fn or run_global_dag_relay_followup_app,
            stage_run_fns=stage_run_fns,
            stage_submit_fn=stage_submit_fn,
            now_fn=now_fn,
        ),
        max_workers=max_workers,
        execution_backend=execution_backend,
    )
