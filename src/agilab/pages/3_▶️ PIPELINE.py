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
try:
    from agilab.pipeline_views import load_pipeline_conceptual_dot, render_pipeline_view
except ModuleNotFoundError:
    _pipeline_views_path = Path(__file__).resolve().parents[1] / "pipeline_views.py"
    _pipeline_views_spec = importlib.util.spec_from_file_location("agilab_pipeline_views_fallback", _pipeline_views_path)
    if _pipeline_views_spec is None or _pipeline_views_spec.loader is None:
        raise
    _pipeline_views_module = importlib.util.module_from_spec(_pipeline_views_spec)
    _pipeline_views_spec.loader.exec_module(_pipeline_views_module)
    load_pipeline_conceptual_dot = _pipeline_views_module.load_pipeline_conceptual_dot
    render_pipeline_view = _pipeline_views_module.render_pipeline_view
try:
    from agilab.pipeline_steps import (
        ORCHESTRATE_LOCKED_SOURCE_KEY,
        ORCHESTRATE_LOCKED_STEP_KEY,
        bump_history_revision as _bump_history_revision,
        ensure_primary_module_key as _ensure_primary_module_key,
        get_available_virtualenvs,
        is_displayable_step as _is_displayable_step,
        is_orchestrate_locked_step as _is_orchestrate_locked_step,
        is_runnable_step as _is_runnable_step,
        load_sequence_preferences as _load_sequence_preferences,
        looks_like_step as _looks_like_step,
        module_keys as _module_keys,
        normalize_runtime_path,
        orchestrate_snippet_source as _orchestrate_snippet_source,
        persist_sequence_preferences as _persist_sequence_preferences,
        pipeline_export_root as _pipeline_export_root,
        prune_invalid_entries as _prune_invalid_entries,
        snippet_source_guidance as _snippet_source_guidance,
        step_button_label as _step_button_label,
        step_label_for_multiselect as _step_label_for_multiselect,
        step_summary as _step_summary,
    )
except ModuleNotFoundError:
    _pipeline_steps_path = Path(__file__).resolve().parents[1] / "pipeline_steps.py"
    _pipeline_steps_spec = importlib.util.spec_from_file_location("agilab_pipeline_steps_fallback", _pipeline_steps_path)
    if _pipeline_steps_spec is None or _pipeline_steps_spec.loader is None:
        raise
    _pipeline_steps_module = importlib.util.module_from_spec(_pipeline_steps_spec)
    _pipeline_steps_spec.loader.exec_module(_pipeline_steps_module)
    ORCHESTRATE_LOCKED_SOURCE_KEY = _pipeline_steps_module.ORCHESTRATE_LOCKED_SOURCE_KEY
    ORCHESTRATE_LOCKED_STEP_KEY = _pipeline_steps_module.ORCHESTRATE_LOCKED_STEP_KEY
    _bump_history_revision = _pipeline_steps_module.bump_history_revision
    _ensure_primary_module_key = _pipeline_steps_module.ensure_primary_module_key
    get_available_virtualenvs = _pipeline_steps_module.get_available_virtualenvs
    _is_displayable_step = _pipeline_steps_module.is_displayable_step
    _is_orchestrate_locked_step = _pipeline_steps_module.is_orchestrate_locked_step
    _is_runnable_step = _pipeline_steps_module.is_runnable_step
    _load_sequence_preferences = _pipeline_steps_module.load_sequence_preferences
    _looks_like_step = _pipeline_steps_module.looks_like_step
    _module_keys = _pipeline_steps_module.module_keys
    normalize_runtime_path = _pipeline_steps_module.normalize_runtime_path
    _orchestrate_snippet_source = _pipeline_steps_module.orchestrate_snippet_source
    _persist_sequence_preferences = _pipeline_steps_module.persist_sequence_preferences
    _pipeline_export_root = _pipeline_steps_module.pipeline_export_root
    _prune_invalid_entries = _pipeline_steps_module.prune_invalid_entries
    _snippet_source_guidance = _pipeline_steps_module.snippet_source_guidance
    _step_button_label = _pipeline_steps_module.step_button_label
    _step_label_for_multiselect = _pipeline_steps_module.step_label_for_multiselect
    _step_summary = _pipeline_steps_module.step_summary
