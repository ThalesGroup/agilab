from __future__ import annotations

import json
import re
import os
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Any

from agi_env.snippet_contract import snippet_contract_block


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

BENCHMARK_MODE_COLUMN_HELP = (
    "Mode is a 4-slot execution signature: r=RAPIDS/GPU, d=Dask/cluster, "
    "c=Cython build, p=worker pool (process or thread backend). _ means disabled."
)

BENCHMARK_MODE_LEGEND_MARKDOWN = (
    "**Mode legend**  \n"
    "`mode` is a 4-slot execution signature: `r d c p`.  \n"
    "`r` RAPIDS/GPU, `d` Dask/cluster, `c` Cython build, "
    "`p` worker pool (process or thread backend).  \n"
    "`_` means that slot is disabled. Examples: `____` local Python, "
    "`_d__` Dask only, `__cp` Cython + pool, `rdcp` full acceleration."
)

_INSTALL_LOG_FATAL_PATTERNS: tuple[tuple[str, ...], ...] = (
    ("traceback",),
    ("unhandled exception",),
    ("command failed with exit code",),
    ("process exited with non-zero exit status",),
    ("non-zero exit status",),
    ("install finished with errors",),
    ("worker start hook failed",),
    ("connection to", "timed out"),
    ("failed to connect",),
    ("connection refused",),
    ("no route to host",),
    ("ssh_exchange_identification",),
    ("broken pipe",),
    ("timeout expired",),
)

_INSTALL_LOG_FATAL_PATTERNS_LOWER: tuple[tuple[str, ...], ...] = tuple(
    tuple(pattern.lower() for pattern in tokens if pattern)
    for tokens in _INSTALL_LOG_FATAL_PATTERNS
    if tokens
)

_INSTALL_LOG_NON_FATAL_LINE_PATTERNS: tuple[tuple[str, ...], ...] = (
    ("failed to update uv", "skipping self update"),
    ("remote command stderr:", "error: permission denied", "os error 13"),
)

_INSTALL_LOG_NON_FATAL_LINE_PATTERNS_LOWER: tuple[tuple[str, ...], ...] = tuple(
    tuple(pattern.lower() for pattern in tokens if pattern)
    for tokens in _INSTALL_LOG_NON_FATAL_LINE_PATTERNS
    if tokens
)


def _python_string(value: Any) -> str:
    return json.dumps(str(value))


def snippet_apps_path(env: Any) -> str:
    apps_path = getattr(env, "apps_path", "")
    app = str(getattr(env, "app", "") or "")
    active_app = getattr(env, "active_app", None)

    if isinstance(active_app, Path) and active_app.parent.name == "builtin":
        return str(active_app.parent)

    if apps_path and app:
        try:
            candidate = Path(str(apps_path)) / "builtin" / app
            if candidate.exists():
                return str(candidate.parent)
        except (OSError, RuntimeError, TypeError, ValueError):
            pass

    return str(apps_path)


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


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def _json_load_expr(value: Any) -> str:
    literal = json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True)
    return f"json.loads({literal!r})"


def _split_run_request_payload(run_args: Mapping[str, Any] | None) -> tuple[dict[str, Any], list[Any], Any, Any, bool | None]:
    payload = dict(run_args or {})
    steps = payload.pop("args", [])
    if steps is None:
        steps = []
    if not isinstance(steps, list):
        raise TypeError("RunRequest steps must be stored as an 'args' list in app settings")
    data_in = payload.pop("data_in", None)
    data_out = payload.pop("data_out", None)
    reset_target = payload.pop("reset_target", None)
    return payload, steps, data_in, data_out, reset_target


def resolve_project_change_args_override(
    *,
    is_args_from_ui: bool,
    args_project: Any,
    previous_project: Any,
    app_settings_snapshot: Any,
) -> dict[str, Any] | None:
    if not is_args_from_ui or args_project != previous_project:
        return None
    if not isinstance(app_settings_snapshot, dict):
        return None
    state_args = app_settings_snapshot.get("args")
    if not isinstance(state_args, dict) or not state_args:
        return None
    return state_args


