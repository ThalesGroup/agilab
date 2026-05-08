from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from agilab.runtime_diagnostics import coerce_diagnostics_verbose


class OrchestrateWorkflowStatus(str, Enum):
    SINGLE_RUN = "single-run"
    BENCHMARK = "benchmark"
    BLOCKED = "blocked"


class OrchestrateExecuteAction(str, Enum):
    RUN = "run"
    COMBO = "combo"


class OrchestrateSetupAction(str, Enum):
    INSTALL = "install"
    DISTRIBUTE = "distribute"


class OrchestrateRunArtifactStatus(str, Enum):
    MISSING = "missing"
    LOADED = "loaded"
    DELETED = "deleted"


class OrchestrateRunArtifactAction(str, Enum):
    LOAD = "load"
    DELETE = "delete"
    EXPORT = "export"
    STATS = "stats"


class OrchestrateWorkflowPhase(str, Enum):
    NOT_INSTALLED = "not_installed"
    INSTALL_READY = "install_ready"
    INSTALLED = "installed"
    DISTRIBUTE_READY = "distribute_ready"
    DISTRIBUTION_GENERATED = "distribution_generated"
    RUNNABLE = "runnable"


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
    benchmark_best_single_node: bool
    run_mode: int | list[int]
    run_mode_label: str
    verbose: int
    scheduler: str
    workers: str
    raw_workers_data_path: Any
    workers_data_path: str
    workers_data_path_issue: str
    cluster_share_issue: str
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


@dataclass(frozen=True)
class OrchestrateSetupActionReadiness:
    action: OrchestrateSetupAction
    enabled: bool
    disabled_reason: str


@dataclass(frozen=True)
class OrchestrateInstallWorkflowState:
    show_install: bool
    command_configured: bool
    cluster_enabled: bool
    runtime_root: Path | None
    install_command: str | None
    context_lines: tuple[str, ...]
    action: OrchestrateSetupActionReadiness


@dataclass(frozen=True)
class OrchestrateDistributionWorkflowState:
    show_distribute: bool
    command_configured: bool
    distribution_path: Path | None
    action: OrchestrateSetupActionReadiness


@dataclass(frozen=True)
class OrchestrateRunArtifactReadiness:
    action: OrchestrateRunArtifactAction
    enabled: bool
    disabled_reason: str


@dataclass(frozen=True)
class OrchestrateRunArtifactState:
    status: OrchestrateRunArtifactStatus
    show_run_panel: bool
    deleted: bool
    has_loaded_dataframe: bool
    has_loaded_graph: bool
    loaded_source_path: Path | None
    actions: Mapping[OrchestrateRunArtifactAction, OrchestrateRunArtifactReadiness]
    blocked_actions: Mapping[OrchestrateRunArtifactAction, str]

    @property
    def has_loaded_artifact(self) -> bool:
        return self.has_loaded_dataframe or self.has_loaded_graph

    @property
    def load_action(self) -> OrchestrateRunArtifactReadiness:
        return self.actions[OrchestrateRunArtifactAction.LOAD]

    @property
    def delete_action(self) -> OrchestrateRunArtifactReadiness:
        return self.actions[OrchestrateRunArtifactAction.DELETE]

    @property
    def export_action(self) -> OrchestrateRunArtifactReadiness:
        return self.actions[OrchestrateRunArtifactAction.EXPORT]

    @property
    def stats_action(self) -> OrchestrateRunArtifactReadiness:
        return self.actions[OrchestrateRunArtifactAction.STATS]


@dataclass(frozen=True)
class OrchestrateCombinedWorkflowState:
    phase: OrchestrateWorkflowPhase
    install_ready: bool
    installed: bool
    distribute_ready: bool
    distribution_generated: bool
    runnable: bool
    blocked_reason: str


DISTRIBUTION_PLAN_FILENAME = "distribution_tree.json"
LEGACY_DISTRIBUTION_PLAN_FILENAME = "distribution.json"


def resolve_distribution_plan_path(worker_env_path: Path | str | None) -> Path | None:
    """Return the runtime distribution plan path, preserving old installs as fallback."""
    if worker_env_path is None:
        return None
    worker_root = Path(worker_env_path)
    plan_path = worker_root / DISTRIBUTION_PLAN_FILENAME
    legacy_path = worker_root / LEGACY_DISTRIBUTION_PLAN_FILENAME
    if plan_path.exists() or not legacy_path.exists():
        return plan_path
    return legacy_path


