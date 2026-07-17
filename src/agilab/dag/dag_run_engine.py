from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
from typing import Any, Callable, Mapping, Protocol, TypeVar
from uuid import uuid4

from .dag_execution_adapters import (
    DAG_STAGE_BACKEND_DISTRIBUTED,
    DAG_STAGE_BACKEND_LOCAL,
    GLOBAL_DAG_DISTRIBUTED_EXECUTION_SCOPE,
    GLOBAL_DAG_REAL_EXECUTION_SCOPE,  # noqa: F401 - re-exported for pipeline_lab compatibility
    GLOBAL_DAG_REAL_RUN_DIRNAME,  # noqa: F401 - re-exported for pipeline_lab compatibility
    DagBatchExecutionResult,
    DagExecutionContext,
    DagStageExecutionResult,
    _DURABLE_CLAIM_RECEIPT,
    available_artifact_ids,  # noqa: F401 - re-exported for pipeline_lab compatibility
    dag_units,
    recover_execution_attempt,
    registered_execution_adapter_ids,
    _run_next_adapter_stage_uncommitted,
    _run_ready_adapter_stages_uncommitted,
)
from .dag_idempotency import DagExternalExecutionUncertainError  # noqa: F401 - public failure contract
from .dag_execution_registry import (
    CONTROLLED_CONTRACT_ADAPTER,
    CONTROLLED_CONTRACT_RUNNER_STATUS,
    CONTROLLED_RUNNER_STATUS,
    DagRealRunSupport,
    FLIGHT_CONTEXT_UNIT_ID,
    FLIGHT_TO_WEATHER_ADAPTER,
    FLIGHT_TO_WEATHER_TEMPLATE_RELATIVE_PATH,
    GLOBAL_DAG_SAMPLE_RELATIVE_PATH,  # noqa: F401 - re-exported for pipeline_lab compatibility
    WEATHER_FORECAST_REVIEW_UNIT_ID,
    UAV_QUEUE_ADAPTER,
    UAV_QUEUE_TEMPLATE_RELATIVE_PATH,
    resolve_real_run_support,
)
from agilab.global_pipeline.global_pipeline_app_dispatch_smoke import (
    QUEUE_UNIT_ID,
    RELAY_UNIT_ID,
    run_queue_baseline_app,
    run_relay_followup_app,
)
from agilab.global_pipeline.global_pipeline_runner_state import (
    RunnerDispatchResult,
    RunnerStateAttemptConflictError,  # noqa: F401 - re-exported for Streamlit compatibility
    RunnerStateConflictError,  # noqa: F401 - re-exported for Streamlit compatibility
    RunnerStateDurabilityError,  # noqa: F401 - re-exported for Streamlit compatibility
    RunnerStateRecoveryRequiredError,  # noqa: F401 - re-exported for Streamlit compatibility
    build_persisted_runner_state,
    dispatch_next_runnable as dispatch_next_runnable_state,
    load_runner_state,  # noqa: F401 - re-exported for pipeline_lab compatibility
    load_runner_state_snapshot,
    persist_runner_state,  # noqa: F401 - re-exported for pipeline_lab compatibility
    runner_state_active_attempt,
    runner_state_revision,
    runner_state_transaction,
    runner_state_write_transaction,
    write_runner_state,  # noqa: F401 - re-exported for pipeline_lab compatibility
)
from agilab.workflow.workflow_run_manifest import WorkflowEvidenceBundle, write_workflow_run_evidence

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
run_multi_app_dag_queue_baseline_app = run_queue_baseline_app
run_multi_app_dag_relay_followup_app = run_relay_followup_app
dispatch_next_runnable = dispatch_next_runnable_state
registered_dag_execution_adapter_ids = registered_execution_adapter_ids


class DagExecutionRecoveryBlockedError(RuntimeError):
    """Raised when the original execution owner may still be running."""


class _RunnerStateResult(Protocol):
    state: dict[str, Any]