try:
    from agilab.pipeline_ai import (
        CODE_STRICT_INSTRUCTIONS,
        UOAIC_AUTOFIX_ENV,
        UOAIC_AUTOFIX_MAX_ENV,
        UOAIC_AUTOFIX_MAX_STATE_KEY,
        UOAIC_AUTOFIX_STATE_KEY,
        UOAIC_DATA_ENV,
        UOAIC_DB_ENV,
        UOAIC_MODE_ENV,
        UOAIC_MODE_OLLAMA,
        UOAIC_MODE_RAG,
        UOAIC_MODE_STATE_KEY,
        UOAIC_PROVIDER,
        UOAIC_REBUILD_FLAG_KEY,
        UOAIC_RUNTIME_KEY,
        ask_gpt,
        configure_assistant_engine,
        extract_code,
        gpt_oss_controls,
        universal_offline_controls,
        _maybe_autofix_generated_code,
    )
    import agilab.pipeline_ai as _pipeline_ai_module
except ModuleNotFoundError:
    _pipeline_ai_path = Path(__file__).resolve().parents[1] / "pipeline_ai.py"
    _pipeline_ai_spec = importlib.util.spec_from_file_location("agilab_pipeline_ai_fallback", _pipeline_ai_path)
    if _pipeline_ai_spec is None or _pipeline_ai_spec.loader is None:
        raise
    _pipeline_ai_module = importlib.util.module_from_spec(_pipeline_ai_spec)
    _pipeline_ai_spec.loader.exec_module(_pipeline_ai_module)
    CODE_STRICT_INSTRUCTIONS = _pipeline_ai_module.CODE_STRICT_INSTRUCTIONS
    UOAIC_AUTOFIX_ENV = _pipeline_ai_module.UOAIC_AUTOFIX_ENV
    UOAIC_AUTOFIX_MAX_ENV = _pipeline_ai_module.UOAIC_AUTOFIX_MAX_ENV
    UOAIC_AUTOFIX_MAX_STATE_KEY = _pipeline_ai_module.UOAIC_AUTOFIX_MAX_STATE_KEY
    UOAIC_AUTOFIX_STATE_KEY = _pipeline_ai_module.UOAIC_AUTOFIX_STATE_KEY
    UOAIC_DATA_ENV = _pipeline_ai_module.UOAIC_DATA_ENV
    UOAIC_DB_ENV = _pipeline_ai_module.UOAIC_DB_ENV
    UOAIC_MODE_ENV = _pipeline_ai_module.UOAIC_MODE_ENV
    UOAIC_MODE_OLLAMA = _pipeline_ai_module.UOAIC_MODE_OLLAMA
    UOAIC_MODE_RAG = _pipeline_ai_module.UOAIC_MODE_RAG
    UOAIC_MODE_STATE_KEY = _pipeline_ai_module.UOAIC_MODE_STATE_KEY
    UOAIC_PROVIDER = _pipeline_ai_module.UOAIC_PROVIDER
    UOAIC_REBUILD_FLAG_KEY = _pipeline_ai_module.UOAIC_REBUILD_FLAG_KEY
    UOAIC_RUNTIME_KEY = _pipeline_ai_module.UOAIC_RUNTIME_KEY
    ask_gpt = _pipeline_ai_module.ask_gpt
    configure_assistant_engine = _pipeline_ai_module.configure_assistant_engine
    extract_code = _pipeline_ai_module.extract_code
    gpt_oss_controls = _pipeline_ai_module.gpt_oss_controls
    universal_offline_controls = _pipeline_ai_module.universal_offline_controls
    _maybe_autofix_generated_code = _pipeline_ai_module._maybe_autofix_generated_code
try:
    from agilab.pipeline_editor import (
        _capture_pipeline_snapshot,
        _force_persist_step,
        _restore_pipeline_snapshot,
        get_steps_list,
        on_import_notebook,
        remove_step,
        save_step,
    )
except ModuleNotFoundError:
    _pipeline_editor_path = Path(__file__).resolve().parents[1] / "pipeline_editor.py"
    _pipeline_editor_spec = importlib.util.spec_from_file_location("agilab_pipeline_editor_fallback", _pipeline_editor_path)
    if _pipeline_editor_spec is None or _pipeline_editor_spec.loader is None:
        raise
    _pipeline_editor_module = importlib.util.module_from_spec(_pipeline_editor_spec)
    _pipeline_editor_spec.loader.exec_module(_pipeline_editor_module)
    _capture_pipeline_snapshot = _pipeline_editor_module._capture_pipeline_snapshot
    _force_persist_step = _pipeline_editor_module._force_persist_step
    _restore_pipeline_snapshot = _pipeline_editor_module._restore_pipeline_snapshot
    get_steps_list = _pipeline_editor_module.get_steps_list
    on_import_notebook = _pipeline_editor_module.on_import_notebook
    remove_step = _pipeline_editor_module.remove_step
    save_step = _pipeline_editor_module.save_step
