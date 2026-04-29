from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Optional, Sequence, Tuple


class PipelineWorkflowStatus(str, Enum):
    EMPTY = "empty"
    GENERATED = "generated"
    STALE = "stale"
    RUNNABLE = "runnable"
    RUNNING = "running"
    FAILED = "failed"
    COMPLETE = "complete"


class PipelineCommandStatus(str, Enum):
    SUCCESS = "success"
    REFUSED = "refused"
    FAILED = "failed"
    NO_OP = "no-op"


class PipelineAction(str, Enum):
    ADD_STEP = "add_step"
    CLEAR_LOGS = "clear_logs"
    DELETE_STEP = "delete_step"
    DELETE_ALL = "delete_all"
    UNDO_DELETE = "undo_delete"
    RUN_PIPELINE = "run_pipeline"
    FORCE_RUN = "force_run"


@dataclass(frozen=True)
class PipelineCommandResult:
    status: PipelineCommandStatus
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in {PipelineCommandStatus.SUCCESS, PipelineCommandStatus.NO_OP}


@dataclass(frozen=True)
class PipelineVisibleStep:
    index: int
    label: str
    summary: str
    runnable: bool


@dataclass(frozen=True)
class PipelinePageState:
    index_page: str
    steps_file: Path
    selected_lab: str
    status: PipelineWorkflowStatus
    total_steps: int
    visible_steps: Tuple[PipelineVisibleStep, ...]
    execution_sequence: Tuple[int, ...]
    stale_step_refs: Tuple[Mapping[str, Any], ...]
    lock_state: Optional[Mapping[str, Any]]
    run_logs: Tuple[str, ...]
    last_run_log_file: str
    runnable_step_count: int
    can_run: bool
    can_force_run: bool
    run_disabled_reason: str
    available_actions: Tuple[PipelineAction, ...]
    blocked_actions: Mapping[PipelineAction, str]


def _default_is_displayable_step(entry: Mapping[str, Any]) -> bool:
    question = entry.get("Q", "")
    if isinstance(question, str) and question.strip():
        return True
    code = entry.get("C", "")
    return isinstance(code, str) and bool(code.strip())


def _default_is_runnable_step(entry: Mapping[str, Any]) -> bool:
    code = entry.get("C", "")
    return isinstance(code, str) and bool(code.strip())


def _default_step_summary(entry: Mapping[str, Any]) -> str:
    question = str(entry.get("Q") or "").strip()
    if question:
        return " ".join(question.split())
    code = str(entry.get("C") or "").strip()
    if code:
        return " ".join(code.splitlines()[0].split())
    return ""


def _default_step_label(idx: int, entry: Mapping[str, Any]) -> str:
    summary = _default_step_summary(entry)
    return f"Step {idx + 1}: {summary}" if summary else f"Step {idx + 1}"


def _default_find_legacy_steps(
    _steps: Sequence[Mapping[str, Any]],
    _sequence: Sequence[int],
) -> Sequence[Mapping[str, Any]]:
    return ()


@dataclass(frozen=True)
class PipelinePageStateDeps:
    is_displayable_step: Callable[[Mapping[str, Any]], bool] = _default_is_displayable_step
    is_runnable_step: Callable[[Mapping[str, Any]], bool] = _default_is_runnable_step
    step_summary: Callable[[Mapping[str, Any]], str] = _default_step_summary
    step_label: Callable[[int, Mapping[str, Any]], str] = _default_step_label
    find_legacy_agi_run_steps: Callable[
        [Sequence[Mapping[str, Any]], Sequence[int]], Sequence[Mapping[str, Any]]
    ] = _default_find_legacy_steps
    inspect_pipeline_run_lock: Optional[Callable[[Any], Optional[Mapping[str, Any]]]] = None


