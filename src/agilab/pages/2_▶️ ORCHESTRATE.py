import asyncio

# ===========================
# Standard Imports (lightweight)
# ===========================
import os
import sys
import socket
import runpy
import ast
import re
import json
import logging
import subprocess
from functools import lru_cache
from pathlib import Path
import importlib
from typing import Optional
from datetime import datetime

import textwrap
# Third-Party imports
import tomllib       # For reading TOML files
import tomli_w       # For writing TOML files
import pandas as pd
# Theme configuration
os.environ.setdefault("STREAMLIT_CONFIG_FILE", str(Path(__file__).resolve().parents[1] / "resources" / "config.toml"))
import streamlit as st
from streamlit.errors import StreamlitAPIException
try:
    from agilab.orchestrate_distribution import (
        show_graph,
        show_tree,
        workload_barchart,
    )
except ModuleNotFoundError:
    _orchestrate_distribution_path = Path(__file__).resolve().parents[1] / "orchestrate_distribution.py"
    _orchestrate_distribution_spec = importlib.util.spec_from_file_location(
        "agilab_orchestrate_distribution_fallback",
        _orchestrate_distribution_path,
    )
    if _orchestrate_distribution_spec is None or _orchestrate_distribution_spec.loader is None:
        raise
    _orchestrate_distribution_module = importlib.util.module_from_spec(_orchestrate_distribution_spec)
    _orchestrate_distribution_spec.loader.exec_module(_orchestrate_distribution_module)
    show_graph = _orchestrate_distribution_module.show_graph
    show_tree = _orchestrate_distribution_module.show_tree
    workload_barchart = _orchestrate_distribution_module.workload_barchart

try:
    from agilab.orchestrate_execute import (
        OrchestrateExecuteDeps,
        render_execute_section,
    )
except ModuleNotFoundError:
    _orchestrate_execute_path = Path(__file__).resolve().parents[1] / "orchestrate_execute.py"
    _orchestrate_execute_spec = importlib.util.spec_from_file_location(
        "agilab_orchestrate_execute_fallback",
        _orchestrate_execute_path,
    )
    if _orchestrate_execute_spec is None or _orchestrate_execute_spec.loader is None:
        raise
    _orchestrate_execute_module = importlib.util.module_from_spec(_orchestrate_execute_spec)
    _orchestrate_execute_spec.loader.exec_module(_orchestrate_execute_module)
    OrchestrateExecuteDeps = _orchestrate_execute_module.OrchestrateExecuteDeps
    render_execute_section = _orchestrate_execute_module.render_execute_section

try:
    from agilab.orchestrate_support import (
        coerce_bool_setting as _coerce_bool_setting,
        coerce_float_setting as _coerce_float_setting,
        coerce_int_setting as _coerce_int_setting,
        evaluate_service_health_gate as _evaluate_service_health_gate,
        extract_result_dict_from_output as _extract_result_dict_from_output,
        looks_like_shared_path as _looks_like_shared_path_impl,
        macos_autofs_hint as _macos_autofs_hint,
        parse_and_validate_scheduler as _parse_and_validate_scheduler_impl,
        parse_and_validate_workers as _parse_and_validate_workers_impl,
        parse_benchmark,
        sanitize_for_toml as _sanitize_for_toml,
        safe_eval as _safe_eval_impl,
        write_app_settings_toml as _write_app_settings_toml,
    )
except ModuleNotFoundError:
    _orchestrate_support_path = Path(__file__).resolve().parents[1] / "orchestrate_support.py"
    _orchestrate_support_spec = importlib.util.spec_from_file_location(
        "agilab_orchestrate_support_fallback",
        _orchestrate_support_path,
    )
    if _orchestrate_support_spec is None or _orchestrate_support_spec.loader is None:
        raise
    _orchestrate_support_module = importlib.util.module_from_spec(_orchestrate_support_spec)
    _orchestrate_support_spec.loader.exec_module(_orchestrate_support_module)
    _coerce_bool_setting = _orchestrate_support_module.coerce_bool_setting
    _coerce_float_setting = _orchestrate_support_module.coerce_float_setting
    _coerce_int_setting = _orchestrate_support_module.coerce_int_setting
    _evaluate_service_health_gate = _orchestrate_support_module.evaluate_service_health_gate
    _extract_result_dict_from_output = _orchestrate_support_module.extract_result_dict_from_output
    _looks_like_shared_path_impl = _orchestrate_support_module.looks_like_shared_path
    _macos_autofs_hint = _orchestrate_support_module.macos_autofs_hint
    _parse_and_validate_scheduler_impl = _orchestrate_support_module.parse_and_validate_scheduler
    _parse_and_validate_workers_impl = _orchestrate_support_module.parse_and_validate_workers
    parse_benchmark = _orchestrate_support_module.parse_benchmark
    _sanitize_for_toml = _orchestrate_support_module.sanitize_for_toml
    _safe_eval_impl = _orchestrate_support_module.safe_eval
    _write_app_settings_toml = _orchestrate_support_module.write_app_settings_toml
# Project Libraries:
from agi_env.pagelib import (
    background_services_enabled, get_about_content, render_logo, activate_mlflow, init_custom_ui, select_project,
    inject_theme, is_valid_ip, resolve_active_app, store_last_active_app
)

from agi_env import AgiEnv

# ===========================
# Session State Initialization
# ===========================
def init_session_state(defaults: dict):
    """
    Initialize session state variables with default values if they are not already set.
    """
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

# ===========================
# Utility and Helper Functions
# ===========================

def clear_log():
    """
    Clear the accumulated log in session_state.
    Call this before starting a new run (INSTALL, DISTRIBUTE, or EXECUTE)
    to avoid mixing logs.
    """
    st.session_state["log_text"] = ""


def _rerun_fragment_or_app() -> None:
    """Prefer a fragment rerun when valid; otherwise fall back to a full app rerun."""
    try:
        st.rerun(scope="fragment")
    except StreamlitAPIException:
        st.rerun()


def _update_delete_confirm_state(
    confirm_key: str,
    *,
    delete_armed_clicked: bool,
    delete_cancel_clicked: bool,
) -> bool:
    """Update the delete-confirm flag and report whether a local rerun is needed."""
    if delete_armed_clicked:
        st.session_state[confirm_key] = True
        return True
    if delete_cancel_clicked:
        st.session_state.pop(confirm_key, None)
        return True
    return False

def update_log(live_log_placeholder, message, max_lines=1000):
    """
    Append a cleaned message to the accumulated log and update the live display.
    Keeps only the last max_lines lines in the log.
    """
    if "log_text" not in st.session_state:
        st.session_state["log_text"] = ""

    clean_msg = strip_ansi(message).rstrip()
    if st.session_state.get('cluster_verbose', 1) < 2:
        if getattr(update_log, '_skip_traceback', False):
            if not clean_msg:
                update_log._skip_traceback = False
            return
        if clean_msg.lower().startswith("traceback (most recent call last"):
            update_log._skip_traceback = True
            return
        if _is_dask_shutdown_noise(clean_msg):
            return
    if clean_msg:
        st.session_state["log_text"] += clean_msg + "\n"

    # Keep only last max_lines lines to avoid huge memory/logs
    lines = st.session_state["log_text"].splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
        st.session_state["log_text"] = "\n".join(lines) + "\n"

    display_lines = lines[-LOG_DISPLAY_MAX_LINES:]
    live_view = "\n".join(display_lines)

    # Calculate height in pixels roughly: 20px per line, capped at 500px (but keep a usable minimum)
    line_count = max(len(display_lines), 1)
    height_px = min(max(20 * line_count, LIVE_LOG_MIN_HEIGHT), 500)

    live_log_placeholder.code(live_view, language="python", height=height_px)

update_log._skip_traceback = False



def strip_ansi(text: str) -> str:
    if not text:
        return ""
    ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
    return ansi_escape.sub('', text)


def _is_dask_shutdown_noise(line: str) -> bool:
    """
    Return True when the line is one of the noisy Dask shutdown messages
    that we don’t want to surface in the UI.
    """
    if not line:
        return False
    normalized = line.strip().lower()
    noise_patterns = (
        "stream is closed",
        "streamclosederror",
        "commclosederror",
        "batched comm closed",
        "closing scheduler",
        "scheduler closing all comms",
        "remove worker addr",
        "close client connection",
        "tornado.iostream.streamclosederror",
        "nbytes = yield coro",
        "value = future.result",
        "convert_stream_closed_error",
        "^",
    )
    if any(pattern in normalized for pattern in noise_patterns):
        return True
    if "traceback (most recent call last" in normalized:
        return True
    if normalized.startswith("the above exception was the direct cause"):
        return True
    if normalized.startswith("traceback"):
        return True
    if normalized.startswith("file \"") and (
        "/site-packages/distributed/" in normalized
        or "/site-packages/tornado/" in normalized
    ):
        return True
    return False


def _filter_noise_lines(text: str) -> str:
    lines = [
        line
        for line in text.splitlines()
        if not _is_dask_shutdown_noise(line.strip())
    ]
    return "\n".join(lines)

def _reset_traceback_skip() -> None:
    _TRACEBACK_SKIP["active"] = False
    update_log._skip_traceback = False


def _append_log_lines(buffer: list[str], payload: str) -> None:
    """
    Append cleaned lines from ``payload`` to ``buffer`` while filtering out
    Dask shutdown chatter. Suppresses multi-line tracebacks emitted during
    scheduler shutdown by skipping until the next blank line (only when verbosity < 2).
    """
    filtered = strip_ansi(payload or "")
    if st.session_state.get('cluster_verbose', 1) < 2:
        skip = _TRACEBACK_SKIP["active"]
        for raw_line in filtered.splitlines():
            stripped = raw_line.rstrip()
            lowered = stripped.lower()
            if skip:
                if not stripped:
                    skip = False
                continue
            if lowered.startswith("traceback (most recent call last"):
                skip = True
                continue
            if stripped and not _is_dask_shutdown_noise(stripped):
                buffer.append(stripped)
        _TRACEBACK_SKIP["active"] = skip
    else:
        for raw_line in filtered.splitlines():
            stripped = raw_line.rstrip()
            if stripped:
                buffer.append(stripped)