try:
    from agilab.pipeline_lab import PipelineLabDeps, display_lab_tab
except ModuleNotFoundError:
    _pipeline_lab_path = Path(__file__).resolve().parents[1] / "pipeline_lab.py"
    _pipeline_lab_spec = importlib.util.spec_from_file_location("agilab_pipeline_lab_fallback", _pipeline_lab_path)
    if _pipeline_lab_spec is None or _pipeline_lab_spec.loader is None:
        raise
    _pipeline_lab_module = importlib.util.module_from_spec(_pipeline_lab_spec)
    _pipeline_lab_spec.loader.exec_module(_pipeline_lab_module)
    PipelineLabDeps = _pipeline_lab_module.PipelineLabDeps
    display_lab_tab = _pipeline_lab_module.display_lab_tab

try:
    from agilab.pipeline_runtime import (
        ensure_safe_service_template as _ensure_safe_service_template,
        is_valid_runtime_root as _is_valid_runtime_root,
        python_for_venv as _python_for_venv,
        run_locked_step as _run_locked_step,
        stream_run_command as _stream_run_command,
        to_bool_flag as _to_bool_flag,
    )
except ModuleNotFoundError:
    _pipeline_runtime_path = Path(__file__).resolve().parents[1] / "pipeline_runtime.py"
    _pipeline_runtime_spec = importlib.util.spec_from_file_location("agilab_pipeline_runtime_fallback", _pipeline_runtime_path)
    if _pipeline_runtime_spec is None or _pipeline_runtime_spec.loader is None:
        raise
    _pipeline_runtime_module = importlib.util.module_from_spec(_pipeline_runtime_spec)
    _pipeline_runtime_spec.loader.exec_module(_pipeline_runtime_module)
    _ensure_safe_service_template = _pipeline_runtime_module.ensure_safe_service_template
    _is_valid_runtime_root = _pipeline_runtime_module.is_valid_runtime_root
    _python_for_venv = _pipeline_runtime_module.python_for_venv
    _run_locked_step = _pipeline_runtime_module.run_locked_step
    _stream_run_command = _pipeline_runtime_module.stream_run_command
    _to_bool_flag = _pipeline_runtime_module.to_bool_flag
try:
    from agilab.pipeline_sidebar import (
        available_lab_modules as _available_lab_modules,
        load_last_active_app_name as _load_last_active_app_name,
        normalize_lab_choice as _normalize_lab_choice,
        on_lab_change,
        open_notebook_in_browser,
        resolve_lab_export_dir as _resolve_lab_export_dir,
    )
except ModuleNotFoundError:
    _pipeline_sidebar_path = Path(__file__).resolve().parents[1] / "pipeline_sidebar.py"
    _pipeline_sidebar_spec = importlib.util.spec_from_file_location("agilab_pipeline_sidebar_fallback", _pipeline_sidebar_path)
    if _pipeline_sidebar_spec is None or _pipeline_sidebar_spec.loader is None:
        raise
    _pipeline_sidebar_module = importlib.util.module_from_spec(_pipeline_sidebar_spec)
    _pipeline_sidebar_spec.loader.exec_module(_pipeline_sidebar_module)
    _available_lab_modules = _pipeline_sidebar_module.available_lab_modules
    _load_last_active_app_name = _pipeline_sidebar_module.load_last_active_app_name
    _normalize_lab_choice = _pipeline_sidebar_module.normalize_lab_choice
    on_lab_change = _pipeline_sidebar_module.on_lab_change
    open_notebook_in_browser = _pipeline_sidebar_module.open_notebook_in_browser
    _resolve_lab_export_dir = _pipeline_sidebar_module.resolve_lab_export_dir

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
            except Exception as exc:
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
    except Exception as exc:
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
    except Exception:
        return PIPELINE_LOCK_DEFAULT_TTL_SEC
    return ttl if ttl > 0 else PIPELINE_LOCK_DEFAULT_TTL_SEC


