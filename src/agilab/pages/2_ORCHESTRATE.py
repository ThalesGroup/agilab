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
import html
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
_import_guard_path = Path(__file__).resolve().parents[1] / "import_guard.py"
_import_guard_spec = importlib.util.spec_from_file_location("agilab_import_guard_local", _import_guard_path)
if _import_guard_spec is None or _import_guard_spec.loader is None:
    raise ModuleNotFoundError(f"Unable to load import_guard.py from {_import_guard_path}")
_import_guard_module = importlib.util.module_from_spec(_import_guard_spec)
_import_guard_spec.loader.exec_module(_import_guard_module)
import_agilab_symbols = _import_guard_module.import_agilab_symbols
import_agilab_module = _import_guard_module.import_agilab_module

_page_docs_module = import_agilab_module(
    "agilab.page_docs",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "page_docs.py",
    fallback_name="agilab_page_docs_fallback",
)
get_docs_menu_items = _page_docs_module.get_docs_menu_items

import_agilab_symbols(
    globals(),
    "agilab.orchestrate_page_support",
    {
        "build_distribution_snippet": "build_distribution_snippet",
        "build_install_snippet": "build_install_snippet",
        "build_run_snippet": "build_run_snippet",
        "available_benchmark_modes": "available_benchmark_modes",
        "BENCHMARK_MODE_LEGEND_MARKDOWN": "BENCHMARK_MODE_LEGEND_MARKDOWN",
        "benchmark_dataframe_column_config": "benchmark_dataframe_column_config",
        "benchmark_mode_label": "benchmark_mode_label",
        "benchmark_rows_with_delta_percent": "benchmark_rows_with_delta_percent",
        "benchmark_workers_data_path_issue": "benchmark_workers_data_path_issue",
        "compute_run_mode": "compute_run_mode",
        "describe_run_mode": "describe_run_mode",
        "merge_app_settings_sources": "merge_app_settings_sources",
        "optional_python_expr": "optional_python_expr",
        "optional_string_expr": "optional_string_expr",
        "order_benchmark_display_columns": "order_benchmark_display_columns",
        "resolve_requested_run_mode": "resolve_requested_run_mode",
        "resolve_project_change_args_override": "resolve_project_change_args_override",
        "sanitize_benchmark_modes": "sanitize_benchmark_modes",
        "filter_noise_lines": "filter_noise_lines",
        "filter_warning_messages": "filter_warning_messages",
        "format_log_block": "format_log_block",
        "has_nonlocal_workers": "has_nonlocal_workers",
        "reassign_distribution_plan": "reassign_distribution_plan",
        "is_dask_shutdown_noise": "is_dask_shutdown_noise",
        "serialize_args_payload": "serialize_args_payload",
        "strip_ansi": "strip_ansi",
        "update_distribution_payload": "update_distribution_payload",
        "workplan_selection_key": "workplan_selection_key",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "orchestrate_page_support.py",
    fallback_name="agilab_orchestrate_page_support_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.orchestrate_page_state",
    {
        "OrchestratePageStateDeps": "OrchestratePageStateDeps",
        "build_orchestrate_distribution_workflow_state": "build_orchestrate_distribution_workflow_state",
        "build_orchestrate_install_workflow_state": "build_orchestrate_install_workflow_state",
        "build_orchestrate_page_state": "build_orchestrate_page_state",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "orchestrate_page_state.py",
    fallback_name="agilab_orchestrate_page_state_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.page_bootstrap",
    {
        "ensure_page_env": "_ensure_page_env",
        "realign_session_env_with_page_root": "_realign_session_env_with_page_root",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "page_bootstrap.py",
    fallback_name="agilab_page_bootstrap_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.pinned_expander",
    {
        "render_pinned_expanders": "render_pinned_expanders",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "pinned_expander.py",
    fallback_name="agilab_pinned_expander_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.workflow_ui",
    {
        "is_dag_worker_base": "is_dag_worker_base",
        "render_page_context": "render_page_context",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "workflow_ui.py",
    fallback_name="agilab_workflow_ui_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.about_page.layout",
    {
        "active_app_cluster_information_lines": "active_app_cluster_information_lines",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "about_page" / "layout.py",
    fallback_name="agilab_about_page_layout_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.page_project_selector",
    {
        "render_project_selector": "render_project_selector",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "page_project_selector.py",
    fallback_name="agilab_page_project_selector_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.runtime_diagnostics",
    {
        "global_diagnostics_verbose": "global_diagnostics_verbose",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "runtime_diagnostics.py",
    fallback_name="agilab_runtime_diagnostics_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.action_execution",
    {
        "ActionResult": "ActionResult",
        "ActionSpec": "ActionSpec",
        "render_action_result": "render_action_result",
        "run_streamlit_action": "run_streamlit_action",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "action_execution.py",
    fallback_name="agilab_action_execution_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.orchestrate_page_helpers",
    {
        "app_install_status": "_orchestrate_app_install_status",
        "init_session_state": "_orchestrate_init_session_state",
        "clear_log": "_orchestrate_clear_log",
        "rerun_fragment_or_app": "_orchestrate_rerun_fragment_or_app",
        "update_delete_confirm_state": "_orchestrate_update_delete_confirm_state",
        "update_log": "_orchestrate_update_log",
        "reset_traceback_skip": "_orchestrate_reset_traceback_skip",
        "append_log_lines": "_orchestrate_append_log_lines",
        "log_indicates_install_failure": "_orchestrate_log_indicates_install_failure",
        "looks_like_shared_path": "_orchestrate_looks_like_shared_path",
        "set_active_app_query_param": "_orchestrate_set_active_app_query_param",
        "clear_cached_distribution": "_orchestrate_clear_cached_distribution",
        "clear_mount_table_cache": "_orchestrate_clear_mount_table_cache",
        "resolve_share_candidate": "_orchestrate_resolve_share_candidate",
        "configured_cluster_share_matches": "_configured_cluster_share_matches",
        "benchmark_display_date": "_orchestrate_benchmark_display_date",
        "display_log": "_orchestrate_display_log",
        "safe_eval": "_orchestrate_safe_eval",
        "parse_and_validate_scheduler": "_orchestrate_parse_and_validate_scheduler",
        "parse_and_validate_workers": "_orchestrate_parse_and_validate_workers",
        "toggle_select_all": "_orchestrate_toggle_select_all",
        "update_select_all": "_orchestrate_update_select_all",
        "capture_dataframe_preview_state": "_orchestrate_capture_dataframe_preview_state",
        "restore_dataframe_preview_state": "_orchestrate_restore_dataframe_preview_state",
        "is_app_installed": "_orchestrate_is_app_installed",
        "LOG_DISPLAY_MAX_LINES": "LOG_DISPLAY_MAX_LINES",
        "LIVE_LOG_MIN_HEIGHT": "LIVE_LOG_MIN_HEIGHT",
        "INSTALL_LOG_HEIGHT": "INSTALL_LOG_HEIGHT",
        "_TRACEBACK_SKIP": "_TRACEBACK_SKIP",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "orchestrate_page_helpers.py",
    fallback_name="agilab_orchestrate_page_helpers_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.orchestrate_cluster",
    {
        "OrchestrateClusterDeps": "OrchestrateClusterDeps",
        "clear_cluster_widget_state": "clear_cluster_widget_state",
        "hydrate_cluster_widget_state": "hydrate_cluster_widget_state",
        "render_cluster_settings_ui": "render_cluster_settings_ui",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "orchestrate_cluster.py",
    fallback_name="agilab_orchestrate_cluster_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.orchestrate_distribution",
    {
        "show_graph": "show_graph",
        "show_tree": "show_tree",
        "workload_barchart": "workload_barchart",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "orchestrate_distribution.py",
    fallback_name="agilab_orchestrate_distribution_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.orchestrate_services",
    {
        "OrchestrateServiceDeps": "OrchestrateServiceDeps",
        "render_service_panel": "render_service_panel",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "orchestrate_services.py",
    fallback_name="agilab_orchestrate_services_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.orchestrate_execute",
    {
        "OrchestrateExecuteDeps": "OrchestrateExecuteDeps",
        "render_execute_section": "render_execute_section",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "orchestrate_execute.py",
    fallback_name="agilab_orchestrate_execute_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.orchestrate_pending_actions",
    {
        "consume_pending_install_action": "consume_pending_install_action",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "orchestrate_pending_actions.py",
    fallback_name="agilab_orchestrate_pending_actions_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.orchestrate_support",
    {
        "coerce_bool_setting": "_coerce_bool_setting",
        "coerce_float_setting": "_coerce_float_setting",
        "coerce_int_setting": "_coerce_int_setting",
        "evaluate_service_health_gate": "_evaluate_service_health_gate",
        "extract_result_dict_from_output": "_extract_result_dict_from_output",
        "fstype_for_path": "_fstype_for_path",
        "macos_autofs_hint": "_macos_autofs_hint",
        "mount_table": "_mount_table",
        "parse_benchmark": "parse_benchmark",
        "sanitize_for_toml": "_sanitize_for_toml",
        "write_app_settings_toml": "_write_app_settings_toml",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "orchestrate_support.py",
    fallback_name="agilab_orchestrate_support_fallback",
)
# Project Libraries:
from agi_gui.pagelib import (
    background_services_enabled, render_logo, activate_mlflow, init_custom_ui, on_project_change,
    inject_theme, is_valid_ip, render_dataframe_preview, resolve_active_app
)

from agi_env import AgiEnv
from agi_gui.ui_support import store_last_active_app
from agi_gui.ux_widgets import compact_choice

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


def _clean_share_path_text(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    return text


def _env_cluster_share_value(env: Any) -> Any:
    cluster_share_path = getattr(env, "AGI_CLUSTER_SHARE", None)
    env_vars = getattr(env, "envars", None)
    if not cluster_share_path and isinstance(env_vars, dict):
        cluster_share_path = env_vars.get("AGI_CLUSTER_SHARE")
    return cluster_share_path


def _has_configured_cluster_share(env: Any) -> bool:
    text = _clean_share_path_text(_env_cluster_share_value(env))
    if text.lower() in {"", "none", "local", "localshare"}:
        return False
    try:
        candidate = _resolve_share_candidate(text, getattr(env, "home_abs", Path.home()))
    except (OSError, RuntimeError, TypeError, ValueError):
        return True
    return not _path_points_to_local_share(candidate, env)


def _env_local_share_paths(env: Any) -> tuple[Path, ...]:
    raw_values: list[Any] = []
    home_abs = getattr(env, "home_abs", Path.home())
    cluster_share_paths: list[Path] = []
    cluster_share_text = _clean_share_path_text(_env_cluster_share_value(env))
    if cluster_share_text.lower() not in {"", "none", "local", "localshare"}:
        try:
            cluster_share_paths.append(_resolve_share_candidate(cluster_share_text, home_abs))
        except (OSError, RuntimeError, TypeError, ValueError):
            pass

    local_share = getattr(env, "AGI_LOCAL_SHARE", None)
    env_vars = getattr(env, "envars", None)
    if local_share:
        raw_values.append(local_share)
    if isinstance(env_vars, dict) and env_vars.get("AGI_LOCAL_SHARE"):
        raw_values.append(env_vars.get("AGI_LOCAL_SHARE"))
    agi_share_path = getattr(env, "agi_share_path", None)
    if agi_share_path:
        try:
            agi_share_candidate = _resolve_share_candidate(agi_share_path, home_abs)
        except (OSError, RuntimeError, TypeError, ValueError):
            raw_values.append(agi_share_path)
        else:
            # In cluster mode AgiEnv.agi_share_path can already be the active
            # scheduler-side AGI_CLUSTER_SHARE. That path is allowed to be a
            # normal local filesystem because workers mount it via SSHFS.
            if agi_share_candidate not in cluster_share_paths:
                raw_values.append(agi_share_path)

    paths: list[Path] = []
    for raw_value in raw_values:
        text = _clean_share_path_text(raw_value)
        if not text:
            continue
        try:
            paths.append(_resolve_share_candidate(text, home_abs))
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
    return tuple(paths)


def _path_is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _path_points_to_local_share(path: Path, env: Any) -> bool:
    for local_share in _env_local_share_paths(env):
        if path == local_share or _path_is_under(path, local_share):
            return True
    return False


def _cluster_args_share_root(env: Any, cluster_params: dict[str, Any]) -> Path | None:
    if not bool(cluster_params.get("cluster_enabled", False)):
        return None
    candidate_values = (
        cluster_params.get("workers_data_path"),
        _env_cluster_share_value(env),
    )
    for raw_value in candidate_values:
        text = _clean_share_path_text(raw_value)
        if text.lower() in {"", "none", "local", "localshare"}:
            continue
        try:
            candidate = _resolve_share_candidate(text, getattr(env, "home_abs", Path.home()))
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        if _path_points_to_local_share(candidate, env):
            continue
        return candidate
    return None


class _ShareRootOverrideEnv:
    def __init__(self, env: Any, share_root: Path) -> None:
        object.__setattr__(self, "_env", env)
        object.__setattr__(self, "_share_root", Path(share_root).expanduser())

    def __getattr__(self, name: str) -> Any:
        return getattr(self._env, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_env", "_share_root"}:
            object.__setattr__(self, name, value)
            return
        setattr(self._env, name, value)

    @property
    def agi_share_path(self) -> Path:
        return self._share_root

    @property
    def agi_share_path_abs(self) -> Path:
        return self._share_root

    @property
    def AGI_CLUSTER_SHARE(self) -> str:
        return str(self._share_root)

    @property
    def envars(self) -> dict[str, Any]:
        env_vars = getattr(self._env, "envars", None)
        payload = dict(env_vars) if isinstance(env_vars, dict) else {}
        payload["AGI_CLUSTER_SHARE"] = str(self._share_root)
        return payload

    def share_root_path(self) -> Path:
        return self._share_root

    def resolve_share_path(self, path: Any = None) -> Path:
        if path in (None, ""):
            return self._share_root
        candidate = Path(str(path)).expanduser()
        if candidate.is_absolute():
            return candidate.resolve(strict=False)
        return (self._share_root / candidate).resolve(strict=False)


def _app_args_env_for_cluster(env: Any, cluster_params: dict[str, Any]) -> Any:
    share_root = _cluster_args_share_root(env, cluster_params)
    if share_root is None:
        return env
    return _ShareRootOverrideEnv(env, share_root)


def _with_app_args_env(args_env: Any):
    class _SessionEnvContext:
        _missing = object()

        def __enter__(self):
            self._previous_env = st.session_state.get("env", self._missing)
            self._previous_private_env = st.session_state.get("_env", self._missing)
            st.session_state["env"] = args_env
            st.session_state["_env"] = args_env
            return args_env

        def __exit__(self, exc_type, exc, tb):
            if self._previous_env is self._missing:
                st.session_state.pop("env", None)
            else:
                st.session_state["env"] = self._previous_env
            if self._previous_private_env is self._missing:
                st.session_state.pop("_env", None)
            else:
                st.session_state["_env"] = self._previous_private_env
            return False

    return _SessionEnvContext()


def _cluster_args_share_warning(env: Any, cluster_params: dict[str, Any]) -> str | None:
    if not bool(cluster_params.get("cluster_enabled", False)):
        return None
    if not has_nonlocal_workers(cluster_params.get("workers")):
        return None
    active_share_root = _cluster_args_share_root(env, cluster_params)
    share_source = active_share_root if active_share_root is not None else getattr(env, "agi_share_path", None)
    if share_source is None:
        return None
    try:
        share_candidate = Path(share_source)
        if not share_candidate.is_absolute():
            share_candidate = Path(getattr(env, "home_abs", Path.home())) / share_candidate
        share_candidate = share_candidate.expanduser()
        share_resolved = _resolve_share_candidate(share_candidate, getattr(env, "home_abs", Path.home()))
    except (OSError, RuntimeError, TypeError, ValueError):
        return None

    is_symlink = share_candidate.is_symlink()
    looks_shared = _looks_like_shared_path(share_candidate) or _looks_like_shared_path(share_resolved)
    workers_data_path = _clean_share_path_text(cluster_params.get("workers_data_path"))
    has_worker_share_path = workers_data_path.lower() not in {"", "none", "local", "localshare"}
    try:
        worker_path = _resolve_share_candidate(workers_data_path, getattr(env, "home_abs", Path.home()))
        has_worker_share_path = has_worker_share_path and not _path_points_to_local_share(worker_path, env)
    except (OSError, RuntimeError, TypeError, ValueError):
        pass
    # SSHFS cluster-share contract: the scheduler-side AGI_CLUSTER_SHARE can be a
    # normal local filesystem; remote workers mount it at Workers Data Path.
    if is_symlink or looks_shared or (
        has_worker_share_path
        and _has_configured_cluster_share(env)
        and has_nonlocal_workers(cluster_params.get("workers"))
    ):
        return None

    fstype = _fstype_for_path(share_resolved) or _fstype_for_path(share_candidate) or "unknown"
    hint = _macos_autofs_hint(share_candidate)
    extra = f"\n\n{hint}" if hint else ""
    return (
        f"Cluster is enabled but the data directory `{share_resolved}` appears local. "
        f"(detected fstype: `{fstype}`) "
        "Set `AGI_CLUSTER_SHARE` to the scheduler-side source path and `Workers Data Path` "
        "to the worker-side SSHFS/shared mount target, or point `AGI_CLUSTER_SHARE` "
        "at a shared mount/symlink when not using the SSHFS cluster-share contract."
        f"{extra}"
    )


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
    app_settings = merge_app_settings_sources(file_settings, session_settings)

    if env.app == "flight_telemetry_project":
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
    app_state_name = Path(str(env.app)).name if env.app else ""
    hydrate_cluster_widget_state(
        st.session_state,
        app_state_name,
        cluster_settings,
        is_managed_pc=bool(getattr(env, "is_managed_pc", False)),
    )
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


def _apply_distribution_plan_action(
    *,
    dist_tree_path: Path,
    workers: list[str],
    work_plan_metadata: list[Any],
    work_plan: list[Any],
    selections: Any,
    target_args: dict[str, Any],
) -> ActionResult:
    try:
        new_work_plan_metadata, new_work_plan = reassign_distribution_plan(
            workers=workers,
            work_plan_metadata=work_plan_metadata,
            work_plan=work_plan,
            selections=selections,
        )
    except (RuntimeError, TypeError, ValueError, KeyError) as exc:
        return ActionResult.error(
            "Distribution plan could not be reassigned.",
            detail=str(exc),
            next_action="Refresh the distribution preview, then retry the assignment.",
            data={"dist_tree_path": dist_tree_path},
        )

    try:
        raw_payload = dist_tree_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ActionResult.error(
            "Distribution plan file does not exist.",
            next_action="Run CHECK distribute to regenerate the distribution plan file.",
            data={"dist_tree_path": dist_tree_path},
        )
    except OSError as exc:
        return ActionResult.error(
            "Distribution plan file could not be read.",
            detail=str(exc),
            next_action="Check filesystem permissions, then rerun CHECK distribute.",
            data={"dist_tree_path": dist_tree_path},
        )

    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        return ActionResult.error(
            "Distribution plan file is not valid JSON.",
            detail=str(exc),
            next_action="Run CHECK distribute to regenerate the distribution plan file.",
            data={"dist_tree_path": dist_tree_path},
        )

    try:
        updated_payload = update_distribution_payload(
            payload,
            target_args=target_args,
            work_plan_metadata=new_work_plan_metadata,
            work_plan=new_work_plan,
        )
        dist_tree_path.write_text(json.dumps(updated_payload), encoding="utf-8")
    except (OSError, RuntimeError, TypeError, ValueError, KeyError) as exc:
        return ActionResult.error(
            "Distribution plan could not be saved.",
            detail=str(exc),
            next_action="Check target args and filesystem permissions, then retry.",
            data={"dist_tree_path": dist_tree_path},
        )

    return ActionResult.success(
        "Distribution plan updated.",
        next_action="Run EXECUTE to use the updated workplan.",
        data={
            "dist_tree_path": dist_tree_path,
            "work_plan_metadata": new_work_plan_metadata,
            "work_plan": new_work_plan,
        },
    )


async def _check_distribution_action(
    env: Any,
    *,
    cmd: str,
    project_path: Path,
) -> ActionResult:
    dist_log: list[str] = []
    # Distribution snippets import agi_cluster and orchestrate worker-side probes.
    # Prefer the controller runtime when it is known, even if source-env inference is absent.
    runtime_root = Path(getattr(env, "agi_cluster", None) or project_path)
    command = cmd.replace("asyncio.run(main())", env.snippet_tail)

    try:
        stdout, stderr = await env.run_agi(
            command,
            log_callback=lambda message: _append_log_lines(dist_log, message),
            venv=runtime_root,
        )
    except (RuntimeError, OSError, TypeError, ValueError, AttributeError, KeyError) as exc:
        _append_log_lines(dist_log, f"ERROR: {exc}")
        return ActionResult.error(
            "Distribution build failed.",
            detail=str(exc),
            next_action="Check orchestration settings and logs, then retry CHECK distribute.",
            data={
                "command": command,
                "dist_log": tuple(dist_log),
                "runtime_root": runtime_root,
            },
        )

    if stderr:
        _append_log_lines(dist_log, stderr)
    if stdout:
        _append_log_lines(dist_log, stdout)

    data = {
        "command": command,
        "dist_log": tuple(dist_log),
        "runtime_root": runtime_root,
        "stdout": stdout,
        "stderr": stderr,
    }
    return ActionResult.success(
        "Distribution built successfully.",
        data=data,
    )


async def _install_worker_action(
    env: Any,
    *,
    install_command: str,
    venv: Any,
    local_log: list[str],
) -> ActionResult:
    install_stdout = ""
    install_stderr = ""
    install_error: Exception | None = None
    try:
        install_stdout, install_stderr = await env.run_agi(
            install_command,
            log_callback=lambda message: _append_log_lines(local_log, message),
            venv=None,
        )
    except (RuntimeError, OSError, TypeError, ValueError, AttributeError, KeyError) as exc:
        install_error = exc
        install_stderr = str(exc)
        _append_log_lines(local_log, f"ERROR: {install_stderr}")

    if install_stderr and install_error is None:
        _append_log_lines(local_log, install_stderr)
    if install_stdout:
        _append_log_lines(local_log, install_stdout)

    error_flag = install_error is not None
    if not error_flag and _log_indicates_install_failure(local_log):
        error_flag = True
        if not str(install_stderr or "").strip():
            install_stderr = "Detected install failure in logs."

    status_line = (
        "✅ Install complete."
        if not error_flag
        else "❌ Install finished with errors. Check logs above."
    )
    _append_log_lines(local_log, status_line)
    data = {
        "install_command": install_command,
        "install_log": tuple(local_log),
        "stdout": install_stdout,
        "stderr": install_stderr,
        "venv": venv,
    }
    if error_flag:
        return ActionResult.error(
            "Cluster installation failed.",
            detail=str(install_stderr or install_error or "Install logs indicate failure."),
            next_action="Check install logs above, fix the worker environment, then rerun INSTALL.",
            data=data,
        )
    return ActionResult.success(
        "Cluster installation completed.",
        data=data,
    )


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
        if env.app == "flight_telemetry_project":
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


def _coerce_worker_slots(value: Any) -> int | None:
    try:
        slots = int(value)
    except (TypeError, ValueError):
        return None
    return slots if slots > 0 else None


def _workers_summary(workers: Any) -> str:
    if isinstance(workers, dict):
        if not workers:
            return "no workers configured"
        slot_values = [_coerce_worker_slots(value) for value in workers.values()]
        known_slots = [value for value in slot_values if value is not None]
        node_count = len(workers)
        if len(known_slots) == node_count:
            total_slots = sum(known_slots)
            node_suffix = "s" if node_count != 1 else ""
            slot_suffix = "s" if total_slots != 1 else ""
            return f"{node_count} node{node_suffix}, {total_slots} worker slot{slot_suffix}"
        return f"{node_count} node{'s' if node_count != 1 else ''}, worker slots incomplete"

    text = str(workers or "").strip()
    if text in {"", "{}", "None", "none"}:
        return "no workers configured"
    return "custom workers configured"


def _is_local_worker_host(host: Any) -> bool:
    text = str(host or "").strip().lower()
    if not text:
        return False
    if text.startswith("tcp://"):
        text = text.split("://", 1)[1]
    if "@" in text:
        text = text.rsplit("@", 1)[-1]
    if text.startswith("[") and "]" in text:
        text = text[1:text.index("]")]
    elif text.count(":") == 1:
        text = text.rsplit(":", 1)[0]
    return text in {"localhost", "127.0.0.1", "::1", socket.gethostname().lower()}


def _cluster_mode_label(cluster_params: dict[str, Any]) -> str:
    if not bool(cluster_params.get("cluster_enabled", False)):
        return "Local"

    workers = cluster_params.get("workers", {})
    worker_hosts = tuple(workers) if isinstance(workers, dict) else ()
    nonlocal_workers = [host for host in worker_hosts if not _is_local_worker_host(host)]
    return "LAN cluster" if nonlocal_workers else "Local Dask demo"


def _runtime_status_label(install_status: dict[str, Any]) -> tuple[str, str]:
    manager_ready = bool(install_status.get("manager_ready"))
    worker_ready = bool(install_status.get("worker_ready"))
    if manager_ready and worker_ready:
        return "Ready", "Manager and worker environments can import AGILAB runtime packages."
    if manager_ready:
        if not install_status.get("worker_exists"):
            return "Needs INSTALL", "Worker environment has not been created yet. Run INSTALL before RUN."
        return "Needs INSTALL", install_status.get("worker_problem") or "Worker environment is missing or stale."
    if worker_ready:
        if not install_status.get("manager_exists"):
            return "Needs INSTALL", "Manager environment has not been created yet. Run INSTALL before RUN."
        return "Needs INSTALL", install_status.get("manager_problem") or "Manager environment is missing or stale."
    return "Needs INSTALL", "Manager and worker environments are not installed yet."


def _install_status_warning_message(install_status: dict[str, Any]) -> str | None:
    """Return a warning only for existing-but-stale install environments."""
    stale_problems = []
    if install_status.get("manager_exists") and not install_status.get("manager_ready"):
        stale_problems.append(str(install_status.get("manager_problem") or "manager environment is stale"))
    if install_status.get("worker_exists") and not install_status.get("worker_ready"):
        stale_problems.append(str(install_status.get("worker_problem") or "worker environment is stale"))
    if not stale_problems:
        return None
    return (
        "Environment install is incomplete or stale. Run INSTALL before RUN / LOAD / EXPORT. "
        + " | ".join(stale_problems)
    )


_INCOMPLETE_HEADER_VALUE_TOKENS = (
    "empty",
    "incomplete",
    "missing",
    "no run",
    "needs install",
    "not configured",
    "not selected",
    "not set",
    "unknown",
)

_DATA_SHARE_HEADER_SCAN_LIMIT = 1_000


def _header_value_state(value: str, caption: str = "") -> str:
    normalized = f"{value or ''} {caption or ''}".strip().lower()
    if not normalized:
        return "incomplete"
    if any(token in normalized for token in _INCOMPLETE_HEADER_VALUE_TOKENS):
        return "incomplete"
    return "ready"


def _render_header_value_card(label: str, value: str, caption: str) -> None:
    state = _header_value_state(value, caption)
    st.markdown(
        (
            f"<div class='agilab-header-card agilab-header-card--{state}'>"
            f"<div class='agilab-header-label'>{html.escape(label)}</div>"
            f"<div class='agilab-header-value agilab-header-value--{state}'>{html.escape(str(value))}</div>"
            f"<div class='agilab-header-caption'>{html.escape(caption)}</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _orchestrate_snippet_state_key(env: Any, name: str) -> str:
    app_name = str(getattr(env, "app", "") or getattr(env, "target", "") or "project")
    return f"orchestrate:notebook_snippet:{app_name}:{name}"


def _store_orchestrate_notebook_snippet(env: Any, name: str, snippet: str | None) -> None:
    key = _orchestrate_snippet_state_key(env, name)
    if snippet:
        st.session_state[key] = snippet
    else:
        st.session_state.pop(key, None)


def _orchestrate_notebook_cell(cell_type: str, source: str) -> dict[str, Any]:
    lines = [line if line.endswith("\n") else line + "\n" for line in source.splitlines()]
    if cell_type == "code":
        return {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": lines,
        }
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": lines,
    }


def _orchestrate_notebook_document(env: Any, snippets: list[tuple[str, str]]) -> dict[str, Any]:
    app_name = str(getattr(env, "app", "") or getattr(env, "target", "") or "project")
    cells: list[dict[str, Any]] = [
        _orchestrate_notebook_cell(
            "markdown",
            "\n".join(
                [
                    f"# AGILAB Orchestration Recipe: {app_name}",
                    "",
                    "This notebook records the ORCHESTRATE snippets generated by AGILAB.",
                    "Run cells selectively: INSTALL prepares environments, CHECK distribute previews work, and RUN executes.",
                    "",
                    "Notebook import remains on the WORKFLOW page because import modifies workflow stages.",
                ]
            ),
        )
    ]
    for label, snippet in snippets:
        cells.append(_orchestrate_notebook_cell("markdown", f"## {label}"))
        cells.append(_orchestrate_notebook_cell("code", snippet))
    return {
        "cells": cells,
        "metadata": {
            "agilab": {
                "schema": "agilab.orchestrate_notebook.v1",
                "app": app_name,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "snippet_labels": [label for label, _snippet in snippets],
            },
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
                "pygments_lexer": "ipython3",
            },
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def _render_orchestrate_notebook_expander(env: Any) -> None:
    snippets: list[tuple[str, str]] = []
    for name, label in (
        ("install", "INSTALL"),
        ("distribution", "CHECK distribute"),
        ("run", "RUN"),
    ):
        snippet = st.session_state.get(_orchestrate_snippet_state_key(env, name))
        if isinstance(snippet, str) and snippet.strip():
            snippets.append((label, snippet))

    with st.expander("Notebook", expanded=False):
        st.caption(
            "Download the current ORCHESTRATE recipe as a runnable notebook. "
            "Import stays in WORKFLOW because it changes workflow stage definitions."
        )
        if not snippets:
            st.info("No orchestration snippets are available yet. Configure INSTALL, CHECK distribute, or RUN first.")
            return
        app_name = str(getattr(env, "app", "") or getattr(env, "target", "") or "project")
        notebook_payload = json.dumps(
            _orchestrate_notebook_document(env, snippets),
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        st.download_button(
            "Download orchestration notebook",
            data=notebook_payload,
            file_name=f"{app_name}_orchestrate.ipynb",
            mime="application/x-ipynb+json",
            key=f"orchestrate:notebook_download:{app_name}",
        )
        st.caption("Includes: " + ", ".join(label for label, _snippet in snippets))


def _safe_display_path(value: Any) -> str:
    if value in (None, ""):
        return "not configured"
    try:
        return str(Path(value).expanduser())
    except (TypeError, ValueError, RuntimeError):
        return str(value)


def _format_header_byte_size(byte_count: int) -> str:
    value = float(max(byte_count, 0))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            precision = 0 if value >= 10 else 1
            return f"{value:.{precision}f} {unit}"
        value /= 1024
    return f"{int(value)} B"


def _data_share_content_summary(path_value: Any) -> tuple[str, str]:
    display_path = _safe_display_path(path_value)
    if display_path == "not configured":
        return "not configured", display_path
    try:
        path = Path(path_value).expanduser()
    except (TypeError, ValueError, RuntimeError):
        return "not configured", str(path_value)

    try:
        if not path.exists():
            return "missing", display_path
        if path.is_file():
            size = path.stat().st_size
            return ("empty" if size <= 0 else _format_header_byte_size(size)), display_path
        if not path.is_dir():
            return "unknown", display_path

        total_size = 0
        file_count = 0
        truncated = False
        for root, dirs, files in os.walk(path):
            dirs[:] = [dirname for dirname in dirs if not (Path(root) / dirname).is_symlink()]
            for filename in files:
                candidate = Path(root) / filename
                if candidate.is_symlink():
                    continue
                try:
                    total_size += candidate.stat().st_size
                except OSError:
                    continue
                file_count += 1
                if file_count >= _DATA_SHARE_HEADER_SCAN_LIMIT:
                    truncated = True
                    break
            if truncated:
                break
    except OSError:
        return "unknown", display_path

    if file_count == 0 or total_size <= 0:
        return "empty", display_path
    size_label = _format_header_byte_size(total_size)
    file_label = f"{file_count} file" if file_count == 1 else f"{file_count} files"
    if truncated:
        size_label = f"{size_label}+"
        file_label = f"{file_count}+ files"
    return size_label, f"{file_label} in {display_path}"


def _path_status(path: Any, *, venv: bool = False, file: bool = False) -> tuple[str, str]:
    if path in (None, ""):
        return "not configured", "not configured"
    try:
        candidate = Path(path)
    except (TypeError, ValueError, RuntimeError):
        return "not configured", str(path)
    if venv:
        python_bin = candidate / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if python_bin.exists():
            return "ready", _safe_display_path(candidate)
        if candidate.exists() or candidate.is_symlink():
            return "incomplete", _safe_display_path(candidate)
        return "missing", _safe_display_path(candidate)
    if file:
        status = "ready" if candidate.exists() and candidate.is_file() else "missing"
        return status, _safe_display_path(candidate)
    status = "ready" if candidate.exists() or candidate.is_symlink() else "missing"
    return status, _safe_display_path(candidate)


def _latest_project_mtime(project_root: Path | None) -> str:
    if project_root is None or not project_root.exists():
        return "unknown"
    try:
        latest = project_root.stat().st_mtime
        ignored_dirs = {".venv", "__pycache__", ".git"}
        for root, dirs, files in os.walk(project_root):
            dirs[:] = [dirname for dirname in dirs if dirname not in ignored_dirs]
            for name in files:
                latest = max(latest, (Path(root) / name).stat().st_mtime)
    except OSError:
        return "unknown"
    return datetime.fromtimestamp(latest).strftime("%Y-%m-%d %H:%M")


def _run_history_summary(env: Any) -> tuple[str, str]:
    """Return the number of ORCHESTRATE run logs and the latest run timestamp."""
    runenv = getattr(env, "runenv", None)
    if runenv:
        log_dir = Path(runenv)
    else:
        app_name = str(getattr(env, "app", "") or getattr(env, "target", "") or "app")
        log_dir = Path.home() / "log" / "execute" / app_name

    try:
        run_logs = sorted(path for path in log_dir.glob("run_*.log") if path.is_file())
    except OSError:
        return "0", "run log directory unavailable"

    if not run_logs:
        return "0", "no run logs yet"

    latest: Path | None = None
    latest_mtime: float | None = None
    for run_log in run_logs:
        try:
            mtime = run_log.stat().st_mtime
        except OSError:
            continue
        if latest_mtime is None or mtime > latest_mtime:
            latest = run_log
            latest_mtime = mtime
    if latest is None or latest_mtime is None:
        return str(len(run_logs)), "latest run log unavailable"
    latest_label = datetime.fromtimestamp(latest_mtime).strftime("%Y-%m-%d %H:%M")
    return str(len(run_logs)), f"latest {latest_label}"


def _render_orchestrate_readiness_panel(
    env: Any,
    *,
    app_settings: dict[str, Any],
    install_status: dict[str, Any],
    show_run: bool,
) -> None:
    """Render the same project runtime header used by the PROJECT page."""
    del app_settings, show_run
    active_app = Path(getattr(env, "active_app", "")) if getattr(env, "active_app", None) else None
    manager_status, manager_path = _path_status(install_status.get("manager_venv"), venv=True)
    worker_status, worker_path = _path_status(install_status.get("worker_venv"), venv=True)
    if not install_status.get("manager_ready"):
        manager_status = "stale" if install_status.get("manager_exists") else "missing"
        if install_status.get("manager_exists"):
            manager_path = install_status.get("manager_problem") or manager_path
    if not install_status.get("worker_ready"):
        worker_status = "stale" if install_status.get("worker_exists") else "missing"
        if install_status.get("worker_exists"):
            worker_path = install_status.get("worker_problem") or worker_path
    run_count, run_caption = _run_history_summary(env)

    with st.container(border=True):
        top_cols = st.columns(3)
        with top_cols[0]:
            _render_header_value_card(
                "Runtime module",
                str(getattr(env, "target", "unknown")),
                "Python package used by INSTALL/RUN",
            )
        with top_cols[1]:
            _render_header_value_card("Manager env", manager_status, manager_path)
        with top_cols[2]:
            _render_header_value_card("Worker env", worker_status, worker_path)

        bottom_cols = st.columns(3)
        with bottom_cols[0]:
            _render_header_value_card("Runs", run_count, run_caption)
        with bottom_cols[1]:
            share_size, share_caption = _data_share_content_summary(getattr(env, "app_data_rel", None))
            _render_header_value_card("Data share content (size)", share_size, share_caption)
        with bottom_cols[2]:
            _render_header_value_card("Last change", _latest_project_mtime(active_app), _safe_display_path(active_app))


_ORCHESTRATE_RESOURCE_SUMMARY_LABELS = ("Share", "CPU", "RAM", "GPU", "NPU")


def _render_orchestrate_resource_summary(env: Any, *, target: Any = None) -> None:
    lines = [
        (label, value)
        for label, value in active_app_cluster_information_lines(env)
        if label in _ORCHESTRATE_RESOURCE_SUMMARY_LABELS
    ]
    if not lines:
        return
    ui = target or st
    with ui.container(border=True):
        st.markdown("**Resource summary**")
        columns = st.columns(len(lines))
        for column, (label, value) in zip(columns, lines):
            with column:
                st.markdown(f"**{label}**")
                st.write(str(value))


async def _render_deployment_panel(
    env: Any,
    *,
    initial_verbose: int,
    show_install: bool,
    install_status: dict[str, Any],
) -> int:
    """Render the deployment expander and return the effective verbose level."""
    verbose = initial_verbose
    with st.expander("1. Resources and install", expanded=True):
        st.caption(
            "Choose local, local Dask, or LAN cluster resources, then install the manager and worker environments."
        )
        install_warning = _install_status_warning_message(install_status)
        if install_warning:
            st.warning(install_warning)

        cluster_deps = OrchestrateClusterDeps(
            parse_and_validate_scheduler=parse_and_validate_scheduler,
            parse_and_validate_workers=parse_and_validate_workers,
            write_app_settings_toml=_write_app_settings_toml,
            clear_load_toml_cache=load_toml_file.clear,
            set_env_var=AgiEnv.set_env_var,
            agi_env_envars=getattr(AgiEnv, "envars", None),
        )
        resource_summary_slot = st.empty()
        render_cluster_settings_ui(env, cluster_deps, show_run_mode_info=False)
        _render_orchestrate_resource_summary(env, target=resource_summary_slot)
        cluster_params = st.session_state.app_settings["cluster"]
        verbose = cluster_params.get('verbose', 1)

        if not show_install:
            if consume_pending_install_action(st.session_state):
                st.info("INSTALL is hidden. Re-enable Resources and install, then retry INSTALL.")
            return verbose

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
        _store_orchestrate_notebook_snippet(env, "install", cmd)
        install_state = build_orchestrate_install_workflow_state(
            show_install=show_install,
            cmd=cmd,
            active_app_path=getattr(env, "active_app", None),
            agi_cluster_path=getattr(env, "agi_cluster", None),
            is_source_env=bool(getattr(env, "is_source_env", False)),
            is_worker_env=bool(getattr(env, "is_worker_env", False)),
            snippet_tail=getattr(env, "snippet_tail", "asyncio.run(main())"),
            app=getattr(env, "app", ""),
            cluster_enabled=bool(enabled),
            verbose=verbose,
            mode=st.session_state.get("mode", "N/A"),
            raw_scheduler=raw_scheduler,
            raw_workers=raw_workers,
            timestamp=datetime.now().isoformat(timespec="seconds"),
        )
        with st.expander("Generated INSTALL snippet", expanded=False):
            st.code(cmd, language="python")
        if not install_state.action.enabled:
            st.caption(install_state.action.disabled_reason)

        install_expanded = st.session_state.get("_install_logs_expanded", False)
        log_expander = st.expander("Install logs", expanded=install_expanded)
        with log_expander:
            log_placeholder = st.empty()
            existing_log = st.session_state.get("log_text", "").strip()
            if existing_log:
                log_placeholder.code(existing_log, language="python")
        pending_install_requested = consume_pending_install_action(st.session_state)
        install_requested = st.button(
            "INSTALL",
            key="install_btn",
            type="primary",
            disabled=not install_state.action.enabled,
        )
        install_requested = install_requested or pending_install_requested
        if install_requested:
            if install_state.runtime_root is None or install_state.install_command is None:
                st.warning(install_state.action.disabled_reason)
                return verbose
            st.session_state["_install_logs_expanded"] = True
            _reset_traceback_skip()
            clear_log()
            venv = install_state.runtime_root
            install_command = install_state.install_command
            context_lines = install_state.context_lines
            local_log: list[str] = []
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
                result = await _install_worker_action(
                    env,
                    install_command=install_command,
                    venv=venv,
                    local_log=local_log,
                )
                with log_expander:
                    log_placeholder.code(
                        "\n".join(result.data.get("install_log", local_log)[-LOG_DISPLAY_MAX_LINES:]),
                        language="python",
                        height=INSTALL_LOG_HEIGHT,
                    )
                render_action_result(st, result)
                if result.status == "success":
                    st.session_state["SET ARGS"] = True
                    st.session_state["show_run"] = True

    return verbose


async def _render_distribution_panel(
    env: Any,
    *,
    verbose: int,
    project_path: Path,
    show_distribute: bool,
) -> None:
    if not show_distribute:
        return

    module = env.target

    with st.expander(f"2. Configure run arguments for {module}", expanded=True):
        st.caption(
            "Set the input, output, and app-specific parameters passed to INSTALL, "
            "CHECK distribute, RUN, or service mode."
        )
        app_args_form = env.app_args_form
        cluster_params = st.session_state.app_settings.setdefault("cluster", {})
        args_env = _app_args_env_for_cluster(env, cluster_params)

        snippet_exists = app_args_form.exists()
        snippet_not_empty = snippet_exists and app_args_form.stat().st_size > 1

        toggle_key = "toggle_edit_ui"
        if toggle_key not in st.session_state:
            st.session_state[toggle_key] = not snippet_not_empty

        st.toggle("Edit", key=toggle_key, on_change=init_custom_ui, args=[app_args_form])

        if st.session_state[toggle_key]:
            with _with_app_args_env(args_env):
                render_generic_ui()
            if not snippet_exists:
                with open(app_args_form, "w") as st_src:
                    st_src.write("")
        else:
            if snippet_exists and snippet_not_empty:
                try:
                    with _with_app_args_env(args_env):
                        runpy.run_path(app_args_form, init_globals={**globals(), "env": args_env})
                except (SyntaxError, RuntimeError, OSError, TypeError, ValueError, AttributeError, ImportError) as e:
                    st.warning(e)
            else:
                with _with_app_args_env(args_env):
                    render_generic_ui()
                if not snippet_exists:
                    with open(app_args_form, "w") as st_src:
                        st_src.write("")

        if bool(cluster_params.get("cluster_enabled", False)):
            # Refresh mount table cache each rerun (mounts can appear/disappear while Streamlit stays alive).
            _clear_mount_table_cache()
        warning_message = _cluster_args_share_warning(env, cluster_params)
        st.session_state["_orchestrate_cluster_share_warning"] = warning_message or ""
        if warning_message:
            st.warning(warning_message, icon="⚠️")

        args_serialized = serialize_args_payload(st.session_state.app_settings["args"])
        st.session_state["args_serialized"] = args_serialized
        if st.session_state.get("args_reload_required"):
            del st.session_state["app_settings"]
            st.rerun()

    with st.expander("3. Preview distribution workplan", expanded=False):
        st.caption("Preview how the current arguments will be partitioned across available workers.")
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
        _store_orchestrate_notebook_snippet(env, "distribution", cmd)
        distribution_state = build_orchestrate_distribution_workflow_state(
            show_distribute=show_distribute,
            cmd=cmd,
            worker_env_path=getattr(env, "wenv_abs", None),
        )
        with st.expander("Generated CHECK distribute snippet", expanded=False):
            st.code(cmd, language="python")
        if not distribution_state.action.enabled:
            st.caption(distribution_state.action.disabled_reason)
        if st.button(
            "CHECK distribute",
            key="preview_btn",
            type="primary",
            disabled=not distribution_state.action.enabled,
        ):
            with st.expander("Orchestration log", expanded=True):
                live_log_placeholder = st.empty()
                _reset_traceback_skip()
                with st.spinner("Building distribution..."):
                    result = await _check_distribution_action(
                        env,
                        cmd=cmd,
                        project_path=project_path,
                    )
                dist_log = list(result.data.get("dist_log", ()))
                live_log_placeholder.code(
                    "\n".join(dist_log[-LOG_DISPLAY_MAX_LINES:]),
                    language="python",
                    height=LIVE_LOG_MIN_HEIGHT,
                )
                render_action_result(st, result)
                if result.status == "success":
                    st.session_state.preview_tree = True

        with st.expander("Workplan", expanded=False):
            if st.session_state.get("preview_tree"):
                dist_tree_path = distribution_state.distribution_path
                if dist_tree_path is not None and dist_tree_path.exists():
                    workers, work_plan_metadata, work_plan = load_distribution(dist_tree_path)
                    partition_key = "Partition"
                    weights_key = "Units"
                    weights_unit = "Unit"
                    tabs = st.tabs(["Tree", "Workload"])
                    with tabs[0]:
                        if is_dag_worker_base(getattr(env, "base_worker_cls", None)):
                            show_graph(
                                workers,
                                work_plan_metadata,
                                work_plan,
                                partition_key,
                                weights_key,
                                show_leaf_list=st.checkbox("Show leaf nodes", value=False),
                            )
                        else:
                            show_tree(
                                workers,
                                work_plan_metadata,
                                work_plan,
                                partition_key,
                                weights_key,
                                show_leaf_list=st.checkbox("Show leaf nodes", value=False),
                            )
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
                        def _rerun_after_apply(_result: Any) -> None:
                            _clear_cached_distribution()
                            st.rerun()

                        run_streamlit_action(
                            st,
                            ActionSpec(
                                name="Apply distribution",
                                start_message="Applying distribution workplan...",
                                failure_title="Distribution apply failed.",
                                failure_next_action=(
                                    "Refresh the distribution preview, then retry the assignment."
                                ),
                            ),
                            lambda: _apply_distribution_plan_action(
                                dist_tree_path=dist_tree_path,
                                workers=workers,
                                work_plan_metadata=work_plan_metadata,
                                work_plan=work_plan,
                                selections=st.session_state,
                                target_args=st.session_state.app_settings["args"],
                            ),
                            on_success=_rerun_after_apply,
                        )
                elif dist_tree_path is not None:
                    st.warning(
                        f"Distribution plan file `{dist_tree_path}` was not found. "
                        "Run CHECK distribute to regenerate it.",
                    )
                else:
                    st.caption("Unable to resolve the worker environment path. Run INSTALL, then retry CHECK distribute.")


async def _render_run_panels(
    env: Any,
    *,
    project_path: Path,
    show_run: bool,
    verbose: int,
) -> tuple[bool, bool, str | None]:
    """Render RUN and Serve sections and return panel state for execute section."""
    show_run_panel = False
    show_submit_panel = False
    cmd = None

    if not show_run:
        return show_run_panel, show_submit_panel, cmd

    prev_app_key = "execute_prev_app"
    if st.session_state.get(prev_app_key) != env.app:
        st.session_state[prev_app_key] = env.app
        st.session_state["run_log_cache"] = ""
        st.session_state.pop("log_text", None)
        st.session_state.pop("_benchmark_expand", None)
        st.session_state.pop("_force_export_open", None)
    st.session_state.setdefault("run_log_cache", "")

    execution_view_key = f"orchestrate_execution_view__{env.app}"
    execution_view = compact_choice(
        st,
        "Execution mode",
        ("Run now", "Serve"),
        key=execution_view_key,
        help="Run now executes once and stops. Serve starts a persistent service with status and stop controls.",
        fallback="radio",
    )
    show_run_panel = execution_view == "Run now"
    show_submit_panel = execution_view == "Serve"

    cluster_params = st.session_state.app_settings["cluster"]
    cluster_enabled = bool(cluster_params.get("cluster_enabled", False))
    enabled = cluster_enabled
    scheduler = optional_string_expr(enabled, cluster_params.get("scheduler"))
    workers = optional_python_expr(enabled, cluster_params.get("workers"))

    if show_run_panel:
        st.markdown("#### 4. Run or serve")
        st.caption("Use the selected execution view, then keep benchmark and generated-code details available on demand.")
        with st.expander("Run options", expanded=True):
            cluster_params = st.session_state.app_settings["cluster"]
            try:
                local_share_path = env.share_root_path()
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                local_share_path = None
            run_state_deps = OrchestratePageStateDeps(
                available_benchmark_modes=available_benchmark_modes,
                sanitize_benchmark_modes=sanitize_benchmark_modes,
                resolve_requested_run_mode=resolve_requested_run_mode,
                describe_run_mode=describe_run_mode,
                benchmark_workers_data_path_issue=benchmark_workers_data_path_issue,
                optional_string_expr=optional_string_expr,
                optional_python_expr=optional_python_expr,
            )
            benchmark_modes_key = f"benchmark_modes__{env.app}"
            benchmark_best_node_key = f"benchmark_best_single_node__{env.app}"
            st.session_state.setdefault(benchmark_best_node_key, False)
            run_state = build_orchestrate_page_state(
                cluster_params=cluster_params,
                selected_benchmark_modes=st.session_state.get(benchmark_modes_key, []),
                benchmark_best_single_node=bool(st.session_state.get(benchmark_best_node_key, False)),
                local_share_path=local_share_path,
                deps=run_state_deps,
            )
            selected_benchmark_modes = list(run_state.selected_benchmark_modes)
            if st.session_state.pop("benchmark_reset_pending", False):
                selected_benchmark_modes = []
            if st.session_state.get(benchmark_modes_key) != selected_benchmark_modes:
                st.session_state[benchmark_modes_key] = selected_benchmark_modes

            with st.expander("Advanced benchmark options", expanded=False):
                selected_benchmark_modes = st.multiselect(
                    "Benchmark modes",
                    options=list(run_state.available_benchmark_modes),
                    key=benchmark_modes_key,
                    format_func=benchmark_mode_label,
                    help=(
                        "Select the exact execution modes to benchmark. Leave empty to run "
                        "the single mode defined by the optimization toggles."
                    ),
                )
                selected_dask_benchmark = any(int(mode) & 4 for mode in selected_benchmark_modes)
                benchmark_best_single_node = st.checkbox(
                    "Add best single-node Dask run",
                    key=benchmark_best_node_key,
                    disabled=not selected_dask_benchmark,
                    help=(
                        "When benchmarking cluster modes, add one comparison run that uses "
                        "only the highest-capacity machine discovered in the current cluster."
                    ),
                )
            run_state = build_orchestrate_page_state(
                cluster_params=cluster_params,
                selected_benchmark_modes=selected_benchmark_modes,
                benchmark_best_single_node=benchmark_best_single_node,
                local_share_path=local_share_path,
                cluster_share_issue=str(st.session_state.get("_orchestrate_cluster_share_warning") or ""),
                deps=run_state_deps,
            )

            st.session_state["benchmark"] = run_state.benchmark_enabled
            st.session_state["mode"] = run_state.run_mode
            st.info(run_state.run_mode_label)
            if run_state.benchmark_enabled:
                labels = ", ".join(benchmark_mode_label(mode) for mode in run_state.selected_benchmark_modes)
                st.caption(f"Benchmark will iterate only on: {labels}")
            else:
                st.caption("Leave Benchmark modes empty to run the single selected mode.")

            verbose = run_state.verbose
            scheduler = run_state.scheduler
            workers = run_state.workers
            if not run_state.can_run:
                st.error(run_state.run_disabled_reason)
                cmd = None
                _store_orchestrate_notebook_snippet(env, "run", None)
            else:
                cmd = build_run_snippet(
                    env=env,
                    verbose=verbose,
                    run_mode=run_state.run_mode,
                    scheduler=scheduler,
                    workers=workers,
                    workers_data_path=run_state.workers_data_path,
                    rapids_enabled=run_state.rapids_enabled,
                    benchmark_best_single_node=run_state.benchmark_best_single_node,
                    run_args=st.session_state.app_settings.get("args", {}),
                )
                _store_orchestrate_notebook_snippet(env, "run", cmd)
                with st.expander("Generated RUN snippet", expanded=False):
                    st.code(cmd, language="python")

            expand_benchmark = st.session_state.pop("_benchmark_expand", False)
            with st.expander("Observe benchmark results", expanded=expand_benchmark):
                try:
                    if env.benchmark.exists():
                        with open(env.benchmark, "r") as f:
                            raw = json.load(f) or {}

                        date_value = str(raw.pop("date", "") or "").strip()
                        raw = benchmark_rows_with_delta_percent(raw)
                        benchmark_df = pd.DataFrame.from_dict(raw, orient="index")

                        df_nonempty = benchmark_df.dropna(how="all")
                        if not df_nonempty.empty:
                            df_nonempty = df_nonempty.loc[:, df_nonempty.notna().any(axis=0)]
                            df_nonempty = df_nonempty.loc[
                                :,
                                order_benchmark_display_columns(list(df_nonempty.columns)),
                            ]
                        if not df_nonempty.empty and df_nonempty.shape[1] > 0:
                            date_value = _benchmark_display_date(env.benchmark, date_value)

                            if date_value:
                                st.caption(f"Benchmark date: {date_value}")
                            st.info(BENCHMARK_MODE_LEGEND_MARKDOWN)

                            render_dataframe_preview(
                                df_nonempty,
                                truncation_label="Benchmark table preview limited",
                                column_config=benchmark_dataframe_column_config(st.column_config),
                            )
                        else:
                            st.info("Benchmark file is present but empty. Run the benchmark to collect data.")
                    else:
                        st.info(
                            "No benchmark results yet. Select one or more Benchmark modes and run EXECUTE to gather data."
                        )
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

    return show_run_panel, show_submit_panel, cmd

# ===========================
# Main Application UI
# ===========================
async def page() -> None:
    env = _ensure_page_env(st, __file__)
    if env is None:
        return

    current_app, changed_from_query = resolve_active_app(env)
    if _realign_session_env_with_page_root(st.session_state, __file__):
        current_app = env.app
        changed_from_query = True
    if changed_from_query:
        st.session_state["project_changed"] = True

    st.session_state["_env"] = env

    st.set_page_config(
        page_title="AGILab ORCHESTRATE",
        layout="wide",
        menu_items=get_docs_menu_items(html_file="execute-help.html"),
    )
    inject_theme(env.st_resources)
    render_logo()
    render_pinned_expanders(st)
    render_page_context(st, page_label="ORCHESTRATE", env=env)

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
    render_project_selector(st, projects, current_project, on_change=on_project_change)
    project_changed = st.session_state.pop("project_changed", False)
    if project_changed or env.app != previous_project:
        _set_active_app_query_param(env.app)
        store_last_active_app(env.active_app)
        app_settings_snapshot = st.session_state.get("app_settings", {})
        previous_args_project = st.session_state.get("args_project")
        args_override = resolve_project_change_args_override(
            is_args_from_ui=bool(st.session_state.get("is_args_from_ui")),
            args_project=previous_args_project,
            previous_project=previous_project,
            app_settings_snapshot=app_settings_snapshot,
        )
        # Clear generic & per-project keys to prevent bleed-through
        st.session_state.pop("cluster_enabled", None)
        st.session_state.pop("cluster_scheduler_value", None)  # legacy
        st.session_state.pop(f"deploy_expanded_{previous_project}", None)
        st.session_state.pop(f"optimize_expanded_{previous_project}", None)
        clear_cluster_widget_state(st.session_state, previous_project)
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
        st.session_state.pop(f"benchmark_modes__{previous_project}", None)
        st.session_state.pop(f"benchmark_best_single_node__{previous_project}", None)
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


    install_status = _app_install_status(env)
    installed = bool(install_status.get("manager_ready") and install_status.get("worker_ready"))

    # Sidebar toggles for each page section
    if "show_install" not in st.session_state:
        st.session_state["show_install"] = True
    if "show_distribute" not in st.session_state:
        st.session_state["show_distribute"] = True
    if "show_run" not in st.session_state:
        st.session_state["show_run"] = installed
    if st.session_state.get("_show_run_app") != env.app:
        st.session_state["_show_run_app"] = env.app
        st.session_state["show_run"] = installed

    show_install = st.session_state["show_install"]
    show_distribute = st.session_state["show_distribute"]
    show_run = st.session_state["show_run"] if installed else False

    selected_verbose_int = global_diagnostics_verbose(
        session_state=st.session_state,
        envars=getattr(env, "envars", None),
        environ=os.environ,
        settings=app_settings if isinstance(app_settings, dict) else None,
    )
    st.session_state["cluster_verbose"] = selected_verbose_int

    _render_orchestrate_readiness_panel(
        env,
        app_settings=app_settings,
        install_status=install_status,
        show_run=show_run,
    )

    verbose = await _render_deployment_panel(
        env,
        initial_verbose=selected_verbose_int,
        show_install=show_install,
        install_status=install_status,
    )
    await _render_distribution_panel(
        env,
        verbose=verbose,
        project_path=project_path,
        show_distribute=show_distribute,
    )
    show_run_panel, show_submit_panel, cmd = await _render_run_panels(
        env,
        project_path=project_path,
        show_run=show_run,
        verbose=verbose,
    )
    _render_orchestrate_notebook_expander(env)

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
    except (RuntimeError, OSError, TypeError, ValueError, AttributeError, KeyError, ImportError) as e:
        st.error(f"An error occurred: {e}")
        import traceback
        st.caption("Full traceback")
        st.code(traceback.format_exc(), language="text")

if __name__ == "__main__":
    asyncio.run(main())
