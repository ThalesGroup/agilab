from __future__ import annotations

import importlib.util
import json
import logging
import os
import socket
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
import re
import streamlit as st
from streamlit.errors import StreamlitAPIException

from agi_env import AgiEnv
from agi_env.snippet_contract import stale_snippet_cleanup_message
from agi_gui.pagelib import run_lab, save_csv

_import_guard_path = Path(__file__).resolve().parent / "import_guard.py"
_import_guard_spec = importlib.util.spec_from_file_location("agilab_import_guard_local", _import_guard_path)
if _import_guard_spec is None or _import_guard_spec.loader is None:
    raise ModuleNotFoundError(f"Unable to load import_guard.py from {_import_guard_path}")
_import_guard_module = importlib.util.module_from_spec(_import_guard_spec)
_import_guard_spec.loader.exec_module(_import_guard_module)
import_agilab_module = _import_guard_module.import_agilab_module

_pipeline_steps = import_agilab_module(
    "agilab.pipeline_steps",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pipeline_steps.py",
    fallback_name="agilab_pipeline_steps_fallback",
)
_pipeline_runtime = import_agilab_module(
    "agilab.pipeline_runtime",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pipeline_runtime.py",
    fallback_name="agilab_pipeline_runtime_fallback",
)
_logging_utils = import_agilab_module(
    "agilab.logging_utils",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "logging_utils.py",
    fallback_name="agilab_logging_utils_fallback",
)

logger = logging.getLogger(__name__)

PIPELINE_LOCK_SCHEMA = "agilab.pipeline.lock.v1"
PIPELINE_LOCK_FILENAME = "pipeline_run.lock"
PIPELINE_LOCK_DEFAULT_TTL_SEC = 6 * 3600.0


def _mlflow_parent_payload(
    env: AgiEnv,
    lab_dir: Path,
    steps_file: Path,
    sequence: List[int],
) -> tuple[str, Dict[str, Any], Dict[str, Any], Dict[str, str]]:
    run_name = f"{env.app or 'agilab'}:{lab_dir.name}:pipeline"
    tags = {
        "agilab.component": "pipeline",
        "agilab.app": str(getattr(env, "app", "") or ""),
        "agilab.lab": lab_dir.name,
        "agilab.steps_file": str(steps_file),
        "agilab.tracking_uri": _pipeline_runtime.mlflow_tracking_uri(env),
    }
    params = {
        "sequence": ",".join(str(idx + 1) for idx in sequence),
        "step_count": len(sequence),
    }
    text_artifacts = {
        "pipeline_metadata/sequence.json": json.dumps(
            {
                "app": str(getattr(env, "app", "") or ""),
                "lab_dir": str(lab_dir),
                "steps_file": str(steps_file),
                "sequence": [idx + 1 for idx in sequence],
            },
            indent=2,
        )
    }
    return run_name, tags, params, text_artifacts


def _mlflow_step_payload(
    env: AgiEnv,
    lab_dir: Path,
    steps_file: Path,
    *,
    step_index: int,
    entry: Dict[str, Any],
    engine: str,
    runtime_root: str,
) -> tuple[str, Dict[str, Any], Dict[str, Any], Dict[str, str]]:
    summary = _pipeline_steps.step_summary(entry, width=80)
    run_name = f"{env.app or 'agilab'}:{lab_dir.name}:step_{step_index + 1}"
    tags = {
        "agilab.component": "pipeline-step",
        "agilab.app": str(getattr(env, "app", "") or ""),
        "agilab.lab": lab_dir.name,
        "agilab.steps_file": str(steps_file),
        "agilab.step_index": step_index + 1,
        "agilab.engine": engine,
        "agilab.runtime": runtime_root or "",
        "agilab.summary": summary,
    }
    params = {
        "description": entry.get("D", ""),
        "question": entry.get("Q", ""),
        "model": entry.get("M", ""),
        "runtime": runtime_root or "",
        "engine": engine,
    }
    text_artifacts = {
        f"step_{step_index + 1}/step_entry.json": json.dumps(
            {
                "step_index": step_index + 1,
                "summary": summary,
                "entry": entry,
            },
            indent=2,
        )
    }
    return run_name, tags, params, text_artifacts


def _append_run_log(index_page: str, message: str) -> None:
    """Add a log line to the run log buffer and keep the last 200 entries."""
    key = f"{index_page}__run_logs"
    logs: List[str] = st.session_state.setdefault(key, [])
    logs.append(message)
    if len(logs) > 200:
        st.session_state[key] = logs[-200:]