def _pipeline_lock_path(env: AgiEnv) -> Path:
    """Return shared lock path for one app pipeline execution."""
    target = str(getattr(env, "target", "") or getattr(env, "app", "") or "agilab").strip()
    relative = Path("pipeline") / target / PIPELINE_LOCK_FILENAME
    try:
        path = env.resolve_share_path(relative)
    except Exception:
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
    except Exception:
        pass
    return {}


def _pipeline_lock_owner_text(payload: Dict[str, Any], age_sec: Optional[float]) -> str:
    """Format a concise lock owner description for logs/UI."""
    owner_host = str(payload.get("host", "?"))
    owner_pid = payload.get("pid", "?")
    owner_app = str(payload.get("app", "?"))
    age_txt = f"{age_sec:.0f}s" if isinstance(age_sec, (int, float)) else "unknown"
    return f"host={owner_host}, pid={owner_pid}, app={owner_app}, age={age_txt}"


def _acquire_pipeline_run_lock(
    env: AgiEnv,
    index_page: str,
    placeholder: Optional[Any] = None,
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
    ttl_sec = _pipeline_lock_ttl_seconds()

    for _ in range(2):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2)
            _push_run_log(index_page, f"Pipeline lock acquired: {lock_path}", placeholder)
            return {"path": lock_path, "token": token}
        except FileExistsError:
            owner_payload = _read_pipeline_lock_payload(lock_path)
            age_sec: Optional[float]
            try:
                age_sec = max(time.time() - lock_path.stat().st_mtime, 0.0)
            except Exception:
                age_sec = None

            if isinstance(age_sec, float) and age_sec > ttl_sec:
                try:
                    lock_path.unlink()
                    _push_run_log(
                        index_page,
                        f"Removed stale pipeline lock ({age_sec:.0f}s > {ttl_sec:.0f}s): {lock_path}",
                        placeholder,
                    )
                    continue
                except FileNotFoundError:
                    continue
                except Exception as exc:
                    msg = f"Unable to remove stale pipeline lock `{lock_path}`: {exc}"
                    st.warning(msg)
                    _push_run_log(index_page, msg, placeholder)
                    return None

            owner_txt = _pipeline_lock_owner_text(owner_payload, age_sec)
            msg = (
                "Another pipeline execution is already running. "
                f"Owner: {owner_txt}. Current run cancelled."
            )
            st.warning(msg)
            _push_run_log(index_page, msg, placeholder)
            return None
        except Exception as exc:
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
    except Exception:
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
    except Exception as exc:
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


