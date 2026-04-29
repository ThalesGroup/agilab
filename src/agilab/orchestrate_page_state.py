from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any


class OrchestrateWorkflowStatus(str, Enum):
    SINGLE_RUN = "single-run"
    BENCHMARK = "benchmark"
    BLOCKED = "blocked"


class OrchestrateExecuteAction(str, Enum):
    RUN = "run"
    COMBO = "combo"


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


@dataclass(frozen=True)
class OrchestrateActionReadiness:
    action: OrchestrateExecuteAction
    enabled: bool
    disabled_reason: str
    missing_install_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class OrchestrateExecuteWorkflowState:
    show_run_panel: bool
    command_configured: bool
    manager_venv_path: Path
    worker_venv_path: Path | None
    missing_install_paths: tuple[str, ...]
    actions: Mapping[OrchestrateExecuteAction, OrchestrateActionReadiness]
    blocked_actions: Mapping[OrchestrateExecuteAction, str]

    @property
    def run_action(self) -> OrchestrateActionReadiness:
        return self.actions[OrchestrateExecuteAction.RUN]

    @property
    def combo_action(self) -> OrchestrateActionReadiness:
        return self.actions[OrchestrateExecuteAction.COMBO]


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


def _missing_install_paths(manager_venv: Path, worker_venv: Path | None) -> tuple[str, ...]:
    missing: list[str] = []
    if not manager_venv.exists():
        missing.append(f"manager venv `{manager_venv}`")
    if worker_venv is None:
        missing.append("worker venv `<unknown>`")
    elif not worker_venv.exists():
        missing.append(f"worker venv `{worker_venv}`")
    return tuple(missing)


def _install_gap_reason(action_label: str, missing_install_paths: tuple[str, ...]) -> str:
    return (
        f"{action_label} is unavailable because the installation is incomplete. "
        "Run INSTALL first to create: " + ", ".join(missing_install_paths)
    )


def _execute_readiness(
    *,
    action: OrchestrateExecuteAction,
    show_run_panel: bool,
    command_configured: bool,
    missing_install_paths: tuple[str, ...],
) -> OrchestrateActionReadiness:
    if not show_run_panel:
        return OrchestrateActionReadiness(
            action=action,
            enabled=False,
            disabled_reason="`Serve` mode selected. Switch to `Run now` to access EXECUTE / LOAD / EXPORT actions.",
            missing_install_paths=missing_install_paths,
        )
    if not command_configured:
        return OrchestrateActionReadiness(
            action=action,
            enabled=False,
            disabled_reason="No EXECUTE command configured; please configure it first.",
            missing_install_paths=missing_install_paths,
        )
    if missing_install_paths:
        action_label = "EXECUTE" if action is OrchestrateExecuteAction.RUN else "EXECUTE \u2192 LOAD \u2192 EXPORT"
        return OrchestrateActionReadiness(
            action=action,
            enabled=False,
            disabled_reason=_install_gap_reason(action_label, missing_install_paths),
            missing_install_paths=missing_install_paths,
        )
    return OrchestrateActionReadiness(
        action=action,
        enabled=True,
        disabled_reason="",
        missing_install_paths=(),
    )


def build_orchestrate_execute_workflow_state(
    *,
    show_run_panel: bool,
    cmd: str | None,
    project_path: Path | str,
    worker_env_path: Path | str | None,
) -> OrchestrateExecuteWorkflowState:
    """Build the pure ORCHESTRATE execute/combo action state."""
    manager_venv = Path(project_path) / ".venv"
    worker_venv = Path(worker_env_path) / ".venv" if worker_env_path else None
    missing_paths = _missing_install_paths(manager_venv, worker_venv)
    command_configured = bool(cmd)
    actions = {
        action: _execute_readiness(
            action=action,
            show_run_panel=show_run_panel,
            command_configured=command_configured,
            missing_install_paths=missing_paths,
        )
        for action in OrchestrateExecuteAction
    }
    blocked_actions = {
        action: readiness.disabled_reason
        for action, readiness in actions.items()
        if not readiness.enabled
    }
    return OrchestrateExecuteWorkflowState(
        show_run_panel=show_run_panel,
        command_configured=command_configured,
        manager_venv_path=manager_venv,
        worker_venv_path=worker_venv,
        missing_install_paths=missing_paths,
        actions=MappingProxyType(actions),
        blocked_actions=MappingProxyType(blocked_actions),
    )


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
