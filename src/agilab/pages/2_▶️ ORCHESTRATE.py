import asyncio

# ===========================
# Standard Imports (lightweight)
# ===========================
import os
import sys
import socket
import runpy
import ast
import json
import logging
import subprocess
from functools import lru_cache
from pathlib import Path
import importlib
from typing import Any, Optional
from datetime import datetime

# Third-Party imports
import tomllib       # For reading TOML files
import tomli_w       # For writing TOML files
import pandas as pd
# Theme configuration
os.environ.setdefault("STREAMLIT_CONFIG_FILE", str(Path(__file__).resolve().parents[1] / "resources" / "config.toml"))
import streamlit as st
from streamlit.errors import StreamlitAPIException
try:
    from agilab.page_docs import render_page_docs_access
except ModuleNotFoundError:
    _page_docs_path = Path(__file__).resolve().parents[1] / "page_docs.py"
    _page_docs_spec = importlib.util.spec_from_file_location("agilab_page_docs_fallback", _page_docs_path)
    if _page_docs_spec is None or _page_docs_spec.loader is None:
        raise
    _page_docs_module = importlib.util.module_from_spec(_page_docs_spec)
    _page_docs_spec.loader.exec_module(_page_docs_module)
    render_page_docs_access = _page_docs_module.render_page_docs_access
try:
    from agilab.orchestrate_page_support import (
        build_distribution_snippet,
        build_install_snippet,
        build_run_snippet,
        compute_run_mode,
        describe_run_mode,
        optional_python_expr,
        optional_string_expr,
        filter_noise_lines,
        filter_warning_messages,
        format_log_block,
        reassign_distribution_plan,
        is_dask_shutdown_noise,
        serialize_args_payload,
        strip_ansi,
        update_distribution_payload,
        workplan_selection_key,
    )
except ModuleNotFoundError:
    _orchestrate_page_support_path = Path(__file__).resolve().parents[1] / "orchestrate_page_support.py"
    _orchestrate_page_support_spec = importlib.util.spec_from_file_location(
        "agilab_orchestrate_page_support_fallback",
        _orchestrate_page_support_path,
    )
    if _orchestrate_page_support_spec is None or _orchestrate_page_support_spec.loader is None:
        raise
    _orchestrate_page_support_module = importlib.util.module_from_spec(_orchestrate_page_support_spec)
    _orchestrate_page_support_spec.loader.exec_module(_orchestrate_page_support_module)
    build_distribution_snippet = _orchestrate_page_support_module.build_distribution_snippet
    build_install_snippet = _orchestrate_page_support_module.build_install_snippet
    build_run_snippet = _orchestrate_page_support_module.build_run_snippet
    compute_run_mode = _orchestrate_page_support_module.compute_run_mode
    describe_run_mode = _orchestrate_page_support_module.describe_run_mode
    filter_noise_lines = _orchestrate_page_support_module.filter_noise_lines
    filter_warning_messages = _orchestrate_page_support_module.filter_warning_messages
    format_log_block = _orchestrate_page_support_module.format_log_block
    optional_python_expr = _orchestrate_page_support_module.optional_python_expr
    optional_string_expr = _orchestrate_page_support_module.optional_string_expr
    reassign_distribution_plan = _orchestrate_page_support_module.reassign_distribution_plan
    is_dask_shutdown_noise = _orchestrate_page_support_module.is_dask_shutdown_noise
    serialize_args_payload = _orchestrate_page_support_module.serialize_args_payload
    strip_ansi = _orchestrate_page_support_module.strip_ansi
    update_distribution_payload = _orchestrate_page_support_module.update_distribution_payload
    workplan_selection_key = _orchestrate_page_support_module.workplan_selection_key