def _coerce_int_tuple(values: Sequence[Any]) -> tuple[int, ...]:
    result: list[int] = []
    for value in values:
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return tuple(result)


def _coerce_verbose(value: Any) -> int:
    return coerce_diagnostics_verbose(value)


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


def _setup_readiness(
    *,
    action: OrchestrateSetupAction,
    visible: bool,
    command_configured: bool,
    runtime_ready: bool = True,
    hidden_reason: str,
    missing_command_reason: str,
    runtime_reason: str,
) -> OrchestrateSetupActionReadiness:
    if not visible:
        return OrchestrateSetupActionReadiness(
            action=action,
            enabled=False,
            disabled_reason=hidden_reason,
        )
    if not command_configured:
        return OrchestrateSetupActionReadiness(
            action=action,
            enabled=False,
            disabled_reason=missing_command_reason,
        )
    if not runtime_ready:
        return OrchestrateSetupActionReadiness(
            action=action,
            enabled=False,
            disabled_reason=runtime_reason,
        )
    return OrchestrateSetupActionReadiness(action=action, enabled=True, disabled_reason="")


def _optional_path(value: Path | str | None) -> Path | None:
    return Path(value) if value else None


def _install_runtime_root(
    *,
    active_app_path: Path | str | None,
    agi_cluster_path: Path | str | None,
    is_source_env: bool,
    is_worker_env: bool,
) -> Path | None:
    if (is_source_env or is_worker_env) and agi_cluster_path:
        return Path(agi_cluster_path)
    active_app = _optional_path(active_app_path)
    if active_app is None:
        return None
    return active_app


def _install_display_venv_path(
    runtime_root: Path | None,
    *,
    is_source_env: bool,
    is_worker_env: bool,
) -> Path | None:
    if runtime_root is None:
        return None
    if is_source_env or is_worker_env:
        return runtime_root
    return runtime_root / ".venv"


def build_orchestrate_install_workflow_state(
    *,
    show_install: bool,
    cmd: str | None,
    active_app_path: Path | str | None,
    agi_cluster_path: Path | str | None,
    is_source_env: bool,
    is_worker_env: bool,
    snippet_tail: str,
    app: Any,
    cluster_enabled: bool,
    verbose: Any,
    mode: Any,
    raw_scheduler: Any,
    raw_workers: Any,
    timestamp: str,
) -> OrchestrateInstallWorkflowState:
    """Build the pure ORCHESTRATE INSTALL request state."""
    runtime_root = _install_runtime_root(
        active_app_path=active_app_path,
        agi_cluster_path=agi_cluster_path,
        is_source_env=is_source_env,
        is_worker_env=is_worker_env,
    )
    command_configured = bool(cmd)
    install_command = cmd.replace("asyncio.run(main())", snippet_tail) if cmd else None
    action = _setup_readiness(
        action=OrchestrateSetupAction.INSTALL,
        visible=show_install,
        command_configured=command_configured,
        runtime_ready=runtime_root is not None,
        hidden_reason="INSTALL controls are hidden.",
        missing_command_reason="No INSTALL command configured; check deployment settings first.",
        runtime_reason="Unable to resolve the INSTALL runtime root; reload the app and retry.",
    )
    context_lines = (
        "=== Install request ===",
        f"timestamp: {timestamp}",
        f"app: {app}",
        f"env_flags: source={is_source_env}, worker={is_worker_env}",
        f"cluster_enabled: {cluster_enabled}",
        f"verbose: {verbose}",
        f"modes_enabled: {mode}",
        f"scheduler: {raw_scheduler if cluster_enabled and raw_scheduler else 'None'}",
        f"workers: {raw_workers if cluster_enabled and raw_workers else 'None'}",
        f"runtime: {runtime_root}",
        f"venv: {_install_display_venv_path(runtime_root, is_source_env=is_source_env, is_worker_env=is_worker_env)}",
        "=== Streaming install logs ===",
    )
    return OrchestrateInstallWorkflowState(
        show_install=show_install,
        command_configured=command_configured,
        cluster_enabled=cluster_enabled,
        runtime_root=runtime_root,
        install_command=install_command,
        context_lines=context_lines,
        action=action,
    )