def merge_app_settings_sources(
    file_settings: Any,
    session_settings: Any,
) -> dict[str, Any]:
    """
    Merge persisted app settings with the current session snapshot.

    `args` is the only section that should merge file + session state because
    app forms may stage in-memory edits before persisting them. `cluster`
    remains file-backed on purpose: the cluster UI writes it immediately to the
    workspace settings file and widget state is rehydrated separately, which
    avoids stale session dicts re-enabling cluster mode on rerun.
    """
    merged: dict[str, Any] = {}

    if isinstance(file_settings, Mapping):
        merged.update(file_settings)

    if isinstance(session_settings, Mapping):
        for key, value in session_settings.items():
            if key == "args" and isinstance(value, Mapping):
                base = merged.get(key, {})
                if isinstance(base, Mapping):
                    merged[key] = {**base, **value}
                else:
                    merged[key] = dict(value)
            elif key != "cluster":
                merged[key] = value

    args_value = merged.get("args")
    if isinstance(args_value, Mapping):
        merged["args"] = dict(args_value)
    elif "args" not in merged:
        merged["args"] = {}

    cluster_value = merged.get("cluster")
    merged["cluster"] = dict(cluster_value) if isinstance(cluster_value, Mapping) else {}
    return merged


def optional_string_expr(enabled: bool, value: Any) -> str:
    if not enabled or value in (None, ""):
        return "None"
    return _python_string(value)


def optional_python_expr(enabled: bool, value: Any) -> str:
    if not enabled or value in (None, "", {}, []):
        return "None"
    return repr(value)


def _install_scheduler_expr(scheduler: str) -> str:
    """Return the scheduler expression expected by ``AGI.install``.

    The ORCHESTRATE UI stores scheduler addresses as ``HOST:PORT`` because run
    mode needs the Dask scheduler endpoint. The install path only needs the
    scheduler host to stage worker environments and validates it as an IP.
    """

    if scheduler in ("", "None"):
        return scheduler
    try:
        value = json.loads(scheduler)
    except (TypeError, ValueError, json.JSONDecodeError):
        return scheduler
    if not isinstance(value, str):
        return scheduler
    host, sep, port = value.strip().rpartition(":")
    if sep and host and port.isdigit():
        return _python_string(host)
    return scheduler


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
            f"scheduler={_install_scheduler_expr(scheduler)}",
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
    run_mode: int | list[int] | None,
    scheduler: str,
    workers: str,
    run_args: Mapping[str, Any] | None,
    workers_data_path: str = "None",
    rapids_enabled: bool = False,
    benchmark_best_single_node: bool = False,
) -> str:
    params, steps, data_in, data_out, reset_target = _split_run_request_payload(run_args)
    workers_data_path_expr = workers_data_path if workers_data_path not in ("", None) else "None"
    snippet_lines = [
        "import asyncio",
        "import json",
        "",
        "from agi_cluster.agi_distributor import AGI, RunRequest, StepRequest",
        "from agi_env import AgiEnv",
        snippet_contract_block(app=str(env.app), generator="agilab.orchestrate"),
        "",
        f"APPS_PATH = {_python_string(snippet_apps_path(env))}",
        f"APP = {_python_string(env.app)}",
        f"RUN_PARAMS = {_json_load_expr(params)}",
        f"RUN_STEPS_PAYLOAD = {_json_load_expr(steps)}",
        f"RUN_DATA_IN = {_json_load_expr(data_in)}",
        f"RUN_DATA_OUT = {_json_load_expr(data_out)}",
        f"RUN_RESET_TARGET = {_json_load_expr(reset_target)}",
        "",
        "async def main():",
        f"    app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose={int(verbose)})",
        "    run_steps = [",
        "        StepRequest(name=step['name'], args=step.get('args') or {})",
        "        for step in RUN_STEPS_PAYLOAD",
        "    ]",
        "    request = RunRequest(",
        "        params=RUN_PARAMS,",
        "        steps=run_steps,",
        "        data_in=RUN_DATA_IN,",
        "        data_out=RUN_DATA_OUT,",
        "        reset_target=RUN_RESET_TARGET,",
        f"        mode={run_mode!r},",
        f"        scheduler={scheduler},",
        f"        workers={workers},",
        f"        workers_data_path={workers_data_path_expr},",
        f"        rapids_enabled={bool(rapids_enabled)!r},",
        f"        benchmark_best_single_node={bool(benchmark_best_single_node)!r},",
        "    )",
        "    res = await AGI.run(app_env, request=request)",
        "    print(res)",
        "    return res",
        "",
        'if __name__ == "__main__":',
        "    asyncio.run(main())",
    ]
    return "\n".join(snippet_lines).strip()


