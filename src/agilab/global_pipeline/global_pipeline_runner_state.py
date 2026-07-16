# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Runner-state helpers for AGILAB global pipeline DAGs."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Iterator, Mapping, TypeVar

_src_root = Path(__file__).resolve().parents[1]
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))
_agilab_pkg = sys.modules.get("agilab")
if _agilab_pkg is not None:
    package_path = str(_src_root / "agilab")
    package_paths = list(getattr(_agilab_pkg, "__path__", []) or [])
    if package_path not in package_paths:
        _agilab_pkg.__path__ = [*package_paths, package_path]

from agilab.global_pipeline.global_pipeline_execution_plan import (  # noqa: E402
    ExecutionPlan,
    build_execution_plan,
)


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
DEFAULT_RUN_ID = "multi-app-dag-runner-state"
MISSING_RUNNER_STATE_REVISION = "<missing-runner-state>"
_WINDOWS_FILE_SHARING_RETRY_TIMEOUT_SECONDS = 0.5
_WINDOWS_FILE_SHARING_RETRY_INTERVAL_SECONDS = 0.01
_RUNNER_STATE_LOCK_TIMEOUT_SECONDS = 5.0
_RUNNER_STATE_LOCK_RETRY_INTERVAL_SECONDS = 0.05
_T = TypeVar("_T")


def _is_windows() -> bool:
    return os.name == "nt"


def _run_with_windows_file_sharing_retry(operation: Callable[[], _T]) -> _T:
    """Retry only transient Windows sharing denials for mutable runner state."""

    deadline = time.monotonic() + _WINDOWS_FILE_SHARING_RETRY_TIMEOUT_SECONDS
    while True:
        try:
            return operation()
        except PermissionError:
            if not _is_windows():
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(_WINDOWS_FILE_SHARING_RETRY_INTERVAL_SECONDS, remaining))


class RunnerStateConflictError(RuntimeError):
    """Raised before a stale runner-state snapshot can overwrite newer state."""

    def __init__(self, path: Path, *, expected_revision: str, actual_revision: str) -> None:
        self.path = path
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        super().__init__(
            f"Runner state changed in another session: {path}; expected revision "
            f"{expected_revision}, found {actual_revision}. Reload the workflow state and retry."
        )


class RunnerStateDurabilityError(RuntimeError):
    """Raised when a pre-execution claim cannot be proven crash-durable."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(
            f"Runner-state claim was replaced at {path}, but its directory could not be fsynced. "
            "External execution was aborted; recover the recorded attempt explicitly before retrying."
        )


class RunnerStateRecoveryRequiredError(RuntimeError):
    """Raised when an ambiguous execution claim must be recovered explicitly."""

    def __init__(self, path: Path, *, attempt_id: str) -> None:
        self.path = path
        self.attempt_id = attempt_id
        super().__init__(
            f"Runner state {path} contains active attempt {attempt_id!r}. "
            "Recover that exact attempt before reset, source switch, preview dispatch, or another run."
        )


class RunnerStateAttemptConflictError(RuntimeError):
    """Raised when recovery or finalization presents the wrong attempt token."""

    def __init__(self, path: Path, *, expected_attempt_id: str, actual_attempt_id: str) -> None:
        self.path = path
        self.expected_attempt_id = expected_attempt_id
        self.actual_attempt_id = actual_attempt_id
        super().__init__(
            f"Runner-state attempt changed at {path}; expected {expected_attempt_id!r}, "
            f"found {actual_attempt_id!r}. Reload the state before recovery or finalization."
        )


_RUNNER_STATE_THREAD_LOCKS: dict[Path, threading.RLock] = {}
_RUNNER_STATE_THREAD_LOCKS_GUARD = threading.Lock()


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
                "detail": "persisted multi-app DAG runner state created",
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


def runner_state_revision(state: Mapping[str, Any]) -> str:
    """Return a deterministic revision used for optimistic state checks."""

    payload = json.dumps(
        state,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_runner_state_snapshot(path: Path) -> tuple[dict[str, Any] | None, str]:
    """Load one atomic state snapshot and its revision, including a missing-file token."""

    try:
        state = load_runner_state(path)
    except FileNotFoundError:
        return None, MISSING_RUNNER_STATE_REVISION
    return state, runner_state_revision(state)


def runner_state_active_attempt(state: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the durable active-execution claim, when one is present."""

    active = state.get("active_execution")
    if not isinstance(active, Mapping):
        return None
    attempt_id = str(active.get("attempt_id", "")).strip()
    if not attempt_id:
        return None
    return dict(active)