def build_orchestrate_distribution_workflow_state(
    *,
    show_distribute: bool,
    cmd: str | None,
    worker_env_path: Path | str | None,
) -> OrchestrateDistributionWorkflowState:
    """Build the pure ORCHESTRATE CHECK distribute state."""
    distribution_path = resolve_distribution_plan_path(worker_env_path)
    command_configured = bool(cmd)
    action = _setup_readiness(
        action=OrchestrateSetupAction.DISTRIBUTE,
        visible=show_distribute,
        command_configured=command_configured,
        runtime_ready=distribution_path is not None,
        hidden_reason="CHECK distribute controls are hidden.",
        missing_command_reason="No CHECK distribute command configured; check orchestration settings first.",
        runtime_reason="Unable to resolve the worker environment path; run INSTALL, then retry CHECK distribute.",
    )
    return OrchestrateDistributionWorkflowState(
        show_distribute=show_distribute,
        command_configured=command_configured,
        distribution_path=distribution_path,
        action=action,
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


def _run_artifact_readiness(
    *,
    action: OrchestrateRunArtifactAction,
    show_run_panel: bool,
    status: OrchestrateRunArtifactStatus,
    has_loaded_dataframe: bool,
    has_loaded_artifact: bool,
) -> OrchestrateRunArtifactReadiness:
    if not show_run_panel:
        if action not in (OrchestrateRunArtifactAction.LOAD, OrchestrateRunArtifactAction.DELETE):
            if has_loaded_dataframe:
                return OrchestrateRunArtifactReadiness(action=action, enabled=True, disabled_reason="")
            return OrchestrateRunArtifactReadiness(
                action=action,
                enabled=False,
                disabled_reason="No data loaded yet. Click 'LOAD dataframe' in Execute to populate it before export.",
            )
        return OrchestrateRunArtifactReadiness(
            action=action,
            enabled=False,
            disabled_reason="`Serve` mode selected. Switch to `Run now` to access EXECUTE / LOAD actions.",
        )
    if action is OrchestrateRunArtifactAction.LOAD:
        if status is OrchestrateRunArtifactStatus.DELETED:
            return OrchestrateRunArtifactReadiness(
                action=action,
                enabled=False,
                disabled_reason="Dataframe preview was deleted. Run EXECUTE again before loading a new export.",
            )
        return OrchestrateRunArtifactReadiness(action=action, enabled=True, disabled_reason="")
    if action is OrchestrateRunArtifactAction.DELETE:
        if not has_loaded_artifact:
            reason = (
                "Dataframe preview was deleted. Run EXECUTE then LOAD to refresh with new output."
                if status is OrchestrateRunArtifactStatus.DELETED
                else "No data loaded yet. Click 'LOAD dataframe' in Execute to populate it before export."
            )
            return OrchestrateRunArtifactReadiness(action=action, enabled=False, disabled_reason=reason)
        return OrchestrateRunArtifactReadiness(action=action, enabled=True, disabled_reason="")
    if not has_loaded_dataframe:
        return OrchestrateRunArtifactReadiness(
            action=action,
            enabled=False,
            disabled_reason="No data loaded yet. Click 'LOAD dataframe' in Execute to populate it before export.",
        )
    return OrchestrateRunArtifactReadiness(action=action, enabled=True, disabled_reason="")


def build_orchestrate_run_artifact_state(
    *,
    show_run_panel: bool,
    loaded_dataframe: Any = None,
    loaded_graph: Any = None,
    loaded_source_path: Path | str | None = None,
    dataframe_deleted: bool = False,
) -> OrchestrateRunArtifactState:
    """Build the pure state for loaded/deleted/missing run output artifacts."""
    has_loaded_dataframe = bool(getattr(loaded_dataframe, "empty", True) is False)
    has_loaded_graph = loaded_graph is not None
    status = (
        OrchestrateRunArtifactStatus.DELETED
        if dataframe_deleted
        else OrchestrateRunArtifactStatus.LOADED
        if has_loaded_dataframe or has_loaded_graph
        else OrchestrateRunArtifactStatus.MISSING
    )
    try:
        source_path = Path(loaded_source_path) if loaded_source_path else None
    except (OSError, RuntimeError, TypeError, ValueError):
        source_path = None
    actions = {
        action: _run_artifact_readiness(
            action=action,
            show_run_panel=show_run_panel,
            status=status,
            has_loaded_dataframe=has_loaded_dataframe,
            has_loaded_artifact=has_loaded_dataframe or has_loaded_graph,
        )
        for action in OrchestrateRunArtifactAction
    }
    blocked_actions = {
        action: readiness.disabled_reason
        for action, readiness in actions.items()
        if not readiness.enabled
    }
    return OrchestrateRunArtifactState(
        status=status,
        show_run_panel=show_run_panel,
        deleted=dataframe_deleted,
        has_loaded_dataframe=has_loaded_dataframe,
        has_loaded_graph=has_loaded_graph,
        loaded_source_path=source_path,
        actions=MappingProxyType(actions),
        blocked_actions=MappingProxyType(blocked_actions),
    )


def build_orchestrate_combined_workflow_state(
    *,
    install_state: OrchestrateInstallWorkflowState,
    distribution_state: OrchestrateDistributionWorkflowState,
    execute_state: OrchestrateExecuteWorkflowState,
    distribution_generated: bool = False,
) -> OrchestrateCombinedWorkflowState:
    """Build a pure high-level INSTALL/CHECK/RUN phase model for ORCHESTRATE."""
    installed = not execute_state.missing_install_paths
    install_ready = install_state.action.enabled and not installed
    distribution_required = distribution_state.show_distribute
    distribution_satisfied = distribution_generated or not distribution_required
    distribute_ready = (
        installed
        and distribution_required
        and distribution_state.action.enabled
        and not distribution_generated
    )
    runnable = execute_state.run_action.enabled and distribution_satisfied

    if runnable:
        phase = OrchestrateWorkflowPhase.RUNNABLE
        blocked_reason = ""
    elif distribution_generated:
        phase = OrchestrateWorkflowPhase.DISTRIBUTION_GENERATED
        blocked_reason = execute_state.run_action.disabled_reason
    elif distribute_ready:
        phase = OrchestrateWorkflowPhase.DISTRIBUTE_READY
        blocked_reason = ""
    elif installed:
        phase = OrchestrateWorkflowPhase.INSTALLED
        blocked_reason = distribution_state.action.disabled_reason or execute_state.run_action.disabled_reason
    elif install_ready:
        phase = OrchestrateWorkflowPhase.INSTALL_READY
        blocked_reason = ""
    else:
        phase = OrchestrateWorkflowPhase.NOT_INSTALLED
        blocked_reason = install_state.action.disabled_reason or execute_state.run_action.disabled_reason

    return OrchestrateCombinedWorkflowState(
        phase=phase,
        install_ready=install_ready,
        installed=installed,
        distribute_ready=distribute_ready,
        distribution_generated=distribution_generated,
        runnable=runnable,
        blocked_reason=blocked_reason,
    )


def build_orchestrate_page_state(
    *,
    cluster_params: Mapping[str, Any],
    selected_benchmark_modes: Sequence[Any],
    benchmark_best_single_node: bool = False,
    local_share_path: Any = None,
    cluster_share_issue: str = "",
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
    benchmark_best_single_node = bool(
        benchmark_best_single_node and any(int(mode) & 4 for mode in sanitized_modes)
    )
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
    run_disabled_reason = workers_data_path_issue or str(cluster_share_issue or "")
    can_run = not bool(run_disabled_reason)
    status = (
        OrchestrateWorkflowStatus.BLOCKED
        if run_disabled_reason
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
        benchmark_best_single_node=benchmark_best_single_node,
        run_mode=run_mode,
        run_mode_label=run_mode_label,
        verbose=_coerce_verbose(cluster_params.get("verbose", 1)),
        scheduler=deps.optional_string_expr(enabled, cluster_params.get("scheduler")),
        workers=deps.optional_python_expr(enabled, cluster_params.get("workers")),
        raw_workers_data_path=raw_workers_data_path,
        workers_data_path=deps.optional_string_expr(enabled, raw_workers_data_path),
        workers_data_path_issue=workers_data_path_issue,
        cluster_share_issue=str(cluster_share_issue or ""),
        rapids_enabled=rapids_enabled,
        can_run=can_run,
        run_disabled_reason=run_disabled_reason,
    )