try:
    from agilab.orchestrate_page_helpers import (
        app_install_status as _orchestrate_app_install_status,
        init_session_state as _orchestrate_init_session_state,
        clear_log as _orchestrate_clear_log,
        rerun_fragment_or_app as _orchestrate_rerun_fragment_or_app,
        update_delete_confirm_state as _orchestrate_update_delete_confirm_state,
        update_log as _orchestrate_update_log,
        reset_traceback_skip as _orchestrate_reset_traceback_skip,
        append_log_lines as _orchestrate_append_log_lines,
        log_indicates_install_failure as _orchestrate_log_indicates_install_failure,
        looks_like_shared_path as _orchestrate_looks_like_shared_path,
        set_active_app_query_param as _orchestrate_set_active_app_query_param,
        clear_cached_distribution as _orchestrate_clear_cached_distribution,
        clear_mount_table_cache as _orchestrate_clear_mount_table_cache,
        resolve_share_candidate as _orchestrate_resolve_share_candidate,
        benchmark_display_date as _orchestrate_benchmark_display_date,
        display_log as _orchestrate_display_log,
        safe_eval as _orchestrate_safe_eval,
        parse_and_validate_scheduler as _orchestrate_parse_and_validate_scheduler,
        parse_and_validate_workers as _orchestrate_parse_and_validate_workers,
        toggle_select_all as _orchestrate_toggle_select_all,
        update_select_all as _orchestrate_update_select_all,
        capture_dataframe_preview_state as _orchestrate_capture_dataframe_preview_state,
        restore_dataframe_preview_state as _orchestrate_restore_dataframe_preview_state,
        is_app_installed as _orchestrate_is_app_installed,
        LOG_DISPLAY_MAX_LINES,
        LIVE_LOG_MIN_HEIGHT,
        INSTALL_LOG_HEIGHT,
        _TRACEBACK_SKIP,
    )
except ModuleNotFoundError:
    _orchestrate_page_helpers_path = Path(__file__).resolve().parents[1] / "orchestrate_page_helpers.py"
    _orchestrate_page_helpers_spec = importlib.util.spec_from_file_location(
        "agilab_orchestrate_page_helpers_fallback",
        _orchestrate_page_helpers_path,
    )
    if _orchestrate_page_helpers_spec is None or _orchestrate_page_helpers_spec.loader is None:
        raise
    _orchestrate_page_helpers_module = importlib.util.module_from_spec(_orchestrate_page_helpers_spec)
    _orchestrate_page_helpers_spec.loader.exec_module(_orchestrate_page_helpers_module)
    _orchestrate_app_install_status = _orchestrate_page_helpers_module.app_install_status
    _orchestrate_init_session_state = _orchestrate_page_helpers_module.init_session_state
    _orchestrate_clear_log = _orchestrate_page_helpers_module.clear_log
    _orchestrate_rerun_fragment_or_app = _orchestrate_page_helpers_module.rerun_fragment_or_app
    _orchestrate_update_delete_confirm_state = _orchestrate_page_helpers_module.update_delete_confirm_state
    _orchestrate_update_log = _orchestrate_page_helpers_module.update_log
    _orchestrate_reset_traceback_skip = _orchestrate_page_helpers_module.reset_traceback_skip
    _orchestrate_append_log_lines = _orchestrate_page_helpers_module.append_log_lines
    _orchestrate_log_indicates_install_failure = _orchestrate_page_helpers_module.log_indicates_install_failure
    _orchestrate_looks_like_shared_path = _orchestrate_page_helpers_module.looks_like_shared_path
    _orchestrate_set_active_app_query_param = _orchestrate_page_helpers_module.set_active_app_query_param
    _orchestrate_clear_cached_distribution = _orchestrate_page_helpers_module.clear_cached_distribution
    _orchestrate_clear_mount_table_cache = _orchestrate_page_helpers_module.clear_mount_table_cache
    _orchestrate_resolve_share_candidate = _orchestrate_page_helpers_module.resolve_share_candidate
    _orchestrate_benchmark_display_date = _orchestrate_page_helpers_module.benchmark_display_date
    _orchestrate_display_log = _orchestrate_page_helpers_module.display_log
    _orchestrate_safe_eval = _orchestrate_page_helpers_module.safe_eval
    _orchestrate_parse_and_validate_scheduler = _orchestrate_page_helpers_module.parse_and_validate_scheduler
    _orchestrate_parse_and_validate_workers = _orchestrate_page_helpers_module.parse_and_validate_workers
    _orchestrate_toggle_select_all = _orchestrate_page_helpers_module.toggle_select_all
    _orchestrate_update_select_all = _orchestrate_page_helpers_module.update_select_all
    _orchestrate_capture_dataframe_preview_state = _orchestrate_page_helpers_module.capture_dataframe_preview_state
    _orchestrate_restore_dataframe_preview_state = _orchestrate_page_helpers_module.restore_dataframe_preview_state
    _orchestrate_is_app_installed = _orchestrate_page_helpers_module.is_app_installed
    LOG_DISPLAY_MAX_LINES = _orchestrate_page_helpers_module.LOG_DISPLAY_MAX_LINES
    LIVE_LOG_MIN_HEIGHT = _orchestrate_page_helpers_module.LIVE_LOG_MIN_HEIGHT
    INSTALL_LOG_HEIGHT = _orchestrate_page_helpers_module.INSTALL_LOG_HEIGHT
    _TRACEBACK_SKIP = _orchestrate_page_helpers_module._TRACEBACK_SKIP