def _runner_state_thread_lock(path: Path) -> threading.RLock:
    key = path.expanduser().resolve(strict=False)
    with _RUNNER_STATE_THREAD_LOCKS_GUARD:
        return _RUNNER_STATE_THREAD_LOCKS.setdefault(key, threading.RLock())


def _runner_state_lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.lock")


def _ensure_directory_hierarchy_durable(path: Path) -> bool:
    """Create a directory tree and durably retain every new parent entry."""

    target = path.expanduser()
    missing: list[Path] = []
    cursor = target
    while not cursor.exists():
        missing.append(cursor)
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent
    if cursor.exists() and not cursor.is_dir():
        raise NotADirectoryError(cursor)

    durable = True
    if missing:
        for directory in reversed(missing):
            directory.mkdir(exist_ok=True)
            if not directory.is_dir():
                raise NotADirectoryError(directory)
            # The directory flush covers its initial contents; the parent flush
            # makes the new directory entry survive a power loss.
            durable = _fsync_runner_state_directory(directory) and durable
            durable = _fsync_runner_state_directory(directory.parent) and durable
    else:
        # A prior best-effort write may have created this entry without proving
        # it durable. Re-establish that proof before a strict execution claim.
        durable = _fsync_runner_state_directory(target) and durable
        if target.parent != target:
            durable = _fsync_runner_state_directory(target.parent) and durable
    return durable


