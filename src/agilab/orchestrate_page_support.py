from __future__ import annotations

import json
import re
import os
import textwrap
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Any


RUN_MODE_LABELS: tuple[str, ...] = (
    "0: python",
    "1: pool of process",
    "2: cython",
    "3: pool and cython",
    "4: dask",
    "5: dask and pool",
    "6: dask and cython",
    "7: dask and pool and cython",
    "8: rapids",
    "9: rapids and pool",
    "10: rapids and cython",
    "11: rapids and pool and cython",
    "12: rapids and dask",
    "13: rapids and dask and pool",
    "14: rapids and dask and cython",
    "15: rapids and dask and pool and cython",
)

_INSTALL_LOG_FATAL_PATTERNS: tuple[tuple[str, ...], ...] = (
    # ("connection to", "timed out"),
    # ("failed to connect",),
    # ("connection refused",),
    # ("no route to host",),
    # ("ssh_exchange_identification",),
    # ("broken pipe",),
    ("error",),
)

_INSTALL_LOG_FATAL_PATTERNS_LOWER: tuple[tuple[str, ...], ...] = tuple(
    tuple(pattern.lower() for pattern in tokens if pattern)
    for tokens in _INSTALL_LOG_FATAL_PATTERNS
    if tokens
)


def _python_string(value: Any) -> str:
    return json.dumps(str(value))


def strip_ansi(text: str) -> str:
    if not text:
        return ""
    ansi_escape = re.compile(r"\x1b\[[0-9;]*m")
    return ansi_escape.sub("", text)


