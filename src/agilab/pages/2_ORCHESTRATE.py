import asyncio

# ===========================
# Standard Imports (lightweight)
# ===========================
import os
import socket
import runpy
import ast
import json
import logging
from pathlib import Path
import importlib
from typing import Any, Callable, Optional, Sequence
from datetime import datetime

# Third-Party imports
import tomllib  # For reading TOML files

# Theme configuration
os.environ.setdefault(
    "STREAMLIT_CONFIG_FILE",
    str(Path(__file__).resolve().parents[1] / "resources" / "config.toml"),
)
import streamlit as st
from streamlit.errors import StreamlitAPIException

_import_guard_path = Path(__file__).resolve().parents[1] / "import_guard.py"
_import_guard_spec = importlib.util.spec_from_file_location(
    "agilab_import_guard_local", _import_guard_path
)
if _import_guard_spec is None or _import_guard_spec.loader is None:
    raise ModuleNotFoundError(
        f"Unable to load import_guard.py from {_import_guard_path}"
    )
_import_guard_module = importlib.util.module_from_spec(_import_guard_spec)
_import_guard_spec.loader.exec_module(_import_guard_module)
import_agilab_symbols = _import_guard_module.import_agilab_symbols
import_agilab_module = _import_guard_module.import_agilab_module

_public_bind_guard_module = import_agilab_module(
    "agilab.ui_public_bind_guard",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "ui_public_bind_guard.py",
    fallback_name="agilab_ui_public_bind_guard_fallback",
)
_public_bind_guard_module.enforce_public_bind_policy_or_stop(st)