@contextmanager
def _exclusive_runner_state_lock(
    path: Path,
    *,
    require_directory_fsync: bool = False,
) -> Iterator[None]:
    """Hold the stable per-state process and cross-process writer lock."""

    state_path = path.expanduser()
    hierarchy_durable = _ensure_directory_hierarchy_durable(state_path.parent)
    if require_directory_fsync and not hierarchy_durable:
        raise RunnerStateDurabilityError(state_path)
    lock_path = _runner_state_lock_path(state_path)
    thread_lock = _runner_state_thread_lock(lock_path)
    thread_locked = thread_lock.acquire(timeout=_RUNNER_STATE_LOCK_TIMEOUT_SECONDS)
    if not thread_locked:
        raise TimeoutError(
            f"Timed out waiting for runner-state lock {lock_path}. "
            "Another session may still be updating this workflow; retry after it finishes."
        )
    try:
        handle = lock_path.open("a+b")
        locked = False
        try:
            if os.name == "nt":  # pragma: no cover - exercised on Windows CI
                import msvcrt

                if lock_path.stat().st_size == 0:
                    handle.write(b"\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                def _try_lock() -> None:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                def _try_lock() -> None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            deadline = time.monotonic() + _RUNNER_STATE_LOCK_TIMEOUT_SECONDS
            while True:
                try:
                    _try_lock()
                    locked = True
                    break
                except OSError as exc:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(
                            f"Timed out waiting for runner-state lock {lock_path}. "
                            "Another session may still be updating this workflow; "
                            "retry after it finishes."
                        ) from exc
                    time.sleep(min(_RUNNER_STATE_LOCK_RETRY_INTERVAL_SECONDS, remaining))
            yield
        finally:
            try:
                if locked and os.name == "nt":  # pragma: no cover - exercised on Windows CI
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                elif locked:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
    finally:
        thread_lock.release()


def _fsync_runner_state_directory(path: Path) -> bool:
    if os.name == "nt":  # pragma: no cover - exercised on Windows CI
        return _flush_windows_directory(path)
    try:
        directory_fd = os.open(path, os.O_RDONLY)
    except OSError:
        # The atomic replace has already committed. Directory fsync is a best-effort
        # durability hardening step and must not report the committed state as failed.
        return False
    durable = True
    try:
        try:
            os.fsync(directory_fd)
        except OSError:
            # Keep post-rename semantics unambiguous: callers may continue to publish
            # evidence for the state that is now visible at ``path``.
            durable = False
    finally:
        try:
            os.close(directory_fd)
        except OSError:
            pass
    return durable


def _flush_windows_directory(path: Path) -> bool:
    """Flush rename metadata through a Windows directory handle or fail closed."""

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        create_file.restype = wintypes.HANDLE
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL
        flush_file_buffers = kernel32.FlushFileBuffers
        flush_file_buffers.argtypes = (wintypes.HANDLE,)
        flush_file_buffers.restype = wintypes.BOOL

        handle = create_file(
            str(path),
            0x40000000,  # GENERIC_WRITE is required by FlushFileBuffers
            0x00000001 | 0x00000002 | 0x00000004,  # share read/write/delete
            None,
            3,  # OPEN_EXISTING
            0x02000000,  # FILE_FLAG_BACKUP_SEMANTICS for directory handles
            None,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if handle in (None, invalid_handle):
            return False
        try:
            return bool(flush_file_buffers(handle))
        finally:
            close_handle(handle)
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def _write_runner_state_atomic(
    path: Path,
    state: Mapping[str, Any],
    *,
    require_directory_fsync: bool = False,
) -> Path:
    path = path.expanduser()
    hierarchy_durable = _ensure_directory_hierarchy_durable(path.parent)
    if require_directory_fsync and not hierarchy_durable:
        raise RunnerStateDurabilityError(path)
    text = json.dumps(state, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        if path.exists():
            os.chmod(tmp_path, path.stat().st_mode & 0o777)
        stream = os.fdopen(fd, "w", encoding="utf-8")
        fd = -1
        with stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        _run_with_windows_file_sharing_retry(lambda: os.replace(tmp_path, path))
        directory_durable = _fsync_runner_state_directory(path.parent)
        if require_directory_fsync and not directory_durable:
            raise RunnerStateDurabilityError(path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
    return path


def _raise_runner_state_conflict(
    path: Path,
    *,
    expected_revision: str,
    actual_revision: str,
) -> None:
    if actual_revision != expected_revision:
        raise RunnerStateConflictError(
            path,
            expected_revision=expected_revision,
            actual_revision=actual_revision,
        )


@dataclass
class RunnerStateTransaction:
    """A locked runner-state snapshot that may be committed with CAS semantics."""

    path: Path
    state: dict[str, Any]
    revision: str
    _active: bool = True

    def commit(
        self,
        state: Mapping[str, Any],
        *,
        require_directory_fsync: bool = False,
    ) -> Path:
        if not self._active:
            raise RuntimeError("Runner-state transaction is no longer active.")
        current = load_runner_state(self.path)
        actual_revision = runner_state_revision(current)
        _raise_runner_state_conflict(
            self.path,
            expected_revision=self.revision,
            actual_revision=actual_revision,
        )
        path = _write_runner_state_atomic(
            self.path,
            state,
            require_directory_fsync=require_directory_fsync,
        )
        self.state = dict(state)
        self.revision = runner_state_revision(state)
        return path


@contextmanager
def runner_state_transaction(
    path: Path,
    *,
    expected_revision: str | None = None,
) -> Iterator[RunnerStateTransaction]:
    """Lock, reload, and optionally reject a stale runner-state revision."""

    state_path = path.expanduser()
    with _exclusive_runner_state_lock(state_path):
        state = load_runner_state(state_path)
        revision = runner_state_revision(state)
        if expected_revision is not None:
            _raise_runner_state_conflict(
                state_path,
                expected_revision=expected_revision,
                actual_revision=revision,
            )
        transaction = RunnerStateTransaction(
            path=state_path,
            state=state,
            revision=revision,
        )
        try:
            yield transaction
        finally:
            transaction._active = False


@contextmanager
def runner_state_write_transaction(
    path: Path,
    state: Mapping[str, Any],
    *,
    expected_revision: str | None = None,
    require_directory_fsync: bool = False,
) -> Iterator[Path]:
    """Atomically write state under the stable runner-state lock.

    ``MISSING_RUNNER_STATE_REVISION`` is an explicit compare-and-swap token for
    first creation. A normal revision protects reset and source-replacement
    writers from overwriting a state changed while they waited for the lock.
    """

    state_path = path.expanduser()
    with _exclusive_runner_state_lock(
        state_path,
        require_directory_fsync=require_directory_fsync,
    ):
        if expected_revision is not None:
            _current, actual_revision = load_runner_state_snapshot(state_path)
            _raise_runner_state_conflict(
                state_path,
                expected_revision=expected_revision,
                actual_revision=actual_revision,
            )
        written_path = _write_runner_state_atomic(
            state_path,
            state,
            require_directory_fsync=require_directory_fsync,
        )
        yield written_path


def write_runner_state(
    path: Path,
    state: Mapping[str, Any],
    *,
    expected_revision: str | None = None,
) -> Path:
    """Atomically write runner state after an optional revision check."""

    state_path = path.expanduser()
    with _exclusive_runner_state_lock(state_path):
        if expected_revision is not None:
            current = load_runner_state(state_path)
            _raise_runner_state_conflict(
                state_path,
                expected_revision=expected_revision,
                actual_revision=runner_state_revision(current),
            )
        return _write_runner_state_atomic(state_path, state)


def load_runner_state(path: Path) -> dict[str, Any]:
    state_path = path.expanduser()
    state = json.loads(
        _run_with_windows_file_sharing_retry(
            lambda: state_path.read_text(encoding="utf-8")
        )
    )
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
        message="No runnable multi-app DAG unit is available to dispatch.",
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
        state_unit = {
            "id": unit_id,
            "order_index": unit.get("order_index"),
            "app": str(unit.get("app", "")),
            "plan_status": str(unit.get("status", "")),
            "plan_runner_status": str(unit.get("runner_status", "")),
            "dispatch_status": dispatch_status,
            "depends_on": _as_str_list(unit.get("depends_on")),
            "artifact_dependencies": dependencies,
            "produces": [
                artifact
                for artifact in unit.get("produces", [])
                if isinstance(artifact, dict)
            ],
            "transitions": _transitions_for_unit(dependencies),
            "retry": _retry_metadata(unit_id),
            "partial_rerun": _partial_rerun_metadata(unit),
            "operator_ui": _operator_ui_state(unit_id, dependencies),
            "provenance": _provenance(plan, unit),
        }
        execution_contract = unit.get("execution_contract")
        if isinstance(execution_contract, dict) and execution_contract:
            state_unit["execution_contract"] = deepcopy(execution_contract)
        state_units.append(state_unit)

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
    "MISSING_RUNNER_STATE_REVISION",
    "PERSISTENCE_FORMAT",
    "PLANNED_STATUS",
    "RUNNER_MODE",
    "RUNNING_STATUS",
    "RUNNABLE_STATUS",
    "RUN_STATUS",
    "RunnerDispatchResult",
    "RunnerStateAttemptConflictError",
    "RunnerStateConflictError",
    "RunnerStateDurabilityError",
    "RunnerStateRecoveryRequiredError",
    "RunnerState",
    "RunnerStateIssue",
    "RunnerStatePersistenceProof",
    "SCHEMA",
    "build_persisted_runner_state",
    "build_runner_state",
    "dispatch_next_runnable",
    "load_runner_state",
    "load_runner_state_snapshot",
    "persist_runner_state",
    "runner_state_revision",
    "runner_state_active_attempt",
    "runner_state_transaction",
    "runner_state_write_transaction",
    "write_runner_state",
]