def is_dask_shutdown_noise(line: str) -> bool:
    """
    Return True when the line is one of the noisy Dask shutdown messages
    that should not surface in the UI.
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


def filter_noise_lines(text: str) -> str:
    return "\n".join(
        line
        for line in text.splitlines()
        if not is_dask_shutdown_noise(line.strip())
    )


def format_log_block(text: str, *, newest_first: bool = True, max_lines: int = 250) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    tail = lines[-max_lines:]
    if newest_first:
        tail = list(reversed(tail))
    return "\n".join(tail)


def filter_warning_messages(log: str) -> str:
    """
    Remove lines containing a specific warning about VIRTUAL_ENV mismatches.
    """
    filtered_lines = [
        line
        for line in log.splitlines()
        if not (
            "VIRTUAL_ENV=" in line
            and "does not match the project environment path" in line
            and ".venv" in line
        )
    ]
    return "\n".join(filtered_lines)


def serialize_args_payload(args: Mapping[str, Any]) -> str:
    return ", ".join(
        f"{key}={_python_string(value)}" if isinstance(value, str) else f"{key}={value!r}"
        for key, value in args.items()
    )


def optional_string_expr(enabled: bool, value: Any) -> str:
    if not enabled or value in (None, ""):
        return "None"
    return _python_string(value)


def optional_python_expr(enabled: bool, value: Any) -> str:
    if not enabled or value in (None, "", {}, []):
        return "None"
    return repr(value)


def build_install_snippet(
    *,
    env: Any,
    verbose: int,
    mode: Any,
    scheduler: str,
    workers: str,
    workers_data_path: str,
) -> str:
    return _build_agi_snippet(
        env=env,
        verbose=verbose,
        method="install",
        arguments=(
            "app_env",
            f"modes_enabled={mode!r}",
            f"scheduler={scheduler}",
            f"workers={workers}",
            f"workers_data_path={workers_data_path}",
        ),
    )


def build_distribution_snippet(
    *,
    env: Any,
    verbose: int,
    scheduler: str,
    workers: str,
    args_serialized: str,
) -> str:
    arguments = [
        "app_env",
        f"scheduler={scheduler}",
        f"workers={workers}",
    ]
    if args_serialized.strip():
        arguments.append(args_serialized)
    return _build_agi_snippet(
        env=env,
        verbose=verbose,
        method="get_distrib",
        arguments=tuple(arguments),
    )


def build_run_snippet(
    *,
    env: Any,
    verbose: int,
    run_mode: int | None,
    scheduler: str,
    workers: str,
    args_serialized: str,
) -> str:
    arguments = [
        "app_env",
        f"mode={run_mode!r}",
        f"scheduler={scheduler}",
        f"workers={workers}",
    ]
    if args_serialized.strip():
        arguments.append(args_serialized)
    return _build_agi_snippet(
        env=env,
        verbose=verbose,
        method="run",
        arguments=tuple(arguments),
    )


def compute_run_mode(cluster_params: Mapping[str, Any], cluster_enabled: bool) -> int:
    return (
        int(cluster_params.get("pool", False))
        + int(cluster_params.get("cython", False)) * 2
        + int(cluster_enabled) * 4
        + int(cluster_params.get("rapids", False)) * 8
    )


def describe_run_mode(run_mode: int | None, benchmark_enabled: bool) -> str:
    if benchmark_enabled:
        return "Run mode benchmark (all modes)"
    if run_mode is None or run_mode < 0 or run_mode >= len(RUN_MODE_LABELS):
        return "Run mode unknown"
    return f"Run mode {RUN_MODE_LABELS[run_mode]}"


def workplan_selection_key(partition: Any, worker_index: int, chunk_index: int) -> str:
    return f"worker_partition_{partition}_{worker_index}_{chunk_index}"


def reassign_distribution_plan(
    *,
    workers: Sequence[str],
    work_plan_metadata: Sequence[Sequence[Any]],
    work_plan: Sequence[Sequence[Any]],
    selections: Mapping[str, Any],
) -> tuple[list[list[Any]], list[list[Any]]]:
    new_work_plan_metadata: list[list[Any]] = [[] for _ in workers]
    new_work_plan: list[list[Any]] = [[] for _ in workers]
    worker_positions = {worker: index for index, worker in enumerate(workers)}

    for worker_index, (chunks, files_tree) in enumerate(zip(work_plan_metadata, work_plan)):
        for chunk_index, (chunk, files) in enumerate(zip(chunks, files_tree)):
            partition = chunk[0] if isinstance(chunk, (list, tuple)) and chunk else None
            selected_worker = selections.get(workplan_selection_key(partition, worker_index, chunk_index))
            if selected_worker not in worker_positions and worker_index < len(workers):
                selected_worker = workers[worker_index]
            target_index = worker_positions.get(selected_worker)
            if target_index is None:
                continue
            new_work_plan_metadata[target_index].append(chunk)
            new_work_plan[target_index].append(files)

    return new_work_plan_metadata, new_work_plan


def update_distribution_payload(
    payload: Mapping[str, Any],
    *,
    target_args: Mapping[str, Any],
    work_plan_metadata: Sequence[Sequence[Any]],
    work_plan: Sequence[Sequence[Any]],
) -> dict[str, Any]:
    updated = dict(payload)
    updated["target_args"] = dict(target_args)
    updated["work_plan_metadata"] = [list(chunks) for chunks in work_plan_metadata]
    updated["work_plan"] = [list(files) for files in work_plan]
    return updated


def _build_agi_snippet(
    *,
    env: Any,
    verbose: int,
    method: str,
    arguments: Sequence[str],
) -> str:
    indented_arguments = ",\n".join(f"        {argument}" for argument in arguments)
    return textwrap.dedent(
        f"""
        import asyncio
        from pathlib import Path
        from agi_cluster.agi_distributor import AGI
        from agi_env import AgiEnv

        APPS_PATH = {_python_string(env.apps_path)}
        APP = {_python_string(env.app)}

        async def main():
            app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose={int(verbose)})
            res = await AGI.{method}(
{indented_arguments}
            )
            print(res)
            return res

        if __name__ == "__main__":
            asyncio.run(main())
        """
    ).strip()


def append_log_lines(
    buffer: list[str],
    payload: str,
    *,
    cluster_verbose: int,
    traceback_state: MutableMapping[str, bool],
    is_dask_shutdown_noise_fn: Callable[[str], bool] = is_dask_shutdown_noise,
) -> None:
    """
    Append filtered log lines to a mutable log buffer.

    At low verbosity, skip traceback sections and Dask shutdown noise while
    preserving skip state across calls through ``traceback_state``.
    """
    filtered = strip_ansi(payload or "")
    if cluster_verbose < 2:
        skip = bool(traceback_state.get("active", False))
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
            if stripped and not is_dask_shutdown_noise_fn(stripped):
                buffer.append(stripped)
        traceback_state["active"] = skip
    else:
        for raw_line in filtered.splitlines():
            stripped = raw_line.rstrip()
            if stripped:
                buffer.append(stripped)


def init_session_state(session_state: Mapping[str, Any], defaults: Mapping[str, Any]) -> None:
    """Initialize session-like state keys that are missing."""
    for key, value in defaults.items():
        session_state.setdefault(key, value)


def clear_log(session_state: MutableMapping[str, Any]) -> None:
    """Clear the accumulated log text in a mutable state mapping."""
    session_state["log_text"] = ""


def update_delete_confirm_state(
    session_state: MutableMapping[str, Any],
    confirm_key: str,
    *,
    delete_armed_clicked: bool,
    delete_cancel_clicked: bool,
) -> bool:
    """Update the delete-confirm state and report if a rerun is required."""
    if delete_armed_clicked:
        session_state[confirm_key] = True
        return True
    if delete_cancel_clicked:
        session_state.pop(confirm_key, None)
        return True
    return False


def clear_cached_distribution(load_distribution_fn: Any) -> None:
    """Clear a cached distribution callable if cache API is available."""
    clear = getattr(load_distribution_fn, "clear", None)
    if callable(clear):
        clear()


def clear_mount_table_cache(mount_table_fn: Any) -> None:
    """Clear a mount-table cache when cluster settings are updated."""
    clear = getattr(mount_table_fn, "cache_clear", None)
    if callable(clear):
        clear()


def resolve_share_candidate(path_value: Any, home_abs: str | Path, *, path_type=Path) -> Path:
    """Resolve share candidate paths without raising on bad references."""
    share_candidate = path_type(path_value)
    if not share_candidate.is_absolute():
        share_candidate = path_type(home_abs) / share_candidate
    share_candidate = share_candidate.expanduser()
    try:
        return share_candidate.resolve()
    except OSError:
        return share_candidate


def benchmark_display_date(benchmark_path: Path, date_value: str) -> str:
    """Return the benchmark date string, using file mtime when no date is provided."""
    if date_value:
        return date_value
    try:
        ts = os.path.getmtime(benchmark_path)
    except OSError:
        return ""
    from datetime import datetime

    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def is_app_installed(env: Any) -> bool:
    """Return whether both manager and worker virtual environments are present."""
    manager_venv = env.active_app / ".venv"
    worker_venv = env.wenv_abs / ".venv"
    return manager_venv.exists() and worker_venv.exists()


def app_install_status(env: Any) -> dict[str, Any]:
    """Return a cached status map for manager/worker installation readiness."""
    manager_venv = env.active_app / ".venv"
    worker_venv = env.wenv_abs / ".venv"
    return {
        "manager_ready": manager_venv.exists(),
        "worker_ready": worker_venv.exists(),
        "manager_venv": manager_venv,
        "worker_venv": worker_venv,
    }


def log_indicates_install_failure(lines: list[str]) -> bool:
    """Return True when install logs likely indicate transport failure."""
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


def capture_dataframe_preview_state(session_state: Mapping[str, Any]) -> dict[str, Any]:
    """Capture dataframe preview-related state for one-step undo."""
    df_cols_raw = session_state.get("df_cols", [])
    selected_cols_raw = session_state.get("selected_cols", [])
    df_cols = list(df_cols_raw) if isinstance(df_cols_raw, (list, tuple)) else []
    selected_cols = list(selected_cols_raw) if isinstance(selected_cols_raw, (list, tuple)) else []
    return {
        "loaded_df": session_state.get("loaded_df"),
        "loaded_graph": session_state.get("loaded_graph"),
        "loaded_source_path": session_state.get("loaded_source_path"),
        "df_cols": df_cols,
        "selected_cols": selected_cols,
        "check_all": bool(session_state.get("check_all", False)),
        "force_export_open": bool(session_state.get("_force_export_open", False)),
        "dataframe_deleted": bool(session_state.get("dataframe_deleted", False)),
    }


def restore_dataframe_preview_state(
    session_state: MutableMapping[str, Any],
    payload: Mapping[str, Any],
) -> None:
    """Restore dataframe preview state from a snapshot."""
    session_state["loaded_df"] = payload.get("loaded_df")
    if payload.get("loaded_graph") is None:
        session_state.pop("loaded_graph", None)
    else:
        session_state["loaded_graph"] = payload.get("loaded_graph")

    source_path = payload.get("loaded_source_path")
    if source_path:
        session_state["loaded_source_path"] = source_path
    else:
        session_state.pop("loaded_source_path", None)

    df_cols_raw = payload.get("df_cols", [])
    selected_cols_raw = payload.get("selected_cols", [])
    df_cols = list(df_cols_raw) if isinstance(df_cols_raw, (list, tuple)) else []
    selected_cols = [col for col in (selected_cols_raw or []) if col in df_cols]
    requested_all = bool(payload.get("check_all", False))
    if requested_all and df_cols:
        selected_cols = df_cols.copy()

    session_state["df_cols"] = df_cols
    session_state["selected_cols"] = selected_cols
    session_state["check_all"] = bool(df_cols) and len(selected_cols) == len(df_cols)
    session_state["_force_export_open"] = bool(payload.get("force_export_open", False))
    session_state["dataframe_deleted"] = bool(payload.get("dataframe_deleted", False))

    for key in [key for key in list(session_state.keys()) if key.startswith("export_col_")]:
        session_state.pop(key, None)
    for idx, col in enumerate(df_cols):
        session_state[f"export_col_{idx}"] = col in selected_cols


def toggle_select_all(session_state: MutableMapping[str, Any]) -> None:
    """Update selected dataframe columns based on a pre-set ``check_all`` flag."""
    if session_state.get("check_all"):
        session_state["selected_cols"] = list(session_state.get("df_cols", []))
    else:
        session_state["selected_cols"] = []


def update_select_all(session_state: MutableMapping[str, Any]) -> None:
    """Synchronize ``check_all`` and selected column state from checkbox session flags."""
    df_cols_raw = session_state.get("df_cols", [])
    df_cols = list(df_cols_raw) if isinstance(df_cols_raw, (list, tuple)) else []
    all_selected = all(session_state.get(f"export_col_{i}", False) for i in range(len(df_cols)))
    session_state["check_all"] = all_selected
    session_state["selected_cols"] = [
        col for i, col in enumerate(df_cols) if session_state.get(f"export_col_{i}", False)
    ]
