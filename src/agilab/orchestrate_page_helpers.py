from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Optional

LOG_DISPLAY_MAX_LINES = 250
LIVE_LOG_MIN_HEIGHT = 160
INSTALL_LOG_HEIGHT = 320
_TRACEBACK_SKIP = {"active": False}

try:
    from agilab.orchestrate_page_support import (
        append_log_lines as _append_log_lines_impl,
        display_log as _display_log_impl,
        init_session_state as _init_session_state_impl,
        clear_log as _clear_log_impl,
        resolve_share_candidate as _resolve_share_candidate_impl,
        clear_cached_distribution as _clear_cached_distribution_impl,
        clear_mount_table_cache as _clear_mount_table_cache_impl,
        update_delete_confirm_state as _update_delete_confirm_state_impl,
        log_indicates_install_failure as _log_indicates_install_failure_impl,
        capture_dataframe_preview_state as _capture_dataframe_preview_state_impl,
        restore_dataframe_preview_state as _restore_dataframe_preview_state_impl,
        toggle_select_all as _toggle_select_all_impl,
        update_select_all as _update_select_all_impl,
        update_log as _update_log_impl,
        filter_noise_lines,
        filter_warning_messages,
        format_log_block,
        is_dask_shutdown_noise,
        strip_ansi,
        workplan_selection_key,
        app_install_status as _app_install_status_impl,
        is_app_installed as _is_app_installed_impl,
    )
except ModuleNotFoundError:
    _page_support_path = Path(__file__).resolve().parent / "orchestrate_page_support.py"
    _page_support_spec = importlib.util.spec_from_file_location(
        "agilab_orchestrate_page_support_fallback",
        _page_support_path,
    )
    if _page_support_spec is None or _page_support_spec.loader is None:
        raise
    _page_support_module = importlib.util.module_from_spec(_page_support_spec)
    _page_support_spec.loader.exec_module(_page_support_module)
    _append_log_lines_impl = _page_support_module.append_log_lines
    _display_log_impl = _page_support_module.display_log
    _init_session_state_impl = _page_support_module.init_session_state
    _clear_log_impl = _page_support_module.clear_log
    _resolve_share_candidate_impl = _page_support_module.resolve_share_candidate
    _clear_cached_distribution_impl = _page_support_module.clear_cached_distribution
    _clear_mount_table_cache_impl = _page_support_module.clear_mount_table_cache
    _update_delete_confirm_state_impl = _page_support_module.update_delete_confirm_state
    _log_indicates_install_failure_impl = _page_support_module.log_indicates_install_failure
    _capture_dataframe_preview_state_impl = _page_support_module.capture_dataframe_preview_state
    _restore_dataframe_preview_state_impl = _page_support_module.restore_dataframe_preview_state
    _toggle_select_all_impl = _page_support_module.toggle_select_all
    _update_select_all_impl = _page_support_module.update_select_all
    _update_log_impl = _page_support_module.update_log
    filter_noise_lines = _page_support_module.filter_noise_lines
    filter_warning_messages = _page_support_module.filter_warning_messages
    format_log_block = _page_support_module.format_log_block
    is_dask_shutdown_noise = _page_support_module.is_dask_shutdown_noise
    workplan_selection_key = _page_support_module.workplan_selection_key
    strip_ansi = _page_support_module.strip_ansi
    _app_install_status_impl = _page_support_module.app_install_status
    _is_app_installed_impl = _page_support_module.is_app_installed

try:
    from agilab.orchestrate_support import (
        looks_like_shared_path as _looks_like_shared_path_impl,
        parse_and_validate_scheduler as _parse_and_validate_scheduler_impl,
        parse_and_validate_workers as _parse_and_validate_workers_impl,
        safe_eval as _safe_eval_impl,
    )
except ModuleNotFoundError:
    _support_path = Path(__file__).resolve().parent / "orchestrate_support.py"
    _support_spec = importlib.util.spec_from_file_location(
        "agilab_orchestrate_support_fallback",
        _support_path,
    )
    if _support_spec is None or _support_spec.loader is None:
        raise
    _support_module = importlib.util.module_from_spec(_support_spec)
    _support_spec.loader.exec_module(_support_module)
    _looks_like_shared_path_impl = _support_module.looks_like_shared_path
    _parse_and_validate_scheduler_impl = _support_module.parse_and_validate_scheduler
    _parse_and_validate_workers_impl = _support_module.parse_and_validate_workers
    _safe_eval_impl = _support_module.safe_eval


def init_session_state(session_state: MutableMapping[str, Any], defaults: Mapping[str, Any]) -> None:
    return _init_session_state_impl(session_state, defaults)


def clear_log(session_state: MutableMapping[str, Any]) -> None:
    return _clear_log_impl(session_state)


def rerun_fragment_or_app(
    rerun: Callable[..., None],
    streamlit_api_exception: type[BaseException],
) -> None:
    try:
        rerun(scope="fragment")
    except streamlit_api_exception:
        rerun()


def update_delete_confirm_state(
    session_state: MutableMapping[str, Any],
    confirm_key: str,
    *,
    delete_armed_clicked: bool,
    delete_cancel_clicked: bool,
) -> bool:
    return _update_delete_confirm_state_impl(
        session_state,
        confirm_key,
        delete_armed_clicked=delete_armed_clicked,
        delete_cancel_clicked=delete_cancel_clicked,
    )