_INSTALL_LOG_FATAL_PATTERNS: tuple[tuple[str, ...], ...] = (
    #("connection to", "timed out"),
    #("failed to connect",),
    #("connection refused",),
    #("no route to host",),
    #("ssh_exchange_identification",),
    #("broken pipe",),
    ("error",),
)
_INSTALL_LOG_FATAL_PATTERNS_LOWER: tuple[tuple[str, ...], ...] = tuple(
    tuple(token.lower() for token in pattern if token)
    for pattern in _INSTALL_LOG_FATAL_PATTERNS
    if pattern
)


def _log_indicates_install_failure(lines: list[str]) -> bool:
    """
    Return True when install logs contain fatal phrases that do not always
    propagate through stderr (e.g., SSH transport errors).
    We reuse a single lower-cased tail snippet so substring checks stay O(1) per token.
    """
    if not lines or not _INSTALL_LOG_FATAL_PATTERNS_LOWER:
        return False

    snippet = "\n".join(lines[-200:]).lower()
    for pattern in _INSTALL_LOG_FATAL_PATTERNS_LOWER:
        for token in pattern:
            if token not in snippet:
                break
        else:
            return True
    return False


def _looks_like_shared_path(path: Path) -> bool:
    project_root = Path(__file__).resolve().parents[2]
    return _looks_like_shared_path_impl(path, project_root=project_root)


LOG_DISPLAY_MAX_LINES = 250
LIVE_LOG_MIN_HEIGHT = 160
INSTALL_LOG_HEIGHT = 320
_TRACEBACK_SKIP = {"active": False}


def _format_log_block(text: str, *, newest_first: bool = True) -> str:
    """Return a trimmed/ordered view of the provided multiline text."""
    if not text:
        return ""
    lines = text.splitlines()
    tail = lines[-LOG_DISPLAY_MAX_LINES:]
    if newest_first:
        tail = list(reversed(tail))
    return "\n".join(tail)


def display_log(stdout, stderr):
    # Use cached log if stdout empty
    if not stdout.strip() and "log_text" in st.session_state:
        stdout = st.session_state["log_text"]

    # Strip ANSI color codes from both stdout and stderr
    clean_stdout = strip_ansi(stdout or "")
    clean_stderr = strip_ansi(stderr or "")
    clean_stdout = _filter_noise_lines(clean_stdout)
    clean_stderr = _filter_noise_lines(clean_stderr)

    # Clean up extra blank lines
    clean_stdout = "\n".join(line for line in clean_stdout.splitlines() if line.strip())
    clean_stderr = "\n".join(line for line in clean_stderr.splitlines() if line.strip())

    combined = "\n".join([clean_stdout, clean_stderr]).strip()

    if "warning:" in combined.lower():
        st.warning("Warnings occurred during cluster installation:")
        st.code(_format_log_block(combined, newest_first=False), language="python", height=400)
    elif clean_stderr:
        st.error("Errors occurred during cluster installation:")
        st.code(_format_log_block(clean_stderr, newest_first=False), language="python", height=400)
    else:
        st.code(_format_log_block(clean_stdout, newest_first=False) or "No logs available", language="python", height=400)


def safe_eval(expression, expected_type, error_message):
    return _safe_eval_impl(
        expression,
        expected_type,
        error_message,
        on_error=st.error,
    )


def parse_and_validate_scheduler(scheduler):
    return _parse_and_validate_scheduler_impl(
        scheduler,
        is_valid_ip=is_valid_ip,
        on_error=st.error,
    )


def parse_and_validate_workers(workers_input):
    return _parse_and_validate_workers_impl(
        workers_input,
        is_valid_ip=is_valid_ip,
        on_error=st.error,
        default_workers={"127.0.0.1": 1},
    )

def initialize_app_settings(args_override=None):
    env = st.session_state["env"]

    file_settings = load_toml_file(env.app_settings_file)
    session_settings = st.session_state.get("app_settings")
    app_settings = {}

    if isinstance(file_settings, dict):
        app_settings.update(file_settings)
    if isinstance(session_settings, dict):
        for key, value in session_settings.items():
            if key in {"args", "cluster"} and isinstance(value, dict):
                base = app_settings.get(key, {})
                if isinstance(base, dict):
                    merged = {**base, **value}
                else:
                    merged = value
                app_settings[key] = merged
            else:
                app_settings[key] = value

    if env.app == "flight_project":
        try:
            from flight import apply_source_defaults, load_args_from_toml

            args_model = apply_source_defaults(load_args_from_toml(env.app_settings_file))
            app_settings["args"] = args_model.to_toml_payload()
        except Exception as exc:
            st.warning(f"Unable to load Flight args: {exc}")
            app_settings.setdefault("args", {})
    else:
        app_settings.setdefault("args", {})

    cluster_settings = app_settings.setdefault("cluster", {})
    if args_override is not None:
        app_settings["args"] = args_override
    st.session_state.app_settings = app_settings
    st.session_state["args_project"] = env.app

def filter_warning_messages(log: str) -> str:
    """
    Remove lines containing a specific warning about VIRTUAL_ENV mismatches.
    """
    filtered_lines = []
    for line in log.splitlines():
        if ("VIRTUAL_ENV=" in line and
            "does not match the project environment path" in line and
            ".venv" in line):
            continue
        filtered_lines.append(line)
    return "\n".join(filtered_lines)

# ===========================
# Caching Functions for Performance
# ===========================
@st.cache_data(ttl=300, show_spinner=False)
def load_toml_file(file_path):
    file_path = Path(file_path)
    if file_path.exists():
        try:
            with file_path.open("rb") as f:
                return tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            st.warning(f"Invalid TOML detected in {file_path.name}: {exc}")
            logger = logging.getLogger(__name__)
            logger.warning("Failed to parse %s: %s", file_path, exc)
            return {}
    return {}

@st.cache_data(show_spinner=False)
def load_distribution(file_path):
    with open(file_path, "r") as f:
        data = json.load(f)
    workers = [f"{ip}-{i}" for ip, count in data.get("workers", {}).items() for i in range(1, count + 1)]
    return workers, data.get("work_plan_metadata", []), data.get("work_plan", [])

@st.cache_data(show_spinner=False)
def generate_profile_report(df):
    env = st.session_state["env"]
    if env.python_version > "3.12":
        from ydata_profiling.profile_report import ProfileReport
        return ProfileReport(df, minimal=True)
    else:
        st.info(f"Function not available with this version of Python {env.python_version}.")
        return None

# ===========================
# UI Rendering Functions
# ===========================
def render_generic_ui():
    env = st.session_state["env"]
    ncols = 2
    cols = st.columns([10, 1, 10])
    new_args_list = []
    arg_valid = True

    args_default = st.session_state.app_settings["args"]
    for i, (key, val) in enumerate(args_default.items()):
        with cols[0 if i % ncols == 0 else 2]:
            c1, c2, c3, c4 = st.columns([5, 5, 3, 1])
            new_key = c1.text_input("Name", value=key, key=f"args_name{i}")
            new_val = c2.text_input("Value", value=repr(val), key=f"args_value{i}")
            try:
                new_val = ast.literal_eval(new_val)
            except (SyntaxError, ValueError):
                pass
            c3.text(type(new_val).__name__)
            remove_confirm_key = f"args_remove_confirm_{i}"
            row_delete_confirmed = False
            row_delete_armed = False
            row_delete_canceled = False

            if st.session_state.get(remove_confirm_key, False):
                row_delete_confirmed = c4.button(
                    "✅",
                    key=f"args_remove_confirm_button{i}",
                    type="primary",
                    help=f"Confirm remove {new_key}",
                )
                row_delete_canceled = c4.button(
                    "✖",
                    key=f"args_remove_cancel_button{i}",
                    type="secondary",
                    help=f"Cancel remove {new_key}",
                )
            else:
                row_delete_armed = c4.button(
                    "🗑️",
                    key=f"args_remove_button{i}",
                    type="primary",
                    help=f"Remove {new_key}",
                )

            if row_delete_armed:
                st.session_state[remove_confirm_key] = True
                st.rerun()
            if row_delete_canceled:
                st.session_state.pop(remove_confirm_key, None)
                st.rerun()
            if row_delete_confirmed:
                st.session_state.pop(remove_confirm_key, None)
                st.session_state["args_remove_arg"] = True
            else:
                new_args_list.append((new_key, new_val))

    c1_add, c2_add, c3_add = st.columns(3)
    i = len(args_default) + 1
    new_key = c1_add.text_input("Name", placeholder="Name", key=f"args_name{i}")
    new_val = c2_add.text_input("Value", placeholder="Value", key=f"args_value{i}")
    if c3_add.button("Add argument", type="primary", key=f"args_add_arg_button"):
        if new_val == "":
            new_val = None
        try:
            new_val = ast.literal_eval(new_val)
        except (SyntaxError, ValueError):
            pass
        new_args_list.append((new_key, new_val))

    if not all(key.strip() for key, _ in new_args_list):
        st.error("Argument name must not be empty.")
        arg_valid = False

    if len(new_args_list) != len(set(key for key, _ in new_args_list)):
        st.error("Argument name already exists.")
        arg_valid = False

    args_input = dict(new_args_list)
    is_args_reload_required = arg_valid and (args_input != st.session_state.app_settings.get("args", {}))

    if is_args_reload_required:
        st.session_state["args_input"] = args_input
        app_settings_file = env.app_settings_file
        if env.app == "flight_project":
            try:
                from flight import apply_source_defaults, dump_args_to_toml, FlightArgs
                from pydantic import ValidationError

                parsed_args = FlightArgs(**args_input)
            except ValidationError as exc:
                messages = env.humanize_validation_errors(exc)
                st.warning("\n".join(messages))
            else:
                parsed_args = apply_source_defaults(parsed_args)
                dump_args_to_toml(parsed_args, app_settings_file)
                st.session_state.app_settings["args"] = parsed_args.to_toml_payload()
        else:
            existing_app_settings = load_toml_file(app_settings_file)
            existing_app_settings.setdefault("args", {})
            existing_app_settings.setdefault("cluster", {})
            existing_app_settings["args"] = args_input
            st.session_state.app_settings = _write_app_settings_toml(
                app_settings_file,
                existing_app_settings,
            )

    if st.session_state.get("args_remove_arg"):
        st.session_state["args_remove_arg"] = False
        st.rerun()

    if arg_valid and st.session_state.get("args_add_arg_button"):
        st.rerun()

    if arg_valid:
        st.session_state.app_settings["args"] = args_input