def normalize_execution_sequence(total_steps: int, sequence: Optional[Sequence[Any]]) -> Tuple[int, ...]:
    """Return a valid execution order, defaulting to all steps when selection is empty."""
    selected: list[int] = []
    seen: set[int] = set()
    for raw in sequence or ():
        try:
            idx = int(raw)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < total_steps and idx not in seen:
            selected.append(idx)
            seen.add(idx)
    if not selected and total_steps:
        selected = list(range(total_steps))
    return tuple(selected)


def _coerce_steps(steps: Sequence[Mapping[str, Any]]) -> Tuple[Mapping[str, Any], ...]:
    coerced: list[Mapping[str, Any]] = []
    for entry in steps:
        if isinstance(entry, Mapping):
            coerced.append(entry)
    return tuple(coerced)


def _format_stale_step_refs(stale_steps: Sequence[Mapping[str, Any]]) -> str:
    refs: list[str] = []
    for item in stale_steps[:5]:
        step = item.get("step", "?")
        line = item.get("line", "?")
        summary = str(item.get("summary") or "").strip()
        project = str(item.get("project") or "").strip()
        label = f"step {step}, line {line}"
        if project:
            label += f", {project}"
        if summary:
            label += f": {summary}"
        refs.append(label)
    if len(stale_steps) > 5:
        refs.append(f"{len(stale_steps) - 5} more")
    return "; ".join(refs)


def _selected_lab_name(raw: Any, steps_file: Path, env: Any = None) -> str:
    candidates = [
        raw,
        getattr(env, "selected_lab", None),
        getattr(env, "lab", None),
        steps_file.parent,
        getattr(env, "app", None),
    ]
    for candidate in candidates:
        if candidate in (None, ""):
            continue
        try:
            text = str(candidate).strip()
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        if not text:
            continue
        try:
            path = Path(text)
        except (OSError, RuntimeError, TypeError, ValueError):
            return text
        name = path.name.strip()
        return name or text
    return ""


def _derive_actions(
    *,
    total_steps: int,
    has_undo_snapshot: bool,
    can_run: bool,
    can_force_run: bool,
    lock_state: Optional[Mapping[str, Any]],
    run_disabled_reason: str,
    runnable_step_count: int,
    stale_step_refs: Sequence[Mapping[str, Any]],
) -> tuple[Tuple[PipelineAction, ...], Mapping[PipelineAction, str]]:
    available: list[PipelineAction] = [
        PipelineAction.ADD_STEP,
        PipelineAction.CLEAR_LOGS,
    ]
    blocked: dict[PipelineAction, str] = {}
    if total_steps > 0:
        available.extend([PipelineAction.DELETE_STEP, PipelineAction.DELETE_ALL])
    else:
        blocked[PipelineAction.DELETE_STEP] = "No pipeline step is available to delete."
        blocked[PipelineAction.DELETE_ALL] = "No pipeline steps are available to delete."

    if has_undo_snapshot:
        available.append(PipelineAction.UNDO_DELETE)
    else:
        blocked[PipelineAction.UNDO_DELETE] = "No delete snapshot is available to restore."

    if can_run:
        available.append(PipelineAction.RUN_PIPELINE)
    else:
        blocked[PipelineAction.RUN_PIPELINE] = (
            run_disabled_reason or "Pipeline cannot run in the current state."
        )

    if can_force_run:
        available.append(PipelineAction.FORCE_RUN)
    else:
        if stale_step_refs:
            reason = run_disabled_reason or "Stale snippets must be regenerated before force-run."
        elif runnable_step_count == 0:
            reason = run_disabled_reason or "No selected pipeline step contains runnable code."
        elif not lock_state:
            reason = "No pipeline lock is present."
        else:
            reason = run_disabled_reason or "Pipeline cannot be force-run in the current state."
        blocked[PipelineAction.FORCE_RUN] = reason

    return tuple(available), blocked