def _push_run_log(index_page: str, message: str, placeholder: Optional[Any] = None) -> None:
    """Append a log entry and refresh the visible placeholder if provided."""
    _append_run_log(index_page, message)
    log_file_key = f"{index_page}__run_log_file"
    log_file_path = st.session_state.get(log_file_key)
    if log_file_path:
        log_text = (message or "").rstrip("\n")
        if log_text:
            try:
                path_obj = Path(log_file_path).expanduser()
                path_obj.parent.mkdir(parents=True, exist_ok=True)
                with path_obj.open("a", encoding="utf-8") as log_file:
                    log_file.write(log_text + "\n")
            except (OSError, TypeError, ValueError) as exc:
                logger.debug(
                    "Failed to append experiment log to %s: %s",
                    _logging_utils.bound_log_value(log_file_path, _logging_utils.LOG_PATH_LIMIT),
                    _logging_utils.bound_log_value(exc, _logging_utils.LOG_DETAIL_LIMIT),
                )
    if placeholder is not None:
        logs = st.session_state.get(f"{index_page}__run_logs", [])
        if logs:
            placeholder.code("\n".join(logs))
        else:
            placeholder.caption("No runs recorded yet.")


def _rerun_fragment_or_app() -> None:
    """Prefer a fragment rerun when valid; otherwise fall back to a full app rerun."""
    try:
        st.rerun(scope="fragment")
    except StreamlitAPIException:
        st.rerun()


def _prepare_run_log_file(
    index_page: str,
    env: AgiEnv,
    prefix: str,
) -> Tuple[Optional[Path], Optional[str]]:
    """Create and register a log file for the current run context."""
    log_file_key = f"{index_page}__run_log_file"
    app_name = str(getattr(env, "app", "") or "agilab")
    raw_prefix = (prefix or "run").strip()
    safe_prefix = re.sub(r"[^A-Za-z0-9_-]+", "_", raw_prefix).strip("_") or "run"
    log_dir_candidate = env.runenv or (Path.home() / "log" / "execute" / app_name)
    try:
        log_dir_path = Path(log_dir_candidate).expanduser()
        log_dir_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        log_file_path = log_dir_path / f"{safe_prefix}_{timestamp}.log"
        log_file_path.write_text("", encoding="utf-8")
        st.session_state[log_file_key] = str(log_file_path)
        st.session_state[f"{index_page}__last_run_log_file"] = str(log_file_path)
        return log_file_path, None
    except (OSError, TypeError, ValueError) as exc:
        st.session_state.pop(log_file_key, None)
        return None, str(exc)


def _get_run_placeholder(index_page: str) -> Optional[Any]:
    """Return the cached run-log placeholder if the UI has rendered it."""
    return st.session_state.get(f"{index_page}__run_placeholder")


def _pipeline_lock_ttl_seconds() -> float:
    """Return lock TTL used to recycle stale pipeline run locks."""
    raw = str(os.environ.get("AGILAB_PIPELINE_LOCK_TTL_SEC", "")).strip()
    if not raw:
        return PIPELINE_LOCK_DEFAULT_TTL_SEC
    try:
        ttl = float(raw)
    except (TypeError, ValueError):
        return PIPELINE_LOCK_DEFAULT_TTL_SEC
    return ttl if ttl > 0 else PIPELINE_LOCK_DEFAULT_TTL_SEC