def compute_run_mode(cluster_params: Mapping[str, Any], cluster_enabled: bool) -> int:
    return (
        int(cluster_params.get("pool", False))
        + int(cluster_params.get("cython", False)) * 2
        + int(cluster_enabled) * 4
        + int(cluster_params.get("rapids", False)) * 8
    )


_POOL_MODE_BIT = 1
_CYTHON_MODE_BIT = 2
_DASK_MODE_BIT = 4
_RAPIDS_MODE_BIT = 8


def available_benchmark_modes(
    cluster_params: Mapping[str, Any],
    *,
    cluster_enabled: bool,
) -> list[int]:
    """Return modes whose required capabilities are currently enabled in the UI."""
    available: list[int] = []
    for mode in range(len(RUN_MODE_LABELS)):
        if mode & _POOL_MODE_BIT and not cluster_params.get("pool", False):
            continue
        if mode & _CYTHON_MODE_BIT and not cluster_params.get("cython", False):
            continue
        if mode & _DASK_MODE_BIT and not cluster_enabled:
            continue
        if mode & _RAPIDS_MODE_BIT and not cluster_params.get("rapids", False):
            continue
        available.append(mode)
    return available


def benchmark_mode_label(mode: int) -> str:
    if mode < 0 or mode >= len(RUN_MODE_LABELS):
        return f"{mode}: unknown"
    return RUN_MODE_LABELS[mode]