def build_pipeline_page_state(
    *,
    index_page: str,
    steps_file: Path,
    steps: Sequence[Mapping[str, Any]],
    sequence: Optional[Sequence[Any]],
    session_state: Mapping[str, Any],
    selected_lab: Any = None,
    env: Any = None,
    deps: PipelinePageStateDeps = PipelinePageStateDeps(),
) -> PipelinePageState:
    """Build a pure view-model for the Pipeline workflow controls."""
    step_entries = _coerce_steps(steps)
    total_steps = len(step_entries)
    execution_sequence = normalize_execution_sequence(total_steps, sequence)

    visible_steps: list[PipelineVisibleStep] = []
    for idx, entry in enumerate(step_entries):
        if not deps.is_displayable_step(entry):
            continue
        visible_steps.append(
            PipelineVisibleStep(
                index=idx,
                label=str(deps.step_label(idx, entry)),
                summary=str(deps.step_summary(entry)),
                runnable=bool(deps.is_runnable_step(entry)),
            )
        )

    stale_step_refs = tuple(dict(item) for item in deps.find_legacy_agi_run_steps(step_entries, execution_sequence))
    lock_state = deps.inspect_pipeline_run_lock(env) if deps.inspect_pipeline_run_lock else None
    lock_state = dict(lock_state) if isinstance(lock_state, Mapping) else None
    active_lock = bool(lock_state and not lock_state.get("is_stale"))
    stale_lock = bool(lock_state and lock_state.get("is_stale"))

    selected_runnable = {
        step.index
        for step in visible_steps
        if step.runnable and step.index in execution_sequence
    }
    runnable_step_count = len(selected_runnable)
    run_logs_key = f"{index_page}__run_logs"
    raw_logs = session_state.get(run_logs_key, ())
    run_logs = tuple(str(line) for line in raw_logs) if isinstance(raw_logs, Sequence) and not isinstance(raw_logs, str) else ()
    last_status = str(session_state.get(f"{index_page}__last_run_status") or "").strip().lower()
    last_run_log_file = str(session_state.get(f"{index_page}__last_run_log_file") or "")
    undo_payload = session_state.get(f"{index_page}__undo_delete_snapshot")
    has_undo_snapshot = isinstance(undo_payload, Mapping) and isinstance(undo_payload.get("steps"), list)

    run_disabled_reason = ""
    if stale_step_refs:
        detail = _format_stale_step_refs(stale_step_refs)
        run_disabled_reason = (
            "Selected steps contain stale AGI.run snippets that must be regenerated "
            f"before execution: {detail}."
        )
        status = PipelineWorkflowStatus.STALE
    elif active_lock:
        owner = str(lock_state.get("owner_text") or "unknown owner") if lock_state else "unknown owner"
        run_disabled_reason = f"Pipeline is already running or locked by {owner}."
        status = PipelineWorkflowStatus.RUNNING
    elif stale_lock:
        status = PipelineWorkflowStatus.STALE
    elif not visible_steps:
        run_disabled_reason = f"No visible pipeline steps were loaded from {steps_file}."
        status = PipelineWorkflowStatus.EMPTY
    elif runnable_step_count == 0:
        run_disabled_reason = "No selected pipeline step contains runnable code."
        status = PipelineWorkflowStatus.GENERATED
    elif last_status in {"failed", "error"}:
        status = PipelineWorkflowStatus.FAILED
    elif last_status in {"complete", "completed", "success", "succeeded"}:
        status = PipelineWorkflowStatus.COMPLETE
    else:
        status = PipelineWorkflowStatus.RUNNABLE

    can_run = not run_disabled_reason and runnable_step_count > 0
    can_force_run = bool(lock_state) and not stale_step_refs and runnable_step_count > 0
    available_actions, blocked_actions = _derive_actions(
        total_steps=total_steps,
        has_undo_snapshot=has_undo_snapshot,
        can_run=can_run,
        can_force_run=can_force_run,
        lock_state=lock_state,
        run_disabled_reason=run_disabled_reason,
        runnable_step_count=runnable_step_count,
        stale_step_refs=stale_step_refs,
    )

    return PipelinePageState(
        index_page=index_page,
        steps_file=Path(steps_file),
        selected_lab=_selected_lab_name(selected_lab, Path(steps_file), env=env),
        status=status,
        total_steps=total_steps,
        visible_steps=tuple(visible_steps),
        execution_sequence=execution_sequence,
        stale_step_refs=stale_step_refs,
        lock_state=lock_state,
        run_logs=run_logs,
        last_run_log_file=last_run_log_file,
        runnable_step_count=runnable_step_count,
        can_run=can_run,
        can_force_run=can_force_run,
        run_disabled_reason=run_disabled_reason,
        available_actions=available_actions,
        blocked_actions=blocked_actions,
    )