def _pipeline_lock_path(env: AgiEnv) -> Path:
    """Return shared lock path for one app pipeline execution."""
    target = str(getattr(env, "target", "") or getattr(env, "app", "") or "agilab").strip()
    relative = Path(".control") / "pipeline" / target / PIPELINE_LOCK_FILENAME
    try:
        path = env.resolve_share_path(relative)
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        fallback_home = Path(getattr(env, "home_abs", Path.home()) or Path.home())
        path = (fallback_home / ".agilab_pipeline" / target / PIPELINE_LOCK_FILENAME).resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_pipeline_lock_payload(path: Path) -> Dict[str, Any]:
    """Read lock payload and return an empty dict on parse or read failure."""
    try:
        with open(path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
        if isinstance(payload, dict):
            return payload
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return {}


def _pipeline_lock_owner_text(payload: Dict[str, Any], age_sec: Optional[float]) -> str:
    """Format a concise lock owner description for logs and UI."""
    owner_host = str(payload.get("host", "?"))
    owner_pid = payload.get("pid", "?")
    owner_app = str(payload.get("app", "?"))
    age_txt = f"{age_sec:.0f}s" if isinstance(age_sec, (int, float)) else "unknown"
    return f"host={owner_host}, pid={owner_pid}, app={owner_app}, age={age_txt}"


def _pipeline_lock_owner_alive(payload: Dict[str, Any]) -> Optional[bool]:
    """Return whether the lock owner PID appears alive on this host."""
    owner_host = str(payload.get("host", "") or "")
    if not owner_host or owner_host != socket.gethostname():
        return None
    try:
        owner_pid = int(payload.get("pid"))
    except (TypeError, ValueError, OverflowError):
        return None
    if owner_pid <= 0:
        return None
    try:
        os.kill(owner_pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None


def _inspect_pipeline_run_lock(env: AgiEnv) -> Optional[Dict[str, Any]]:
    """Return current lock metadata for UI and stale-lock decisions."""
    lock_path = _pipeline_lock_path(env)
    if not lock_path.exists():
        return None
    payload = _read_pipeline_lock_payload(lock_path)
    try:
        age_sec: Optional[float] = max(time.time() - lock_path.stat().st_mtime, 0.0)
    except OSError:
        age_sec = None
    owner_alive = _pipeline_lock_owner_alive(payload)
    ttl_sec = _pipeline_lock_ttl_seconds()
    stale_reason: Optional[str] = None
    if isinstance(age_sec, float) and age_sec > ttl_sec:
        stale_reason = f"heartbeat expired ({age_sec:.0f}s > {ttl_sec:.0f}s)"
    elif owner_alive is False:
        stale_reason = "owner process is no longer running on this host"
    return {
        "path": lock_path,
        "payload": payload,
        "age_sec": age_sec,
        "owner_alive": owner_alive,
        "owner_text": _pipeline_lock_owner_text(payload, age_sec),
        "stale_reason": stale_reason,
        "is_stale": bool(stale_reason),
    }


def _clear_pipeline_run_lock(
    env: AgiEnv,
    index_page: str,
    placeholder: Optional[Any] = None,
    *,
    reason: str,
) -> bool:
    """Remove the current pipeline lock, if any, and log why."""
    lock_state = _inspect_pipeline_run_lock(env)
    if not lock_state:
        return True
    lock_path = Path(lock_state["path"])
    try:
        lock_path.unlink()
        _push_run_log(
            index_page,
            f"Removed pipeline lock ({reason}): {lock_path}",
            placeholder,
        )
        return True
    except FileNotFoundError:
        return True
    except OSError as exc:
        msg = f"Unable to remove pipeline lock `{lock_path}`: {exc}"
        st.error(msg)
        _push_run_log(index_page, msg, placeholder)
        return False


def _acquire_pipeline_run_lock(
    env: AgiEnv,
    index_page: str,
    placeholder: Optional[Any] = None,
    *,
    force: bool = False,
) -> Optional[Dict[str, Any]]:
    """Acquire a cross-process pipeline lock with stale lock cleanup."""
    lock_path = _pipeline_lock_path(env)
    token = uuid.uuid4().hex
    now = time.time()
    payload = {
        "schema": PIPELINE_LOCK_SCHEMA,
        "token": token,
        "app": str(getattr(env, "app", "")),
        "target": str(getattr(env, "target", "")),
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "created_at": now,
        "heartbeat_at": now,
    }

    if force and not _clear_pipeline_run_lock(
        env,
        index_page,
        placeholder,
        reason="forced by user before starting a new run",
    ):
        return None

    for _ in range(2):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2)
            _push_run_log(index_page, f"Pipeline lock acquired: {lock_path}", placeholder)
            return {"path": lock_path, "token": token}
        except FileExistsError:
            lock_state = _inspect_pipeline_run_lock(env) or {
                "path": lock_path,
                "payload": {},
                "age_sec": None,
                "owner_text": _pipeline_lock_owner_text({}, None),
                "stale_reason": None,
                "is_stale": False,
            }
            if lock_state.get("is_stale"):
                reason = str(lock_state.get("stale_reason") or "stale lock")
                if _clear_pipeline_run_lock(env, index_page, placeholder, reason=reason):
                    continue
                return None

            owner_txt = str(lock_state.get("owner_text") or "?")
            msg = (
                "Another pipeline execution is already running. "
                f"Owner: {owner_txt}. Current run cancelled. "
                "If that run was interrupted, use 'Force unlock and run'."
            )
            st.warning(msg)
            _push_run_log(index_page, msg, placeholder)
            return None
        except (OSError, TypeError, ValueError) as exc:
            msg = f"Unable to acquire pipeline lock `{lock_path}`: {exc}"
            st.error(msg)
            _push_run_log(index_page, msg, placeholder)
            return None

    msg = f"Unable to acquire pipeline lock after stale cleanup retries: {lock_path}"
    st.warning(msg)
    _push_run_log(index_page, msg, placeholder)
    return None


def _refresh_pipeline_run_lock(lock_handle: Optional[Dict[str, Any]]) -> None:
    """Refresh heartbeat for an acquired pipeline lock."""
    if not lock_handle:
        return
    lock_path_raw = lock_handle.get("path")
    token = lock_handle.get("token")
    if not lock_path_raw or not token:
        return
    lock_path = Path(lock_path_raw)
    if not lock_path.exists():
        return

    payload = _read_pipeline_lock_payload(lock_path)
    if payload.get("token") != token:
        return
    payload["heartbeat_at"] = time.time()
    tmp_path = lock_path.with_suffix(lock_path.suffix + ".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
        os.replace(tmp_path, lock_path)
    except (OSError, TypeError, ValueError):
        logger.debug("Failed to refresh pipeline lock heartbeat for %s", lock_path, exc_info=True)


def _release_pipeline_run_lock(
    lock_handle: Optional[Dict[str, Any]],
    index_page: str,
    placeholder: Optional[Any] = None,
) -> None:
    """Release pipeline lock if still owned by this process and token."""
    if not lock_handle:
        return
    lock_path_raw = lock_handle.get("path")
    token = lock_handle.get("token")
    if not lock_path_raw or not token:
        return
    lock_path = Path(lock_path_raw)
    try:
        if not lock_path.exists():
            return
        payload = _read_pipeline_lock_payload(lock_path)
        if payload and payload.get("token") != token:
            return
        lock_path.unlink()
        _push_run_log(index_page, f"Pipeline lock released: {lock_path}", placeholder)
    except FileNotFoundError:
        return
    except OSError as exc:
        logger.debug("Failed to release pipeline lock %s: %s", lock_path, exc)


def _format_legacy_step_refs(stale_steps: List[Dict[str, Any]]) -> str:
    refs: List[str] = []
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


def _abort_if_legacy_agi_run_steps(
    index_page: str,
    steps_file: Path,
    steps: List[Dict[str, Any]],
    sequence: List[int],
    placeholder: Optional[Any],
) -> bool:
    """Block stale embedded AGI.run snippets before any pipeline work starts."""
    stale_steps = _pipeline_steps.find_legacy_agi_run_steps(steps, sequence)
    if not stale_steps:
        return False

    detail = _format_legacy_step_refs(stale_steps)
    message = (
        "Run pipeline aborted before execution: the selected lab steps contain old "
        "AGI.run snippets that call the removed keyword API instead of RunRequest. "
        f"{stale_snippet_cleanup_message([steps_file])} "
        f"Affected step(s): {detail}."
    )
    st.error(message)
    _push_run_log(index_page, message, placeholder)
    return True


def run_all_steps(
    lab_dir: Path,
    index_page_str: str,
    steps_file: Path,
    module_path: Path,
    env: AgiEnv,
    *,
    load_all_steps_fn: Callable[[Path, Path, str], Optional[List[Dict[str, Any]]]],
    stream_run_command_fn: Callable[..., str],
    log_placeholder: Optional[Any] = None,
    force_lock_clear: bool = False,
) -> None:
    """Execute all steps sequentially, honouring per-step virtual environments."""
    if log_placeholder is None:
        log_placeholder = _get_run_placeholder(index_page_str)
    _push_run_log(index_page_str, "Run pipeline invoked.", log_placeholder)
    steps = load_all_steps_fn(module_path, steps_file, index_page_str) or []
    if not steps:
        st.info(f"No steps available to run from {steps_file}.")
        _push_run_log(index_page_str, "Run pipeline aborted: no steps available.", log_placeholder)
        return

    selected_map = st.session_state.setdefault(f"{index_page_str}__venv_map", {})
    engine_map = st.session_state.setdefault(f"{index_page_str}__engine_map", {})
    sequence_state_key = f"{index_page_str}__run_sequence"
    details_store = st.session_state.setdefault(f"{index_page_str}__details", {})
    original_step = st.session_state[index_page_str][0]
    original_selected = _pipeline_steps.normalize_runtime_path(
        st.session_state.get("lab_selected_venv", "")
    )
    original_engine = st.session_state.get("lab_selected_engine", "")
    snippet_file = st.session_state.get("snippet_file")
    if not snippet_file:
        st.error("Snippet file is not configured. Reload the page and try again.")
        _push_run_log(index_page_str, "Run pipeline aborted: snippet file not configured.", log_placeholder)
        return

    raw_sequence = st.session_state.get(sequence_state_key, [])
    sequence = [idx for idx in raw_sequence if 0 <= idx < len(steps)]
    if not sequence:
        sequence = list(range(len(steps)))

    if _abort_if_legacy_agi_run_steps(index_page_str, steps_file, steps, sequence, log_placeholder):
        return

    lock_handle = _acquire_pipeline_run_lock(
        env,
        index_page_str,
        log_placeholder,
        force=force_lock_clear,
    )
    if lock_handle is None:
        return

    executed = 0
    try:
        parent_run_name, parent_tags, parent_params, parent_text_artifacts = _mlflow_parent_payload(
            env,
            lab_dir,
            steps_file,
            sequence,
        )
        pipeline_log_artifact = st.session_state.get(f"{index_page_str}__run_log_file")
        with _pipeline_runtime.start_tracker_run(
            env,
            run_name=parent_run_name,
            tags=parent_tags,
            params=parent_params,
        ) as pipeline_tracker:
            if pipeline_tracker:
                pipeline_tracker.log_artifacts(
                    text_artifacts=parent_text_artifacts,
                    file_artifacts=[steps_file],
                )
            with st.spinner("Running all steps…"):
                for idx in sequence:
                    _refresh_pipeline_run_lock(lock_handle)
                    entry = steps[idx]
                    code = entry.get("C", "")
                    if not _pipeline_steps.is_runnable_step(entry):
                        continue
                    _push_run_log(index_page_str, f"Running step {idx + 1}…", log_placeholder)

                    raw_runtime = _pipeline_steps.normalize_runtime_path(entry.get("E", ""))
                    venv_path = (
                        raw_runtime if _pipeline_runtime.is_valid_runtime_root(raw_runtime) else ""
                    )
                    if venv_path:
                        selected_map[idx] = venv_path
                        st.session_state["lab_selected_venv"] = venv_path
                    else:
                        selected_map.pop(idx, None)
                    runtime_root = venv_path or st.session_state.get("lab_selected_venv", "")

                    st.session_state[index_page_str][0] = idx
                    st.session_state[index_page_str][1] = entry.get("D", "")
                    st.session_state[index_page_str][2] = entry.get("Q", "")
                    st.session_state[index_page_str][3] = entry.get("M", "")
                    st.session_state[index_page_str][4] = code
                    st.session_state[index_page_str][5] = details_store.get(idx, "")

                    venv_root = runtime_root
                    entry_engine = str(entry.get("R", "") or "")
                    ui_engine = str(engine_map.get(idx) or "")
                    if ui_engine and ui_engine != entry_engine:
                        if entry_engine.startswith("agi.") and ui_engine == "runpy":
                            engine = entry_engine
                        else:
                            engine = ui_engine
                    elif entry_engine:
                        engine = entry_engine
                    else:
                        engine = "agi.run" if venv_root else "runpy"
                    if venv_root and engine == "runpy":
                        engine = "agi.run"
                    if engine.startswith("agi.") and not venv_root:
                        fallback_runtime = _pipeline_steps.normalize_runtime_path(
                            getattr(env, "active_app", "") or ""
                        )
                        if _pipeline_runtime.is_valid_runtime_root(fallback_runtime):
                            venv_root = fallback_runtime
                            st.session_state["lab_selected_venv"] = venv_root

                    step_run_name, step_tags, step_params, step_text_artifacts = _mlflow_step_payload(
                        env,
                        lab_dir,
                        steps_file,
                        step_index=idx,
                        entry=entry,
                        engine=engine,
                        runtime_root=venv_root,
                    )
                    target_base = Path(steps_file).parent.resolve()
                    if target_base.name == target_base.parent.name:
                        target_base = target_base.parent
                    target_base.mkdir(parents=True, exist_ok=True)
                    script_artifact: Optional[Path] = None
                    export_target = st.session_state.get("df_file_out", "")
                    with _pipeline_runtime.start_tracker_run(
                        env,
                        run_name=step_run_name,
                        tags=step_tags,
                        params=step_params,
                        nested=bool(pipeline_tracker),
                    ) as step_tracker:
                        step_env = _pipeline_runtime.build_mlflow_process_env(
                            env,
                            run_id=step_tracker.run_id if step_tracker else None,
                        )
                        if step_tracker:
                            step_tracker.log_artifacts(
                                text_artifacts=step_text_artifacts,
                            )
                        if engine == "runpy":
                            output = run_lab(
                                [entry.get("D", ""), entry.get("Q", ""), code],
                                snippet_file,
                                env.copilot_file,
                                env_overrides=step_env,
                            )
                            script_artifact = Path(snippet_file)
                        else:
                            script_path = (target_base / "AGI_run.py").resolve()
                            script_path.write_text(_pipeline_runtime.wrap_code_with_mlflow_resume(code))
                            script_artifact = script_path
                            python_cmd = _pipeline_runtime.python_for_step(
                                venv_root,
                                engine=engine,
                                code=code,
                            )
                            output = stream_run_command_fn(
                                env,
                                index_page_str,
                                [str(python_cmd), str(script_path)],
                                cwd=target_base,
                                placeholder=log_placeholder,
                                extra_env=step_env,
                            )
                        _refresh_pipeline_run_lock(lock_handle)

                        preview = (output or "").strip()
                        if preview:
                            _push_run_log(
                                index_page_str,
                                f"Output (step {idx + 1}):\n{preview}",
                                log_placeholder,
                            )
                            if "No such file or directory" in preview:
                                _push_run_log(
                                    index_page_str,
                                    "Hint: for AGI app steps, input/output data is normally resolved under "
                                    "agi_env.AGI_CLUSTER_SHARE. Check whether the upstream step created the "
                                    "expected file there before this step ran.",
                                    log_placeholder,
                                )
                        else:
                            _push_run_log(
                                index_page_str,
                                f"Output (step {idx + 1}): {engine} executed (no captured stdout)",
                                log_placeholder,
                            )

                        if isinstance(st.session_state.get("data"), pd.DataFrame) and not st.session_state["data"].empty:
                            if save_csv(st.session_state["data"], export_target):
                                st.session_state["df_file_in"] = export_target
                                st.session_state["step_checked"] = True
                        summary = _pipeline_steps.step_summary({"Q": entry.get("Q", ""), "C": code})
                        env_label = _pipeline_runtime.label_for_step_runtime(
                            venv_root,
                            engine=engine,
                            code=code,
                        )
                        _push_run_log(
                            index_page_str,
                            f"Step {idx + 1}: engine={engine}, env={env_label}, summary=\"{summary}\"",
                            log_placeholder,
                        )
                        if step_tracker:
                            step_files = [script_artifact]
                            if export_target:
                                step_files.append(export_target)
                            step_tracker.log_artifacts(
                                text_artifacts={f"step_{idx + 1}/stdout.txt": preview or ""},
                                file_artifacts=step_files,
                                tags={
                                    "agilab.status": "completed",
                                    "agilab.output_present": bool(preview),
                                },
                            )
                        executed += 1
            if pipeline_tracker:
                pipeline_tracker.log_artifacts(
                    file_artifacts=[pipeline_log_artifact] if pipeline_log_artifact else [],
                    tags={"agilab.status": "completed"},
                    metrics={"executed_steps": executed},
                )

        if executed:
            st.success(f"Executed {executed} step{'s' if executed != 1 else ''}.")
            _push_run_log(index_page_str, f"Run pipeline completed: {executed} step(s) executed.", log_placeholder)
        else:
            st.info("No runnable code found in the steps.")
            _push_run_log(index_page_str, "Run pipeline completed: no runnable code found.", log_placeholder)
    finally:
        st.session_state[index_page_str][0] = original_step
        st.session_state["lab_selected_venv"] = _pipeline_steps.normalize_runtime_path(
            original_selected
        )
        st.session_state["lab_selected_engine"] = original_engine
        st.session_state[f"{index_page_str}__force_blank_q"] = True
        st.session_state[f"{index_page_str}__q_rev"] = st.session_state.get(f"{index_page_str}__q_rev", 0) + 1
        _release_pipeline_run_lock(lock_handle, index_page_str, log_placeholder)