def render_cluster_settings_ui():

    env = st.session_state["env"]
    app_settings = st.session_state.get("app_settings")
    if not isinstance(app_settings, dict):
        app_settings = {"args": {}, "cluster": {}}
        st.session_state["app_settings"] = app_settings

    cluster_params = app_settings.setdefault("cluster", {})

    boolean_params = ["cython", "pool"]
    if env.is_managed_pc:
        cluster_params["rapids"] = False
    else:
        boolean_params.append("rapids")
    cols_other = st.columns(len(boolean_params))
    for idx, param in enumerate(boolean_params):
        current_value = cluster_params.get(param, False)
        updated_value = cols_other[idx].checkbox(
            param.replace("_", " ").capitalize(),
            value=current_value,
            key=f"cluster_{param}",
            help=f"Enable or disable {param}."
        )
        cluster_params[param] = updated_value

    # -------- per-project cluster toggle seeded from TOML; do not pass value= while also using session_state
    app_state_name = Path(str(env.app)).name if env.app else ""
    cluster_enabled_key = f"cluster_enabled__{app_state_name}"
    if cluster_enabled_key not in st.session_state:
        st.session_state[cluster_enabled_key] = bool(cluster_params.get("cluster_enabled", False))
    cluster_enabled = st.toggle(
        "Enable Cluster",
        key=cluster_enabled_key,
        help="Enable cluster: provide a scheduler IP and workers configuration."
    )
    cluster_params["cluster_enabled"] = bool(cluster_enabled)

    # Keep scheduler/workers persisted even if disabled (don’t pop them)
    if cluster_enabled:
        # Helper to persist environment variables if the value changed
        def _persist_env_var(key: str, value: Optional[str]):
            normalized = "" if value is None else str(value)
            current = ""
            envars = getattr(AgiEnv, "envars", None)
            if isinstance(envars, dict):
                current = str(envars.get(key, "") or "")
            if normalized != current:
                AgiEnv.set_env_var(key, normalized)

        share_raw = env.agi_share_path
        share_display: str
        resolved_display: Optional[Path] = None
        is_symlink = False
        if share_raw:
            share_display = str(share_raw)
            try:
                share_root = env.share_root_path()
            except Exception:
                share_root = None
            if share_root is not None:
                resolved_display = share_root
                try:
                    is_symlink = share_root.is_symlink()
                    resolved_target = share_root.resolve(strict=False)
                except Exception:
                    resolved_target = share_root
                if resolved_target != share_root:
                    resolved_display = resolved_target
            if resolved_display and str(resolved_display) != share_display:
                share_display = f"{share_display} → {resolved_display}"
        else:
            share_display = (
                "not set. Set `AGI_SHARE_DIR` to a shared mount (or symlink to one) so remote workers can read outputs."
            )
        st.markdown(f"**agi_share_path:** {share_display}")

        # per-project widget key & seeding; do not also pass value=
        scheduler_widget_key = f"cluster_scheduler__{app_state_name}"
        if scheduler_widget_key not in st.session_state:
            st.session_state[scheduler_widget_key] = cluster_params.get("scheduler", "")
        user_widget_key = f"cluster_user__{app_state_name}"
        stored_user = cluster_params.get("user")
        if stored_user in (None, ""):
            stored_user = env.user or ""
        if user_widget_key not in st.session_state:
            st.session_state[user_widget_key] = stored_user
        auth_toggle_key = f"cluster_use_key__{app_state_name}"
        auth_method = cluster_params.get("auth_method")
        default_use_key = bool(cluster_params.get("ssh_key_path"))
        if isinstance(auth_method, str):
            default_use_key = auth_method.lower() == "ssh_key"
        if auth_toggle_key not in st.session_state:
            st.session_state[auth_toggle_key] = default_use_key

        auth_row = st.container()
        scheduler_col, user_col, credential_col, toggle_col = auth_row.columns(4, vertical_alignment="top")
        with scheduler_col:
            scheduler_input = st.text_input(
                "Scheduler IP Address",
                key=scheduler_widget_key,
                placeholder="e.g., 192.168.0.100 or 192.168.0.100:8786",
                help="Provide a scheduler IP address (optionally with :PORT).",
            )
        with user_col:
            user_input = st.text_input(
                "SSH User",
                key=user_widget_key,
                placeholder="e.g., ubuntu",
                help="Remote account used for cluster SSH connections.",
            )
        # Note: do not write back to `st.session_state[user_widget_key]` here.
        # Streamlit forbids mutating a widget-backed key after instantiation
        # (raises StreamlitAPIException). We only sanitize for persistence/use.
        sanitized_user = (user_input or "").strip()
        if not sanitized_user and stored_user:
            sanitized_user = str(stored_user).strip()

        env.user = sanitized_user
        cluster_params["user"] = sanitized_user
        if not sanitized_user:
            _persist_env_var("CLUSTER_CREDENTIALS", "")

        sanitized_key = None
        password_value = ""
        with toggle_col:
            use_ssh_key = st.toggle(
                "Use SSH key",
                key=auth_toggle_key,
                help="Toggle between SSH key-based auth (recommended) and password auth for cluster workers.",
            )
        cluster_params["auth_method"] = "ssh_key" if use_ssh_key else "password"

        if use_ssh_key:
            ssh_key_widget_key = f"cluster_ssh_key__{app_state_name}"
            stored_key = cluster_params.get("ssh_key_path")
            if stored_key in (None, ""):
                stored_key = env.ssh_key_path or ""
            if ssh_key_widget_key not in st.session_state:
                st.session_state[ssh_key_widget_key] = stored_key
            with credential_col:
                ssh_key_input = st.text_input(
                    "SSH Key Path",
                    key=ssh_key_widget_key,
                    placeholder="e.g., ~/.ssh/id_rsa",
                    help="Private key used for SSH authentication.",
                )
            # Same rule as above: do not mutate widget-backed session keys post-instantiation.
            sanitized_key = (ssh_key_input or "").strip()
            if not sanitized_key and stored_key:
                sanitized_key = str(stored_key).strip()
        else:
            password_widget_key = f"cluster_password__{app_state_name}"
            stored_password = cluster_params.get("password")
            if stored_password is None:
                stored_password = env.password or ""
            if password_widget_key not in st.session_state:
                st.session_state[password_widget_key] = stored_password
            with credential_col:
                password_input = st.text_input(
                    "SSH Password",
                    key=password_widget_key,
                    type="password",
                    placeholder="Enter SSH password",
                    help="Password for SSH authentication. Leave blank if workers use key-based auth.",
                )
            password_value = password_input or ""

        if use_ssh_key:
            cluster_params["ssh_key_path"] = sanitized_key
            env.password = None
            env.ssh_key_path = sanitized_key or None

            if sanitized_user:
                _persist_env_var("CLUSTER_CREDENTIALS", sanitized_user)
            _persist_env_var("AGI_SSH_KEY_PATH", sanitized_key)
        else:
            cluster_params.pop("password", None)
            env.password = password_value or None
            env.ssh_key_path = None

            if sanitized_user:
                credentials_value = sanitized_user if not password_value else f"{sanitized_user}:{password_value}"
                _persist_env_var("CLUSTER_CREDENTIALS", credentials_value)
            else:
                _persist_env_var("CLUSTER_CREDENTIALS", "")
            _persist_env_var("AGI_SSH_KEY_PATH", "")
        if scheduler_input:
            scheduler = parse_and_validate_scheduler(scheduler_input)
            if scheduler:
                cluster_params["scheduler"] = scheduler

        workers_data_path_widget_key = f"cluster_workers_data_path__{app_state_name}"
        if workers_data_path_widget_key not in st.session_state:
            st.session_state[workers_data_path_widget_key] = cluster_params.get("workers_data_path", "")

        workers_data_path_input = st.text_input(
            "Workers Data Path",
            key=workers_data_path_widget_key,
            placeholder="/path/to/data",
            help="Path to data directory on workers.",
        )
        if workers_data_path_input:
            cluster_params["workers_data_path"] = workers_data_path_input

        workers_widget_key = f"cluster_workers__{app_state_name}"
        workers_dict = cluster_params.get("workers", {})
        if workers_widget_key not in st.session_state:
            st.session_state[workers_widget_key] = json.dumps(workers_dict, indent=2) if isinstance(workers_dict, dict) else "{}"
        workers_input = st.text_area(
            "Workers Configuration",
            key=workers_widget_key,
            placeholder='e.g., {"192.168.0.1": 2, "192.168.0.2": 3}',
            help="Provide a dictionary of worker IP addresses and capacities.",
        )
        if workers_input:
            workers = parse_and_validate_workers(workers_input)
            if workers:
                cluster_params["workers"] = workers
    else:
        # Keep scheduler/workers settings persisted even when Cluster is disabled,
        # so users don't lose their configuration on toggles/page reloads.
        pass

    st.session_state.dask = cluster_enabled
    benchmark_enabled = st.session_state.get("benchmark", False)

    run_mode_label = [
        "0: python", "1: pool of process", "2: cython", "3: pool and cython",
        "4: dask", "5: dask and pool", "6: dask and cython", "7: dask and pool and cython",
        "8: rapids", "9: rapids and pool", "10: rapids and cython", "11: rapids and pool and cython",
        "12: rapids and dask", "13: rapids and dask and pool", "14: rapids and dask and cython",
        "15: rapids and dask and pool and cython"
    ]

    if benchmark_enabled:
        st.session_state["mode"] = None
        st.info("Run mode benchmark (all modes)")
    else:
        mode_value = (
            int(cluster_params.get("pool", False))
            + int(cluster_params.get("cython", False)) * 2
            + int(cluster_enabled) * 4
            + int(cluster_params.get("rapids", False)) * 8
        )
        st.session_state["mode"] = mode_value
        st.info(f"Run mode {run_mode_label[mode_value]}")
    st.session_state.app_settings["cluster"] = cluster_params

    # Persist to TOML
    st.session_state.app_settings = _write_app_settings_toml(
        env.app_settings_file,
        st.session_state.app_settings,
    )
    try:
        load_toml_file.clear()
    except Exception:
        pass