def clear_pipeline_run_logs(
    session_state: MutableMapping[str, Any],
    index_page: str,
) -> PipelineCommandResult:
    """Clear displayed Pipeline logs without touching steps or saved log files."""
    key = f"{index_page}__run_logs"
    try:
        logs = session_state.get(key, [])
        if not logs:
            session_state.setdefault(key, [])
            return PipelineCommandResult(
                status=PipelineCommandStatus.NO_OP,
                message="No page run logs to clear.",
                details={"key": key},
            )
        count = len(logs) if hasattr(logs, "__len__") else 0
        session_state[key] = []
    except Exception as exc:
        return PipelineCommandResult(
            status=PipelineCommandStatus.FAILED,
            message=f"Could not clear page run logs: {exc}",
            details={"key": key, "error": str(exc)},
        )
    return PipelineCommandResult(
        status=PipelineCommandStatus.SUCCESS,
        message="Page run logs cleared; saved log files are untouched.",
        details={"key": key, "count": count},
    )


def start_pipeline_run_command(
    *,
    page_state: PipelinePageState,
    requested_action: PipelineAction,
    session_state: MutableMapping[str, Any],
    env: Any,
    prepare_run_log_file: Callable[..., tuple[Any, Any]],
    get_run_placeholder: Callable[..., Any],
    push_run_log: Callable[..., Any],
    force_confirm_key: str | None = None,
) -> PipelineCommandResult:
    """Prepare a Pipeline run from typed state before Streamlit renders progress."""
    if requested_action not in {PipelineAction.RUN_PIPELINE, PipelineAction.FORCE_RUN}:
        return PipelineCommandResult(
            status=PipelineCommandStatus.REFUSED,
            message=f"Unsupported pipeline action: {requested_action}.",
            details={"action": requested_action},
        )

    if requested_action not in page_state.available_actions:
        return PipelineCommandResult(
            status=PipelineCommandStatus.REFUSED,
            message=page_state.blocked_actions.get(
                requested_action,
                "Pipeline cannot run in the current state.",
            ),
            details={"action": requested_action, "status": page_state.status},
        )

    if force_confirm_key:
        session_state.pop(force_confirm_key, None)
    session_state[f"{page_state.index_page}__last_run_status"] = "running"

    try:
        run_placeholder = get_run_placeholder(page_state.index_page)
        log_file_path, log_error = prepare_run_log_file(page_state.index_page, env, prefix="pipeline")
        if log_file_path:
            message = f"Run pipeline started... logs will be saved to {log_file_path}"
        else:
            message = f"Run pipeline started... (unable to prepare log file: {log_error})"
        push_run_log(page_state.index_page, message, run_placeholder)
    except Exception as exc:
        session_state[f"{page_state.index_page}__last_run_status"] = "failed"
        return PipelineCommandResult(
            status=PipelineCommandStatus.FAILED,
            message=f"Could not start pipeline run: {exc}",
            details={"action": requested_action, "error": str(exc)},
        )

    return PipelineCommandResult(
        status=PipelineCommandStatus.SUCCESS,
        message=message,
        details={
            "action": requested_action,
            "force_lock_clear": requested_action is PipelineAction.FORCE_RUN,
            "log_file_path": str(log_file_path) if log_file_path else "",
            "log_error": str(log_error or ""),
            "log_placeholder": run_placeholder,
        },
    )