def load_all_steps(
    module_path: Path,
    steps_file: Path,
    index_page: str,
) -> Optional[List[Dict[str, Any]]]:
    """Load all steps for a module from a TOML file using str(module_path) as key.

    Uses a small cache keyed by file mtime to avoid re-parsing on every rerun.
    """
    _ensure_primary_module_key(module_path, steps_file)
    try:
        module_key = _module_keys(module_path)[0]
        mtime_ns = steps_file.stat().st_mtime_ns
        raw_entries = _read_steps(steps_file, module_key, mtime_ns)
        filtered_entries = _prune_invalid_entries(raw_entries)
        if filtered_entries and not st.session_state[index_page][-1]:
            st.session_state[index_page][-1] = len(filtered_entries)
        # Lazily materialize a notebook if it's missing; read full TOML once
        if filtered_entries and not steps_file.with_suffix(".ipynb").exists():
            try:
                with open(steps_file, "rb") as f:
                    steps_full = tomllib.load(f)
                toml_to_notebook(steps_full, steps_file)
            except Exception as e:
                logger.warning(f"Skipping notebook generation: {e}")
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

    lock_handle = _acquire_pipeline_run_lock(env, index_page_str, log_placeholder)
    if lock_handle is None:
        return

    executed = 0
    try:
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
                target_base = Path(steps_file).parent.resolve()
                # Collapse duplicated tail (e.g., export/<app>/export/<app>)
                if target_base.name == target_base.parent.name:
                    target_base = target_base.parent
                target_base.mkdir(parents=True, exist_ok=True)
                if engine == "runpy":
                    output = run_lab(
                        [entry.get("D", ""), entry.get("Q", ""), code],
                        snippet_file,
                        env.copilot_file,
                    )
                else:
                    script_path = (target_base / "AGI_run.py").resolve()
                    script_path.write_text(code)
                    python_cmd = _python_for_venv(venv_root)
                    output = _stream_run_command(
                        env,
                        index_page_str,
                        f"{python_cmd} {script_path}",
                        cwd=target_base,
                        push_run_log=_push_run_log,
                        ansi_escape_re=ANSI_ESCAPE_RE,
                        jump_exception_cls=JumpToMain,
                        placeholder=log_placeholder,
                    )
                _refresh_pipeline_run_lock(lock_handle)

                # Append execution output to logs for better visibility
                if output:
                    preview = output.strip()
                    if preview:
                        _push_run_log(
                            index_page_str,
                            f"Output (step {idx + 1}):\n{preview}",
                            log_placeholder,
                        )
                        if "No such file or directory" in preview:
                            _push_run_log(
                                index_page_str,
                                "Hint: the code tried to call a file that is not present in the export environment. "
                                "Adjust the step to use a path that exists under the export/lab directory.",
                                log_placeholder,
                            )
                else:
                    _push_run_log(
                        index_page_str,
                        f"Output (step {idx + 1}): {engine} executed (no captured stdout)",
                        log_placeholder,
                    )

                if isinstance(st.session_state.get("data"), pd.DataFrame) and not st.session_state["data"].empty:
                    export_target = st.session_state.get("df_file_out", "")
                    if save_csv(st.session_state["data"], export_target):
                        st.session_state["df_file_in"] = export_target
                        st.session_state["step_checked"] = True
                summary = _step_summary({"Q": entry.get("Q", ""), "C": code})
                env_label = Path(venv_root).name if venv_root else "default env"
                _push_run_log(
                    index_page_str,
                    f"Step {idx + 1}: engine={engine}, env={env_label}, summary=\"{summary}\"",
                    log_placeholder,
                )
                executed += 1

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
        persisted_lab = normalized_target or env.target
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
        args=(key, module_path, index_page_str, steps_file),
    )


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
            use_container_width=True,
        )
    elif not st.session_state.get("server_started"):
        st.sidebar.markdown("**Status:** stopped")
        st.sidebar.caption("Start it from Edit.")


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

    pre_prompt_path = Path(env.app_src) / "pre_prompt.json"
    try:
        with open(pre_prompt_path) as f:
            pre_prompt_content = json.load(f)
            if isinstance(pre_prompt_content, list):
                st.session_state["lab_prompt"] = pre_prompt_content
            else:
                st.warning(
                    f"pre_prompt.json at {pre_prompt_path} is not a list of messages; using empty prompt."
                )
                st.session_state["lab_prompt"] = []
    except FileNotFoundError:
        st.session_state["lab_prompt"] = []
        st.warning(f"Missing pre_prompt.json at {pre_prompt_path}; using empty prompt.")
        try:
            pre_prompt_path.write_text("[]\n", encoding="utf-8")
        except OSError:
            st.warning(f"Unable to create {pre_prompt_path}; check folder permissions.")
    except Exception as exc:
        st.session_state["lab_prompt"] = []
        st.warning(f"Failed to load pre_prompt.json: {exc}")

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
        refresh_pipeline_run_lock=_refresh_pipeline_run_lock,
        acquire_pipeline_run_lock=_acquire_pipeline_run_lock,
        release_pipeline_run_lock=_release_pipeline_run_lock,
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
        page_module = None
        last_exc: Optional[Exception] = None
        for module_name in ("agilab.About_agilab", "About_agilab"):
            try:
                page_module = importlib.import_module(module_name)
                break
            except ModuleNotFoundError as exc:
                last_exc = exc
        if page_module is None:
            try:
                about_path = Path(__file__).resolve().parents[1] / "About_agilab.py"
                spec = importlib.util.spec_from_file_location("agilab_about_fallback", about_path)
                if spec and spec.loader:
                    page_module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(page_module)
            except Exception as exc:
                last_exc = exc
        if page_module is None or not hasattr(page_module, "main"):
            if last_exc is not None:
                raise last_exc
            raise ModuleNotFoundError("Unable to import About_agilab page module.")
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

    except Exception as e:
        st.error(f"An error occurred: {e}")
        import traceback

        st.code(f"```\n{traceback.format_exc()}\n```")


if __name__ == "__main__":
    main()