def toggle_select_all():
    if st.session_state.check_all:
        st.session_state.selected_cols = st.session_state.df_cols.copy()
    else:
        st.session_state.selected_cols = []

def update_select_all():
    all_selected = all(st.session_state.get(f"export_col_{i}", False) for i in range(len(st.session_state.df_cols)))
    st.session_state.check_all = all_selected
    st.session_state.selected_cols = [
        col for i, col in enumerate(st.session_state.df_cols) if st.session_state.get(f"export_col_{i}", False)
    ]


def _capture_dataframe_preview_state() -> dict:
    """Capture dataframe preview-related session state for one-step undo."""
    df_cols_raw = st.session_state.get("df_cols", [])
    selected_cols_raw = st.session_state.get("selected_cols", [])
    df_cols = list(df_cols_raw) if isinstance(df_cols_raw, (list, tuple)) else []
    selected_cols = list(selected_cols_raw) if isinstance(selected_cols_raw, (list, tuple)) else []
    return {
        "loaded_df": st.session_state.get("loaded_df"),
        "loaded_graph": st.session_state.get("loaded_graph"),
        "loaded_source_path": st.session_state.get("loaded_source_path"),
        "df_cols": df_cols,
        "selected_cols": selected_cols,
        "check_all": bool(st.session_state.get("check_all", False)),
        "force_export_open": bool(st.session_state.get("_force_export_open", False)),
        "dataframe_deleted": bool(st.session_state.get("dataframe_deleted", False)),
    }


def _restore_dataframe_preview_state(payload: dict) -> None:
    """Restore dataframe preview session state from an undo payload."""
    st.session_state["loaded_df"] = payload.get("loaded_df")
    if payload.get("loaded_graph") is None:
        st.session_state.pop("loaded_graph", None)
    else:
        st.session_state["loaded_graph"] = payload.get("loaded_graph")

    source_path = payload.get("loaded_source_path")
    if source_path:
        st.session_state["loaded_source_path"] = source_path
    else:
        st.session_state.pop("loaded_source_path", None)

    df_cols_raw = payload.get("df_cols", [])
    selected_cols_raw = payload.get("selected_cols", [])
    df_cols = list(df_cols_raw) if isinstance(df_cols_raw, (list, tuple)) else []
    selected_cols = [col for col in (selected_cols_raw or []) if col in df_cols]
    requested_all = bool(payload.get("check_all", False))
    if requested_all and df_cols:
        selected_cols = df_cols.copy()

    st.session_state["df_cols"] = df_cols
    st.session_state["selected_cols"] = selected_cols
    st.session_state["check_all"] = bool(df_cols) and len(selected_cols) == len(df_cols)
    st.session_state["_force_export_open"] = bool(payload.get("force_export_open", False))
    st.session_state["dataframe_deleted"] = bool(payload.get("dataframe_deleted", False))

    for key in [key for key in st.session_state.keys() if key.startswith("export_col_")]:
        st.session_state.pop(key, None)
    for idx, col in enumerate(df_cols):
        st.session_state[f"export_col_{idx}"] = col in selected_cols

def _is_app_installed(env):
    venv_root = env.active_app / ".venv"
    return venv_root.exists()