def finish_pipeline_run_command(
    *,
    session_state: MutableMapping[str, Any],
    index_page: str,
    succeeded: bool,
    message: str | None = None,
) -> PipelineCommandResult:
    """Record Pipeline run completion through the command boundary."""
    status_value = "complete" if succeeded else "failed"
    try:
        session_state[f"{index_page}__last_run_status"] = status_value
    except Exception as exc:
        return PipelineCommandResult(
            status=PipelineCommandStatus.FAILED,
            message=f"Could not record pipeline run status: {exc}",
            details={"index_page": index_page, "status": status_value, "error": str(exc)},
        )

    return PipelineCommandResult(
        status=PipelineCommandStatus.SUCCESS if succeeded else PipelineCommandStatus.FAILED,
        message=message
        or (
            "Pipeline run finished."
            if succeeded
            else "Pipeline run failed. Inspect Run logs."
        ),
        details={"index_page": index_page, "status": status_value},
    )


def _delete_timestamp(timestamp: str | None = None) -> str:
    return timestamp or datetime.now().isoformat(timespec="seconds")


def _snapshot_with_delete_metadata(
    raw_snapshot: Any,
    *,
    label: str,
    timestamp: str | None,
) -> dict[str, Any]:
    snapshot = dict(raw_snapshot) if isinstance(raw_snapshot, Mapping) else {"steps": []}
    snapshot["label"] = label
    snapshot["timestamp"] = _delete_timestamp(timestamp)
    return snapshot


def delete_pipeline_step_command(
    *,
    session_state: MutableMapping[str, Any],
    index_page: str,
    step_index: int,
    lab_dir: Path,
    steps_file: Path,
    persisted_steps: Sequence[Mapping[str, Any]],
    selected_map: MutableMapping[Any, Any],
    capture_pipeline_snapshot: Callable[..., Any],
    remove_step: Callable[..., Any],
    timestamp: str | None = None,
) -> PipelineCommandResult:
    """Delete one Pipeline step through a typed command boundary."""
    if step_index < 0 or step_index >= len(persisted_steps):
        return PipelineCommandResult(
            status=PipelineCommandStatus.REFUSED,
            message=f"Step {step_index + 1} cannot be deleted because it is not available.",
            details={"index_page": index_page, "step_index": step_index},
        )

    undo_key = f"{index_page}__undo_delete_snapshot"
    try:
        snapshot = _snapshot_with_delete_metadata(
            capture_pipeline_snapshot(index_page, list(persisted_steps)),
            label=f"remove step {step_index + 1}",
            timestamp=timestamp,
        )
        session_state[undo_key] = snapshot
        selected_map.pop(step_index, None)
        remove_step(lab_dir, str(step_index), steps_file, index_page)
    except Exception as exc:
        return PipelineCommandResult(
            status=PipelineCommandStatus.FAILED,
            message=f"Could not delete step {step_index + 1}: {exc}",
            details={"index_page": index_page, "step_index": step_index, "error": str(exc)},
        )

    return PipelineCommandResult(
        status=PipelineCommandStatus.SUCCESS,
        message=f"Step {step_index + 1} deleted.",
        details={"index_page": index_page, "step_index": step_index, "undo_key": undo_key},
    )


def _coerce_total_steps(session_state: Mapping[str, Any], index_page: str, fallback: int) -> int:
    page_state = session_state.get(index_page)
    if isinstance(page_state, Sequence) and not isinstance(page_state, (str, bytes)) and page_state:
        try:
            total = int(page_state[-1])
        except (TypeError, ValueError):
            total = fallback
        else:
            return max(total, 0)
    return max(fallback, 0)