import_agilab_symbols(
    globals(),
    "agilab.orchestrate_page_support",
    {
        "build_distribution_snippet": "build_distribution_snippet",
        "build_install_snippet": "build_install_snippet",
        "build_manager_install_snippet": "build_manager_install_snippet",
        "build_run_snippet": "build_run_snippet",
        "DEPLOY_WORKERS_AGI_INSTALL_RATIONALE": "DEPLOY_WORKERS_AGI_INSTALL_RATIONALE",
        "available_benchmark_modes": "available_benchmark_modes",
        "BENCHMARK_MODE_LEGEND_MARKDOWN": "BENCHMARK_MODE_LEGEND_MARKDOWN",
        "benchmark_dataframe_column_config": "benchmark_dataframe_column_config",
        "benchmark_mode_label": "benchmark_mode_label",
        "benchmark_results_caption": "benchmark_results_caption",
        "benchmark_rows_with_delta_percent": "benchmark_rows_with_delta_percent",
        "benchmark_workers_data_path_issue": "benchmark_workers_data_path_issue",
        "compute_run_mode": "compute_run_mode",
        "describe_run_mode": "describe_run_mode",
        "merge_app_settings_sources": "merge_app_settings_sources",
        "ORCHESTRATE_ACTION_LABELS": "ORCHESTRATE_ACTION_LABELS",
        "optional_python_expr": "optional_python_expr",
        "optional_string_expr": "optional_string_expr",
        "order_benchmark_display_columns": "order_benchmark_display_columns",
        "orchestrate_snippet_runtime_root": "orchestrate_snippet_runtime_root",
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
        "supports_distribution_preview": "supports_distribution_preview",
        "supports_service_mode": "supports_service_mode",
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
        "PAGE_ENV_REALIGNED_STATE_KEY": "_PAGE_ENV_REALIGNED_STATE_KEY",
        "ensure_page_env": "_ensure_page_env",
        "realign_session_env_with_page_root": "_realign_session_env_with_page_root",
        "render_page_chrome": "render_page_chrome",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "page_bootstrap.py",
    fallback_name="agilab_page_bootstrap_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.workflow_ui",
    {
        "is_dag_worker_base": "is_dag_worker_base",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "workflow_ui.py",
    fallback_name="agilab_workflow_ui_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.environment_health",
    {
        "compact_data_share_caption": "_environment_compact_data_share_caption",
        "compact_path_caption": "_environment_compact_path_caption",
        "data_share_content_summary": "_environment_data_share_content_summary",
        "format_byte_size": "_environment_format_byte_size",
        "header_value_state": "_environment_header_value_state",
        "latest_project_mtime": "_environment_latest_project_mtime",
        "path_status": "_environment_path_status",
        "render_environment_details": "_environment_render_environment_details",
        "render_environment_health_panel": "render_environment_health_panel",
        "render_health_card": "_environment_render_health_card",
        "run_history_summary": "_environment_run_history_summary",
        "safe_display_path": "_environment_safe_display_path",
        "EnvironmentHealthCard": "_EnvironmentHealthCard",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "environment_health.py",
    fallback_name="agilab_environment_health_fallback",
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
    "agilab.runtime_failure_diagnostics",
    {
        "classify_runtime_failure": "classify_runtime_failure",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1]
    / "runtime_failure_diagnostics.py",
    fallback_name="agilab_runtime_failure_diagnostics_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.app_surface",
    {
        "configured_app_surface_entrypoint": "configured_app_surface_entrypoint",
        "render_app_surface": "render_app_surface",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "app_surface.py",
    fallback_name="agilab_app_surface_fallback",
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
        "finish_action_elapsed": "_orchestrate_finish_action_elapsed",
        "is_app_installed": "_orchestrate_is_app_installed",
        "start_action_elapsed": "_orchestrate_start_action_elapsed",
        "update_action_elapsed_status": "_orchestrate_update_action_elapsed_status",
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
        "cluster_widget_keys": "cluster_widget_keys",
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
        "profile_report_disabled_reason_for_python": "profile_report_disabled_reason_for_python",
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
        "queue_pending_install_action": "queue_pending_install_action",
        "queue_pending_execute_action": "queue_pending_execute_action",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1]
    / "orchestrate_pending_actions.py",
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
logger = logging.getLogger(__name__)

_LAZY_IMPORT_ATTR_CACHE: dict[tuple[str, str], Any] = {}


def _lazy_import_attr(module_name: str, attr_name: str) -> Any:
    cache_key = (module_name, attr_name)
    if cache_key not in _LAZY_IMPORT_ATTR_CACHE:
        _LAZY_IMPORT_ATTR_CACHE[cache_key] = getattr(
            importlib.import_module(module_name), attr_name
        )
    return _LAZY_IMPORT_ATTR_CACHE[cache_key]


class _LazyAgiEnv:
    def __getattr__(self, name: str) -> Any:
        return getattr(_lazy_import_attr("agi_env", "AgiEnv"), name)


AgiEnv = _LazyAgiEnv()


def background_services_enabled(*args: Any, **kwargs: Any) -> Any:
    return _lazy_import_attr("agi_gui.pagelib", "background_services_enabled")(
        *args, **kwargs
    )


def activate_mlflow(*args: Any, **kwargs: Any) -> Any:
    return _lazy_import_attr("agi_gui.pagelib", "activate_mlflow")(*args, **kwargs)


def init_custom_ui(*args: Any, **kwargs: Any) -> Any:
    return _lazy_import_attr("agi_gui.pagelib", "init_custom_ui")(*args, **kwargs)


def on_project_change(*args: Any, **kwargs: Any) -> Any:
    return _lazy_import_attr("agi_gui.pagelib", "on_project_change")(*args, **kwargs)


def is_valid_ip(*args: Any, **kwargs: Any) -> Any:
    return _lazy_import_attr("agi_gui.pagelib", "is_valid_ip")(*args, **kwargs)


def render_dataframe_preview(*args: Any, **kwargs: Any) -> Any:
    return _lazy_import_attr("agi_gui.pagelib", "render_dataframe_preview")(
        *args, **kwargs
    )


def resolve_active_app(*args: Any, **kwargs: Any) -> Any:
    return _lazy_import_attr("agi_gui.pagelib", "resolve_active_app")(*args, **kwargs)


def store_last_active_app(*args: Any, **kwargs: Any) -> Any:
    return _lazy_import_attr("agi_gui.ui_support", "store_last_active_app")(
        *args, **kwargs
    )


def compact_choice(*args: Any, **kwargs: Any) -> Any:
    return _lazy_import_attr("agi_gui.ux_widgets", "compact_choice")(*args, **kwargs)

FIRST_PROOF_ACTION_QUERY_KEY = "first_proof_action"
FIRST_PROOF_ORCHESTRATE_ACTIONS = {"install", "run"}
FIRST_PROOF_SAFE_CLUSTER_FLAGS = ("cluster_enabled", "cython", "pool", "rapids")


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
        cluster_verbose=st.session_state.get(
            "_cluster_verbose_value", st.session_state.get("cluster_verbose", 1)
        ),
        traceback_state=_TRACEBACK_SKIP,
        strip_ansi_fn=strip_ansi,
        is_dask_shutdown_noise_fn=is_dask_shutdown_noise,
        log_display_max_lines=LOG_DISPLAY_MAX_LINES,
        live_log_min_height=LIVE_LOG_MIN_HEIGHT,
        max_log_height=LIVE_LOG_MIN_HEIGHT,
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
        cluster_verbose=st.session_state.get(
            "_cluster_verbose_value", st.session_state.get("cluster_verbose", 1)
        ),
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
    _orchestrate_set_active_app_query_param(
        st.query_params, active_app, streamlit_api_exception=StreamlitAPIException
    )


def _query_param_scalar(query_params: Any, key: str) -> str:
    """Return a query-param value as a single stripped string."""
    try:
        value = query_params.get(key, "")
    except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
        return ""
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "").strip()


def _query_params_as_dict(query_params: Any) -> dict:
    """Return a mutable dict copy of Streamlit query params."""
    to_dict = getattr(query_params, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict() or {})
    return dict(query_params)


def _remove_query_param(query_params: Any, key: str) -> bool:
    """Remove one query parameter without touching the rest of the URL state."""
    try:
        current = _query_params_as_dict(query_params)
        if key not in current:
            return False
        cleaned = {name: value for name, value in current.items() if name != key}

        from_dict = getattr(query_params, "from_dict", None)
        if callable(from_dict):
            from_dict(cleaned)
            return True

        del query_params[key]
        return True
    except (
        AttributeError,
        KeyError,
        RuntimeError,
        TypeError,
        ValueError,
        RecursionError,
    ):
        return False


def _apply_first_proof_safe_local_settings(session_state: Any, env: Any) -> None:
    """Force first-proof wizard actions onto the safe local Python path."""
    app_settings = session_state.get("app_settings")
    if not isinstance(app_settings, dict):
        app_settings = {"args": {}, "cluster": {}}
    cluster_settings = app_settings.setdefault("cluster", {})
    for flag in FIRST_PROOF_SAFE_CLUSTER_FLAGS:
        cluster_settings[flag] = False
    cluster_settings.setdefault("verbose", 1)

    app_state_name = Path(str(getattr(env, "app", "") or "")).name
    if app_state_name:
        keys = cluster_widget_keys(app_state_name)
        for flag in FIRST_PROOF_SAFE_CLUSTER_FLAGS:
            session_state[keys[flag]] = False
        session_state.pop(f"{keys['cluster_enabled']}__reset", None)
        session_state[f"orchestrate_execution_view__{app_state_name}"] = "Run now"
        session_state[f"benchmark_modes__{app_state_name}"] = []
        session_state[f"benchmark_best_single_node__{app_state_name}"] = False

    session_state["benchmark"] = False
    session_state["dask"] = False
    session_state["mode"] = 0
    session_state["app_settings"] = app_settings


def _consume_first_proof_action_query_seed(
    session_state: Any, query_params: Any, *, env: Any | None = None
) -> str | None:
    """Queue a first-proof ORCHESTRATE action requested by a new-tab URL."""
    action = _query_param_scalar(query_params, FIRST_PROOF_ACTION_QUERY_KEY).lower()
    if not action:
        return None

    _remove_query_param(query_params, FIRST_PROOF_ACTION_QUERY_KEY)
    if action not in FIRST_PROOF_ORCHESTRATE_ACTIONS:
        return None

    if env is not None:
        _apply_first_proof_safe_local_settings(session_state, env)

    if action == "install":
        queue_pending_install_action(session_state)
        session_state["show_install"] = True
        return action

    queue_pending_execute_action(session_state, "run")
    session_state["show_run"] = True
    return action


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
        candidate = _resolve_share_candidate(
            text, getattr(env, "home_abs", Path.home())
        )
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
            cluster_share_paths.append(
                _resolve_share_candidate(cluster_share_text, home_abs)
            )
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
            candidate = _resolve_share_candidate(
                text, getattr(env, "home_abs", Path.home())
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        if _path_points_to_local_share(candidate, env):
            continue
        return candidate
    return None


class _ShareRootOverrideEnv:
    def __init__(self, env: Any, share_root: Path) -> None:
        object.__setattr__(self, "_env", env)
        object.__setattr__(self, "_data_root", Path(share_root).expanduser())

    def __getattr__(self, name: str) -> Any:
        return getattr(self._env, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_env", "_data_root"}:
            object.__setattr__(self, name, value)
            return
        setattr(self._env, name, value)

    @property
    def agi_share_path(self) -> Path:
        return Path(self.AGI_CLUSTER_SHARE).expanduser()

    @property
    def agi_share_path_abs(self) -> Path:
        candidate = Path(self.AGI_CLUSTER_SHARE).expanduser()
        if not candidate.is_absolute():
            candidate = Path(getattr(self._env, "home_abs", Path.home())) / candidate
        return candidate.resolve(strict=False)

    @property
    def AGI_CLUSTER_SHARE(self) -> str:
        env_vars = getattr(self._env, "envars", None)
        env_value = getattr(self._env, "AGI_CLUSTER_SHARE", None)
        if not env_value and isinstance(env_vars, dict):
            env_value = env_vars.get("AGI_CLUSTER_SHARE")
        return str(env_value or self._data_root)

    @property
    def AGILAB_WORKFLOW_DATA_ROOT(self) -> str:
        return str(self._data_root)

    @property
    def agi_workflow_data_root(self) -> str:
        return str(self._data_root)

    @property
    def envars(self) -> dict[str, Any]:
        env_vars = getattr(self._env, "envars", None)
        payload = dict(env_vars) if isinstance(env_vars, dict) else {}
        payload["AGI_CLUSTER_SHARE"] = self.AGI_CLUSTER_SHARE
        payload["AGILAB_WORKFLOW_DATA_ROOT"] = str(self._data_root)
        return payload

    def share_root_path(self) -> Path:
        return self._data_root

    def resolve_share_path(self, path: Any = None) -> Path:
        if path in (None, ""):
            return self._data_root
        candidate = Path(str(path)).expanduser()
        if candidate.is_absolute():
            return candidate.resolve(strict=False)
        return (self._data_root / candidate).resolve(strict=False)


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
    share_source = (
        active_share_root
        if active_share_root is not None
        else getattr(env, "agi_share_path", None)
    )
    if share_source is None:
        return None
    try:
        share_candidate = Path(share_source)
        if not share_candidate.is_absolute():
            share_candidate = (
                Path(getattr(env, "home_abs", Path.home())) / share_candidate
            )
        share_candidate = share_candidate.expanduser()
        share_resolved = _resolve_share_candidate(
            share_candidate, getattr(env, "home_abs", Path.home())
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        return None

    is_symlink = share_candidate.is_symlink()
    looks_shared = _looks_like_shared_path(share_candidate) or _looks_like_shared_path(
        share_resolved
    )
    workers_data_path = _clean_share_path_text(cluster_params.get("workers_data_path"))
    has_worker_share_path = workers_data_path.lower() not in {
        "",
        "none",
        "local",
        "localshare",
    }
    try:
        worker_path = _resolve_share_candidate(
            workers_data_path, getattr(env, "home_abs", Path.home())
        )
        has_worker_share_path = (
            has_worker_share_path and not _path_points_to_local_share(worker_path, env)
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        pass
    # SSHFS cluster-share contract: the scheduler-side AGI_CLUSTER_SHARE can be a
    # normal local filesystem; remote workers mount it at Workers Data Path.
    if (
        is_symlink
        or looks_shared
        or (
            has_worker_share_path
            and _has_configured_cluster_share(env)
            and has_nonlocal_workers(cluster_params.get("workers"))
        )
    ):
        return None

    fstype = (
        _fstype_for_path(share_resolved)
        or _fstype_for_path(share_candidate)
        or "unknown"
    )
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
        filter_warning_messages_fn=lambda text: filter_warning_messages(
            filter_noise_lines(text)
        ),
        format_log_block_fn=lambda text: format_log_block(
            text,
            newest_first=False,
            max_lines=LOG_DISPLAY_MAX_LINES,
        ),
        warning_fn=lambda message: st.warning(message),
        error_fn=lambda message: st.error(message),
        code_fn=lambda *args, **kwargs: st.code(*args, **kwargs),
        log_display_height=INSTALL_LOG_HEIGHT,
    )


update_log._skip_traceback = False


def safe_eval(expression: str, expected_type: Any, error_message: str) -> Any:
    return _orchestrate_safe_eval(
        expression, expected_type, error_message, on_error=st.error
    )


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
            from flight_telemetry import apply_source_defaults, load_args_from_toml

            args_model = apply_source_defaults(
                load_args_from_toml(env.app_settings_file)
            )
            app_settings["args"] = args_model.to_toml_payload()
        except (
            ImportError,
            AttributeError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            tomllib.TOMLDecodeError,
        ) as exc:
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
            logger.warning("Failed to parse %s: %s", file_path, exc)
            return {}
    return {}


@st.cache_data(show_spinner=False)
def load_distribution(file_path: str | Path) -> tuple[list[str], list[Any], list[Any], str, str, str]:
    with open(file_path, "r") as f:
        data = json.load(f)
    workers = [
        f"{ip}-{i}"
        for ip, count in data.get("workers", {}).items()
        for i in range(1, count + 1)
    ]
    partition_key = str(data.get("partition_key") or "Partition")
    weights_key = str(data.get("nb_unit") or data.get("weights_key") or "Units")
    weights_unit = str(data.get("weights_unit") or "Unit")
    return (
        workers,
        data.get("work_plan_metadata", []),
        data.get("work_plan", []),
        partition_key,
        weights_key,
        weights_unit,
    )


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
        next_action="Click RUN to use the updated workplan.",
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
    on_log: Optional[Callable[[str], None]] = None,
) -> ActionResult:
    dist_log: list[str] = []
    runtime_root = orchestrate_snippet_runtime_root(env, project_path)
    command = cmd.replace("asyncio.run(main())", env.snippet_tail)

    def _append_distribution_log(message: str) -> None:
        _append_log_lines(dist_log, message)
        if on_log is not None:
            on_log(message)

    try:
        stdout, stderr = await env.run_agi(
            command,
            log_callback=_append_distribution_log,
            venv=runtime_root,
        )
    except (
        RuntimeError,
        OSError,
        TypeError,
        ValueError,
        AttributeError,
        KeyError,
    ) as exc:
        _append_distribution_log(f"ERROR: {exc}")
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
        _append_distribution_log(stderr)
    if stdout:
        _append_distribution_log(stdout)

    data = {
        "command": command,
        "dist_log": tuple(dist_log),
        "runtime_root": runtime_root,
        "stdout": stdout,
        "stderr": stderr,
    }
    if _log_indicates_install_failure(dist_log):
        diagnostic = classify_runtime_failure(
            "\n".join(str(line) for line in dist_log),
            phase="distribute",
        )
        if diagnostic is not None:
            data["failure_category"] = diagnostic.category
        return ActionResult.error(
            diagnostic.title if diagnostic else "Distribution build failed.",
            detail=diagnostic.detail
            if diagnostic
            else "Detected distribution failure in logs.",
            next_action=diagnostic.next_action
            if diagnostic
            else "Check orchestration logs above, then retry CHECK distribute.",
            data=data,
        )
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
    on_log: Optional[Callable[[str], None]] = None,
    workerless: bool = False,
    manager_install_command: str | None = None,
) -> ActionResult:
    def _append_install_log(message: str) -> None:
        _append_log_lines(local_log, message)
        if on_log is not None:
            on_log(message)

    if manager_install_command:
        manager_stdout = ""
        manager_stderr = ""
        manager_error: Exception | None = None
        _append_install_log("=== Manager environment preinstall ===")
        try:
            manager_stdout, manager_stderr = await env.run_agi(
                manager_install_command,
                log_callback=_append_install_log,
                venv=None,
            )
        except (
            RuntimeError,
            OSError,
            TypeError,
            ValueError,
            AttributeError,
            KeyError,
        ) as exc:
            manager_error = exc
            manager_stderr = str(exc)
            _append_install_log(f"ERROR: {manager_stderr}")

        if manager_stderr and manager_error is None:
            _append_install_log(manager_stderr)
        if manager_stdout:
            _append_install_log(manager_stdout)

        manager_error_flag = manager_error is not None
        if not manager_error_flag and _log_indicates_install_failure(local_log):
            manager_error_flag = True
            if not str(manager_stderr or "").strip():
                manager_stderr = "Detected manager install failure in logs."

        if manager_error_flag:
            _append_install_log(
                "❌ Manager environment deployment failed. Check logs above.",
            )
            data = {
                "install_command": install_command,
                "manager_install_command": manager_install_command,
                "install_log": tuple(local_log),
                "stdout": "",
                "stderr": manager_stderr,
                "venv": venv,
            }
            diagnostic = classify_runtime_failure(
                "\n".join(str(line) for line in (*local_log, manager_stderr)),
                phase="install",
            )
            if diagnostic is not None:
                data["failure_category"] = diagnostic.category
            return ActionResult.error(
                diagnostic.title
                if diagnostic
                else "Manager environment deployment failed.",
                detail=diagnostic.detail
                if diagnostic
                else str(
                    manager_stderr
                    or manager_error
                    or "Manager deployment logs indicate failure."
                ),
                next_action=diagnostic.next_action
                if diagnostic
                else "Check deployment logs above, fix the manager environment, then rerun Deploy scheduler & workers.",
                data=data,
            )

        _append_install_log("✅ Manager environment ready.")
        _append_install_log("=== Worker environment deployment ===")

    install_stdout = ""
    install_stderr = ""
    install_error: Exception | None = None
    try:
        install_stdout, install_stderr = await env.run_agi(
            install_command,
            log_callback=_append_install_log,
            venv=None,
        )
    except (
        RuntimeError,
        OSError,
        TypeError,
        ValueError,
        AttributeError,
        KeyError,
    ) as exc:
        install_error = exc
        install_stderr = str(exc)
        _append_install_log(f"ERROR: {install_stderr}")

    if install_stderr and install_error is None:
        _append_install_log(install_stderr)
    if install_stdout:
        _append_install_log(install_stdout)

    error_flag = install_error is not None
    if not error_flag and _log_indicates_install_failure(local_log):
        error_flag = True
        if not str(install_stderr or "").strip():
            install_stderr = "Detected install failure in logs."

    if error_flag:
        status_line = "❌ Worker deployment finished with errors. Check logs above."
    elif workerless:
        status_line = "✅ Manager environment ready."
    else:
        status_line = "✅ Worker deployment complete."
    _append_install_log(status_line)
    data = {
        "install_command": install_command,
        "manager_install_command": manager_install_command,
        "install_log": tuple(local_log),
        "stdout": install_stdout,
        "stderr": install_stderr,
        "venv": venv,
    }
    if error_flag:
        diagnostic = classify_runtime_failure(
            "\n".join(str(line) for line in (*local_log, install_stderr)),
            phase="install",
        )
        if diagnostic is not None:
            data["failure_category"] = diagnostic.category
        return ActionResult.error(
            diagnostic.title if diagnostic else "Worker deployment failed.",
            detail=diagnostic.detail
            if diagnostic
            else str(
                install_stderr or install_error or "Deployment logs indicate failure."
            ),
            next_action=diagnostic.next_action
            if diagnostic
            else "Check deployment logs above, fix the worker environment, then rerun Deploy scheduler & workers.",
            data=data,
        )
    return ActionResult.success(
        "Manager environment ready." if workerless else "Worker deployment completed.",
        data=data,
    )


@st.cache_data(show_spinner=False)
def generate_profile_report(df: Any) -> Any:
    env = st.session_state["env"]
    disabled_reason = profile_report_disabled_reason_for_python(
        getattr(env, "python_version", "")
    )
    if disabled_reason:
        st.info(disabled_reason)
        return None
    from ydata_profiling.profile_report import ProfileReport

    return ProfileReport(df, minimal=True)


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
        # Key rows by arg name (dict-backed) so deleting a middle row does not
        # shift widget state onto the following rows.
        row_key = f"{env.app}__{key}"
        with cols[0 if i % ncols == 0 else 2]:
            c1, c2, c3, c4 = st.columns([5, 5, 3, 1])
            new_key = c1.text_input("Name", value=key, key=f"args_name__{row_key}")
            new_val = c2.text_input(
                "Value", value=repr(val), key=f"args_value__{row_key}"
            )
            try:
                new_val = ast.literal_eval(new_val)
            except (SyntaxError, ValueError):
                pass
            c3.text(type(new_val).__name__)
            remove_confirm_key = f"args_remove_confirm__{row_key}"
            row_delete_confirmed = False
            row_delete_armed = False
            row_delete_canceled = False

            if st.session_state.get(remove_confirm_key, False):
                row_delete_confirmed = c4.button(
                    "✅",
                    key=f"args_remove_confirm_button__{row_key}",
                    type="primary",
                    help=f"Confirm remove {new_key}",
                )
                row_delete_canceled = c4.button(
                    "✖",
                    key=f"args_remove_cancel_button__{row_key}",
                    type="secondary",
                    help=f"Cancel remove {new_key}",
                )
            else:
                row_delete_armed = c4.button(
                    "🗑️",
                    key=f"args_remove_button__{row_key}",
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
    new_key = c1_add.text_input(
        "Name", placeholder="Name", key=f"args_name__new__{env.app}"
    )
    new_val = c2_add.text_input(
        "Value", placeholder="Value", key=f"args_value__new__{env.app}"
    )
    if c3_add.button("Add argument", type="primary", key="args_add_arg_button"):
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
    is_args_reload_required = arg_valid and (
        args_input != st.session_state.app_settings.get("args", {})
    )

    if is_args_reload_required:
        st.session_state["args_input"] = args_input
        app_settings_file = env.app_settings_file
        if env.app == "flight_telemetry_project":
            try:
                from flight_telemetry import (
                    apply_source_defaults,
                    dump_args_to_toml,
                    FlightArgs,
                )
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
        text = text[1 : text.index("]")]
    elif text.count(":") == 1:
        text = text.rsplit(":", 1)[0]
    return text in {"localhost", "127.0.0.1", "::1", socket.gethostname().lower()}


def _cluster_mode_label(cluster_params: dict[str, Any]) -> str:
    if not bool(cluster_params.get("cluster_enabled", False)):
        return "Local"

    workers = cluster_params.get("workers", {})
    worker_hosts = tuple(workers) if isinstance(workers, dict) else ()
    nonlocal_workers = [
        host for host in worker_hosts if not _is_local_worker_host(host)
    ]
    return "LAN cluster" if nonlocal_workers else "Local Dask demo"


def _runtime_status_label(install_status: dict[str, Any]) -> tuple[str, str]:
    manager_ready = bool(install_status.get("manager_ready"))
    worker_ready = bool(install_status.get("worker_ready"))
    workerless = bool(install_status.get("workerless"))
    if workerless:
        if manager_ready:
            return "Ready", "Manager environment can import AGILAB runtime packages."
        if install_status.get("manager_exists"):
            return "Needs deployment", install_status.get(
                "manager_problem"
            ) or "Manager environment is missing or stale."
        return (
            "Needs deployment",
            "Manager environment has not been created yet. Run Deploy scheduler & workers before RUN.",
        )
    if manager_ready and worker_ready:
        return (
            "Ready",
            "Manager and worker environments can import AGILAB runtime packages.",
        )
    if manager_ready:
        if not install_status.get("worker_exists"):
            return (
                "Needs deployment",
                "Worker environment has not been created yet. Run Deploy scheduler & workers before RUN.",
            )
        return "Needs deployment", install_status.get(
            "worker_problem"
        ) or "Worker environment is missing or stale."
    if worker_ready:
        if not install_status.get("manager_exists"):
            return (
                "Needs deployment",
                "Manager environment has not been created yet. Run Deploy scheduler & workers before RUN.",
            )
        return "Needs deployment", install_status.get(
            "manager_problem"
        ) or "Manager environment is missing or stale."
    return "Needs deployment", "Manager and worker environments are not deployed yet."


def _run_mode_requires_worker_environment(run_mode: Any) -> bool:
    if isinstance(run_mode, (list, tuple, set)):
        return any(_run_mode_requires_worker_environment(mode) for mode in run_mode)
    try:
        return int(run_mode) != 0
    except (TypeError, ValueError):
        return True


def _install_ready_for_run(
    install_status: dict[str, Any], *, worker_required: bool
) -> bool:
    manager_ready = bool(
        install_status.get("manager_exists") and install_status.get("manager_ready")
    )
    if not worker_required:
        return manager_ready
    return manager_ready and bool(
        install_status.get("worker_exists") and install_status.get("worker_ready")
    )


def _install_block_reason_for_run(
    install_status: dict[str, Any], *, worker_required: bool
) -> str:
    if worker_required:
        return (
            _install_status_warning_message(install_status)
            or _runtime_status_label(install_status)[1]
        )
    if install_status.get("manager_exists") and install_status.get("manager_ready"):
        return ""
    if install_status.get("manager_exists"):
        return str(
            install_status.get("manager_problem")
            or "Manager environment is missing or stale."
        )
    return "Manager environment has not been created yet. Run Deploy scheduler & workers before RUN."


def _install_status_warning_message(install_status: dict[str, Any]) -> str | None:
    """Return a warning only for existing-but-stale install environments."""
    stale_problems = []
    if install_status.get("manager_exists") and not install_status.get("manager_ready"):
        stale_problems.append(
            str(install_status.get("manager_problem") or "manager environment is stale")
        )
    if (
        not install_status.get("workerless")
        and install_status.get("worker_exists")
        and not install_status.get("worker_ready")
    ):
        stale_problems.append(
            str(install_status.get("worker_problem") or "worker environment is stale")
        )
    if not stale_problems:
        return None
    return (
        "Environment deployment is incomplete or stale. Run Deploy scheduler & workers before RUN / LOAD / EXPORT. "
        + " | ".join(stale_problems)
    )


def _header_value_state(value: str, caption: str = "") -> str:
    return _environment_header_value_state(value, caption)


def _render_header_value_card(label: str, value: str, caption: str) -> None:
    _environment_render_health_card(st, _EnvironmentHealthCard(label, value, caption))


def _orchestrate_snippet_state_key(env: Any, name: str) -> str:
    app_name = str(getattr(env, "app", "") or getattr(env, "target", "") or "project")
    return f"orchestrate:notebook_snippet:{app_name}:{name}"


def _store_orchestrate_notebook_snippet(
    env: Any, name: str, snippet: str | None
) -> None:
    key = _orchestrate_snippet_state_key(env, name)
    if snippet:
        st.session_state[key] = snippet
    else:
        st.session_state.pop(key, None)


def _orchestrate_notebook_cell(cell_type: str, source: str) -> dict[str, Any]:
    lines = [
        line if line.endswith("\n") else line + "\n" for line in source.splitlines()
    ]
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


def _orchestrate_notebook_document(
    env: Any, snippets: list[tuple[str, str]]
) -> dict[str, Any]:
    app_name = str(getattr(env, "app", "") or getattr(env, "target", "") or "project")
    snippet_labels = [label for label, _snippet in snippets]
    run_sentence = (
        "Run cells selectively: Deploy scheduler & workers prepares manager/worker environments, CHECK distribute previews work, and RUN executes."
        if "CHECK distribute" in snippet_labels
        else "Run cells selectively: Deploy scheduler & workers prepares manager/worker environments and RUN executes."
    )
    cells: list[dict[str, Any]] = [
        _orchestrate_notebook_cell(
            "markdown",
            "\n".join(
                [
                    f"# AGILAB Orchestration Recipe: {app_name}",
                    "",
                    "This notebook records the ORCHESTRATE snippets generated by AGILAB.",
                    run_sentence,
                    DEPLOY_WORKERS_AGI_INSTALL_RATIONALE,
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
                "snippet_labels": snippet_labels,
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
        ("install", ORCHESTRATE_ACTION_LABELS["deploy_workers"]),
        ("distribution", ORCHESTRATE_ACTION_LABELS["check_distribute"]),
        ("run", ORCHESTRATE_ACTION_LABELS["run"]),
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
            if supports_distribution_preview(env):
                st.info(
                    "No orchestration snippets are available yet. Configure Deploy scheduler & workers, CHECK distribute, or RUN first."
                )
            else:
                st.info(
                    "No orchestration snippets are available yet. Configure Deploy scheduler & workers or RUN first."
                )
            return
        app_name = str(
            getattr(env, "app", "") or getattr(env, "target", "") or "project"
        )
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


def _render_orchestrate_analysis_expander(env: Any) -> None:
    """Render a compact read-only analysis preview without replacing ANALYSIS."""
    active_app = getattr(env, "active_app", None)

    with st.expander("Analysis preview", expanded=False):
        st.caption(
            "Quickly inspect the latest app-owned analysis surface from ORCHESTRATE. "
            "Use ANALYSIS for the full evidence workspace, notebooks, manifests, and artifacts."
        )
        if active_app is None:
            st.info("Select a project before opening an analysis preview.")
            return

        project_path = Path(active_app)
        if configured_app_surface_entrypoint(project_path) is None:
            st.info("This project does not declare an app-specific analysis surface yet.")
            return

        try:
            rendered = render_app_surface(
                project_path,
                mode="analysis",
                env=env,
                container=st,
                streamlit=st,
            )
        except Exception as exc:  # pragma: no cover - defensive UI guard
            st.warning(f"Analysis preview is unavailable: {exc}")
            return

        if not rendered:
            st.info("No analysis preview was rendered for the selected project.")


def _safe_display_path(value: Any) -> str:
    return _environment_safe_display_path(value)


def _compact_path_caption(value: Any, *, fallback: str = "see runtime details") -> str:
    """Return a card-safe path label while keeping the full path for details."""
    return _environment_compact_path_caption(value, fallback=fallback)


def _compact_data_share_caption(caption: str) -> str:
    return _environment_compact_data_share_caption(caption)


def _render_runtime_details(rows: Sequence[tuple[str, Any]]) -> None:
    _environment_render_environment_details(st, rows)


def _format_header_byte_size(byte_count: int) -> str:
    return _environment_format_byte_size(byte_count)


def _data_share_content_summary(path_value: Any) -> tuple[str, str]:
    return _environment_data_share_content_summary(path_value)


def _path_status(
    path: Any, *, venv: bool = False, file: bool = False
) -> tuple[str, str]:
    return _environment_path_status(path, venv=venv, file=file)


def _latest_project_mtime(project_root: Path | None) -> str:
    return _environment_latest_project_mtime(project_root)


def _run_history_summary(env: Any) -> tuple[str, str]:
    """Return the number of ORCHESTRATE run logs and the latest run timestamp."""
    return _environment_run_history_summary(env)


def _render_orchestrate_readiness_panel(
    env: Any,
    *,
    app_settings: dict[str, Any],
    install_status: dict[str, Any],
    show_run: bool,
) -> Any:
    """Render the shared first-run Environment Health surface."""
    del show_run
    return render_environment_health_panel(
        st,
        env,
        app_settings=app_settings,
        install_status=install_status,
        render_details=False,
    )


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
) -> tuple[int, dict[str, Any]]:
    """Render the deployment expander and return the effective verbose level."""
    verbose = initial_verbose
    workerless = bool(install_status.get("workerless"))
    with st.expander("1. Resources and deployment", expanded=True):
        if workerless:
            st.caption("Prepare the manager environment for this workerless local app.")
        else:
            st.caption(
                "Choose local, local Dask, or LAN cluster resources, then deploy the manager and worker environments."
            )
        st.caption(DEPLOY_WORKERS_AGI_INSTALL_RATIONALE)
        install_warning_slot = st.empty()
        install_warning = _install_status_warning_message(install_status)
        if install_warning:
            install_warning_slot.warning(install_warning)

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
        verbose = cluster_params.get("verbose", 1)

        if not show_install:
            if consume_pending_install_action(st.session_state):
                st.info(
                    "Deploy scheduler & workers is hidden. Re-enable Resources, then retry Deploy scheduler & workers."
                )
            return verbose, install_status

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
            mode=st.session_state.get("mode", 0),
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
        deploy_workers_label = ORCHESTRATE_ACTION_LABELS["deploy_workers"]
        with st.expander(f"Generated {deploy_workers_label} snippet", expanded=False):
            st.code(cmd, language="python")
            st.caption(DEPLOY_WORKERS_AGI_INSTALL_RATIONALE)
        if not install_state.action.enabled:
            st.caption(install_state.action.disabled_reason)

        existing_log = st.session_state.get("log_text", "").strip()
        if existing_log:
            install_expanded = st.session_state.get("_install_logs_expanded", False)
            with st.expander("Deployment logs", expanded=install_expanded):
                log_placeholder = st.empty()
                update_log(log_placeholder, "")
        pending_install_requested = consume_pending_install_action(st.session_state)
        install_requested = st.button(
            ORCHESTRATE_ACTION_LABELS["deploy_workers"],
            key="install_btn",
            type="primary",
            disabled=not install_state.action.enabled,
            help=DEPLOY_WORKERS_AGI_INSTALL_RATIONALE,
        )
        install_requested = install_requested or pending_install_requested
        if install_requested:
            if (
                install_state.runtime_root is None
                or install_state.install_command is None
            ):
                st.warning(install_state.action.disabled_reason)
                return verbose, install_status
            st.session_state["_install_logs_expanded"] = True
            _reset_traceback_skip()
            clear_log()
            venv = install_state.runtime_root
            install_command = install_state.install_command
            context_lines = install_state.context_lines
            local_log: list[str] = []
            log_expander = st.expander("Deployment logs", expanded=True)
            with log_expander:
                log_placeholder = st.empty()
                elapsed_placeholder = st.empty()
            with log_expander:
                log_placeholder.empty()
                for line in context_lines:
                    _append_log_lines(local_log, line)
                    update_log(log_placeholder, line)
            elapsed_started = _orchestrate_start_action_elapsed(
                st.session_state,
                "orchestrate_deploy_workers",
            )
            _orchestrate_update_action_elapsed_status(
                elapsed_placeholder,
                st.session_state,
                "orchestrate_deploy_workers",
                deploy_workers_label,
                started_monotonic=elapsed_started,
            )

            def _tick_deploy_progress(message: str) -> None:
                update_log(log_placeholder, message)
                _orchestrate_update_action_elapsed_status(
                    elapsed_placeholder,
                    st.session_state,
                    "orchestrate_deploy_workers",
                    deploy_workers_label,
                    started_monotonic=elapsed_started,
                )

            spinner_label = (
                "Deploying manager environment..."
                if workerless
                else "Deploying worker environments..."
            )
            with st.spinner(spinner_label):
                result = await _install_worker_action(
                    env,
            install_command=install_command,
            manager_install_command=(
                build_manager_install_snippet(
                    env=env,
                    verbose=verbose,
                    mode=st.session_state.get("mode", 0),
                ).replace("asyncio.run(main())", getattr(env, "snippet_tail", "asyncio.run(main())"))
                if enabled and not workerless
                else None
            ),
                    venv=venv,
                    local_log=local_log,
                    on_log=_tick_deploy_progress,
                    workerless=workerless,
                )
                _orchestrate_finish_action_elapsed(
                    elapsed_placeholder,
                    st.session_state,
                    "orchestrate_deploy_workers",
                    deploy_workers_label,
                    status="completed" if result.status == "success" else "failed",
                    started_monotonic=elapsed_started,
                )
                with log_expander:
                    final_install_log = result.data.get("install_log", local_log)
                    if final_install_log:
                        st.session_state["log_text"] = (
                            "\n".join(str(line) for line in final_install_log) + "\n"
                        )
                    update_log(log_placeholder, "")
                render_action_result(st, result)
                if result.status == "success":
                    st.session_state["show_run"] = True
                    install_status = _app_install_status(env)
                    refreshed_warning = _install_status_warning_message(install_status)
                    if refreshed_warning:
                        install_warning_slot.warning(refreshed_warning)
                    else:
                        install_warning_slot.empty()

    return verbose, install_status


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
            "Set the input, output, and app-specific parameters passed to Deploy scheduler & workers, "
            "CHECK distribute, RUN, or service mode."
        )
        app_args_form = env.app_args_form
        cluster_params = st.session_state.app_settings.setdefault("cluster", {})
        args_env = _app_args_env_for_cluster(env, cluster_params)

        snippet_exists = app_args_form.exists()
        snippet_not_empty = snippet_exists and app_args_form.stat().st_size > 1

        surface_rendered = False
        if configured_app_surface_entrypoint(project_path) is not None:
            try:
                with _with_app_args_env(args_env):
                    surface_rendered = render_app_surface(
                        project_path,
                        mode="configure",
                        env=args_env,
                        container=st,
                    )
            except (
                SyntaxError,
                RuntimeError,
                OSError,
                TypeError,
                ValueError,
                AttributeError,
                ImportError,
            ) as e:
                st.warning(e)

        if not surface_rendered:
            toggle_key = "toggle_edit_ui"
            if toggle_key not in st.session_state:
                st.session_state[toggle_key] = not snippet_not_empty

            st.toggle(
                "Edit", key=toggle_key, on_change=init_custom_ui, args=[app_args_form]
            )

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
                            runpy.run_path(
                                app_args_form,
                                init_globals={**globals(), "env": args_env},
                            )
                    except (
                        SyntaxError,
                        RuntimeError,
                        OSError,
                        TypeError,
                        ValueError,
                        AttributeError,
                        ImportError,
                    ) as e:
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
        if st.session_state.pop("args_reload_required", False):
            st.session_state.pop("app_settings", None)
            st.rerun()

    if not supports_distribution_preview(env):
        _store_orchestrate_notebook_snippet(env, "distribution", None)
        st.session_state.pop("preview_tree", None)
        return

    with st.expander("3. Preview distribution workplan", expanded=False):
        st.caption(
            "Preview how the current arguments will be partitioned across available workers."
        )
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
        check_distribute_label = ORCHESTRATE_ACTION_LABELS["check_distribute"]
        with st.expander(f"Generated {check_distribute_label} snippet", expanded=False):
            st.code(cmd, language="python")
        if not distribution_state.action.enabled:
            st.caption(distribution_state.action.disabled_reason)
        if st.button(
            ORCHESTRATE_ACTION_LABELS["check_distribute"],
            key="preview_btn",
            type="primary",
            disabled=not distribution_state.action.enabled,
        ):
            with st.expander("Orchestration log", expanded=True):
                live_log_placeholder = st.empty()
                elapsed_placeholder = st.empty()
                _reset_traceback_skip()
                elapsed_started = _orchestrate_start_action_elapsed(
                    st.session_state,
                    "orchestrate_check_distribute",
                )
                _orchestrate_update_action_elapsed_status(
                    elapsed_placeholder,
                    st.session_state,
                    "orchestrate_check_distribute",
                    check_distribute_label,
                    started_monotonic=elapsed_started,
                )

                def _tick_distribution_progress(message: str) -> None:
                    update_log(live_log_placeholder, message)
                    _orchestrate_update_action_elapsed_status(
                        elapsed_placeholder,
                        st.session_state,
                        "orchestrate_check_distribute",
                        check_distribute_label,
                        started_monotonic=elapsed_started,
                    )

                with st.spinner("Building distribution..."):
                    clear_log()
                    result = await _check_distribution_action(
                        env,
                        cmd=cmd,
                        project_path=project_path,
                        on_log=_tick_distribution_progress,
                    )
                _orchestrate_finish_action_elapsed(
                    elapsed_placeholder,
                    st.session_state,
                    "orchestrate_check_distribute",
                    check_distribute_label,
                    status="completed" if result.status == "success" else "failed",
                    started_monotonic=elapsed_started,
                )
                dist_log = list(result.data.get("dist_log", ()))
                if dist_log:
                    st.session_state["log_text"] = (
                        "\n".join(str(line) for line in dist_log) + "\n"
                    )
                update_log(live_log_placeholder, "")
                render_action_result(st, result)
                if result.status == "success":
                    st.session_state.preview_tree = True

        with st.expander("Workplan", expanded=False):
            if st.session_state.get("preview_tree"):
                dist_tree_path = distribution_state.distribution_path
                if dist_tree_path is not None and dist_tree_path.exists():
                    (
                        workers,
                        work_plan_metadata,
                        work_plan,
                        partition_key,
                        weights_key,
                        weights_unit,
                    ) = load_distribution(dist_tree_path)
                    tabs = st.tabs(["Tree", "Workload"])
                    with tabs[0]:
                        if is_dag_worker_base(getattr(env, "base_worker_cls", None)):
                            show_graph(
                                workers,
                                work_plan_metadata,
                                work_plan,
                                partition_key,
                                weights_key,
                                show_leaf_list=st.checkbox(
                                    "Show leaf nodes",
                                    value=False,
                                    key=f"workplan_show_leaves_graph__{env.app}",
                                ),
                            )
                        else:
                            show_tree(
                                workers,
                                work_plan_metadata,
                                work_plan,
                                partition_key,
                                weights_key,
                                show_leaf_list=st.checkbox(
                                    "Show leaf nodes",
                                    value=False,
                                    key=f"workplan_show_leaves_tree__{env.app}",
                                ),
                            )
                    with tabs[1]:
                        workload_barchart(
                            workers,
                            work_plan_metadata,
                            partition_key,
                            weights_key,
                            weights_unit,
                        )
                    unused_workers = [
                        worker
                        for worker, chunks in zip(workers, work_plan_metadata)
                        if not chunks
                    ]
                    if unused_workers:
                        st.warning(
                            f"**{len(unused_workers)} Unused workers:** "
                            + ", ".join(unused_workers)
                        )
                    st.markdown("**Modify Distribution:**")
                    ncols = 2
                    cols = st.columns([10, 1, 10])
                    count = 0
                    for i, chunks in enumerate(work_plan_metadata):
                        for j, chunk in enumerate(chunks):
                            partition, size = chunk
                            with cols[0 if count % ncols == 0 else 2]:
                                b1, b2 = st.columns(2)
                                b1.text(
                                    f"{partition_key.title()} {partition} ({weights_key}: {size} {weights_unit})"
                                )
                                key = workplan_selection_key(partition, i, j)
                                b2.selectbox(
                                    "Worker",
                                    options=workers,
                                    key=key,
                                    index=i if i < len(workers) else 0,
                                )
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
                    st.caption(
                        "Unable to resolve the worker environment path. Run Deploy scheduler & workers, then retry CHECK distribute."
                    )


def _execution_mode_options(env: Any) -> tuple[str, ...]:
    if supports_service_mode(env):
        return ("Run now", "Serve")
    return ("Run now",)


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
    execution_options = _execution_mode_options(env)
    if len(execution_options) > 1:
        execution_view = compact_choice(
            st,
            "Execution mode",
            execution_options,
            key=execution_view_key,
            help="Run now executes once and stops. Serve starts a persistent service with status and stop controls.",
            fallback="radio",
        )
    else:
        execution_view = "Run now"
        st.caption("Service mode is not available for this app.")
    show_run_panel = execution_view == "Run now"
    show_submit_panel = execution_view == "Serve"

    cluster_params = st.session_state.app_settings["cluster"]
    cluster_enabled = bool(cluster_params.get("cluster_enabled", False))
    enabled = cluster_enabled
    scheduler = optional_string_expr(enabled, cluster_params.get("scheduler"))
    workers = optional_python_expr(enabled, cluster_params.get("workers"))

    if show_run_panel:
        st.markdown("#### 4. Run or serve")
        st.caption(
            "Use the selected execution view, then keep benchmark and generated-code details available on demand."
        )
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
                benchmark_best_single_node=bool(
                    st.session_state.get(benchmark_best_node_key, False)
                ),
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
                        "the single mode defined by the optimization toggles. Dask modes "
                        "keep the historical in-worker pooling behavior, so a Dask mode "
                        "with and without 'pool' executes the same code inside each worker."
                    ),
                )
                selected_dask_benchmark = any(
                    int(mode) & 4 for mode in selected_benchmark_modes
                )
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
                cluster_share_issue=str(
                    st.session_state.get("_orchestrate_cluster_share_warning") or ""
                ),
                deps=run_state_deps,
            )

            st.session_state["benchmark"] = run_state.benchmark_enabled
            st.session_state["mode"] = run_state.run_mode
            st.info(run_state.run_mode_label)
            if run_state.benchmark_enabled:
                labels = ", ".join(
                    benchmark_mode_label(mode)
                    for mode in run_state.selected_benchmark_modes
                )
                st.caption(f"Benchmark will iterate only on: {labels}")
            else:
                st.caption(
                    "Leave Benchmark modes empty to run the single selected mode."
                )

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
            benchmark_exists = False
            try:
                benchmark_exists = bool(env.benchmark.exists())
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                benchmark_exists = False
            show_benchmark_results = (
                run_state.benchmark_enabled or benchmark_exists or expand_benchmark
            )
            if show_benchmark_results:
                with st.expander("Observe benchmark results", expanded=expand_benchmark):
                    try:
                        if benchmark_exists:
                            with open(env.benchmark, "r") as f:
                                raw = json.load(f) or {}

                            date_value = str(raw.pop("date", "") or "").strip()
                            raw = benchmark_rows_with_delta_percent(raw)
                            import pandas as pd

                            benchmark_df = pd.DataFrame.from_dict(raw, orient="index")

                            df_nonempty = benchmark_df.dropna(how="all")
                            if not df_nonempty.empty:
                                df_nonempty = df_nonempty.loc[
                                    :, df_nonempty.notna().any(axis=0)
                                ]
                                df_nonempty = df_nonempty.loc[
                                    :,
                                    order_benchmark_display_columns(
                                        list(df_nonempty.columns)
                                    ),
                                ]
                            if not df_nonempty.empty and df_nonempty.shape[1] > 0:
                                date_value = _benchmark_display_date(
                                    env.benchmark, date_value
                                )

                                if date_value:
                                    st.caption(f"Benchmark date: {date_value}")
                                st.caption(benchmark_results_caption(raw))
                                st.info(BENCHMARK_MODE_LEGEND_MARKDOWN)

                                render_dataframe_preview(
                                    df_nonempty,
                                    truncation_label="Benchmark table preview limited",
                                    column_config=benchmark_dataframe_column_config(
                                        st.column_config
                                    ),
                                )
                            else:
                                st.info(
                                    "Benchmark file is present but empty. Run the benchmark to collect data."
                                )
                        else:
                            st.info(
                                "No benchmark results yet. Select one or more Benchmark modes and click RUN to gather data."
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
def _skip_orchestrate_project_cockpit(*_args: Any, **_kwargs: Any) -> None:
    """ORCHESTRATE uses its action rail and Environment Health instead."""
    return None


async def page() -> None:
    env = _ensure_page_env(st, __file__)
    if env is None:
        return

    realigned_with_page_root = bool(st.session_state.pop(_PAGE_ENV_REALIGNED_STATE_KEY, False))
    current_app, changed_from_query = resolve_active_app(env)
    if _realign_session_env_with_page_root(st.session_state, __file__):
        realigned_with_page_root = True
    if realigned_with_page_root:
        current_app = env.app
    if changed_from_query:
        st.session_state["project_changed"] = True

    st.session_state["_env"] = env

    render_page_chrome(
        st,
        env=env,
        page_label="ORCHESTRATE",
        docs_html_file="execute-help.html",
        render_page_context=_skip_orchestrate_project_cockpit,
    )
    orchestrate_banner_slot = st.container()

    if background_services_enabled() and not st.session_state.get("server_started"):
        activate_mlflow(env)

    # Define defaults for session state keys.
    defaults = {
        "profile_report_file": env.AGILAB_EXPORT_ABS / "profile_report.html",
        "df_export_file": str(env.AGILAB_EXPORT_ABS / env.target / "export.csv"),
        "preview_tree": False,
        "data_source": "file",
        "scheduler_ipport": {socket.gethostbyname("localhost"): 8786},
        "workers": {"127.0.0.1": 1},
        "mode": 0,
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
        st.session_state.pop("toggle_edit_ui", None)
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
        st.session_state["rapids_default"] = (
            "-cu12" in pyproject_content
        ) and os.name != "nt"
    else:
        st.session_state["rapids_default"] = False

    # Reload app settings after potential project change
    app_settings = st.session_state.get("app_settings")
    if not isinstance(app_settings, dict):
        initialize_app_settings()
        app_settings = st.session_state.get("app_settings")
        if not isinstance(app_settings, dict):
            app_settings = {"args": {}, "cluster": {}}
            st.session_state["app_settings"] = app_settings

    _consume_first_proof_action_query_seed(st.session_state, st.query_params, env=env)

    install_status = _app_install_status(env)
    worker_required_for_run = _run_mode_requires_worker_environment(
        st.session_state.get("mode", 0)
    )
    installed = _install_ready_for_run(
        install_status, worker_required=worker_required_for_run
    )
    install_block_reason = _install_block_reason_for_run(
        install_status, worker_required=worker_required_for_run
    )

    # Sidebar toggles for each page section
    if "show_install" not in st.session_state:
        st.session_state["show_install"] = True
    if "show_distribute" not in st.session_state:
        st.session_state["show_distribute"] = True
    if "show_run" not in st.session_state:
        st.session_state["show_run"] = True
    if st.session_state.get("_show_run_app") != env.app:
        st.session_state["_show_run_app"] = env.app
        st.session_state["show_run"] = True

    show_install = st.session_state["show_install"]
    show_distribute = st.session_state["show_distribute"]
    show_run = bool(st.session_state["show_run"])

    selected_verbose_int = global_diagnostics_verbose(
        session_state=st.session_state,
        envars=getattr(env, "envars", None),
        environ=os.environ,
        settings=app_settings if isinstance(app_settings, dict) else None,
    )
    st.session_state["_cluster_verbose_value"] = selected_verbose_int

    with orchestrate_banner_slot:
        environment_health = _render_orchestrate_readiness_panel(
            env,
            app_settings=app_settings,
            install_status=install_status,
            show_run=show_run,
        )
    _environment_render_environment_details(st, environment_health.details)

    verbose, install_status = await _render_deployment_panel(
        env,
        initial_verbose=selected_verbose_int,
        show_install=show_install,
        install_status=install_status,
    )
    worker_required_for_run = _run_mode_requires_worker_environment(
        st.session_state.get("mode", 0)
    )
    installed = _install_ready_for_run(
        install_status, worker_required=worker_required_for_run
    )
    install_block_reason = _install_block_reason_for_run(
        install_status, worker_required=worker_required_for_run
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
    worker_required_for_run = _run_mode_requires_worker_environment(
        st.session_state.get("mode", 0)
    )
    installed = _install_ready_for_run(
        install_status, worker_required=worker_required_for_run
    )
    install_block_reason = _install_block_reason_for_run(
        install_status, worker_required=worker_required_for_run
    )
    _render_orchestrate_analysis_expander(env)
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
        install_ready=installed,
        install_disabled_reason=install_block_reason,
        worker_env_required=worker_required_for_run,
    )


# ===========================
# Main Entry Point
# ===========================
async def main():
    try:
        await page()
    except (
        RuntimeError,
        OSError,
        TypeError,
        ValueError,
        AttributeError,
        KeyError,
        ImportError,
    ) as e:
        st.error(f"An error occurred: {e}")
        import traceback

        st.caption("Full traceback")
        st.code(traceback.format_exc(), language="text", height=400)


if __name__ == "__main__":
    asyncio.run(main())
