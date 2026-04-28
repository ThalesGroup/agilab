from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any


class OrchestrateWorkflowStatus(str, Enum):
    SINGLE_RUN = "single-run"
    BENCHMARK = "benchmark"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class OrchestratePageStateDeps:
    available_benchmark_modes: Callable[..., Sequence[int]]
    sanitize_benchmark_modes: Callable[[Any, Sequence[int]], Sequence[int]]
    resolve_requested_run_mode: Callable[..., int | list[int]]
    describe_run_mode: Callable[[int | list[int] | None, bool], str]
    benchmark_workers_data_path_issue: Callable[..., str]
    optional_string_expr: Callable[[bool, Any], str]
    optional_python_expr: Callable[[bool, Any], str]


@dataclass(frozen=True)
class OrchestratePageState:
    status: OrchestrateWorkflowStatus
    cluster_enabled: bool
    benchmark_enabled: bool
    available_benchmark_modes: tuple[int, ...]
    selected_benchmark_modes: tuple[int, ...]
    run_mode: int | list[int]
    run_mode_label: str
    verbose: int
    scheduler: str
    workers: str
    raw_workers_data_path: Any
    workers_data_path: str
    workers_data_path_issue: str
    rapids_enabled: bool
    can_run: bool
    run_disabled_reason: str


def _coerce_int_tuple(values: Sequence[Any]) -> tuple[int, ...]:
    result: list[int] = []
    for value in values:
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return tuple(result)


def _coerce_verbose(value: Any) -> int:
    if isinstance(value, bool):
        return 1
    try:
        verbose = int(value)
    except (TypeError, ValueError):
        return 1
    return verbose if verbose >= 0 else 1


def build_orchestrate_page_state(
    *,
    cluster_params: Mapping[str, Any],
    selected_benchmark_modes: Sequence[Any],
    local_share_path: Any = None,
    deps: OrchestratePageStateDeps,
) -> OrchestratePageState:
    """Build the pure ORCHESTRATE run-mode view model."""
    cluster_enabled = bool(cluster_params.get("cluster_enabled", False))
    available_modes = _coerce_int_tuple(
        deps.available_benchmark_modes(
            cluster_params,
            cluster_enabled=cluster_enabled,
        )
    )
    sanitized_modes = _coerce_int_tuple(
        deps.sanitize_benchmark_modes(selected_benchmark_modes, available_modes)
    )
    benchmark_enabled = bool(sanitized_modes)
    run_mode = deps.resolve_requested_run_mode(
        cluster_params,
        cluster_enabled=cluster_enabled,
        benchmark_enabled=benchmark_enabled,
        benchmark_modes=list(sanitized_modes),
    )
    run_mode_label = str(deps.describe_run_mode(run_mode, benchmark_enabled))

    enabled = cluster_enabled
    raw_workers_data_path = cluster_params.get("workers_data_path", "")
    workers_data_path_issue = deps.benchmark_workers_data_path_issue(
        modes=sanitized_modes,
        workers=cluster_params.get("workers"),
        workers_data_path=raw_workers_data_path,
        local_share_path=local_share_path,
    )
    can_run = not bool(workers_data_path_issue)
    status = (
        OrchestrateWorkflowStatus.BLOCKED
        if workers_data_path_issue
        else OrchestrateWorkflowStatus.BENCHMARK
        if benchmark_enabled
        else OrchestrateWorkflowStatus.SINGLE_RUN
    )
    rapids_enabled = (
        any(int(mode) & 8 for mode in sanitized_modes)
        if benchmark_enabled
        else bool(cluster_params.get("rapids", False))
    )

    return OrchestratePageState(
        status=status,
        cluster_enabled=cluster_enabled,
        benchmark_enabled=benchmark_enabled,
        available_benchmark_modes=available_modes,
        selected_benchmark_modes=sanitized_modes,
        run_mode=run_mode,
        run_mode_label=run_mode_label,
        verbose=_coerce_verbose(cluster_params.get("verbose", 1)),
        scheduler=deps.optional_string_expr(enabled, cluster_params.get("scheduler")),
        workers=deps.optional_python_expr(enabled, cluster_params.get("workers")),
        raw_workers_data_path=raw_workers_data_path,
        workers_data_path=deps.optional_string_expr(enabled, raw_workers_data_path),
        workers_data_path_issue=workers_data_path_issue,
        rapids_enabled=rapids_enabled,
        can_run=can_run,
        run_disabled_reason=workers_data_path_issue,
    )