try:
    from agilab.orchestrate_cluster import (
        OrchestrateClusterDeps,
        render_cluster_settings_ui,
    )
except ModuleNotFoundError:
    _orchestrate_cluster_path = Path(__file__).resolve().parents[1] / "orchestrate_cluster.py"
    _orchestrate_cluster_spec = importlib.util.spec_from_file_location(
        "agilab_orchestrate_cluster_fallback",
        _orchestrate_cluster_path,
    )
    if _orchestrate_cluster_spec is None or _orchestrate_cluster_spec.loader is None:
        raise
    _orchestrate_cluster_module = importlib.util.module_from_spec(_orchestrate_cluster_spec)
    _orchestrate_cluster_spec.loader.exec_module(_orchestrate_cluster_module)
    OrchestrateClusterDeps = _orchestrate_cluster_module.OrchestrateClusterDeps
    render_cluster_settings_ui = _orchestrate_cluster_module.render_cluster_settings_ui

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
    from agilab.orchestrate_services import (
        OrchestrateServiceDeps,
        render_service_panel,
    )
except ModuleNotFoundError:
    _orchestrate_services_path = Path(__file__).resolve().parents[1] / "orchestrate_services.py"
    _orchestrate_services_spec = importlib.util.spec_from_file_location(
        "agilab_orchestrate_services_fallback",
        _orchestrate_services_path,
    )
    if _orchestrate_services_spec is None or _orchestrate_services_spec.loader is None:
        raise
    _orchestrate_services_module = importlib.util.module_from_spec(_orchestrate_services_spec)
    _orchestrate_services_spec.loader.exec_module(_orchestrate_services_module)
    OrchestrateServiceDeps = _orchestrate_services_module.OrchestrateServiceDeps
    render_service_panel = _orchestrate_services_module.render_service_panel

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
        fstype_for_path as _fstype_for_path,
        macos_autofs_hint as _macos_autofs_hint,
        mount_table as _mount_table,
        parse_benchmark,
        sanitize_for_toml as _sanitize_for_toml,
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
    _fstype_for_path = _orchestrate_support_module.fstype_for_path
    _macos_autofs_hint = _orchestrate_support_module.macos_autofs_hint
    _mount_table = _orchestrate_support_module.mount_table
    parse_benchmark = _orchestrate_support_module.parse_benchmark
    _sanitize_for_toml = _orchestrate_support_module.sanitize_for_toml
    _write_app_settings_toml = _orchestrate_support_module.write_app_settings_toml
# Project Libraries:
from agi_env.pagelib import (
    background_services_enabled, get_about_content, render_logo, activate_mlflow, init_custom_ui, select_project,
    inject_theme, is_valid_ip, render_dataframe_preview, resolve_active_app
)

from agi_env import AgiEnv
from agi_env.ui_support import store_last_active_app

# ===========================
# Session State Initialization
# ===========================
def init_session_state(defaults: dict[str, Any]) -> None:
    """Initialize session state variables with default values if they are not already set."""
    _orchestrate_init_session_state(st.session_state, defaults)

# ===========================
# Utility and Helper Functions
# ===========================

def clear_log() -> None:
    """Clear the accumulated log in session state."""
    _orchestrate_clear_log(st.session_state)


def _rerun_fragment_or_app() -> None:
    """Prefer a fragment rerun when valid; otherwise fall back to a full app rerun."""
    _orchestrate_rerun_fragment_or_app(st.rerun, StreamlitAPIException)


def _update_delete_confirm_state(
    confirm_key: str,
    *,
    delete_armed_clicked: bool,
    delete_cancel_clicked: bool,
) -> bool:
    """Update the delete-confirm flag and report whether a local rerun is needed."""
    return _orchestrate_update_delete_confirm_state(
        st.session_state,
        confirm_key,
        delete_armed_clicked=delete_armed_clicked,
        delete_cancel_clicked=delete_cancel_clicked,
    )