def update_log(
    session_state: MutableMapping[str, Any],
    live_log_placeholder: Any,
    message: str,
    *,
    max_lines: int,
    cluster_verbose: int,
    traceback_state: MutableMapping[str, bool],
    strip_ansi_fn: Callable[[str], str],
    is_dask_shutdown_noise_fn: Callable[[str], bool],
    log_display_max_lines: int,
    live_log_min_height: int,
    max_log_height: int = 500,
) -> None:
    _update_log_impl(
        session_state,
        live_log_placeholder,
        message,
        max_lines=max_lines,
        cluster_verbose=cluster_verbose,
        traceback_state=traceback_state,
        strip_ansi_fn=strip_ansi_fn,
        is_dask_shutdown_noise_fn=is_dask_shutdown_noise_fn,
        log_display_max_lines=log_display_max_lines,
        live_log_min_height=live_log_min_height,
        max_log_height=max_log_height,
    )


def reset_traceback_skip(traceback_state: MutableMapping[str, bool]) -> None:
    traceback_state["active"] = False


def append_log_lines(
    buffer: list[str],
    payload: str,
    *,
    cluster_verbose: int,
    traceback_state: MutableMapping[str, bool],
    is_dask_shutdown_noise_fn: Callable[[str], bool],
) -> None:
    _append_log_lines_impl(
        buffer,
        payload,
        cluster_verbose=cluster_verbose,
        traceback_state=traceback_state,
        is_dask_shutdown_noise_fn=is_dask_shutdown_noise_fn,
    )


def log_indicates_install_failure(lines: list[str]) -> bool:
    return _log_indicates_install_failure_impl(lines)


def looks_like_shared_path(path: Path, project_root: Path) -> bool:
    return _looks_like_shared_path_impl(path, project_root=project_root)


def set_active_app_query_param(query_params: MutableMapping[str, Any], active_app: Any, *, streamlit_api_exception: type[BaseException]) -> None:
    try:
        query_params["active_app"] = active_app
    except streamlit_api_exception:
        return


def clear_cached_distribution(load_distribution_fn: Callable[[], Any]) -> None:
    return _clear_cached_distribution_impl(load_distribution_fn)


def clear_mount_table_cache(mount_table: Any) -> None:
    return _clear_mount_table_cache_impl(mount_table)


def resolve_share_candidate(
    path_value: Any,
    home_abs: Path | str,
    *,
    path_type: Any = Path,
) -> Path:
    return _resolve_share_candidate_impl(path_value, home_abs, path_type=path_type)


def benchmark_display_date(
    benchmark_path: Path,
    date_value: str,
    *,
    os_module: Any = None,
    datetime_type: Any = datetime,
) -> str:
    if date_value:
        return date_value
    if os_module is None:
        import os
        os_module = os
    try:
        ts = os_module.path.getmtime(benchmark_path)
    except OSError:
        return ""
    return datetime_type.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def display_log(
    stdout: str,
    stderr: str,
    *,
    session_state: Mapping[str, Any],
    strip_ansi_fn: Callable[[str], str],
    filter_warning_messages_fn: Callable[[str], str] = filter_warning_messages,
    format_log_block_fn: Callable[[str], str] = lambda text: format_log_block(text, newest_first=False),
    warning_fn: Callable[[str], Any] = lambda message: None,
    error_fn: Callable[[str], Any] = lambda message: None,
    code_fn: Callable[..., Any] = lambda *args, **kwargs: None,
    log_display_max_lines: int = LOG_DISPLAY_MAX_LINES,
    log_display_height: int = 400,
) -> None:
    return _display_log_impl(
        stdout,
        stderr,
        session_state=session_state,
        strip_ansi_fn=strip_ansi_fn,
        filter_warning_messages_fn=filter_warning_messages_fn,
        format_log_block_fn=format_log_block_fn,
        warning_fn=warning_fn,
        error_fn=error_fn,
        code_fn=code_fn,
        log_display_max_lines=log_display_max_lines,
        log_display_height=log_display_height,
    )


def safe_eval(
    expression: str,
    expected_type: Any,
    error_message: str,
    *,
    on_error: Callable[[str], None],
) -> Any:
    return _safe_eval_impl(
        expression,
        expected_type,
        error_message,
        on_error=on_error,
    )


def parse_and_validate_scheduler(
    scheduler: str,
    *,
    is_valid_ip: Callable[[str], bool],
    on_error: Callable[[str], None],
) -> Optional[str]:
    return _parse_and_validate_scheduler_impl(
        scheduler,
        is_valid_ip=is_valid_ip,
        on_error=on_error,
    )


def parse_and_validate_workers(
    workers_input: str,
    *,
    is_valid_ip: Callable[[str], bool],
    on_error: Callable[[str], None],
    default_workers: Optional[dict] = None,
) -> dict[str, int]:
    return _parse_and_validate_workers_impl(
        workers_input,
        is_valid_ip=is_valid_ip,
        on_error=on_error,
        default_workers=default_workers,
    )


def toggle_select_all(session_state: MutableMapping[str, Any]) -> None:
    return _toggle_select_all_impl(session_state)


def update_select_all(session_state: MutableMapping[str, Any]) -> None:
    return _update_select_all_impl(session_state)


def capture_dataframe_preview_state(session_state: Mapping[str, Any]) -> dict[str, Any]:
    return _capture_dataframe_preview_state_impl(session_state)


def restore_dataframe_preview_state(session_state: MutableMapping[str, Any], payload: Mapping[str, Any]) -> None:
    return _restore_dataframe_preview_state_impl(session_state, payload)


def is_app_installed(env: Any) -> bool:
    return _is_app_installed_impl(env)


def app_install_status(env: Any) -> dict[str, Any]:
    return _app_install_status_impl(env)
