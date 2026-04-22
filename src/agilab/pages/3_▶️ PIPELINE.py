import logging
import os
import json
import socket
import time
import traceback
import uuid
from pathlib import Path
import importlib
import importlib.util
import sys
import sysconfig
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd
import re
os.environ.setdefault("STREAMLIT_CONFIG_FILE", str(Path(__file__).resolve().parents[1] / "resources" / "config.toml"))
import streamlit as st
from streamlit.errors import StreamlitAPIException
import tomllib        # For reading TOML files

_import_guard_path = Path(__file__).resolve().parents[1] / "import_guard.py"
_import_guard_spec = importlib.util.spec_from_file_location("agilab_import_guard_local", _import_guard_path)
if _import_guard_spec is None or _import_guard_spec.loader is None:
    raise ModuleNotFoundError(f"Unable to load import_guard.py from {_import_guard_path}")
_import_guard_module = importlib.util.module_from_spec(_import_guard_spec)
_import_guard_spec.loader.exec_module(_import_guard_module)
import_agilab_symbols = _import_guard_module.import_agilab_symbols
load_local_module = _import_guard_module.load_local_module

import_agilab_symbols(
    globals(),
    "agilab.page_docs",
    ["render_page_docs_access"],
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "page_docs.py",
    fallback_name="agilab_page_docs_fallback",
)
from agi_env.pagelib import (
    activate_mlflow,
    background_services_enabled,
    find_files,
    run_agi,
    run_lab,
    load_df,
    get_custom_buttons,
    get_info_bar,
    get_about_content,
    get_css_text,
    export_df,
    save_csv,
    on_df_change,
    render_logo,
    inject_theme,
)
from agi_env import AgiEnv, normalize_path
import_agilab_symbols(
    globals(),
    "agilab.pipeline_views",
    {
        "load_pipeline_conceptual_dot": "load_pipeline_conceptual_dot",
        "render_pipeline_view": "render_pipeline_view",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "pipeline_views.py",
    fallback_name="agilab_pipeline_views_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.pipeline_steps",
    {
        "ORCHESTRATE_LOCKED_SOURCE_KEY": "ORCHESTRATE_LOCKED_SOURCE_KEY",
        "ORCHESTRATE_LOCKED_STEP_KEY": "ORCHESTRATE_LOCKED_STEP_KEY",
        "bump_history_revision": "_bump_history_revision",
        "ensure_primary_module_key": "_ensure_primary_module_key",
        "get_available_virtualenvs": "get_available_virtualenvs",
        "is_displayable_step": "_is_displayable_step",
        "is_orchestrate_locked_step": "_is_orchestrate_locked_step",
        "is_runnable_step": "_is_runnable_step",
        "load_sequence_preferences": "_load_sequence_preferences",
        "looks_like_step": "_looks_like_step",
        "module_keys": "_module_keys",
        "normalize_runtime_path": "normalize_runtime_path",
        "orchestrate_snippet_source": "_orchestrate_snippet_source",
        "persist_sequence_preferences": "_persist_sequence_preferences",
        "pipeline_export_root": "_pipeline_export_root",
        "prune_invalid_entries": "_prune_invalid_entries",
        "snippet_source_guidance": "_snippet_source_guidance",
        "step_button_label": "_step_button_label",
        "step_label_for_multiselect": "_step_label_for_multiselect",
        "step_summary": "_step_summary",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "pipeline_steps.py",
    fallback_name="agilab_pipeline_steps_fallback",
)
_pipeline_ai_module = import_agilab_symbols(
    globals(),
    "agilab.pipeline_ai",
    {
        "CODE_STRICT_INSTRUCTIONS": "CODE_STRICT_INSTRUCTIONS",
        "UOAIC_AUTOFIX_ENV": "UOAIC_AUTOFIX_ENV",
        "UOAIC_AUTOFIX_MAX_ENV": "UOAIC_AUTOFIX_MAX_ENV",
        "UOAIC_AUTOFIX_MAX_STATE_KEY": "UOAIC_AUTOFIX_MAX_STATE_KEY",
        "UOAIC_AUTOFIX_STATE_KEY": "UOAIC_AUTOFIX_STATE_KEY",
        "UOAIC_DATA_ENV": "UOAIC_DATA_ENV",
        "UOAIC_DB_ENV": "UOAIC_DB_ENV",
        "UOAIC_MODE_ENV": "UOAIC_MODE_ENV",
        "UOAIC_MODE_OLLAMA": "UOAIC_MODE_OLLAMA",
        "UOAIC_MODE_RAG": "UOAIC_MODE_RAG",
        "UOAIC_MODE_STATE_KEY": "UOAIC_MODE_STATE_KEY",
        "UOAIC_PROVIDER": "UOAIC_PROVIDER",
        "UOAIC_REBUILD_FLAG_KEY": "UOAIC_REBUILD_FLAG_KEY",
        "UOAIC_RUNTIME_KEY": "UOAIC_RUNTIME_KEY",
        "ask_gpt": "ask_gpt",
        "configure_assistant_engine": "configure_assistant_engine",
        "extract_code": "extract_code",
        "gpt_oss_controls": "gpt_oss_controls",
        "universal_offline_controls": "universal_offline_controls",
        "_maybe_autofix_generated_code": "_maybe_autofix_generated_code",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "pipeline_ai.py",
    fallback_name="agilab_pipeline_ai_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.pipeline_editor",
    {
        "_capture_pipeline_snapshot": "_capture_pipeline_snapshot",
        "_force_persist_step": "_force_persist_step",
        "_restore_pipeline_snapshot": "_restore_pipeline_snapshot",
        "build_notebook_export_context": "build_notebook_export_context",
        "get_steps_list": "get_steps_list",
        "on_import_notebook": "on_import_notebook",
        "refresh_notebook_export": "refresh_notebook_export",
        "remove_step": "remove_step",
        "save_step": "save_step",
        "toml_to_notebook": "toml_to_notebook",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "pipeline_editor.py",
    fallback_name="agilab_pipeline_editor_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.pipeline_lab",
    {
        "PipelineLabDeps": "PipelineLabDeps",
        "display_lab_tab": "display_lab_tab",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "pipeline_lab.py",
    fallback_name="agilab_pipeline_lab_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.pipeline_runtime",
    {
        "build_mlflow_process_env": "build_mlflow_process_env",
        "label_for_step_runtime": "_label_for_step_runtime",
        "log_mlflow_artifacts": "log_mlflow_artifacts",
        "mlflow_tracking_uri": "mlflow_tracking_uri",
        "ensure_safe_service_template": "_ensure_safe_service_template",
        "is_valid_runtime_root": "_is_valid_runtime_root",
        "python_for_step": "_python_for_step",
        "python_for_venv": "_python_for_venv",
        "run_locked_step": "_run_locked_step",
        "start_mlflow_run": "start_mlflow_run",
        "stream_run_command": "_stream_run_command",
        "to_bool_flag": "_to_bool_flag",
        "wrap_code_with_mlflow_resume": "wrap_code_with_mlflow_resume",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "pipeline_runtime.py",
    fallback_name="agilab_pipeline_runtime_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.pipeline_sidebar",
    {
        "available_lab_modules": "_available_lab_modules",
        "load_last_active_app_name": "_load_last_active_app_name",
        "normalize_lab_choice": "_normalize_lab_choice",
        "on_lab_change": "on_lab_change",
        "open_notebook_in_browser": "open_notebook_in_browser",
        "resolve_lab_export_dir": "_resolve_lab_export_dir",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "pipeline_sidebar.py",
    fallback_name="agilab_pipeline_sidebar_fallback",
)

# Constants
STEPS_FILE_NAME = "lab_steps.toml"
DEFAULT_DF = "lab_out.csv"
PIPELINE_LOCK_SCHEMA = "agilab.pipeline.lock.v1"
PIPELINE_LOCK_FILENAME = "pipeline_run.lock"
PIPELINE_LOCK_DEFAULT_TTL_SEC = 6 * 3600.0
SAFE_SERVICE_START_TEMPLATE_FILENAME = "AGI_serve_safe_start_template.py"
SAFE_SERVICE_START_TEMPLATE_MARKER = "# AGILAB_AUTO_GENERATED_PIPELINE_SNIPPET: SAFE_SERVICE_START"
# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
ANSI_ESCAPE_RE = re.compile(r"\x1b[^m]*m")


class JumpToMain(Exception):
    """Custom exception to jump back to the main execution flow."""
    pass


_pipeline_ai_module.JumpToMain = JumpToMain


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
        "agilab.tracking_uri": mlflow_tracking_uri(env),
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
    summary = _step_summary(entry, width=80)
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
    """Add a log line to the run log buffer (keeps the last 200)."""
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
                logger.debug(f"Failed to append experiment log to {log_file_path}: {exc}")
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
    """Return the cached run-log placeholder (if the UI has rendered it)."""
    key = f"{index_page}__run_placeholder"
    placeholder = st.session_state.get(key)
    return placeholder


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
    """Read lock payload; return empty dict on parse/read failure."""
    try:
        with open(path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
        if isinstance(payload, dict):
            return payload
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return {}


def _pipeline_lock_owner_text(payload: Dict[str, Any], age_sec: Optional[float]) -> str:
    """Format a concise lock owner description for logs/UI."""
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
    age_sec: Optional[float]
    try:
        age_sec = max(time.time() - lock_path.stat().st_mtime, 0.0)
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

    if force:
        if not _clear_pipeline_run_lock(
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
                if _clear_pipeline_run_lock(
                    env,
                    index_page,
                    placeholder,
                    reason=reason,
                ):
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
    """Release pipeline lock if still owned by this process/token."""
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

def on_page_change() -> None:
    """Set the 'page_broken' flag in session state."""
    st.session_state.page_broken = True


def on_step_change(
    module_dir: Path,
    steps_file: Path,
    index_step: int,
    index_page: str,
) -> None:
    """Update session state when a step is selected."""
    st.session_state[index_page][0] = index_step
    st.session_state.step_checked = False
    # Schedule prompt clear and blank on next render; bump input revision to remount widget
    st.session_state[f"{index_page}__clear_q"] = True
    st.session_state[f"{index_page}__q_rev"] = st.session_state.get(f"{index_page}__q_rev", 0) + 1
    # Drop any existing editor instance state for this step (best-effort)
    st.session_state.pop(f"{index_page}_a_{index_step}", None)
    venv_map = st.session_state.get(f"{index_page}__venv_map", {})
    st.session_state["lab_selected_venv"] = normalize_runtime_path(venv_map.get(index_step, ""))
    # Do not call st.rerun() here: callbacks automatically trigger a rerun
    # after returning. Rely on the updated session_state to refresh the UI.
    return


def load_last_step(
    module_dir: Path,
    steps_file: Path,
    index_page: str,
) -> None:
    """Load the last step for a module into session state."""
    details_store = st.session_state.setdefault(f"{index_page}__details", {})
    all_steps = load_all_steps(module_dir, steps_file, index_page)
    if all_steps:
        last_step = len(all_steps) - 1
        current_step = st.session_state[index_page][0]
        if current_step <= last_step:
            entry = all_steps[current_step] or {}
            d = entry.get("D", "")
            q = entry.get("Q", "")
            m = entry.get("M", "")
            c = entry.get("C", "")
            detail = details_store.get(current_step, "")
            st.session_state[index_page][1:6] = [d, q, m, c, detail]
            raw_e = normalize_runtime_path(entry.get("E", ""))
            e = raw_e if _is_valid_runtime_root(raw_e) else ""
            venv_map = st.session_state.setdefault(f"{index_page}__venv_map", {})
            if e:
                venv_map[current_step] = e
                st.session_state["lab_selected_venv"] = e
            else:
                venv_map.pop(current_step, None)
                st.session_state["lab_selected_venv"] = ""
            engine_map = st.session_state.setdefault(f"{index_page}__engine_map", {})
            selected_engine = entry.get("R", "") or ("agi.run" if e else "runpy")
            if selected_engine:
                engine_map[current_step] = selected_engine
            else:
                engine_map.pop(current_step, None)
            st.session_state["lab_selected_engine"] = selected_engine
            # Drive the text area via session state, using a revisioned key to control remounts
            q_rev = st.session_state.get(f"{index_page}__q_rev", 0)
            prompt_key = f"{index_page}_q__{q_rev}"
            # Allow actions to force a blank prompt on the next run
            if st.session_state.pop(f"{index_page}__force_blank_q", False):
                st.session_state[prompt_key] = ""
            else:
                st.session_state[prompt_key] = q
        else:
            clean_query(index_page)


def clean_query(index_page: str) -> None:
    """Reset the query fields in session state."""
    df_value = st.session_state.get("df_file", "") or ""
    st.session_state[index_page][1:-1] = [df_value, "", "", "", ""]
    details_store = st.session_state.setdefault(f"{index_page}__details", {})
    current_step = st.session_state[index_page][0] if index_page in st.session_state else None
    if current_step is not None:
        details_store.pop(current_step, None)
        venv_store = st.session_state.setdefault(f"{index_page}__venv_map", {})
        venv_store.pop(current_step, None)
        st.session_state["lab_selected_venv"] = ""

@st.cache_data(show_spinner=False)
def _read_steps(steps_file: Path, module_key: str, mtime_ns: int) -> List[Dict[str, Any]]:
    """Read steps for a specific module key from a TOML file.

    Caches on (path, module_key, mtime_ns) so saves invalidate automatically.
    """
    with open(steps_file, "rb") as f:
        data = tomllib.load(f)
    return list(data.get(module_key, []))


def _ensure_notebook_export(steps_file: Path) -> None:
    """Materialize the notebook export for a steps file when missing."""
    notebook_path = steps_file.with_suffix(".ipynb")
    if notebook_path.exists():
        return
    try:
        with open(steps_file, "rb") as stream:
            steps_full = tomllib.load(stream)
        toml_to_notebook(steps_full, steps_file)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, TypeError, ValueError) as exc:
        logger.warning(f"Skipping notebook generation: {exc}")


def _render_notebook_download_button(notebook_path: Path, key: str) -> None:
    """Render the notebook download button for an exported notebook."""
    try:
        notebook_data = notebook_path.read_bytes()
        st.sidebar.download_button(
            "Export notebook",
            data=notebook_data,
            file_name=notebook_path.name,
            mime="application/x-ipynb+json",
            key=key,
        )
    except (OSError, StreamlitAPIException) as exc:
        st.sidebar.error(f"Failed to prepare notebook export: {exc}")


def load_all_steps(
    module_path: Path,
    steps_file: Path,
    index_page: str,
) -> Optional[List[Dict[str, Any]]]:
    """Load all steps for a module from a TOML file using str(module_path) as key.

    Uses a small cache keyed by file mtime to avoid re-parsing on every rerun.
    """
    try:
        module_key = _module_keys(module_path)[0]
        mtime_ns = steps_file.stat().st_mtime_ns
        raw_entries = _read_steps(steps_file, module_key, mtime_ns)
        filtered_entries = _prune_invalid_entries(raw_entries)
        if filtered_entries and not st.session_state[index_page][-1]:
            st.session_state[index_page][-1] = len(filtered_entries)
        if filtered_entries and not steps_file.with_suffix(".ipynb").exists():
            _ensure_notebook_export(steps_file)
        return filtered_entries
    except FileNotFoundError:
        return []
    except tomllib.TOMLDecodeError as e:
        st.error(f"Error decoding TOML: {e}")
        return []


def on_query_change(
    request_key: str,
    module: Path,
    step: int,
    steps_file: Path,
    df_file: Path,
    index_page: str,
    env: AgiEnv,
    provider_snapshot: str,
) -> None:
    """Handle the query action when user input changes."""
    current_provider = st.session_state.get(
        "lab_llm_provider",
        env.envars.get("LAB_LLM_PROVIDER", "openai"),
    )
    if provider_snapshot and provider_snapshot != current_provider:
        # Provider changed between the widget render and callback; skip the stale request.
        return

    try:
        if st.session_state.get(request_key):
            raw_text = str(st.session_state[request_key])
            trimmed = raw_text.strip()
            # Skip chat calls when the input looks like a pure comment.
            if trimmed.startswith("#") or trimmed.endswith("#"):
                st.info("Query skipped because it looks like a comment (starts/ends with '#').")
                return

            answer = ask_gpt(
                raw_text, df_file, index_page, env.envars
            )
            detail = answer[4] if len(answer) > 4 else ""
            model_label = answer[2] if len(answer) > 2 else ""
            venv_map = st.session_state.get(f"{index_page}__venv_map", {})
            engine_map = st.session_state.get(f"{index_page}__engine_map", {})
            nstep, entry = save_step(
                module,
                answer,
                step,
                0,
                steps_file,
                venv_map=venv_map,
                engine_map=engine_map,
            )
            skipped = st.session_state.get("_experiment_last_save_skipped", False)
            details_key = f"{index_page}__details"
            details_store = st.session_state.setdefault(details_key, {})
            if skipped or not detail:
                details_store.pop(step, None)
            else:
                details_store[step] = detail
            if skipped:
                st.info("Assistant response did not include runnable code. Step was not saved.")
            _bump_history_revision()
            st.session_state[index_page][0] = step
            # Deterministic mapping to D/Q/M/C slots
            d = entry.get("D", "")
            q = entry.get("Q", "")
            c = entry.get("C", "")
            m = entry.get("M", model_label)
            st.session_state[index_page][1:6] = [d, q, m, c, detail or ""]
            e = entry.get("E", "")
            if e:
                venv_map[step] = e
                st.session_state["lab_selected_venv"] = e
            st.session_state[f"{index_page}_q"] = q
            st.session_state[index_page][-1] = nstep
        st.session_state.pop(f"{index_page}_a_{step}", None)
        st.session_state.page_broken = True
    except JumpToMain:
        pass


def run_all_steps(
    lab_dir: Path,
    index_page_str: str,
    steps_file: Path,
    module_path: Path,
    env: AgiEnv,
    log_placeholder: Optional[Any] = None,
    force_lock_clear: bool = False,
) -> None:
    """Execute all steps sequentially, honouring per-step virtual environments."""
    if log_placeholder is None:
        log_placeholder = _get_run_placeholder(index_page_str)
    _push_run_log(index_page_str, "Run pipeline invoked.", log_placeholder)
    steps = load_all_steps(module_path, steps_file, index_page_str) or []
    if not steps:
        st.info(f"No steps available to run from {steps_file}.")
        _push_run_log(index_page_str, "Run pipeline aborted: no steps available.", log_placeholder)
        return

    selected_map = st.session_state.setdefault(f"{index_page_str}__venv_map", {})
    engine_map = st.session_state.setdefault(f"{index_page_str}__engine_map", {})
    sequence_state_key = f"{index_page_str}__run_sequence"
    details_store = st.session_state.setdefault(f"{index_page_str}__details", {})
    original_step = st.session_state[index_page_str][0]
    original_selected = normalize_runtime_path(st.session_state.get("lab_selected_venv", ""))
    original_engine = st.session_state.get("lab_selected_engine", "")
    snippet_file = st.session_state.get("snippet_file")
    display_order: Dict[int, int] = {}
    if not snippet_file:
        st.error("Snippet file is not configured. Reload the page and try again.")
        _push_run_log(index_page_str, "Run pipeline aborted: snippet file not configured.", log_placeholder)
        return

    raw_sequence = st.session_state.get(sequence_state_key, [])
    sequence = [idx for idx in raw_sequence if 0 <= idx < len(steps)]
    if not sequence:
        sequence = list(range(len(steps)))

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
        with start_mlflow_run(
            env,
            run_name=parent_run_name,
            tags=parent_tags,
            params=parent_params,
        ) as pipeline_tracking:
            if pipeline_tracking:
                log_mlflow_artifacts(
                    pipeline_tracking,
                    text_artifacts=parent_text_artifacts,
                    file_artifacts=[steps_file],
                )
            with st.spinner("Running all steps…"):
                for idx in sequence:
                    _refresh_pipeline_run_lock(lock_handle)
                    entry = steps[idx]
                    code = entry.get("C", "")
                    if not _is_runnable_step(entry):
                        continue
                    _push_run_log(index_page_str, f"Running step {idx + 1}…", log_placeholder)

                    raw_runtime = normalize_runtime_path(entry.get("E", ""))
                    venv_path = raw_runtime if _is_valid_runtime_root(raw_runtime) else ""
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
                        fallback_runtime = normalize_runtime_path(getattr(env, "active_app", "") or "")
                        if _is_valid_runtime_root(fallback_runtime):
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
                    with start_mlflow_run(
                        env,
                        run_name=step_run_name,
                        tags=step_tags,
                        params=step_params,
                        nested=bool(pipeline_tracking),
                    ) as step_tracking:
                        step_env = build_mlflow_process_env(
                            env,
                            run_id=step_tracking["run"].info.run_id if step_tracking else None,
                        )
                        if step_tracking:
                            log_mlflow_artifacts(step_tracking, text_artifacts=step_text_artifacts)
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
                            script_path.write_text(wrap_code_with_mlflow_resume(code))
                            script_artifact = script_path
                            python_cmd = _python_for_step(venv_root, engine=engine, code=code)
                            output = _stream_run_command(
                                env,
                                index_page_str,
                                f"{python_cmd} {script_path}",
                                cwd=target_base,
                                push_run_log=_push_run_log,
                                ansi_escape_re=ANSI_ESCAPE_RE,
                                jump_exception_cls=JumpToMain,
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
                        summary = _step_summary({"Q": entry.get("Q", ""), "C": code})
                        env_label = _label_for_step_runtime(venv_root, engine=engine, code=code)
                        _push_run_log(
                            index_page_str,
                            f"Step {idx + 1}: engine={engine}, env={env_label}, summary=\"{summary}\"",
                            log_placeholder,
                        )
                        if step_tracking:
                            step_files = [script_artifact]
                            if export_target:
                                step_files.append(export_target)
                            log_mlflow_artifacts(
                                step_tracking,
                                text_artifacts={
                                    f"step_{idx + 1}/stdout.txt": preview or "",
                                },
                                file_artifacts=step_files,
                                tags={
                                    "agilab.status": "completed",
                                    "agilab.output_present": bool(preview),
                                },
                            )
                        executed += 1
            if pipeline_tracking:
                log_mlflow_artifacts(
                    pipeline_tracking,
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
        st.session_state["lab_selected_venv"] = normalize_runtime_path(original_selected)
        st.session_state["lab_selected_engine"] = original_engine
        st.session_state[f"{index_page_str}__force_blank_q"] = True
        st.session_state[f"{index_page_str}__q_rev"] = st.session_state.get(f"{index_page_str}__q_rev", 0) + 1
        _release_pipeline_run_lock(lock_handle, index_page_str, log_placeholder)


def on_nb_change(
    module: Path,
    query: List[Any],
    file_step_path: Path,
    project: str,
    notebook_file: Path,
    env: AgiEnv,
) -> None:
    """Handle notebook interaction and run notebook if possible."""
    module_path = Path(module)
    index_page = str(st.session_state.get("index_page", module_path))
    venv_map = st.session_state.get(f"{index_page}__venv_map", {})
    engine_map = st.session_state.get(f"{index_page}__engine_map", {})
    save_step(
        module_path,
        query[1:5],
        query[0],
        query[-1],
        file_step_path,
        venv_map=venv_map,
        engine_map=engine_map,
    )
    _bump_history_revision()
    project_path = env.apps_path / project
    if notebook_file.exists():
        cmd = f"uv -q run jupyter notebook {notebook_file}"
        code = (
            "import subprocess\n"
            f"subprocess.Popen({cmd!r}, shell=True, cwd={str(project_path)!r})\n"
        )
        output = run_agi(code, path=project_path)
        if output is None:
            open_notebook_in_browser()
        else:
            st.info(output)
    else:
        st.info(f"No file named {notebook_file} found!")


def sidebar_controls() -> None:
    """Create sidebar controls for selecting modules and DataFrames."""
    env: AgiEnv = st.session_state["env"]
    Agi_export_abs = _pipeline_export_root(env)
    modules = _available_lab_modules(env, Agi_export_abs)
    if not modules:
        modules = [env.target] if env.target else []

    # Keep the current AgiEnv target available even when no export directory
    # exists yet so the workflow does not jump to another project.
    if env.target and env.target not in modules:
        modules = [env.target] + modules

    # The active app can be renamed with _project; the exports are usually
    # un-suffixed (e.g. "flight"), keep both forms synchronized.
    target_name = Path(env.target).name if env.target else None
    if target_name and target_name not in modules:
        modules = [target_name] + modules

    requested_lab = _normalize_lab_choice(st.session_state.get("_requested_lab_dir"), modules)

    # If no explicit project was known, prefer the configured environment target.
    project_changed = st.session_state.pop("project_changed", False)
    if project_changed:
        for key in (
            "lab_dir_selectbox",
            "lab_dir",
            "index_page",
            "steps_file",
            "df_file",
            "df_file_in",
            "df_file_out",
            "steps_files",
            "df_files",
            "df_dir",
            "lab_prompt",
            "_experiment_reload_required",
        ):
            st.session_state.pop(key, None)
        st.session_state["_experiment_reload_required"] = True

    modules = [m for m in modules if m != "apps"]
    if not modules:
        modules = ["apps"]
    st.session_state['modules'] = modules

    def _qp_first(key: str) -> str | None:
        val = st.query_params.get(key)
        if isinstance(val, list):
            return val[0] if val else None
        if val is None:
            return None
        return str(val)

    configure_assistant_engine(env)

    last_active = _load_last_active_app_name(modules)
    normalized_target = _normalize_lab_choice(env.target, modules)
    if project_changed:
        persisted_lab = requested_lab or normalized_target or env.target
    else:
        persisted_lab = (
            _normalize_lab_choice(_qp_first("lab_dir_selectbox"), modules)
            or _normalize_lab_choice(st.session_state.get("lab_dir_selectbox"), modules)
            or _normalize_lab_choice(st.session_state.get("lab_dir"), modules)
            or _normalize_lab_choice(last_active, modules)
            or normalized_target
            or env.target
        )

    if persisted_lab not in modules:
        fallback = _normalize_lab_choice(env.target, modules)
        persisted_lab = fallback if fallback in modules else modules[0]
    elif persisted_lab == "apps" and normalized_target in modules:
        # Avoid selecting the top-level "apps" directory; prefer the active app/target.
        persisted_lab = normalized_target

    st.session_state["lab_dir"] = st.sidebar.selectbox(
        "Lab directory",
        modules,
        index=modules.index(persisted_lab),
        on_change=lambda: on_lab_change(st.session_state.lab_dir_selectbox),
        key="lab_dir_selectbox",
    )
    if requested_lab and st.session_state.get("lab_dir_selectbox") == requested_lab:
        st.session_state.pop("_requested_lab_dir", None)

    steps_file_name = st.session_state["steps_file_name"]
    export_root = _pipeline_export_root(env)
    lab_choice = Path(st.session_state["lab_dir_selectbox"]).name
    lab_dir = _resolve_lab_export_dir(export_root, lab_choice)
    lab_dir.mkdir(parents=True, exist_ok=True)
    st.session_state.df_dir = lab_dir
    steps_file = (lab_dir / steps_file_name).resolve()
    st.session_state["steps_file"] = steps_file

    steps_files = find_files(lab_dir, ".toml")
    st.session_state.steps_files = steps_files
    lab_root = lab_dir.name
    steps_files_path = [
        Path(file)
        for file in steps_files
        if Path(file).is_file()
        and Path(file).suffix.lower() == ".toml"
        and "lab_steps" in Path(file).name
    ]
    steps_file_rel = sorted(
        [
            rel_path
            for rel_path in (
                file.relative_to(Agi_export_abs)
                for file in steps_files_path
                if file.is_relative_to(Agi_export_abs)
            )
            if rel_path.parts and rel_path.parts[0] == lab_root
        ],
        key=str,
    )

    if "index_page" not in st.session_state:
        index_page = steps_file_rel[0] if steps_file_rel else env.target
        st.session_state["index_page"] = index_page
    else:
        index_page = st.session_state["index_page"]

    index_page_str = str(index_page)

    if steps_file_rel:
        st.sidebar.selectbox("Steps file", steps_file_rel, key="index_page", on_change=on_page_change)

    df_files = find_files(lab_dir)
    st.session_state.df_files = df_files

    if not steps_file.parent.exists():
        steps_file.parent.mkdir(parents=True, exist_ok=True)

    df_files_rel = sorted((Path(file).relative_to(Agi_export_abs) for file in df_files), key=str)
    key_df = index_page_str + "df"
    index = next((i for i, f in enumerate(df_files_rel) if f.name == DEFAULT_DF), 0)
    df_file_default = st.session_state.get("df_file")

    module_path = lab_dir.relative_to(Agi_export_abs)
    st.session_state["module_path"] = module_path

    st.sidebar.selectbox(
        "Dataframe",
        df_files_rel,
        key=key_df,
        index=index,
        on_change=on_df_change,
        args=(module_path, df_file_default, index_page_str, steps_file),
    )

    if st.session_state.get(key_df):
        st.session_state["df_file"] = str(Agi_export_abs / st.session_state[key_df])
    else:
        st.session_state["df_file"] = None

    # Persist sidebar selections into query params for reloads
    st.query_params.update(
        {
            "lab_dir_selectbox": st.session_state.get("lab_dir_selectbox", ""),
            "index_page": str(st.session_state.get("index_page", "")),
            "lab_llm_provider": st.session_state.get("lab_llm_provider", ""),
            "gpt_oss_endpoint": st.session_state.get("gpt_oss_endpoint", ""),
            "df_file": st.session_state.get("df_file", ""),
            # Keep other pages (e.g., Explore) aware of the current project
            "active_app": st.session_state.get("lab_dir_selectbox", ""),
        }
    )

    # Persist last active app for cross-page defaults (use current lab_dir path)
    # Last active app is now persisted via on_lab_change when user switches labs.

    key = index_page_str + "import_notebook"
    st.sidebar.file_uploader(
        "Import notebook",
        type="ipynb",
        key=key,
        on_change=on_import_notebook,
        args=(key, module_path, steps_file, index_page_str),
    )

    export_context = build_notebook_export_context(
        env,
        module_path,
        steps_file,
        project_name=lab_choice,
    )
    notebook_path = refresh_notebook_export(steps_file, export_context=export_context)
    if notebook_path and notebook_path.exists():
        _render_notebook_download_button(notebook_path, index_page_str + "export_notebook")


def mlflow_controls() -> None:
    """Display MLflow UI controls in sidebar."""
    st.sidebar.divider()
    st.sidebar.subheader("MLflow")
    st.sidebar.caption("Inspect experiment runs separately from pipeline execution.")

    if st.session_state.get("server_started"):
        mlflow_port = st.session_state.get("mlflow_port", 5000)
        mlflow_url = f"http://localhost:{mlflow_port}"
        st.sidebar.markdown(f"**Status:** running  \n**Port:** `{mlflow_port}`")
        st.sidebar.link_button(
            "Open UI",
            mlflow_url,
            help=f"Open the MLflow UI in a new tab on port {mlflow_port}.",
            width="stretch",
        )
    elif not st.session_state.get("server_started"):
        st.sidebar.markdown("**Status:** stopped")
        st.sidebar.caption("Start it from Edit.")


def _load_pre_prompt_messages(env: AgiEnv) -> list[Any]:
    """Load pre-prompt messages for the current app, falling back to an empty list."""
    pre_prompt_path = Path(env.app_src) / "pre_prompt.json"
    try:
        with open(pre_prompt_path, encoding="utf-8") as stream:
            pre_prompt_content = json.load(stream)
    except FileNotFoundError:
        st.warning(f"Missing pre_prompt.json at {pre_prompt_path}; using empty prompt.")
        try:
            pre_prompt_path.write_text("[]\n", encoding="utf-8")
        except OSError:
            st.warning(f"Unable to create {pre_prompt_path}; check folder permissions.")
        return []
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        st.warning(f"Failed to load pre_prompt.json: {exc}")
        return []

    if isinstance(pre_prompt_content, list):
        return pre_prompt_content

    st.warning(f"pre_prompt.json at {pre_prompt_path} is not a list of messages; using empty prompt.")
    return []


def _load_about_page_module():
    """Load the About page module using import fallback for source and packaged layouts."""
    about_path = Path(__file__).resolve().parents[1] / "About_agilab.py"
    page_module = load_local_module(
        "agilab.About_agilab",
        current_file=__file__,
        fallback_path=about_path,
        fallback_name="agilab_about_fallback",
    )
    if not hasattr(page_module, "main"):
        raise ModuleNotFoundError("Unable to import About_agilab page module.")
    return page_module


def page() -> None:
    """Main page logic handler."""
    global df_file

    if 'env' not in st.session_state or not getattr(st.session_state["env"], "init_done", False):
        page_module = importlib.import_module("agilab.About_agilab")
        page_module.main()
        st.rerun()

    env: AgiEnv = st.session_state["env"]
    if "openai_api_key" not in st.session_state:
        seed_key = env.envars.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
        if seed_key:
            st.session_state["openai_api_key"] = seed_key

    st.session_state["lab_prompt"] = _load_pre_prompt_messages(env)

    sidebar_controls()

    # Use the steps file parent as the concrete lab directory path
    lab_dir = Path(st.session_state["steps_file"]).parent
    index_page = st.session_state.get("index_page", lab_dir)
    index_page_str = str(index_page)
    steps_file = st.session_state["steps_file"]
    steps_file.parent.mkdir(parents=True, exist_ok=True)

    nsteps = len(get_steps_list(lab_dir, steps_file))
    st.session_state.setdefault(index_page_str, [nsteps, "", "", "", "", "", nsteps])
    st.session_state.setdefault(f"{index_page_str}__details", {})
    st.session_state.setdefault(f"{index_page_str}__venv_map", {})
    st.session_state.setdefault(f"{index_page_str}__engine_map", {})

    module_path = st.session_state["module_path"]
    # If a prompt clear was requested, clear the current revisioned key before loading the step
    if st.session_state.pop(f"{index_page_str}__clear_q", False):
        q_rev = st.session_state.get(f"{index_page_str}__q_rev", 0)
        st.session_state.pop(f"{index_page_str}_q__{q_rev}", None)
    load_last_step(module_path, steps_file, index_page_str)

    df_file = st.session_state.get("df_file")
    if not df_file or not Path(df_file).exists():
        default_df_path = (lab_dir / DEFAULT_DF).resolve()
        st.info(
            f"No dataframe exported for {lab_dir.name}. "
            f"You can proceed without a dataframe; data-dependent steps may need {default_df_path}."
        )
        st.session_state["df_file"] = None

    mlflow_controls()
    gpt_oss_controls(env)
    universal_offline_controls(env)

    lab_deps = PipelineLabDeps(
        load_all_steps=load_all_steps,
        save_step=save_step,
        remove_step=remove_step,
        force_persist_step=_force_persist_step,
        capture_pipeline_snapshot=_capture_pipeline_snapshot,
        restore_pipeline_snapshot=_restore_pipeline_snapshot,
        run_all_steps=run_all_steps,
        prepare_run_log_file=_prepare_run_log_file,
        get_run_placeholder=_get_run_placeholder,
        push_run_log=_push_run_log,
        rerun_fragment_or_app=_rerun_fragment_or_app,
        bump_history_revision=_bump_history_revision,
        ask_gpt=ask_gpt,
        maybe_autofix_generated_code=_maybe_autofix_generated_code,
        load_df_cached=load_df_cached,
        ensure_safe_service_template=_ensure_safe_service_template,
        inspect_pipeline_run_lock=_inspect_pipeline_run_lock,
        refresh_pipeline_run_lock=_refresh_pipeline_run_lock,
        acquire_pipeline_run_lock=_acquire_pipeline_run_lock,
        release_pipeline_run_lock=_release_pipeline_run_lock,
        label_for_step_runtime=_label_for_step_runtime,
        python_for_step=_python_for_step,
        python_for_venv=_python_for_venv,
        stream_run_command=lambda *args, **kwargs: _stream_run_command(
            *args,
            push_run_log=_push_run_log,
            ansi_escape_re=ANSI_ESCAPE_RE,
            jump_exception_cls=JumpToMain,
            **kwargs,
        ),
        run_locked_step=_run_locked_step,
        load_pipeline_conceptual_dot=load_pipeline_conceptual_dot,
        render_pipeline_view=render_pipeline_view,
        default_df=DEFAULT_DF,
        safe_service_template_filename=SAFE_SERVICE_START_TEMPLATE_FILENAME,
        safe_service_template_marker=SAFE_SERVICE_START_TEMPLATE_MARKER,
    )

    display_lab_tab(lab_dir, index_page_str, steps_file, module_path, env, lab_deps)
    # Disabled per request to hide the lab_steps.toml expander from the main UI.
    # display_history_tab(steps_file, module_path)


@st.cache_data
def get_df_files(export_abs_path: Path) -> List[Path]:
    return find_files(export_abs_path)


@st.cache_data
def load_df_cached(path: Path, nrows: int = 50, with_index: bool = True) -> Optional[pd.DataFrame]:
    return load_df(path, nrows, with_index)


def main() -> None:
    if 'env' not in st.session_state or not getattr(st.session_state["env"], "init_done", True):
        page_module = _load_about_page_module()
        page_module.main()
        st.rerun()

    env: AgiEnv = st.session_state['env']

    try:
        st.set_page_config(
            page_title="AGILab PIPELINE",
            layout="wide",
            menu_items=get_about_content(),
        )
        inject_theme(env.st_resources)

        st.session_state.setdefault("steps_file_name", STEPS_FILE_NAME)
        st.session_state.setdefault("help_path", Path(env.agilab_pck) / "gui/help")
        st.session_state.setdefault("projects", env.apps_path)
        st.session_state.setdefault("snippet_file", Path(env.AGILAB_LOG_ABS) / "lab_snippet.py")
        st.session_state.setdefault("server_started", False)
        st.session_state.setdefault("mlflow_port", 5000)
        st.session_state.setdefault("lab_selected_venv", "")

        df_dir_def = _pipeline_export_root(env) / env.target
        st.session_state.setdefault("steps_file", Path(env.active_app) / STEPS_FILE_NAME)
        st.session_state.setdefault("df_file_out", str(df_dir_def / DEFAULT_DF))
        st.session_state.setdefault("df_file", str(df_dir_def / DEFAULT_DF))

        df_file = Path(st.session_state["df_file"]) if st.session_state["df_file"] else None
        if df_file:
            render_logo()
        else:
            render_logo()
        render_page_docs_access(
            env,
            html_file="experiment-help.html",
            key_prefix="pipeline",
            sidebar=True,
            caption="Open the PIPELINE guide.",
        )

        if background_services_enabled() and not st.session_state.get("server_started", False):
            activate_mlflow(env)

        # Initialize session defaults
        defaults = {
            "response_dict": {"type": "", "text": ""},
            "apps_abs": env.apps_path,
            "page_broken": False,
            "step_checked": False,
            "virgin_page": True,
        }
        for key, value in defaults.items():
            st.session_state.setdefault(key, value)

        page()

    except (RuntimeError, OSError, TypeError, ValueError, AttributeError, KeyError) as e:
        st.error(f"An error occurred: {e}")
        import traceback

        st.code(f"```\n{traceback.format_exc()}\n```")


if __name__ == "__main__":
    main()