def update_log(live_log_placeholder: Any, message: str, max_lines: int = 1000) -> None:
    _orchestrate_update_log(
        st.session_state,
        live_log_placeholder,
        message,
        max_lines=max_lines,
        cluster_verbose=st.session_state.get("cluster_verbose", 1),
        traceback_state=_TRACEBACK_SKIP,
        strip_ansi_fn=strip_ansi,
        is_dask_shutdown_noise_fn=is_dask_shutdown_noise,
        log_display_max_lines=LOG_DISPLAY_MAX_LINES,
        live_log_min_height=LIVE_LOG_MIN_HEIGHT,
        max_log_height=500,
    )
    update_log._skip_traceback = bool(_TRACEBACK_SKIP["active"])
    return None



def _reset_traceback_skip() -> None:
    _orchestrate_reset_traceback_skip(_TRACEBACK_SKIP)
    update_log._skip_traceback = False


def _append_log_lines(buffer: list[str], payload: str) -> None:
    """Delegate to support helper to keep log filtering behavior centralized."""
    _orchestrate_append_log_lines(
        buffer,
        payload,
        cluster_verbose=st.session_state.get("cluster_verbose", 1),
        traceback_state=_TRACEBACK_SKIP,
        is_dask_shutdown_noise_fn=is_dask_shutdown_noise,
    )


def _log_indicates_install_failure(lines: list[str]) -> bool:
    """Delegate to support helper for shared install-failure heuristics."""
    return _orchestrate_log_indicates_install_failure(lines)


def _looks_like_shared_path(path: Path) -> bool:
    project_root = Path(__file__).resolve().parents[2]
    return _orchestrate_looks_like_shared_path(path, project_root)


def _set_active_app_query_param(active_app: Any) -> None:
    """Best-effort update of the active-app query parameter during page transitions."""
    _orchestrate_set_active_app_query_param(st.query_params, active_app, streamlit_api_exception=StreamlitAPIException)


def _clear_cached_distribution() -> None:
    """Clear cached distribution data when the selected project changes."""
    _orchestrate_clear_cached_distribution(load_distribution)


def _clear_mount_table_cache() -> None:
    """Clear the mount-table cache when cluster settings are active."""
    _orchestrate_clear_mount_table_cache(_mount_table)


def _resolve_share_candidate(path_value: Any, home_abs: Path | str) -> Path:
    """Resolve the configured share path without failing on broken targets."""
    return _orchestrate_resolve_share_candidate(path_value, home_abs, path_type=Path)


def _benchmark_display_date(benchmark_path: Path, date_value: str) -> str:
    """Return the benchmark date string, using file mtime as a fallback."""
    return _orchestrate_benchmark_display_date(
        benchmark_path,
        date_value,
        os_module=os,
        datetime_type=datetime,
    )


def display_log(stdout, stderr):
    _orchestrate_display_log(
        stdout,
        stderr,
        session_state=st.session_state,
        strip_ansi_fn=strip_ansi,
        filter_warning_messages_fn=lambda text: filter_warning_messages(filter_noise_lines(text)),
        format_log_block_fn=lambda text: format_log_block(
            text,
            newest_first=False,
            max_lines=LOG_DISPLAY_MAX_LINES,
        ),
        warning_fn=lambda message: st.warning(message),
        error_fn=lambda message: st.error(message),
        code_fn=lambda *args, **kwargs: st.code(*args, **kwargs),
        log_display_height=400,
    )

update_log._skip_traceback = False


def safe_eval(expression: str, expected_type: Any, error_message: str) -> Any:
    return _orchestrate_safe_eval(expression, expected_type, error_message, on_error=st.error)


def parse_and_validate_scheduler(scheduler: str) -> Optional[str]:
    return _orchestrate_parse_and_validate_scheduler(
        scheduler,
        is_valid_ip=is_valid_ip,
        on_error=st.error,
    )


def parse_and_validate_workers(workers_input: str) -> dict[str, int]:
    return _orchestrate_parse_and_validate_workers(
        workers_input,
        is_valid_ip=is_valid_ip,
        on_error=st.error,
        default_workers={"127.0.0.1": 1},
    )