def delete_all_pipeline_steps_command(
    *,
    session_state: MutableMapping[str, Any],
    index_page: str,
    lab_dir: Path,
    module_path: Path,
    steps_file: Path,
    persisted_steps: Sequence[Mapping[str, Any]],
    sequence_widget_key: str,
    capture_pipeline_snapshot: Callable[..., Any],
    remove_step: Callable[..., Any],
    bump_history_revision: Callable[..., Any],
    persist_sequence_preferences: Callable[..., Any],
    confirm_key: str | None = None,
    timestamp: str | None = None,
) -> PipelineCommandResult:
    """Delete every Pipeline step while preserving an undo snapshot."""
    total_steps = _coerce_total_steps(session_state, index_page, len(persisted_steps))
    if total_steps <= 0:
        if confirm_key:
            session_state.pop(confirm_key, None)
        return PipelineCommandResult(
            status=PipelineCommandStatus.NO_OP,
            message="No pipeline steps to delete.",
            details={"index_page": index_page, "count": 0},
        )

    undo_key = f"{index_page}__undo_delete_snapshot"
    try:
        if confirm_key:
            session_state.pop(confirm_key, None)
        snapshot = _snapshot_with_delete_metadata(
            capture_pipeline_snapshot(index_page, list(persisted_steps)),
            label="delete pipeline",
            timestamp=timestamp,
        )
        session_state[undo_key] = snapshot
        for idx_remove in reversed(range(total_steps)):
            remove_step(lab_dir, str(idx_remove), steps_file, index_page)
        session_state[index_page] = [0, "", "", "", "", "", 0]
        session_state[f"{index_page}__details"] = {}
        session_state[f"{index_page}__venv_map"] = {}
        session_state[f"{index_page}__run_sequence"] = []
        session_state.pop(sequence_widget_key, None)
        session_state["lab_selected_venv"] = ""
        session_state[f"{index_page}__clear_q"] = True
        session_state[f"{index_page}__force_blank_q"] = True
        session_state[f"{index_page}__q_rev"] = session_state.get(f"{index_page}__q_rev", 0) + 1
        bump_history_revision()
        persist_sequence_preferences(module_path, steps_file, [])
    except Exception as exc:
        return PipelineCommandResult(
            status=PipelineCommandStatus.FAILED,
            message=f"Could not delete pipeline steps: {exc}",
            details={"index_page": index_page, "count": total_steps, "error": str(exc)},
        )

    return PipelineCommandResult(
        status=PipelineCommandStatus.SUCCESS,
        message=f"Deleted {total_steps} pipeline step(s).",
        details={"index_page": index_page, "count": total_steps, "undo_key": undo_key},
    )


def undo_pipeline_delete_command(
    *,
    session_state: MutableMapping[str, Any],
    index_page: str,
    module_path: Path,
    steps_file: Path,
    sequence_widget_key: str,
    restore_pipeline_snapshot: Callable[..., Any],
) -> PipelineCommandResult:
    """Restore the latest Pipeline delete snapshot through a typed command boundary."""
    undo_key = f"{index_page}__undo_delete_snapshot"
    undo_payload = session_state.get(undo_key)
    if not (isinstance(undo_payload, Mapping) and isinstance(undo_payload.get("steps"), list)):
        return PipelineCommandResult(
            status=PipelineCommandStatus.NO_OP,
            message="No deleted pipeline state is available to restore.",
            details={"index_page": index_page, "undo_key": undo_key},
        )

    try:
        restore_error = restore_pipeline_snapshot(
            module_path,
            steps_file,
            index_page,
            sequence_widget_key,
            dict(undo_payload),
        )
    except Exception as exc:
        return PipelineCommandResult(
            status=PipelineCommandStatus.FAILED,
            message=f"Undo failed: {exc}",
            details={"index_page": index_page, "undo_key": undo_key, "error": str(exc)},
        )
    if restore_error:
        return PipelineCommandResult(
            status=PipelineCommandStatus.FAILED,
            message=f"Undo failed: {restore_error}",
            details={"index_page": index_page, "undo_key": undo_key, "error": str(restore_error)},
        )

    session_state.pop(undo_key, None)
    return PipelineCommandResult(
        status=PipelineCommandStatus.SUCCESS,
        message="Deleted steps restored.",
        details={"index_page": index_page, "undo_key": undo_key},
    )