# ===========================
# Main Application UI
# ===========================
async def page():
    if 'env' not in st.session_state or not getattr(st.session_state["env"], "init_done", True):
        page_module = importlib.import_module("agilab.About_agilab")
        page_module.main()
        st.rerun()
        return

    env = st.session_state["env"]
    current_app, changed_from_query = resolve_active_app(env)
    if changed_from_query:
        st.session_state["project_changed"] = True

    st.session_state["_env"] = env

    st.set_page_config(page_title="AGILab ORCHESTRATE", layout="wide", menu_items=get_about_content())
    inject_theme(env.st_resources)
    render_logo()

    if background_services_enabled() and not st.session_state.get("server_started"):
        activate_mlflow(env)
        st.session_state["server_started"] = True

    # Define defaults for session state keys.
    defaults = {
        "profile_report_file": env.AGILAB_EXPORT_ABS / "profile_report.html",
        "preview_tree": False,
        "data_source": "file",
        "scheduler_ipport": {socket.gethostbyname("localhost"): 8786},
        "workers": {"127.0.0.1": 1},
        "learn": {0, None, None, None, 1},
        "args_input": {},
        "loaded_df": None,
        "df_cols": [],
        "selected_cols": [],
        "check_all": True,
        "export_tab_previous_project": None,
        "env": env,
        "_env": env,
        "TABLE_MAX_ROWS": env.TABLE_MAX_ROWS,
        "_experiment_reload_required": False,
        "dataframe_deleted": False,
    }

    init_session_state(defaults)
    projects = list(env.projects or [])
    if env.app and env.app not in projects:
        projects = [env.app] + projects
    # Seed the selectbox default without touching widget state
    current_project = current_app
    if "args_serialized" not in st.session_state:
        st.session_state["args_serialized"] = ""
    if current_project not in projects:
        current_project = projects[0] if projects else None
    previous_project = current_project
    select_project(projects, current_project)
    project_changed = st.session_state.pop("project_changed", False)
    if project_changed or env.app != previous_project:
        try:
            st.query_params["active_app"] = env.app
        except Exception:
            pass
        store_last_active_app(env.active_app)
        app_settings_snapshot = st.session_state.get("app_settings", {})
        # Clear generic & per-project keys to prevent bleed-through
        st.session_state.pop("cluster_enabled", None)
        st.session_state.pop(f"cluster_enabled__{previous_project}", None)
        st.session_state.pop(f"cluster_scheduler__{previous_project}", None)
        st.session_state.pop(f"cluster_workers__{previous_project}", None)
        st.session_state.pop("cluster_scheduler_value", None)  # legacy
        st.session_state.pop(f"deploy_expanded_{previous_project}", None)
        st.session_state.pop(f"optimize_expanded_{previous_project}", None)
        st.session_state.pop("app_settings", None)
        st.session_state.pop("args_project", None)
        st.session_state["args_serialized"] = ""
        st.session_state["run_log_cache"] = ""
        st.session_state.pop("log_text", None)
        st.session_state.pop("service_log_cache", None)
        st.session_state.pop("service_status_cache", None)
        st.session_state.pop("_service_logs_expanded", None)
        st.session_state.pop("_benchmark_expand", None)
        st.session_state.pop("benchmark", None)
        args_override = None
        if st.session_state.get("is_args_from_ui") and st.session_state.get("args_project") == previous_project:
            state_args = app_settings_snapshot.get("args") if isinstance(app_settings_snapshot, dict) else None
            if state_args:
                args_override = state_args
        st.session_state.pop("is_args_from_ui", None)
        try:
            load_distribution.clear()
        except Exception:
            pass
        initialize_app_settings(args_override=args_override)
        st.rerun()

    module = env.target
    project_path = env.active_app
    export_abs_module = env.AGILAB_EXPORT_ABS / module
    export_abs_module.mkdir(parents=True, exist_ok=True)
    pyproject_file = env.active_app / "pyproject.toml"
    if pyproject_file.exists():
        pyproject_content = pyproject_file.read_text()
        st.session_state["rapids_default"] = ("-cu12" in pyproject_content) and os.name != "nt"
    else:
        st.session_state["rapids_default"] = False
    if "df_export_file" not in st.session_state:
        st.session_state["df_export_file"] = str(export_abs_module / "export.csv")
    if "loaded_df" not in st.session_state:
        st.session_state["loaded_df"] = None

    # Reload app settings after potential project change
    app_settings = st.session_state.get("app_settings")
    if not isinstance(app_settings, dict):
        initialize_app_settings()
        app_settings = st.session_state.get("app_settings")
        if not isinstance(app_settings, dict):
            app_settings = {"args": {}, "cluster": {}}
            st.session_state["app_settings"] = app_settings


    # Sidebar toggles for each page section
    if "show_install" not in st.session_state:
        st.session_state["show_install"] = True
    if "show_distribute" not in st.session_state:
        st.session_state["show_distribute"] = True
    if "show_run" not in st.session_state:
        st.session_state["show_run"] = _is_app_installed(env)
    if st.session_state.get("_show_run_app") != env.app:
        st.session_state["_show_run_app"] = env.app
        st.session_state["show_run"] = _is_app_installed(env)

    show_install = st.session_state["show_install"]
    show_distribute = st.session_state["show_distribute"]
    show_run = st.session_state["show_run"] if _is_app_installed(env) else False

    show_export = True

    cluster_params = app_settings.setdefault("cluster", {})
    cluster_params.setdefault("verbose", 1)
    verbosity_options = [0, 1, 2, 3]
    current_verbose = cluster_params.get("verbose", 1)
    if isinstance(current_verbose, bool):
        current_verbose = 1
    try:
        current_verbose = int(current_verbose)
    except (TypeError, ValueError):
        current_verbose = 1
    if current_verbose not in verbosity_options:
        current_verbose = 1

    user_override = st.session_state.get("_verbose_user_override", False)
    if not user_override:
        current_verbose = 1
        cluster_params["verbose"] = 1

    st.session_state.setdefault("cluster_verbose", current_verbose)

    selected_verbose = st.sidebar.selectbox(
        "Verbosity level",
        options=verbosity_options,
        key="cluster_verbose",
        help="Controls AgiEnv verbosity for generated install/distribute/run snippets.",
    )

    try:
        selected_verbose_int = int(selected_verbose)
    except (TypeError, ValueError):
        selected_verbose_int = 1

    if selected_verbose_int not in verbosity_options:
        selected_verbose_int = 1

    cluster_params["verbose"] = selected_verbose_int
    st.session_state["_verbose_user_override"] = selected_verbose_int != 1

    verbose = cluster_params.get('verbose', 1)
    with st.expander("Do deployment", expanded=True):
        render_cluster_settings_ui()
        cluster_params = st.session_state.app_settings["cluster"]
        verbose = cluster_params.get('verbose', 1)

        if show_install:
            enabled = cluster_params.get("cluster_enabled", False)
            raw_scheduler = cluster_params.get("scheduler", "")
            scheduler = f'"{str(raw_scheduler)}"' if enabled and raw_scheduler else "None"
            raw_workers = cluster_params.get("workers", "")
            workers = str(raw_workers) if enabled and raw_workers else "None"
            raw_workers_data_path = cluster_params.get("workers_data_path", "")
            workers_data_path = f'"{str(raw_workers_data_path)}"' if enabled and raw_workers_data_path else "None"
            cmd = f"""
import asyncio
from pathlib import Path
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

APPS_PATH = "{env.apps_path}"
APP = "{env.app}"

async def main():
    app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose={verbose})
    res = await AGI.install(app_env, 
                            modes_enabled={st.session_state.mode},
                            scheduler={scheduler}, 
                            workers={workers},
                            workers_data_path={workers_data_path})
    print(res)
    return res

if __name__ == "__main__":
    asyncio.run(main())"""
            st.code(cmd, language="python")

            install_expanded = st.session_state.get("_install_logs_expanded", True)
            log_expander = st.expander("Install logs", expanded=install_expanded)
            with log_expander:
                log_placeholder = st.empty()
                existing_log = st.session_state.get("log_text", "").strip()
                if existing_log:
                    log_placeholder.code(existing_log, language="python")
            if st.button("INSTALL", key="install_btn", type="primary"):
                st.session_state["_install_logs_expanded"] = True
                _reset_traceback_skip()
                clear_log()
                venv = env.agi_cluster if (env.is_source_env or env.is_worker_env) else env.active_app.parents[1]
                install_command = cmd.replace("asyncio.run(main())", env.snippet_tail)
                context_lines = [
                    "=== Install request ===",
                    f"timestamp: {datetime.now().isoformat(timespec='seconds')}",
                    f"app: {env.app}",
                    f"env_flags: source={env.is_source_env}, worker={env.is_worker_env}",
                    f"cluster_enabled: {enabled}",
                    f"verbose: {verbose}",
                    f"modes_enabled: {st.session_state.get('mode', 'N/A')}",
                    f"scheduler: {raw_scheduler if enabled and raw_scheduler else 'None'}",
                    f"workers: {raw_workers if enabled and raw_workers else 'None'}",
                    f"venv: {venv}",
                    "=== Streaming install logs ===",
                ]
                local_log = []
                with log_expander:
                    log_placeholder.empty()
                    for line in context_lines:
                        _append_log_lines(local_log, line)
                log_placeholder.code(
                    "\n".join(local_log[-LOG_DISPLAY_MAX_LINES:]),
                    language="python",
                    height=INSTALL_LOG_HEIGHT,
                )
                with st.spinner("Installing worker..."):
                    _install_stdout = ""
                    install_stderr = ""
                    install_error: Exception | None = None
                    try:
                        _install_stdout, install_stderr = await env.run_agi(
                            install_command,
                            log_callback=lambda message: _append_log_lines(local_log, message),
                            venv=venv,
                        )
                    except Exception as exc:
                        install_error = exc
                        install_stderr = str(exc)
                        _append_log_lines(local_log, f"ERROR: {install_stderr}")

                    error_flag = bool(install_stderr.strip()) or install_error is not None
                    if not error_flag and _log_indicates_install_failure(local_log):
                        error_flag = True
                        if not install_stderr.strip():
                            install_stderr = "Detected connection failure in install logs."

                    status_line = (
                        "✅ Install complete."
                        if not error_flag
                        else "❌ Install finished with errors. Check logs above."
                    )
                    _append_log_lines(local_log, status_line)
                    with log_expander:
                        log_placeholder.code(
                            "\n".join(local_log[-LOG_DISPLAY_MAX_LINES:]),
                            language="python",
                            height=INSTALL_LOG_HEIGHT,
                        )
                    if error_flag:
                        st.error("Cluster installation failed.")
                    else:
                        st.success("Cluster installation completed.")
                        st.session_state["SET ARGS"] = True
                        st.session_state["show_run"] = True

    # ------------------
    # DISTRIBUTE Section
    # ------------------
    if show_distribute:
        with st.expander(f"{module} args", expanded=True):
            app_args_form = env.app_args_form

            snippet_exists = app_args_form.exists()
            snippet_not_empty = snippet_exists and app_args_form.stat().st_size > 1

            toggle_key = "toggle_edit_ui"
            if toggle_key not in st.session_state:
                st.session_state[toggle_key] = not snippet_not_empty

            st.toggle("Edit", key=toggle_key, on_change=init_custom_ui, args=[app_args_form])

            if st.session_state[toggle_key]:
                render_generic_ui()
                if not snippet_exists:
                    with open(app_args_form, "w") as st_src:
                        st_src.write("")
            else:
                if snippet_exists and snippet_not_empty:
                    try:
                        runpy.run_path(app_args_form, init_globals=globals())
                    except Exception as e:
                        st.warning(e)
                else:
                    render_generic_ui()
                    if not snippet_exists:
                        with open(app_args_form, "w") as st_src:
                            st_src.write("")

            cluster_params = st.session_state.app_settings.setdefault("cluster", {})
            cluster_enabled = bool(cluster_params.get("cluster_enabled", False))
            if cluster_enabled:
                # Refresh mount table cache each rerun (mounts can appear/disappear while Streamlit stays alive).
                try:
                    _mount_table.cache_clear()
                except Exception:
                    pass
                share_candidate = Path(env.agi_share_path)
                if not share_candidate.is_absolute():
                    share_candidate = Path(env.home_abs) / share_candidate
                share_candidate = share_candidate.expanduser()
                is_symlink = share_candidate.is_symlink()
                try:
                    share_resolved = share_candidate.resolve()
                except Exception:
                    share_resolved = share_candidate
                looks_shared = _looks_like_shared_path(share_candidate) or _looks_like_shared_path(share_resolved)
                if not is_symlink and not looks_shared:
                    fstype = _fstype_for_path(share_resolved) or _fstype_for_path(share_candidate) or "unknown"
                    hint = _macos_autofs_hint(share_candidate)
                    extra = f"\n\n{hint}" if hint else ""
                    st.warning(
                        f"Cluster is enabled but the data directory `{share_resolved}` appears local. "
                        f"(detected fstype: `{fstype}`) "
                        "Set `AGI_SHARE_DIR` to a shared mount (or symlink to one) so remote workers can read outputs."
                        f"{extra}",
                        icon="⚠️",
                    )

            args_serialized = ", ".join(
                [f'{key}="{value}"' if isinstance(value, str) else f"{key}={value}"
                 for key, value in st.session_state.app_settings["args"].items()]
            )
            st.session_state["args_serialized"] = args_serialized
            if st.session_state.get("args_reload_required"):
                del st.session_state["app_settings"]
                st.rerun()
        with st.expander("Check orchestration", expanded=False):
            cluster_params = st.session_state.app_settings["cluster"]
            enabled = cluster_params.get("cluster_enabled", False)
            scheduler = cluster_params.get("scheduler", "")
            scheduler = f'"{str(scheduler)}"' if enabled and scheduler else "None"
            workers = cluster_params.get("workers", {})
            workers = str(workers) if enabled and workers else "None"
            cmd = f"""
import asyncio
from pathlib import Path
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

APPS_PATH = "{env.apps_path}"
APP = "{env.app}"

async def main():
    app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose={verbose})
    res = await AGI.get_distrib(app_env,
                               scheduler={scheduler}, 
                               workers={workers},
                               {st.session_state.args_serialized})
    print(res)
    return res

if __name__ == "__main__":
    asyncio.run(main())"""
            st.code(cmd, language="python")
            if st.button("CHECK distribute", key="preview_btn", type="primary"):
                st.session_state.preview_tree = True
                with st.expander("Orchestration log", expanded=False):
                    dist_log: list[str] = []
                    live_log_placeholder = st.empty()
                    _reset_traceback_skip()
                    with st.spinner("Building distribution..."):
                        stdout, stderr = await env.run_agi(
                            cmd.replace("asyncio.run(main())", env.snippet_tail),
                            log_callback=lambda message: _append_log_lines(dist_log, message),
                            venv=project_path
                        )
                    if stderr:
                        _append_log_lines(dist_log, stderr)
                    if stdout:
                        _append_log_lines(dist_log, stdout)
                    live_log_placeholder.code(
                        "\n".join(dist_log[-LOG_DISPLAY_MAX_LINES:]),
                        language="python",
                        height=LIVE_LOG_MIN_HEIGHT,
                    )
                    if not stderr:
                        st.success("Distribution built successfully.")

            with st.expander("Workplan", expanded=False):
                if st.session_state.get("preview_tree"):
                    dist_tree_path = env.wenv_abs / "distribution.json"
                    if dist_tree_path.exists():
                        workers, work_plan_metadata, work_plan = load_distribution(dist_tree_path)
                        partition_key = "Partition"
                        weights_key = "Units"
                        weights_unit = "Unit"
                        tabs = st.tabs(["Tree", "Workload"])
                        with tabs[0]:
                            if env.base_worker_cls.endswith('dag-worker'):
                                show_graph(workers, work_plan_metadata, work_plan, partition_key, weights_key,
                                       show_leaf_list=st.checkbox("Show leaf nodes", value=False))
                            else:
                                show_tree(workers, work_plan_metadata, work_plan, partition_key, weights_key,
                                       show_leaf_list=st.checkbox("Show leaf nodes", value=False))
                        with tabs[1]:
                            workload_barchart(workers, work_plan_metadata, partition_key, weights_key, weights_unit)
                        unused_workers = [worker for worker, chunks in zip(workers, work_plan_metadata) if not chunks]
                        if unused_workers:
                            st.warning(f"**{len(unused_workers)} Unused workers:** " + ", ".join(unused_workers))
                        st.markdown("**Modify Distribution:**")
                        ncols = 2
                        cols = st.columns([10, 1, 10])
                        count = 0
                        for i, chunks in enumerate(work_plan_metadata):
                            for j, chunk in enumerate(chunks):
                                partition, size = chunk
                                with cols[0 if count % ncols == 0 else 2]:
                                    b1, b2 = st.columns(2)
                                    b1.text(f"{partition_key.title()} {partition} ({weights_key}: {size} {weights_unit})")
                                    key = f"worker_partition_{partition}_{i}_{j}"
                                    b2.selectbox("Worker", options=workers, key=key, index=i if i < len(workers) else 0)
                                count += 1
                        if st.button("Apply", key="apply_btn", type="primary"):
                            new_work_plan_metadata = [[] for _ in workers]
                            new_work_plan = [[] for _ in workers]
                            for i, (chunks, files_tree) in enumerate(zip(work_plan_metadata, work_plan)):
                                for j, (chunk, files) in enumerate(zip(chunks, files_tree)):
                                    key = f"worker_partition{chunk[0]}"
                                    selected_worker = st.session_state.get(key)
                                    if selected_worker and selected_worker in workers:
                                        idx = workers.index(selected_worker)
                                        new_work_plan_metadata[idx].append(chunk)
                                        new_work_plan[idx].append(files)
                            # Read & update the original JSON dict (avoid writing to the workers list)
                            with open(dist_tree_path, "r") as f:
                                data = json.load(f)
                            data["target_args"] = st.session_state.app_settings["args"]
                            data["work_plan_metadata"] = new_work_plan_metadata
                            data["work_plan"] = new_work_plan
                            with open(dist_tree_path, "w") as f:
                                json.dump(data, f)
                            st.rerun()

    # ------------------
    # RUN Section
    # ------------------
    show_run_panel = False
    show_submit_panel = False
    cmd = None
    if show_run:
        prev_app_key = "execute_prev_app"
        if st.session_state.get(prev_app_key) != env.app:
            st.session_state[prev_app_key] = env.app
            st.session_state["run_log_cache"] = ""
            st.session_state.pop("log_text", None)
            st.session_state.pop("_benchmark_expand", None)
            st.session_state.pop("_force_export_open", None)
        st.session_state.setdefault("run_log_cache", "")

        execution_view_key = f"orchestrate_execution_view__{env.app}"
        if execution_view_key not in st.session_state:
            st.session_state[execution_view_key] = "Run now"

        execution_view = st.radio(
            "Execution panel",
            options=("Run now", "Serve"),
            key=execution_view_key,
            horizontal=True,
            help="Show either the run panel or the submit panel.",
        )
        show_run_panel = execution_view == "Run now"
        show_submit_panel = execution_view == "Serve"

        cluster_params = st.session_state.app_settings["cluster"]
        cluster_enabled = bool(cluster_params.get("cluster_enabled", False))
        enabled = cluster_enabled
        scheduler = f'"{cluster_params.get("scheduler")}"' if enabled and cluster_params.get("scheduler") else "None"
        workers = str(cluster_params.get("workers")) if enabled and cluster_params.get("workers") else "None"

        if show_run_panel:
            with st.expander("Optimize execution"):
                st.session_state.setdefault("benchmark", False)
                if st.session_state.pop("benchmark_reset_pending", False):
                    st.session_state["benchmark"] = False

                cluster_params = st.session_state.app_settings["cluster"]
                cluster_enabled = bool(cluster_params.get("cluster_enabled", False))

                benchmark_prereqs_met = cluster_enabled and all(
                    cluster_params.get(flag, False) for flag in ("pool", "cython")
                )
                if not benchmark_prereqs_met and st.session_state.get("benchmark"):
                    st.session_state["benchmark"] = False

                requested_benchmark = st.toggle(
                    "Benchmark all modes",
                    key="benchmark",
                    help="Run the snippet once per mode and report timings for each path",
                    disabled=not benchmark_prereqs_met,
                )

                if benchmark_prereqs_met:
                    benchmark_enabled = requested_benchmark
                else:
                    benchmark_enabled = False
                    st.warning("Benchmark requires Cluster, Pool, and Cython to be enabled together.")

                def _compute_mode():
                    return (
                        int(cluster_params.get("pool", False))
                        + int(cluster_params.get("cython", False)) * 2
                        + int(cluster_enabled) * 4
                        + int(cluster_params.get("rapids", False)) * 8
                    )

                if benchmark_enabled:
                    run_mode = None
                    info_label = "Run mode benchmark (all modes)"
                else:
                    run_mode = _compute_mode()
                    run_mode_label = [
                        "0: python", "1: pool of process", "2: cython", "3: pool and cython",
                        "4: dask", "5: dask and pool", "6: dask and cython", "7: dask and pool and cython",
                        "8: rapids", "9: rapids and pool", "10: rapids and cython", "11: rapids and pool and cython",
                        "12: rapids and dask", "13: rapids and dask and pool", "14: rapids and dask and cython",
                        "15: rapids and dask and pool and cython",
                    ]
                    info_label = f"Run mode {run_mode_label[run_mode]}"

                st.session_state["mode"] = run_mode
                st.info(info_label)

                verbose = cluster_params.get("verbose", 1)
                enabled = cluster_enabled
                scheduler = f'"{cluster_params.get("scheduler")}"' if enabled and cluster_params.get("scheduler") else "None"
                workers = str(cluster_params.get("workers")) if enabled and cluster_params.get("workers") else "None"
                cmd = textwrap.dedent(f"""
    import asyncio
    from pathlib import Path
    from agi_cluster.agi_distributor import AGI
    from agi_env import AgiEnv

    APPS_PATH = "{env.apps_path}"
    APP = "{env.app}"

    async def main():
        app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose={verbose})
        res = await AGI.run(app_env, 
                            mode={run_mode if run_mode is not None else "None"}, 
                            scheduler={scheduler}, 
                            workers={workers}, 
                            {st.session_state.args_serialized})
        print(res)
        return res

    if __name__ == "__main__":
        asyncio.run(main())""")
                st.code(cmd, language="python")

                expand_benchmark = st.session_state.pop("_benchmark_expand", False)
                with st.expander("Benchmark results", expanded=expand_benchmark):
                    try:
                        if env.benchmark.exists():
                            with open(env.benchmark, "r") as f:
                                raw = json.load(f) or {}

                            date_value = str(raw.pop("date", "") or "").strip()
                            benchmark_df = pd.DataFrame.from_dict(raw, orient="index")

                            df_nonempty = benchmark_df.dropna(how="all")
                            if not df_nonempty.empty:
                                df_nonempty = df_nonempty.loc[:, df_nonempty.notna().any(axis=0)]
                            if not df_nonempty.empty and df_nonempty.shape[1] > 0:
                                if not date_value:
                                    try:
                                        ts = os.path.getmtime(env.benchmark)
                                        date_value = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                                    except Exception:
                                        date_value = ""

                                if date_value:
                                    st.caption(f"Benchmark date: {date_value}")

                                st.dataframe(df_nonempty)
                            else:
                                st.info("Benchmark file is present but empty. Run the benchmark to collect data.")
                        else:
                            st.info("No benchmark results yet. Enable 'Benchmark all modes' and run EXECUTE to gather data.")
                    except json.JSONDecodeError as e:
                        st.warning(f"Error decoding JSON: {e}")

        if show_submit_panel:
            st.session_state.setdefault("service_log_cache", "")
            st.session_state.setdefault("service_status_cache", "idle")
            st.session_state.setdefault("service_poll_interval", 1.0)
            st.session_state.setdefault("service_stop_timeout", 30.0)
            st.session_state.setdefault("service_shutdown_on_stop", True)
            st.session_state.setdefault("service_heartbeat_timeout", 10.0)
            st.session_state.setdefault("service_cleanup_done_ttl_hours", 168.0)
            st.session_state.setdefault("service_cleanup_failed_ttl_hours", 336.0)
            st.session_state.setdefault("service_cleanup_heartbeat_ttl_hours", 24.0)
            st.session_state.setdefault("service_cleanup_done_max_files", 2000)
            st.session_state.setdefault("service_cleanup_failed_max_files", 2000)
            st.session_state.setdefault("service_cleanup_heartbeat_max_files", 1000)
            st.session_state.setdefault("service_health_cache", [])

            with st.expander("Service mode (persistent workers)", expanded=False):
                service_enabled = bool(cluster_params.get("cluster_enabled", False))
                if not service_enabled:
                    st.info("Enable Cluster in deployment settings before starting service mode.")

                service_mode = (
                    int(cluster_params.get("pool", False))
                    + int(cluster_params.get("cython", False)) * 2
                    + int(service_enabled) * 4
                    + int(cluster_params.get("rapids", False)) * 8
                )

                service_poll_interval = st.number_input(
                    "Service poll interval (seconds)",
                    min_value=0.0,
                    value=float(st.session_state.get("service_poll_interval", 1.0)),
                    step=0.1,
                    key="service_poll_interval",
                    disabled=not service_enabled,
                    help="Used when worker loop does not handle stop_event directly.",
                )
                service_stop_timeout = st.number_input(
                    "Service stop timeout (seconds)",
                    min_value=0.0,
                    value=float(st.session_state.get("service_stop_timeout", 30.0)),
                    step=1.0,
                    key="service_stop_timeout",
                    disabled=not service_enabled,
                    help="Maximum wait time for worker service loops to stop.",
                )
                service_shutdown_on_stop = st.toggle(
                    "Shutdown cluster on STOP",
                    value=bool(st.session_state.get("service_shutdown_on_stop", True)),
                    key="service_shutdown_on_stop",
                    disabled=not service_enabled,
                )
                service_heartbeat_timeout = st.number_input(
                    "Heartbeat timeout (seconds)",
                    min_value=0.1,
                    value=float(st.session_state.get("service_heartbeat_timeout", 10.0)),
                    step=0.5,
                    key="service_heartbeat_timeout",
                    disabled=not service_enabled,
                    help="Worker health timeout before auto-restart is triggered.",
                )
                with st.expander("Retention policy", expanded=False):
                    service_cleanup_done_ttl_hours = st.number_input(
                        "Done artifacts TTL (hours)",
                        min_value=0.0,
                        value=float(st.session_state.get("service_cleanup_done_ttl_hours", 168.0)),
                        step=1.0,
                        key="service_cleanup_done_ttl_hours",
                        disabled=not service_enabled,
                    )
                    service_cleanup_failed_ttl_hours = st.number_input(
                        "Failed artifacts TTL (hours)",
                        min_value=0.0,
                        value=float(st.session_state.get("service_cleanup_failed_ttl_hours", 336.0)),
                        step=1.0,
                        key="service_cleanup_failed_ttl_hours",
                        disabled=not service_enabled,
                    )
                    service_cleanup_heartbeat_ttl_hours = st.number_input(
                        "Heartbeat artifacts TTL (hours)",
                        min_value=0.0,
                        value=float(st.session_state.get("service_cleanup_heartbeat_ttl_hours", 24.0)),
                        step=1.0,
                        key="service_cleanup_heartbeat_ttl_hours",
                        disabled=not service_enabled,
                    )
                    service_cleanup_done_max_files = st.number_input(
                        "Done artifacts max files",
                        min_value=0,
                        value=int(st.session_state.get("service_cleanup_done_max_files", 2000)),
                        step=100,
                        key="service_cleanup_done_max_files",
                        disabled=not service_enabled,
                    )
                    service_cleanup_failed_max_files = st.number_input(
                        "Failed artifacts max files",
                        min_value=0,
                        value=int(st.session_state.get("service_cleanup_failed_max_files", 2000)),
                        step=100,
                        key="service_cleanup_failed_max_files",
                        disabled=not service_enabled,
                    )
                    service_cleanup_heartbeat_max_files = st.number_input(
                        "Heartbeat artifacts max files",
                        min_value=0,
                        value=int(st.session_state.get("service_cleanup_heartbeat_max_files", 1000)),
                        step=100,
                        key="service_cleanup_heartbeat_max_files",
                        disabled=not service_enabled,
                    )

                service_health_defaults = {
                    "allow_idle": False,
                    "max_unhealthy": 0,
                    "max_restart_rate": 0.25,
                }
                service_health_settings = cluster_params.get("service_health", {})
                if isinstance(service_health_settings, dict):
                    service_health_defaults["allow_idle"] = _coerce_bool_setting(
                        service_health_settings.get("allow_idle"),
                        service_health_defaults["allow_idle"],
                    )
                    service_health_defaults["max_unhealthy"] = _coerce_int_setting(
                        service_health_settings.get("max_unhealthy"),
                        service_health_defaults["max_unhealthy"],
                        minimum=0,
                    )
                    service_health_defaults["max_restart_rate"] = _coerce_float_setting(
                        service_health_settings.get("max_restart_rate"),
                        service_health_defaults["max_restart_rate"],
                        minimum=0.0,
                        maximum=1.0,
                    )

                gate_allow_idle_key = f"service_health_allow_idle__{env.app}"
                gate_max_unhealthy_key = f"service_health_max_unhealthy__{env.app}"
                gate_max_restart_rate_key = f"service_health_max_restart_rate__{env.app}"
                if gate_allow_idle_key not in st.session_state:
                    st.session_state[gate_allow_idle_key] = service_health_defaults["allow_idle"]
                if gate_max_unhealthy_key not in st.session_state:
                    st.session_state[gate_max_unhealthy_key] = service_health_defaults["max_unhealthy"]
                if gate_max_restart_rate_key not in st.session_state:
                    st.session_state[gate_max_restart_rate_key] = service_health_defaults["max_restart_rate"]

                with st.expander("Health gate (SLA)", expanded=False):
                    st.caption("Used by the one-click HEALTH gate action and persisted in app_settings.toml.")
                    service_health_allow_idle = st.toggle(
                        "Allow idle status",
                        key=gate_allow_idle_key,
                        disabled=not service_enabled,
                    )
                    service_health_max_unhealthy = st.number_input(
                        "Max unhealthy workers",
                        min_value=0,
                        value=int(st.session_state.get(gate_max_unhealthy_key, 0)),
                        step=1,
                        key=gate_max_unhealthy_key,
                        disabled=not service_enabled,
                    )
                    service_health_max_restart_rate = st.number_input(
                        "Max restart rate (0.0-1.0)",
                        min_value=0.0,
                        max_value=1.0,
                        value=float(st.session_state.get(gate_max_restart_rate_key, 0.25)),
                        step=0.05,
                        key=gate_max_restart_rate_key,
                        disabled=not service_enabled,
                    )

                updated_service_health_settings = {
                    "allow_idle": bool(service_health_allow_idle),
                    "max_unhealthy": int(service_health_max_unhealthy),
                    "max_restart_rate": float(service_health_max_restart_rate),
                }
                if cluster_params.get("service_health") != updated_service_health_settings:
                    cluster_params["service_health"] = updated_service_health_settings
                    st.session_state.app_settings["cluster"] = cluster_params
                    st.session_state.app_settings = _write_app_settings_toml(
                        env.app_settings_file,
                        st.session_state.app_settings,
                    )
                    try:
                        load_toml_file.clear()
                    except Exception:
                        pass

                st.caption(f"Service status: `{st.session_state.get('service_status_cache', 'idle')}`")

                def _build_service_snippet(service_action: str) -> str:
                    return textwrap.dedent(f"""
    import asyncio
    from pathlib import Path
    from agi_cluster.agi_distributor import AGI
    from agi_env import AgiEnv

    APPS_PATH = "{env.apps_path}"
    APP = "{env.app}"

    async def main():
        app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose={verbose})
        res = await AGI.serve(
            app_env,
            action="{service_action}",
            mode={service_mode},
            scheduler={scheduler},
            workers={workers},
            poll_interval={float(service_poll_interval)},
            shutdown_on_stop={bool(service_shutdown_on_stop)},
            stop_timeout={float(service_stop_timeout)},
            heartbeat_timeout={float(service_heartbeat_timeout)},
            cleanup_done_ttl_sec={float(service_cleanup_done_ttl_hours) * 3600.0},
            cleanup_failed_ttl_sec={float(service_cleanup_failed_ttl_hours) * 3600.0},
            cleanup_heartbeat_ttl_sec={float(service_cleanup_heartbeat_ttl_hours) * 3600.0},
            cleanup_done_max_files={int(service_cleanup_done_max_files)},
            cleanup_failed_max_files={int(service_cleanup_failed_max_files)},
            cleanup_heartbeat_max_files={int(service_cleanup_heartbeat_max_files)},
            {st.session_state.args_serialized}
        )
        print(res)
        return res

    if __name__ == "__main__":
        asyncio.run(main())""")

                preview_action = st.selectbox(
                    "Service snippet action",
                    options=["start", "status", "health", "stop"],
                    index=0,
                    key="service_snippet_action",
                )
                st.code(_build_service_snippet(preview_action), language="python")

                start_col, status_col, health_col, stop_col = st.columns(4)
                start_service_clicked = start_col.button(
                    "START service",
                    key="service_start_btn",
                    type="primary",
                    use_container_width=True,
                    disabled=not service_enabled,
                )
                status_service_clicked = status_col.button(
                    "STATUS service",
                    key="service_status_btn",
                    type="secondary",
                    use_container_width=True,
                    disabled=not service_enabled,
                )
                health_gate_clicked = health_col.button(
                    "HEALTH gate",
                    key="service_health_gate_btn",
                    type="secondary",
                    use_container_width=True,
                    disabled=not service_enabled,
                )
                stop_service_clicked = stop_col.button(
                    "STOP service",
                    key="service_stop_btn",
                    type="secondary",
                    use_container_width=True,
                    disabled=not service_enabled,
                )

                service_log_placeholder = st.empty()
                service_health_placeholder = st.empty()

                def _render_service_health_table() -> None:
                    health_rows = st.session_state.get("service_health_cache") or []
                    if not isinstance(health_rows, list) or not health_rows:
                        service_health_placeholder.empty()
                        return
                    try:
                        health_df = pd.DataFrame(health_rows)
                    except Exception:
                        service_health_placeholder.empty()
                        return
                    ordered_cols = [
                        "worker",
                        "healthy",
                        "reason",
                        "future_state",
                        "heartbeat_state",
                        "heartbeat_age_sec",
                    ]
                    display_cols = [col for col in ordered_cols if col in health_df.columns]
                    if display_cols:
                        health_df = health_df[display_cols]
                    service_health_placeholder.dataframe(health_df, use_container_width=True)

                _render_service_health_table()
                cached_service_log = st.session_state.get("service_log_cache", "").strip()
                if cached_service_log:
                    service_log_placeholder.code(
                        cached_service_log,
                        language="python",
                        height=INSTALL_LOG_HEIGHT,
                    )

                async def _execute_service_action(action_name: str) -> None:
                    _reset_traceback_skip()
                    local_log: list[str] = []
                    context_lines = [
                        f"=== Service action: {action_name.upper()} ===",
                        f"timestamp: {datetime.now().isoformat(timespec='seconds')}",
                        f"app: {env.app}",
                        f"mode: {service_mode}",
                        f"scheduler: {cluster_params.get('scheduler') if service_enabled else 'None'}",
                        f"workers: {cluster_params.get('workers') if service_enabled else 'None'}",
                        f"poll_interval: {service_poll_interval}",
                        f"stop_timeout: {service_stop_timeout}",
                        f"shutdown_on_stop: {service_shutdown_on_stop}",
                        f"heartbeat_timeout: {service_heartbeat_timeout}",
                        f"cleanup_done_ttl_h: {service_cleanup_done_ttl_hours}",
                        f"cleanup_failed_ttl_h: {service_cleanup_failed_ttl_hours}",
                        f"cleanup_heartbeat_ttl_h: {service_cleanup_heartbeat_ttl_hours}",
                        f"cleanup_done_max: {service_cleanup_done_max_files}",
                        f"cleanup_failed_max: {service_cleanup_failed_max_files}",
                        f"cleanup_heartbeat_max: {service_cleanup_heartbeat_max_files}",
                        f"health_allow_idle: {bool(service_health_allow_idle)}",
                        f"health_max_unhealthy: {int(service_health_max_unhealthy)}",
                        f"health_max_restart_rate: {float(service_health_max_restart_rate)}",
                        "=== Streaming service logs ===",
                    ]
                    for line in context_lines:
                        _append_log_lines(local_log, line)

                    def _render_logs() -> None:
                        service_log_placeholder.code(
                            "\n".join(local_log[-LOG_DISPLAY_MAX_LINES:]),
                            language="python",
                            height=INSTALL_LOG_HEIGHT,
                        )

                    _render_logs()
                    cmd_service = _build_service_snippet(action_name)
                    service_stdout = ""
                    service_stderr = ""
                    service_error: Exception | None = None

                    with st.spinner(f"Service action '{action_name}' in progress..."):
                        def _service_log_callback(message: str) -> None:
                            _append_log_lines(local_log, message)
                            _render_logs()

                        try:
                            service_stdout, service_stderr = await env.run_agi(
                                cmd_service.replace("asyncio.run(main())", env.snippet_tail),
                                log_callback=_service_log_callback,
                                venv=project_path,
                            )
                        except Exception as exc:
                            service_error = exc
                            service_stderr = str(exc)
                            _append_log_lines(local_log, f"ERROR: {service_stderr}")

                    if service_stdout:
                        _append_log_lines(local_log, service_stdout)
                    if service_stderr:
                        _append_log_lines(local_log, service_stderr)

                    result_payload = _extract_result_dict_from_output(service_stdout)
                    if isinstance(result_payload, dict) and isinstance(result_payload.get("status"), str):
                        st.session_state["service_status_cache"] = result_payload["status"]
                        if st.session_state["service_status_cache"] in {"stopped", "idle"}:
                            st.session_state["service_health_cache"] = []
                            _render_service_health_table()
                        restarted_workers = result_payload.get("restarted_workers") or []
                        restart_reasons = result_payload.get("restart_reasons") or {}
                        cleanup_stats = result_payload.get("cleanup") or {}
                        worker_health = result_payload.get("worker_health") or []
                        heartbeat_timeout_sec = result_payload.get("heartbeat_timeout_sec")
                        health_json_path = result_payload.get("health_path") or result_payload.get("path")

                        if isinstance(worker_health, list):
                            st.session_state["service_health_cache"] = worker_health
                            _render_service_health_table()
                            if worker_health:
                                _append_log_lines(local_log, "=== Service health ===")
                                for row in worker_health:
                                    if not isinstance(row, dict):
                                        continue
                                    worker_name = row.get("worker", "?")
                                    healthy = bool(row.get("healthy", False))
                                    reason = row.get("reason", "")
                                    age = row.get("heartbeat_age_sec", None)
                                    hb_state = row.get("heartbeat_state", "missing")
                                    status_word = "healthy" if healthy else "unhealthy"
                                    _append_log_lines(
                                        local_log,
                                        f"{worker_name}: {status_word} "
                                        f"(hb_state={hb_state}, hb_age={age}, reason={reason})",
                                    )
                        else:
                            st.session_state["service_health_cache"] = []
                            _render_service_health_table()

                        if restarted_workers:
                            _append_log_lines(local_log, "=== Service auto-restart ===")
                            for worker in restarted_workers:
                                reason = restart_reasons.get(worker, "unhealthy")
                                _append_log_lines(local_log, f"restart {worker}: {reason}")

                        if heartbeat_timeout_sec is not None:
                            _append_log_lines(local_log, f"heartbeat_timeout_sec={heartbeat_timeout_sec}")
                        if health_json_path:
                            _append_log_lines(local_log, f"service_health_json={health_json_path}")

                        if isinstance(cleanup_stats, dict) and any(
                                int(cleanup_stats.get(key, 0) or 0) > 0
                                for key in ("done", "failed", "heartbeats")
                        ):
                            _append_log_lines(local_log, "=== Service cleanup ===")
                            _append_log_lines(
                                local_log,
                                f"done={int(cleanup_stats.get('done', 0) or 0)} "
                                f"failed={int(cleanup_stats.get('failed', 0) or 0)} "
                                f"heartbeats={int(cleanup_stats.get('heartbeats', 0) or 0)}",
                            )
                    elif service_error or service_stderr.strip():
                        st.session_state["service_status_cache"] = "error"
                        st.session_state["service_health_cache"] = []
                        _render_service_health_table()

                    st.session_state["service_log_cache"] = "\n".join(local_log[-LOG_DISPLAY_MAX_LINES:])
                    _render_logs()

                    if service_error or service_stderr.strip():
                        st.error(f"Service action '{action_name}' failed.")
                    else:
                        if isinstance(result_payload, dict):
                            restarted_workers = result_payload.get("restarted_workers") or []
                            if restarted_workers:
                                st.warning(
                                    "Service auto-restarted worker loops: "
                                    + ", ".join(str(worker) for worker in restarted_workers)
                                )
                        st.success(
                            f"Service action '{action_name}' completed with status "
                            f"'{st.session_state.get('service_status_cache', 'unknown')}'."
                        )
                    if isinstance(result_payload, dict):
                        return result_payload
                    return None

                if start_service_clicked:
                    await _execute_service_action("start")
                elif status_service_clicked:
                    await _execute_service_action("status")
                elif health_gate_clicked:
                    health_payload = await _execute_service_action("health")
                    if isinstance(health_payload, dict):
                        gate_code, gate_reason, gate_details = _evaluate_service_health_gate(
                            health_payload,
                            allow_idle=bool(service_health_allow_idle),
                            max_unhealthy=int(service_health_max_unhealthy),
                            max_restart_rate=float(service_health_max_restart_rate),
                        )
                        restart_rate = float(gate_details.get("restart_rate", 0.0) or 0.0)
                        st.caption(
                            f"Health gate metrics: status={gate_details.get('status')}, "
                            f"unhealthy={gate_details.get('workers_unhealthy_count')}, "
                            f"restarted={gate_details.get('workers_restarted_count')}, "
                            f"running={gate_details.get('workers_running_count')}, "
                            f"restart_rate={restart_rate:.3f}"
                        )
                        if gate_code == 0:
                            st.success("HEALTH gate passed.")
                        else:
                            st.error(f"HEALTH gate failed (code {gate_code}): {gate_reason}")
                    else:
                        st.error("HEALTH gate failed: unable to parse service health payload.")
                elif stop_service_clicked:
                    await _execute_service_action("stop")

    execute_deps = OrchestrateExecuteDeps(
        clear_log=clear_log,
        update_log=update_log,
        strip_ansi=strip_ansi,
        reset_traceback_skip=_reset_traceback_skip,
        append_log_lines=_append_log_lines,
        display_log=display_log,
        rerun_fragment_or_app=_rerun_fragment_or_app,
        update_delete_confirm_state=_update_delete_confirm_state,
        capture_dataframe_preview_state=_capture_dataframe_preview_state,
        restore_dataframe_preview_state=_restore_dataframe_preview_state,
        generate_profile_report=generate_profile_report,
        log_display_max_lines=LOG_DISPLAY_MAX_LINES,
        live_log_min_height=LIVE_LOG_MIN_HEIGHT,
        install_log_height=INSTALL_LOG_HEIGHT,
    )
    await render_execute_section(
        env=env,
        project_path=project_path,
        app_state_name=app_state_name,
        controls_visible=show_run,
        show_run_panel=show_run_panel,
        cmd=cmd,
        deps=execute_deps,
    )

# ===========================
# Main Entry Point
# ===========================
async def main():
    try:
        await page()
    except Exception as e:
        st.error(f"An error occurred: {e}")
        import traceback
        st.code(f"```\n{traceback.format_exc()}\n```")

if __name__ == "__main__":
    asyncio.run(main())