def initialize_app_settings(args_override: dict[str, Any] | None = None) -> None:
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
        except (ImportError, AttributeError, OSError, RuntimeError, TypeError, ValueError, tomllib.TOMLDecodeError) as exc:
            st.warning(f"Unable to load Flight args: {exc}")
            app_settings.setdefault("args", {})
    else:
        app_settings.setdefault("args", {})

    cluster_settings = app_settings.setdefault("cluster", {})
    if args_override is not None:
        app_settings["args"] = args_override
    st.session_state.app_settings = app_settings
    st.session_state["args_project"] = env.app

# ===========================
# Caching Functions for Performance
# ===========================
@st.cache_data(ttl=300, show_spinner=False)
def load_toml_file(file_path: str | Path) -> dict[str, Any]:
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
def load_distribution(file_path: str | Path) -> tuple[list[str], list[Any], list[Any]]:
    with open(file_path, "r") as f:
        data = json.load(f)
    workers = [f"{ip}-{i}" for ip, count in data.get("workers", {}).items() for i in range(1, count + 1)]
    return workers, data.get("work_plan_metadata", []), data.get("work_plan", [])

@st.cache_data(show_spinner=False)
def generate_profile_report(df: pd.DataFrame) -> Any:
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
def render_generic_ui() -> None:
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

def toggle_select_all():
    _orchestrate_toggle_select_all(st.session_state)

def update_select_all():
    _orchestrate_update_select_all(st.session_state)


def _capture_dataframe_preview_state() -> dict:
    """Capture dataframe preview-related session state for one-step undo."""
    return _orchestrate_capture_dataframe_preview_state(st.session_state)


def _restore_dataframe_preview_state(payload: dict) -> None:
    """Restore dataframe preview session state from an undo payload."""
    _orchestrate_restore_dataframe_preview_state(st.session_state, payload)

def _is_app_installed(env: Any) -> bool:
    return _orchestrate_is_app_installed(env)


def _app_install_status(env: Any) -> dict[str, Any]:
    return _orchestrate_app_install_status(env)