_RunnerStateResultT = TypeVar("_RunnerStateResultT", bound=_RunnerStateResult)
_ACTIVE_EXECUTION_OWNERS: dict[tuple[str, str], int] = {}
_FINISHED_EXECUTION_OWNERS: set[tuple[str, str]] = set()
_ACTIVE_EXECUTION_OWNERS_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _process_incarnation(pid: int) -> str | None:
    """Return a stable process start proof, None when dead, or empty when unknown."""

    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return None
        except PermissionError:
            pass

    if sys.platform.startswith("linux"):
        try:
            stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError:
            return ""
        command_end = stat_text.rfind(")")
        fields = stat_text[command_end + 2 :].split() if command_end >= 0 else []
        return f"procfs:{fields[19]}" if len(fields) > 19 else ""

    if os.name == "nt":  # pragma: no cover - exercised on Windows CI
        try:
            import ctypes
            from ctypes import wintypes

            class _FileTime(ctypes.Structure):
                _fields_ = (("low", wintypes.DWORD), ("high", wintypes.DWORD))

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            open_process = kernel32.OpenProcess
            open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            open_process.restype = wintypes.HANDLE
            get_process_times = kernel32.GetProcessTimes
            get_process_times.argtypes = (
                wintypes.HANDLE,
                ctypes.POINTER(_FileTime),
                ctypes.POINTER(_FileTime),
                ctypes.POINTER(_FileTime),
                ctypes.POINTER(_FileTime),
            )
            get_process_times.restype = wintypes.BOOL
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = (wintypes.HANDLE,)
            close_handle.restype = wintypes.BOOL
            handle = open_process(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return None if ctypes.get_last_error() == 87 else ""
            try:
                created = _FileTime()
                exited = _FileTime()
                kernel = _FileTime()
                user = _FileTime()
                if not get_process_times(
                    handle,
                    ctypes.byref(created),
                    ctypes.byref(exited),
                    ctypes.byref(kernel),
                    ctypes.byref(user),
                ):
                    return ""
                return f"filetime:{(created.high << 32) | created.low}"
            finally:
                close_handle(handle)
        except (AttributeError, OSError, TypeError, ValueError):
            return ""

    try:
        completed = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    started = completed.stdout.strip()
    if completed.returncode != 0 or not started:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return None
        except (PermissionError, OSError):
            return ""
        return ""
    return f"ps:{started}"


_CURRENT_PROCESS_PID = os.getpid()
_CURRENT_PROCESS_INCARNATION = _process_incarnation(_CURRENT_PROCESS_PID)


def _current_execution_owner() -> dict[str, Any]:
    pid = os.getpid()
    incarnation = (
        _CURRENT_PROCESS_INCARNATION
        if pid == _CURRENT_PROCESS_PID
        else _process_incarnation(pid)
    )
    if not incarnation:
        raise RuntimeError("Could not prove the DAG execution owner process incarnation.")
    return {
        "host": socket.gethostname(),
        "pid": pid,
        "process_incarnation": incarnation,
        "thread_id": threading.get_ident(),
    }


def _execution_owner_key(path: Path, attempt_id: str) -> tuple[str, str]:
    return str(path.expanduser().resolve(strict=False)), attempt_id


def _register_execution_owner(path: Path, attempt_id: str, thread_id: int) -> None:
    with _ACTIVE_EXECUTION_OWNERS_LOCK:
        key = _execution_owner_key(path, attempt_id)
        _FINISHED_EXECUTION_OWNERS.discard(key)
        _ACTIVE_EXECUTION_OWNERS[key] = thread_id


def _unregister_execution_owner(
    path: Path,
    attempt_id: str,
    *,
    callback_finished: bool = False,
) -> None:
    with _ACTIVE_EXECUTION_OWNERS_LOCK:
        key = _execution_owner_key(path, attempt_id)
        _ACTIVE_EXECUTION_OWNERS.pop(key, None)
        if callback_finished:
            _FINISHED_EXECUTION_OWNERS.add(key)


def _clear_finished_execution_owner(path: Path, attempt_id: str) -> None:
    with _ACTIVE_EXECUTION_OWNERS_LOCK:
        _FINISHED_EXECUTION_OWNERS.discard(_execution_owner_key(path, attempt_id))


def _execution_owner_liveness(
    path: Path,
    active_execution: Mapping[str, Any],
) -> bool | None:
    """Return True for live, False for dead, and None when proof is unavailable."""

    if str(active_execution.get("status", "")) == "recovery_required":
        return False
    owner = active_execution.get("owner")
    if not isinstance(owner, Mapping) or str(owner.get("host", "")) != socket.gethostname():
        return None
    try:
        pid = int(owner.get("pid"))
        thread_id = int(owner.get("thread_id"))
    except (TypeError, ValueError):
        return None
    recorded_incarnation = str(owner.get("process_incarnation", ""))
    if not recorded_incarnation:
        return None
    current_incarnation = (
        _CURRENT_PROCESS_INCARNATION
        if pid == _CURRENT_PROCESS_PID
        else _process_incarnation(pid)
    )
    if current_incarnation is None or (
        current_incarnation and current_incarnation != recorded_incarnation
    ):
        return False
    if not current_incarnation:
        return None
    if pid != os.getpid():
        return True
    owner_key = _execution_owner_key(
        path,
        str(active_execution.get("attempt_id", "")),
    )
    with _ACTIVE_EXECUTION_OWNERS_LOCK:
        if owner_key in _FINISHED_EXECUTION_OWNERS:
            return False
        registered_thread = _ACTIVE_EXECUTION_OWNERS.get(owner_key)
    if registered_thread is None:
        return None
    return registered_thread == thread_id


def _active_attempt_id(state: Mapping[str, Any]) -> str:
    active = runner_state_active_attempt(state)
    return str(active.get("attempt_id", "")).strip() if active is not None else ""


def _active_unit_tokens(state: Mapping[str, Any]) -> dict[str, str]:
    active = runner_state_active_attempt(state)
    values = active.get("unit_tokens") if active is not None else None
    if not isinstance(values, Mapping):
        return {}
    return {
        str(unit_id): str(token)
        for unit_id, token in values.items()
        if str(unit_id) and str(token)
    }


def _claimed_unit_tokens(state: Mapping[str, Any], attempt_id: str) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for unit in dag_units(state):
        attempt = unit.get("execution_attempt")
        if not isinstance(attempt, Mapping) or str(attempt.get("id", "")) != attempt_id:
            continue
        if unit.get("dispatch_status") != "running" or attempt.get("status") != "running":
            continue
        token = str(attempt.get("idempotency_token", "")).strip()
        unit_id = str(unit.get("id", "")).strip()
        if unit_id and token:
            tokens[unit_id] = token
    return tokens


def _raise_if_active_attempt(path: Path, state: Mapping[str, Any]) -> None:
    attempt_id = _active_attempt_id(state)
    if attempt_id:
        raise RunnerStateRecoveryRequiredError(path, attempt_id=attempt_id)


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
    attempt_id_fn: Callable[[], str] = lambda: uuid4().hex

    @property
    def state_path(self) -> Path:
        return self.lab_dir / ".agilab" / self.state_filename

    def load_or_create_state(self, *, reset: bool = False) -> tuple[dict[str, Any], Path, Path | None]:
        state, observed_revision = load_runner_state_snapshot(self.state_path)
        if state is not None and not reset:
            if runner_state_dag_matches(state, self.dag_path, self.repo_root):
                return state, self.state_path, self.dag_path
        if state is not None:
            _raise_if_active_attempt(self.state_path, state)

        replacement = build_persisted_runner_state(
            repo_root=self.repo_root,
            dag_path=self.dag_path,
        )
        try:
            with runner_state_write_transaction(
                self.state_path,
                replacement,
                expected_revision=observed_revision,
            ) as state_path:
                pass
            self.write_evidence(
                replacement,
                state_path=state_path,
                trigger={"surface": "workflow", "action": "state_created"},
            )
        except RunnerStateConflictError:
            if not reset:
                current, _current_revision = load_runner_state_snapshot(self.state_path)
                if current is not None and runner_state_dag_matches(
                    current,
                    self.dag_path,
                    self.repo_root,
                ):
                    return current, self.state_path, self.dag_path
            raise
        return replacement, self.state_path, self.dag_path

    def write_state(
        self,
        state: Mapping[str, Any],
        *,
        expected_revision: str | None = None,
    ) -> Path:
        current, current_revision = load_runner_state_snapshot(self.state_path)
        if current is not None:
            _raise_if_active_attempt(self.state_path, current)
            if expected_revision is None:
                raise ValueError(
                    "Writing an existing DAG runner state requires the revision observed "
                    "with the caller's snapshot."
                )
        effective_revision = (
            expected_revision
            if expected_revision is not None
            else current_revision
        )
        with runner_state_write_transaction(
            self.state_path,
            state,
            expected_revision=effective_revision,
        ) as state_path:
            pass
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

    def dispatch_next_runnable_transaction(
        self,
        state: Mapping[str, Any],
    ) -> RunnerDispatchResult:
        return self._run_state_transaction(
            state,
            action=self.dispatch_next_runnable,
            trigger_action="preview_dispatched",
        )

    def real_run_supported(self, state: Mapping[str, Any]) -> bool:
        return self.real_run_support(state).supported

    def real_run_support(self, state: Mapping[str, Any]) -> DagRealRunSupport:
        return controlled_real_run_support(state, self.dag_path, self.repo_root)

    def run_next_controlled_stage(
        self,
        state: Mapping[str, Any],
    ) -> DagStageExecutionResult:
        """Run one stage through the durable runner-state transaction boundary."""

        return self.run_next_controlled_stage_transaction(state)

    def _run_next_controlled_stage_uncommitted(
        self,
        state: Mapping[str, Any],
        *,
        execution_attempt_id: str,
        persist_execution_claim_fn: Callable[[Mapping[str, Any]], object],
    ) -> DagStageExecutionResult:
        return _run_next_controlled_stage_uncommitted(
            state,
            repo_root=self.repo_root,
            dag_path=self.dag_path,
            lab_dir=self.lab_dir,
            run_queue_fn=self.run_queue_fn,
            run_relay_fn=self.run_relay_fn,
            stage_run_fns=self.stage_run_fns,
            now_fn=self.now_fn,
            execution_attempt_id=execution_attempt_id,
            persist_execution_claim_fn=persist_execution_claim_fn,
        )

    def run_next_controlled_stage_transaction(
        self,
        state: Mapping[str, Any],
    ) -> DagStageExecutionResult:
        return self._run_execution_state_transaction(
            state,
            action=lambda current, attempt_id, persist_claim: self._run_next_controlled_stage_uncommitted(
                current,
                execution_attempt_id=attempt_id,
                persist_execution_claim_fn=persist_claim,
            ),
            trigger_action="controlled_stage_executed",
        )

    def run_ready_controlled_stages(
        self,
        state: Mapping[str, Any],
        *,
        max_workers: int | None = None,
        execution_backend: str = GLOBAL_DAG_STAGE_BACKEND_LOCAL,
    ) -> DagBatchExecutionResult:
        """Run all ready stages through the durable runner-state transaction boundary."""

        return self.run_ready_controlled_stages_transaction(
            state,
            max_workers=max_workers,
            execution_backend=execution_backend,
        )

    def _run_ready_controlled_stages_uncommitted(
        self,
        state: Mapping[str, Any],
        *,
        max_workers: int | None,
        execution_backend: str,
        execution_attempt_id: str,
        persist_execution_claim_fn: Callable[[Mapping[str, Any]], object],
    ) -> DagBatchExecutionResult:
        return _run_ready_controlled_stages_uncommitted(
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
            execution_attempt_id=execution_attempt_id,
            persist_execution_claim_fn=persist_execution_claim_fn,
        )

    def run_ready_controlled_stages_transaction(
        self,
        state: Mapping[str, Any],
        *,
        max_workers: int | None = None,
        execution_backend: str = GLOBAL_DAG_STAGE_BACKEND_LOCAL,
    ) -> DagBatchExecutionResult:
        return self._run_execution_state_transaction(
            state,
            action=lambda current, attempt_id, persist_claim: self._run_ready_controlled_stages_uncommitted(
                current,
                max_workers=max_workers,
                execution_backend=execution_backend,
                execution_attempt_id=attempt_id,
                persist_execution_claim_fn=persist_claim,
            ),
            trigger_action="controlled_stages_executed",
        )

    def _run_execution_state_transaction(
        self,
        state: Mapping[str, Any],
        *,
        action: Callable[
            [Mapping[str, Any], str, Callable[[Mapping[str, Any]], object]],
            _RunnerStateResultT,
        ],
        trigger_action: str,
    ) -> _RunnerStateResultT:
        attempt_id = self.attempt_id_fn()
        expected_revision = runner_state_revision(state)
        _raise_if_active_attempt(self.state_path, state)
        claim_persisted = False
        claim_revision = ""
        claimed_tokens: dict[str, str] = {}
        owner_registered = False

        def _persist_claim(claim_state: Mapping[str, Any]) -> object:
            nonlocal claim_persisted, claim_revision, claimed_tokens, owner_registered
            if claim_persisted:
                raise RuntimeError("A DAG execution attempt may persist only one pre-execution claim.")
            mutable_claim = claim_state if isinstance(claim_state, dict) else dict(claim_state)
            claimed_tokens = _claimed_unit_tokens(mutable_claim, attempt_id)
            if not claimed_tokens:
                raise RuntimeError("A DAG execution attempt must claim at least one unique unit token.")
            if len(set(claimed_tokens.values())) != len(claimed_tokens):
                raise RuntimeError("A DAG execution attempt produced duplicate per-unit idempotency tokens.")
            owner = _current_execution_owner()
            mutable_claim["active_execution"] = {
                "attempt_id": attempt_id,
                "status": "running",
                "claimed_at": str(mutable_claim.get("updated_at", "")),
                "unit_tokens": claimed_tokens,
                "recovery_policy": "exact_unit_token_required",
                "owner": owner,
            }
            with runner_state_write_transaction(
                self.state_path,
                mutable_claim,
                expected_revision=expected_revision,
                require_directory_fsync=True,
            ) as state_path:
                pass
            claim_revision = runner_state_revision(mutable_claim)
            claim_persisted = True
            _register_execution_owner(
                self.state_path,
                attempt_id,
                int(owner["thread_id"]),
            )
            owner_registered = True
            self.write_evidence(
                mutable_claim,
                state_path=state_path,
                trigger={
                    "surface": "workflow",
                    "action": "controlled_stage_claimed",
                    "attempt_id": attempt_id,
                    "idempotency_tokens": claimed_tokens,
                },
            )
            return _DURABLE_CLAIM_RECEIPT

        def _persist_recovery_required(exc: BaseException) -> None:
            error_detail = (
                exc.detail
                if isinstance(exc, DagExternalExecutionUncertainError)
                else (str(exc).strip() or type(exc).__name__)
            )
            if not claim_persisted:
                return
            try:
                # The exact attempt/tokens are the ownership proof. Do not let
                # an unrelated revision bump prevent fail-closed recovery state.
                with runner_state_transaction(self.state_path) as transaction:
                    latest_attempt_id = _active_attempt_id(transaction.state)
                    if (
                        latest_attempt_id != attempt_id
                        or _active_unit_tokens(transaction.state) != claimed_tokens
                    ):
                        raise RunnerStateAttemptConflictError(
                            self.state_path,
                            expected_attempt_id=attempt_id,
                            actual_attempt_id=latest_attempt_id,
                        )
                    recovery_state = deepcopy(transaction.state)
                    active_execution = recovery_state.get("active_execution")
                    if not isinstance(active_execution, dict):
                        raise RunnerStateAttemptConflictError(
                            self.state_path,
                            expected_attempt_id=attempt_id,
                            actual_attempt_id="",
                        )
                    active_execution["status"] = "recovery_required"
                    active_execution["recovery_required_at"] = self.now_fn()
                    active_execution["error"] = error_detail
                    state_path = transaction.commit(recovery_state)
                self.write_evidence(
                    recovery_state,
                    state_path=state_path,
                    trigger={
                        "surface": "workflow",
                        "action": "controlled_stage_recovery_required",
                        "attempt_id": attempt_id,
                        "idempotency_tokens": claimed_tokens,
                        "error": error_detail,
                    },
                )
            except BaseException as status_exc:
                exc.add_note(
                    "AGILAB could not persist the recovery-required status update: "
                    f"{status_exc}"
                )

        try:
            result = action(state, attempt_id, _persist_claim)
        except BaseException as exc:
            _persist_recovery_required(exc)
            if owner_registered:
                _unregister_execution_owner(
                    self.state_path,
                    attempt_id,
                    callback_finished=claim_persisted,
                )
            raise
        finalization_succeeded = False
        try:
            if claim_persisted:
                final_state = deepcopy(result.state)
                result_tokens = _active_unit_tokens(final_state)
                if (
                    result_tokens != claimed_tokens
                    or _active_attempt_id(final_state) != attempt_id
                ):
                    raise RunnerStateAttemptConflictError(
                        self.state_path,
                        expected_attempt_id=attempt_id,
                        actual_attempt_id=_active_attempt_id(final_state),
                    )
                for unit in dag_units(final_state):
                    unit_id = str(unit.get("id", ""))
                    if unit_id not in claimed_tokens:
                        continue
                    attempt = unit.get("execution_attempt")
                    token = (
                        str(attempt.get("idempotency_token", ""))
                        if isinstance(attempt, Mapping)
                        else ""
                    )
                    if token != claimed_tokens[unit_id] or unit.get(
                        "dispatch_status"
                    ) not in {"completed", "failed"}:
                        raise RunnerStateAttemptConflictError(
                            self.state_path,
                            expected_attempt_id=attempt_id,
                            actual_attempt_id=(
                                str(attempt.get("id", ""))
                                if isinstance(attempt, Mapping)
                                else ""
                            ),
                        )
                final_state.pop("active_execution", None)
                with runner_state_transaction(
                    self.state_path,
                    expected_revision=claim_revision,
                ) as transaction:
                    latest_attempt_id = _active_attempt_id(transaction.state)
                    if (
                        latest_attempt_id != attempt_id
                        or _active_unit_tokens(transaction.state) != claimed_tokens
                    ):
                        raise RunnerStateAttemptConflictError(
                            self.state_path,
                            expected_attempt_id=attempt_id,
                            actual_attempt_id=latest_attempt_id,
                        )
                    state_path = transaction.commit(final_state)
                result.state.clear()
                result.state.update(final_state)
                self.write_evidence(
                    final_state,
                    state_path=state_path,
                    trigger={
                        "surface": "workflow",
                        "action": trigger_action,
                        "attempt_id": attempt_id,
                        "idempotency_tokens": claimed_tokens,
                    },
                )
                finalization_succeeded = True
                return result

            if runner_state_revision(result.state) != expected_revision:
                with runner_state_transaction(
                    self.state_path,
                    expected_revision=expected_revision,
                ) as transaction:
                    state_path = transaction.commit(result.state)
                self.write_evidence(
                    result.state,
                    state_path=state_path,
                    trigger={"surface": "workflow", "action": trigger_action},
                )
            finalization_succeeded = True
            return result
        except BaseException as exc:
            _persist_recovery_required(exc)
            raise
        finally:
            if owner_registered:
                _unregister_execution_owner(
                    self.state_path,
                    attempt_id,
                    callback_finished=claim_persisted and not finalization_succeeded,
                )

    def _run_state_transaction(
        self,
        state: Mapping[str, Any],
        *,
        action: Callable[[Mapping[str, Any]], _RunnerStateResultT],
        trigger_action: str,
    ) -> _RunnerStateResultT:
        expected_revision = runner_state_revision(state)
        _raise_if_active_attempt(self.state_path, state)
        with runner_state_transaction(
            self.state_path,
            expected_revision=expected_revision,
        ) as transaction:
            result = action(transaction.state)
            if runner_state_revision(result.state) != transaction.revision:
                state_path = transaction.commit(result.state)
            else:
                state_path = None
        if state_path is not None:
            self.write_evidence(
                result.state,
                state_path=state_path,
                trigger={"surface": "workflow", "action": trigger_action},
            )
        return result

    def recover_execution_attempt_transaction(
        self,
        state: Mapping[str, Any],
        *,
        unit_id: str,
        idempotency_token: str,
    ) -> dict[str, Any]:
        expected_revision = runner_state_revision(state)
        with runner_state_transaction(
            self.state_path,
            expected_revision=expected_revision,
        ) as transaction:
            active_attempt_id = _active_attempt_id(transaction.state)
            recorded_token = _active_unit_tokens(transaction.state).get(unit_id, "")
            if recorded_token != idempotency_token:
                raise RunnerStateAttemptConflictError(
                    self.state_path,
                    expected_attempt_id=idempotency_token,
                    actual_attempt_id=recorded_token,
                )
            active_execution = runner_state_active_attempt(transaction.state)
            owner_liveness = (
                _execution_owner_liveness(self.state_path, active_execution)
                if active_execution is not None
                else None
            )
            if owner_liveness is not False:
                detail = "is still live" if owner_liveness else "cannot be proven stopped"
                raise DagExecutionRecoveryBlockedError(
                    f"Execution attempt `{_active_attempt_id(transaction.state)}` owner {detail}; "
                    "exact-token recovery is denied until the callback has stopped."
                )
            recovered = recover_execution_attempt(
                transaction.state,
                unit_id=unit_id,
                idempotency_token=idempotency_token,
                timestamp=self.now_fn(),
            )
            state_path = transaction.commit(recovered)
        _clear_finished_execution_owner(self.state_path, active_attempt_id)
        self.write_evidence(
            recovered,
            state_path=state_path,
            trigger={
                "surface": "workflow",
                "action": "controlled_stage_recovered",
                "unit_id": unit_id,
                "idempotency_token": idempotency_token,
            },
        )
        return recovered

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
    """Run one controlled stage with a durable claim and CAS finalization."""

    return DagRunEngine(
        repo_root=repo_root,
        lab_dir=lab_dir,
        dag_path=dag_path,
        run_queue_fn=run_queue_fn,
        run_relay_fn=run_relay_fn,
        stage_run_fns=stage_run_fns,
        now_fn=now_fn,
    ).run_next_controlled_stage(state)


def _run_next_controlled_stage_uncommitted(
    state: Mapping[str, Any],
    *,
    repo_root: Path,
    dag_path: Path | None,
    lab_dir: Path,
    execution_attempt_id: str,
    persist_execution_claim_fn: Callable[[Mapping[str, Any]], object],
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

    return _run_next_adapter_stage_uncommitted(
        support.adapter,
        state,
        DagExecutionContext(
            repo_root=repo_root,
            lab_dir=lab_dir,
            run_queue_fn=run_queue_fn or run_multi_app_dag_queue_baseline_app,
            run_relay_fn=run_relay_fn or run_multi_app_dag_relay_followup_app,
            stage_run_fns=stage_run_fns,
            now_fn=now_fn,
            execution_attempt_id=execution_attempt_id,
            persist_execution_claim_fn=persist_execution_claim_fn,
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
    """Run ready controlled stages with one durable multi-unit transaction."""

    return DagRunEngine(
        repo_root=repo_root,
        lab_dir=lab_dir,
        dag_path=dag_path,
        run_queue_fn=run_queue_fn,
        run_relay_fn=run_relay_fn,
        stage_run_fns=stage_run_fns,
        stage_submit_fn=stage_submit_fn,
        now_fn=now_fn,
    ).run_ready_controlled_stages(
        state,
        max_workers=max_workers,
        execution_backend=execution_backend,
    )


def _run_ready_controlled_stages_uncommitted(
    state: Mapping[str, Any],
    *,
    repo_root: Path,
    dag_path: Path | None,
    lab_dir: Path,
    execution_attempt_id: str,
    persist_execution_claim_fn: Callable[[Mapping[str, Any]], object],
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

    return _run_ready_adapter_stages_uncommitted(
        support.adapter,
        state,
        DagExecutionContext(
            repo_root=repo_root,
            lab_dir=lab_dir,
            run_queue_fn=run_queue_fn or run_multi_app_dag_queue_baseline_app,
            run_relay_fn=run_relay_fn or run_multi_app_dag_relay_followup_app,
            stage_run_fns=stage_run_fns,
            stage_submit_fn=stage_submit_fn,
            now_fn=now_fn,
            execution_attempt_id=execution_attempt_id,
            persist_execution_claim_fn=persist_execution_claim_fn,
        ),
        max_workers=max_workers,
        execution_backend=execution_backend,
    )