def _benchmark_seconds(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _best_node_rapids_counterpart_key(key: str) -> str | None:
    mode_text, separator, suffix = key.partition(":")
    if separator != ":" or suffix != "best-node":
        return None
    try:
        mode = int(mode_text)
    except ValueError:
        return None
    if mode & _RAPIDS_MODE_BIT:
        return None
    return f"{mode | _RAPIDS_MODE_BIT}:best-node"


def _drop_shadowed_best_node_non_rapids_rows(rows: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(rows)
    for key, row in list(rows.items()):
        if not isinstance(row, Mapping):
            continue
        counterpart_key = _best_node_rapids_counterpart_key(key)
        if counterpart_key is None:
            continue
        counterpart = rows.get(counterpart_key)
        if not isinstance(counterpart, Mapping):
            continue
        if row.get("variant") != "best-node" or counterpart.get("variant") != "best-node":
            continue
        if str(row.get("node", "")) != str(counterpart.get("node", "")):
            continue
        normalized.pop(key, None)
    return normalized


def benchmark_rows_with_delta_percent(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Return benchmark rows augmented with a display-only percent delta."""
    rows: dict[str, Any] = {}
    numeric_seconds: list[float] = []
    for key, value in raw.items():
        if not isinstance(value, Mapping):
            rows[str(key)] = value
            continue
        row = dict(value)
        seconds = _benchmark_seconds(row.get("seconds"))
        if seconds is not None:
            numeric_seconds.append(seconds)
        rows[str(key)] = row
    rows = _drop_shadowed_best_node_non_rapids_rows(rows)
    numeric_seconds = [
        seconds
        for row in rows.values()
        if isinstance(row, Mapping)
        for seconds in [_benchmark_seconds(row.get("seconds"))]
        if seconds is not None
    ]

    if not numeric_seconds:
        return rows

    best_seconds = min(numeric_seconds)
    for row in rows.values():
        if not isinstance(row, dict):
            continue
        seconds = _benchmark_seconds(row.get("seconds"))
        if seconds is None:
            continue
        if best_seconds > 0:
            row["delta (%)"] = round(((seconds - best_seconds) / best_seconds) * 100.0, 2)
        else:
            row["delta (%)"] = 0.0 if seconds == best_seconds else None
    return rows


def sanitize_benchmark_modes(
    selected_modes: Any,
    available_modes: Sequence[int],
) -> list[int]:
    available = {int(mode) for mode in available_modes}
    sanitized: list[int] = []
    if not isinstance(selected_modes, Sequence) or isinstance(selected_modes, (str, bytes)):
        return sanitized
    for raw_mode in selected_modes:
        try:
            mode = int(raw_mode)
        except (TypeError, ValueError):
            continue
        if mode in available and mode not in sanitized:
            sanitized.append(mode)
    return sorted(sanitized)


def compute_benchmark_run_mode(
    cluster_params: Mapping[str, Any],
    cluster_enabled: bool,
) -> list[int]:
    return available_benchmark_modes(cluster_params, cluster_enabled=cluster_enabled)


def benchmark_modes_include_cluster(modes: Sequence[int]) -> bool:
    return any(int(mode) & _DASK_MODE_BIT for mode in modes)


def order_benchmark_display_columns(columns: Sequence[Any]) -> list[Any]:
    """Return display columns with benchmark execution context near mode."""
    ordered = list(columns)
    context_order = ["variant", "nodes", "node", "mode"]
    context_columns = [column for column in context_order if column in ordered]
    if not context_columns:
        return ordered
    insert_index = min(ordered.index(column) for column in context_columns)
    remaining = [column for column in ordered if column not in context_columns]
    return remaining[:insert_index] + context_columns + remaining[insert_index:]


def benchmark_dataframe_column_config(column_config_module: Any) -> dict[str, Any]:
    """Return Streamlit column config for the benchmark results dataframe."""
    text_column = getattr(column_config_module, "TextColumn", None)
    if not callable(text_column):
        return {}
    return {
        "mode": text_column(
            "mode",
            help=BENCHMARK_MODE_COLUMN_HELP,
        )
    }


_LOCAL_WORKER_HOSTS = {"", "127.0.0.1", "localhost", "::1", "0.0.0.0"}


def _worker_host(worker_key: Any) -> str:
    host = str(worker_key or "").strip()
    if "://" in host:
        host = host.rsplit("://", 1)[-1]
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    if host.startswith("[") and "]" in host:
        return host[1:host.index("]")].strip().lower()
    if host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host.strip().lower()


def has_nonlocal_workers(workers: Any) -> bool:
    if not isinstance(workers, Mapping):
        return False
    return any(_worker_host(worker) not in _LOCAL_WORKER_HOSTS for worker in workers)


def _resolved_path(value: Any) -> Path | None:
    if value in (None, ""):
        return None
    try:
        return Path(str(value)).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def benchmark_workers_data_path_issue(
    *,
    modes: Sequence[int],
    workers: Any,
    workers_data_path: Any,
    local_share_path: Any = None,
) -> str:
    if not benchmark_modes_include_cluster(modes) or not has_nonlocal_workers(workers):
        return ""

    data_path_text = str(workers_data_path or "").strip()
    if not data_path_text or data_path_text.lower() == "none":
        return (
            "Benchmark modes using Dask with non-local workers require Workers Data Path. "
            "Use a shared path visible from the remote workers."
        )

    data_path = _resolved_path(data_path_text)
    local_share = _resolved_path(local_share_path)
    if data_path is not None and local_share is not None and data_path == local_share:
        return (
            "Workers Data Path points to the local share. For Dask benchmark modes with "
            "non-local workers, use a shared workers path instead of the manager-local path."
        )
    return ""


def resolve_requested_run_mode(
    cluster_params: Mapping[str, Any],
    *,
    cluster_enabled: bool,
    benchmark_enabled: bool,
    benchmark_modes: Sequence[int] | None = None,
) -> int | list[int]:
    if benchmark_enabled:
        if benchmark_modes is not None:
            return sanitize_benchmark_modes(
                benchmark_modes,
                available_benchmark_modes(cluster_params, cluster_enabled=cluster_enabled),
            )
        return compute_benchmark_run_mode(cluster_params, cluster_enabled)
    return compute_run_mode(cluster_params, cluster_enabled)


def describe_run_mode(run_mode: int | list[int] | None, benchmark_enabled: bool) -> str:
    if benchmark_enabled:
        if isinstance(run_mode, list) and run_mode:
            mode_list = ", ".join(str(mode) for mode in run_mode)
            return f"Run mode benchmark (selected modes: {mode_list})"
        return "Run mode benchmark (no mode selected)"
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
    snippet_lines = [
        "import asyncio",
    ]
    snippet_lines.extend(
        [
            "",
            "from agi_cluster.agi_distributor import AGI",
            "from agi_env import AgiEnv",
            snippet_contract_block(app=str(env.app), generator="agilab.orchestrate"),
            "",
            f"APPS_PATH = {_python_string(snippet_apps_path(env))}",
            f"APP = {_python_string(env.app)}",
            "",
            "async def main():",
            f"    app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose={int(verbose)})",
            f"    res = await AGI.{method}(",
            indented_arguments,
            "    )",
            "    print(res)",
            "    return res",
            "",
            'if __name__ == "__main__":',
            "    asyncio.run(main())",
        ]
    )
    return "\n".join(snippet_lines).strip()


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
    """Append a cleaned message to accumulated log and refresh live display."""
    if "log_text" not in session_state:
        session_state["log_text"] = ""

    clean_msg = strip_ansi_fn(message).rstrip()
    if cluster_verbose < 2:
        if bool(traceback_state.get("active", False)):
            if not clean_msg:
                traceback_state["active"] = False
            return
        if clean_msg.lower().startswith("traceback (most recent call last"):
            traceback_state["active"] = True
            return
        if is_dask_shutdown_noise_fn(clean_msg):
            return
    if clean_msg:
        session_state["log_text"] += clean_msg + "\n"

    lines = str(session_state.get("log_text", "")).splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
        session_state["log_text"] = "\n".join(lines) + "\n"

    display_lines = lines[-log_display_max_lines:]
    live_view = "\n".join(display_lines)
    line_count = max(len(display_lines), 1)
    height_px = min(max(20 * line_count, live_log_min_height), max_log_height)
    live_log_placeholder.code(live_view, language="python", height=height_px)


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
    log_display_max_lines: int = 250,
    log_display_height: int = 400,
) -> None:
    """Render combined stdout/stderr logs with warning and error normalization."""
    if not stdout.strip() and "log_text" in session_state:
        stdout = str(session_state.get("log_text", ""))

    clean_stdout = filter_warning_messages_fn(strip_ansi_fn(stdout or ""))
    clean_stderr = filter_warning_messages_fn(strip_ansi_fn(stderr or ""))
    clean_stdout = "\n".join(line for line in clean_stdout.splitlines() if line.strip())
    clean_stderr = "\n".join(line for line in clean_stderr.splitlines() if line.strip())

    combined = "\n".join([clean_stdout, clean_stderr]).strip()

    if "warning:" in combined.lower():
        warning_fn("Warnings occurred during cluster installation:")
        code_fn(
            format_log_block_fn(combined),
            language="python",
            height=log_display_height,
        )
    elif clean_stderr:
        error_fn("Errors occurred during cluster installation:")
        code_fn(
            format_log_block_fn(clean_stderr),
            language="python",
            height=log_display_height,
        )
    else:
        code_fn(
            format_log_block_fn(clean_stdout) or "No logs available",
            language="python",
            height=log_display_height,
        )


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


def configured_cluster_share_matches(
    path_value: Any,
    *,
    cluster_share_path: Any,
    home_abs: str | Path,
    path_type=Path,
) -> bool:
    """Return whether a path is the configured cluster-share root.

    The scheduler-side source of a remote share may still report as a local
    filesystem such as APFS. In that case the explicit AGI_CLUSTER_SHARE
    contract is a stronger signal than the local filesystem type.
    """
    if cluster_share_path in (None, ""):
        return False
    try:
        candidate = resolve_share_candidate(path_value, home_abs, path_type=path_type)
        configured = resolve_share_candidate(cluster_share_path, home_abs, path_type=path_type)
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    return candidate == configured


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
    """Return True when install logs likely indicate fatal install failure."""
    if not lines or not _INSTALL_LOG_FATAL_PATTERNS_LOWER:
        return False

    for raw_line in lines[-200:]:
        line = str(raw_line).lower()
        if any(
            all(token in line for token in pattern)
            for pattern in _INSTALL_LOG_NON_FATAL_LINE_PATTERNS_LOWER
        ):
            continue
        if any(all(token in line for token in pattern) for pattern in _INSTALL_LOG_FATAL_PATTERNS_LOWER):
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