# ===========================
# Main Application UI
# ===========================
async def page() -> None:
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
    render_page_docs_access(
        env,
        html_file="execute-help.html",
        key_prefix="orchestrate",
        sidebar=True,
        caption="Open the ORCHESTRATE guide.",
    )

    if background_services_enabled() and not st.session_state.get("server_started"):
        activate_mlflow(env)

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
        _set_active_app_query_param(env.app)
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
        _clear_cached_distribution()
        initialize_app_settings(args_override=args_override)
        st.rerun()

    module = env.target
    project_path = env.active_app
    app_state_name = Path(str(env.app)).name if env.app else ""
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
    install_status = _app_install_status(env)

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
        if install_status["manager_ready"] and not install_status["worker_ready"]:
            st.warning(
                "Manager environment detected, but the worker environment is missing. "
                f"Run INSTALL to rebuild the worker venv at `{install_status['worker_venv']}` "
                f"before using RUN for `{env.app}`."
            )
        elif install_status["worker_ready"] and not install_status["manager_ready"]:
            st.warning(
                "Worker environment detected, but the manager environment is missing. "
                f"Run INSTALL to rebuild the app venv at `{install_status['manager_venv']}` "
                f"before using RUN for `{env.app}`."
            )
        cluster_deps = OrchestrateClusterDeps(
            parse_and_validate_scheduler=parse_and_validate_scheduler,
            parse_and_validate_workers=parse_and_validate_workers,
            write_app_settings_toml=_write_app_settings_toml,
            clear_load_toml_cache=load_toml_file.clear,
            set_env_var=AgiEnv.set_env_var,
            agi_env_envars=getattr(AgiEnv, "envars", None),
        )
        render_cluster_settings_ui(env, cluster_deps)
        cluster_params = st.session_state.app_settings["cluster"]
        verbose = cluster_params.get('verbose', 1)

        if show_install:
            enabled = cluster_params.get("cluster_enabled", False)
            raw_scheduler = cluster_params.get("scheduler", "")
            scheduler = optional_string_expr(enabled, raw_scheduler)
            raw_workers = cluster_params.get("workers", "")
            workers = optional_python_expr(enabled, raw_workers)
            raw_workers_data_path = cluster_params.get("workers_data_path", "")
            workers_data_path = optional_string_expr(enabled, raw_workers_data_path)
            cmd = build_install_snippet(
                env=env,
                verbose=verbose,
                mode=st.session_state.mode,
                scheduler=scheduler,
                workers=workers,
                workers_data_path=workers_data_path,
            )
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
                _clear_mount_table_cache()
                share_candidate = Path(env.agi_share_path)
                if not share_candidate.is_absolute():
                    share_candidate = Path(env.home_abs) / share_candidate
                share_candidate = share_candidate.expanduser()
                is_symlink = share_candidate.is_symlink()
                share_resolved = _resolve_share_candidate(env.agi_share_path, env.home_abs)
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

            args_serialized = serialize_args_payload(st.session_state.app_settings["args"])
            st.session_state["args_serialized"] = args_serialized
            if st.session_state.get("args_reload_required"):
                del st.session_state["app_settings"]
                st.rerun()
        with st.expander("Check orchestration", expanded=False):
            cluster_params = st.session_state.app_settings["cluster"]
            enabled = cluster_params.get("cluster_enabled", False)
            scheduler = cluster_params.get("scheduler", "")
            scheduler = optional_string_expr(enabled, scheduler)
            workers = cluster_params.get("workers", {})
            workers = optional_python_expr(enabled, workers)
            cmd = build_distribution_snippet(
                env=env,
                verbose=verbose,
                scheduler=scheduler,
                workers=workers,
                args_serialized=st.session_state.args_serialized,
            )
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
                                    key = workplan_selection_key(partition, i, j)
                                    b2.selectbox("Worker", options=workers, key=key, index=i if i < len(workers) else 0)
                                count += 1
                        if st.button("Apply", key="apply_btn", type="primary"):
                            new_work_plan_metadata, new_work_plan = reassign_distribution_plan(
                                workers=workers,
                                work_plan_metadata=work_plan_metadata,
                                work_plan=work_plan,
                                selections=st.session_state,
                            )
                            # Read & update the original JSON dict (avoid writing to the workers list)
                            with open(dist_tree_path, "r") as f:
                                data = json.load(f)
                            data = update_distribution_payload(
                                data,
                                target_args=st.session_state.app_settings["args"],
                                work_plan_metadata=new_work_plan_metadata,
                                work_plan=new_work_plan,
                            )
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
        scheduler = optional_string_expr(enabled, cluster_params.get("scheduler"))
        workers = optional_python_expr(enabled, cluster_params.get("workers"))

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

                if benchmark_enabled:
                    run_mode = None
                else:
                    run_mode = compute_run_mode(cluster_params, cluster_enabled)

                info_label = describe_run_mode(run_mode, benchmark_enabled)

                st.session_state["mode"] = run_mode
                st.info(info_label)

                verbose = cluster_params.get("verbose", 1)
                enabled = cluster_enabled
                scheduler = optional_string_expr(enabled, cluster_params.get("scheduler"))
                workers = optional_python_expr(enabled, cluster_params.get("workers"))
                cmd = build_run_snippet(
                    env=env,
                    verbose=verbose,
                    run_mode=run_mode,
                    scheduler=scheduler,
                    workers=workers,
                    args_serialized=st.session_state.args_serialized,
                )
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
                                date_value = _benchmark_display_date(env.benchmark, date_value)

                                if date_value:
                                    st.caption(f"Benchmark date: {date_value}")

                                render_dataframe_preview(
                                    df_nonempty,
                                    truncation_label="Benchmark table preview limited",
                                )
                            else:
                                st.info("Benchmark file is present but empty. Run the benchmark to collect data.")
                        else:
                            st.info("No benchmark results yet. Enable 'Benchmark all modes' and run EXECUTE to gather data.")
                    except json.JSONDecodeError as e:
                        st.warning(f"Error decoding JSON: {e}")

        if show_submit_panel:
            service_deps = OrchestrateServiceDeps(
                reset_traceback_skip=_reset_traceback_skip,
                append_log_lines=_append_log_lines,
                extract_result_dict_from_output=_extract_result_dict_from_output,
                evaluate_service_health_gate=_evaluate_service_health_gate,
                coerce_bool_setting=_coerce_bool_setting,
                coerce_int_setting=_coerce_int_setting,
                coerce_float_setting=_coerce_float_setting,
                write_app_settings_toml=_write_app_settings_toml,
                clear_load_toml_cache=load_toml_file.clear,
                log_display_max_lines=LOG_DISPLAY_MAX_LINES,
                install_log_height=INSTALL_LOG_HEIGHT,
            )
            await render_service_panel(
                env=env,
                project_path=project_path,
                cluster_params=cluster_params,
                verbose=verbose,
                scheduler=scheduler,
                workers=workers,
                deps=service_deps,
            )

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
