from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pandas as pd


def _import_agilab_module(module_name: str):
    src_root = Path(__file__).resolve().parents[1] / "src"
    package_root = src_root / "agilab"
    src_root_str = str(src_root)
    package_root_str = str(package_root)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)
    pkg = sys.modules.get("agilab")
    if pkg is None or not hasattr(pkg, "__path__"):
        pkg = types.ModuleType("agilab")
        pkg.__path__ = [package_root_str]
        sys.modules["agilab"] = pkg
    else:
        package_path = list(pkg.__path__)
        if package_root_str not in package_path:
            pkg.__path__ = [package_root_str, *package_path]
    importlib.invalidate_caches()
    return importlib.import_module(module_name)


orchestrate_page_state = _import_agilab_module("agilab.orchestrate_page_state")
orchestrate_page_support = _import_agilab_module("agilab.orchestrate_page_support")


def _deps() -> orchestrate_page_state.OrchestratePageStateDeps:
    return orchestrate_page_state.OrchestratePageStateDeps(
        available_benchmark_modes=orchestrate_page_support.available_benchmark_modes,
        sanitize_benchmark_modes=orchestrate_page_support.sanitize_benchmark_modes,
        resolve_requested_run_mode=orchestrate_page_support.resolve_requested_run_mode,
        describe_run_mode=orchestrate_page_support.describe_run_mode,
        benchmark_workers_data_path_issue=orchestrate_page_support.benchmark_workers_data_path_issue,
        optional_string_expr=orchestrate_page_support.optional_string_expr,
        optional_python_expr=orchestrate_page_support.optional_python_expr,
    )


def test_orchestrate_page_state_defaults_to_single_run():
    state = orchestrate_page_state.build_orchestrate_page_state(
        cluster_params={"pool": True, "cython": False, "rapids": False, "verbose": 2},
        selected_benchmark_modes=[],
        deps=_deps(),
    )

    assert state.status is orchestrate_page_state.OrchestrateWorkflowStatus.SINGLE_RUN
    assert state.cluster_enabled is False
    assert state.benchmark_enabled is False
    assert state.available_benchmark_modes == (0, 1)
    assert state.selected_benchmark_modes == ()
    assert state.benchmark_best_single_node is False
    assert state.run_mode == 1
    assert state.run_mode_label == "Run mode 1: pool of process"
    assert state.verbose == 2
    assert state.scheduler == "None"
    assert state.workers == "None"
    assert state.can_run is True


def test_orchestrate_page_state_bounds_diagnostics_verbose():
    state = orchestrate_page_state.build_orchestrate_page_state(
        cluster_params={"pool": True, "verbose": 99},
        selected_benchmark_modes=[],
        deps=_deps(),
    )

    assert state.verbose == 1


def test_orchestrate_page_state_sanitizes_benchmark_modes_and_preserves_run_list():
    state = orchestrate_page_state.build_orchestrate_page_state(
        cluster_params={
            "cluster_enabled": True,
            "pool": True,
            "cython": True,
            "rapids": True,
            "scheduler": "tcp://scheduler:8786",
            "workers": {"127.0.0.1": 1},
            "workers_data_path": "/mnt/shared/agilab",
        },
        selected_benchmark_modes=[15, "bad", 7, 0, 99, "7"],
        benchmark_best_single_node=True,
        deps=_deps(),
    )

    assert state.status is orchestrate_page_state.OrchestrateWorkflowStatus.BENCHMARK
    assert state.benchmark_enabled is True
    assert state.selected_benchmark_modes == (0, 7, 15)
    assert state.benchmark_best_single_node is True
    assert state.run_mode == [0, 7, 15]
    assert state.run_mode_label == "Run mode benchmark (selected modes: 0, 7, 15)"
    assert state.scheduler == '"tcp://scheduler:8786"'
    assert state.workers == "{'127.0.0.1': 1}"
    assert state.workers_data_path == '"/mnt/shared/agilab"'
    assert state.rapids_enabled is True
    assert state.can_run is True


def test_orchestrate_page_state_ignores_best_single_node_without_dask_benchmark():
    state = orchestrate_page_state.build_orchestrate_page_state(
        cluster_params={
            "cluster_enabled": False,
            "pool": True,
            "cython": False,
            "rapids": False,
        },
        selected_benchmark_modes=[1],
        benchmark_best_single_node=True,
        deps=_deps(),
    )

    assert state.benchmark_enabled is True
    assert state.selected_benchmark_modes == (1,)
    assert state.benchmark_best_single_node is False


def test_orchestrate_page_state_drops_cluster_modes_when_cluster_is_disabled():
    state = orchestrate_page_state.build_orchestrate_page_state(
        cluster_params={"pool": False, "cython": False, "rapids": False},
        selected_benchmark_modes=[4, 12],
        deps=_deps(),
    )

    assert state.cluster_enabled is False
    assert state.available_benchmark_modes == (0,)
    assert state.selected_benchmark_modes == ()
    assert state.benchmark_enabled is False
    assert state.run_mode == 0


def test_orchestrate_page_state_blocks_remote_dask_without_shared_workers_path(tmp_path):
    local_share = tmp_path / "localshare"
    local_share.mkdir()

    state = orchestrate_page_state.build_orchestrate_page_state(
        cluster_params={
            "cluster_enabled": True,
            "pool": False,
            "cython": False,
            "rapids": False,
            "workers": {"192.168.1.20": 1},
            "workers_data_path": str(local_share),
        },
        selected_benchmark_modes=[4],
        local_share_path=local_share,
        deps=_deps(),
    )

    assert state.status is orchestrate_page_state.OrchestrateWorkflowStatus.BLOCKED
    assert state.benchmark_enabled is True
    assert state.run_mode == [4]
    assert state.can_run is False
    assert "local share" in state.run_disabled_reason


def test_orchestrate_page_state_blocks_cluster_share_warning():
    state = orchestrate_page_state.build_orchestrate_page_state(
        cluster_params={
            "cluster_enabled": True,
            "pool": True,
            "cython": True,
            "rapids": False,
            "workers": {"127.0.0.1": 2},
            "workers_data_path": "clustershare/agi",
        },
        selected_benchmark_modes=[],
        cluster_share_issue="Cluster is enabled but the data directory appears local.",
        deps=_deps(),
    )

    assert state.status is orchestrate_page_state.OrchestrateWorkflowStatus.BLOCKED
    assert state.can_run is False
    assert state.cluster_share_issue == "Cluster is enabled but the data directory appears local."
    assert "appears local" in state.run_disabled_reason


def test_orchestrate_install_workflow_state_uses_app_runtime_root(tmp_path):
    active_app = tmp_path / "src" / "agilab" / "apps" / "builtin" / "flight_telemetry_project"
    cmd = "asyncio.run(main())"

    state = orchestrate_page_state.build_orchestrate_install_workflow_state(
        show_install=True,
        cmd=cmd,
        active_app_path=active_app,
        agi_cluster_path=None,
        is_source_env=False,
        is_worker_env=False,
        snippet_tail="await main()",
        app="flight_telemetry_project",
        cluster_enabled=False,
        verbose=1,
        mode=1,
        raw_scheduler="tcp://ignored:8786",
        raw_workers={"ignored": 1},
        timestamp="2026-04-30T07:00:00",
    )

    assert state.action.enabled is True
    assert state.command_configured is True
    assert state.runtime_root == active_app
    assert state.install_command == "await main()"
    assert "cluster_enabled: False" in state.context_lines
    assert "scheduler: None" in state.context_lines
    assert f"runtime: {active_app}" in state.context_lines
    assert f"venv: {active_app / '.venv'}" in state.context_lines


def test_orchestrate_install_workflow_state_uses_core_runtime_root_for_source_env(tmp_path):
    active_app = tmp_path / "src" / "agilab" / "apps" / "flight_telemetry_project"
    agi_cluster = tmp_path / "src" / "agilab" / "core" / "agi-cluster"

    state = orchestrate_page_state.build_orchestrate_install_workflow_state(
        show_install=True,
        cmd="asyncio.run(main())",
        active_app_path=active_app,
        agi_cluster_path=agi_cluster,
        is_source_env=True,
        is_worker_env=False,
        snippet_tail="asyncio.run(main())",
        app="flight_telemetry_project",
        cluster_enabled=True,
        verbose=2,
        mode=15,
        raw_scheduler="tcp://scheduler:8786",
        raw_workers={"127.0.0.1": 2},
        timestamp="2026-04-30T07:05:00",
    )

    assert state.action.enabled is True
    assert state.runtime_root == agi_cluster
    assert "cluster_enabled: True" in state.context_lines
    assert "scheduler: tcp://scheduler:8786" in state.context_lines
    assert "workers: {'127.0.0.1': 2}" in state.context_lines


def test_orchestrate_install_workflow_state_blocks_missing_runtime_root():
    state = orchestrate_page_state.build_orchestrate_install_workflow_state(
        show_install=True,
        cmd="asyncio.run(main())",
        active_app_path=None,
        agi_cluster_path=None,
        is_source_env=False,
        is_worker_env=False,
        snippet_tail="asyncio.run(main())",
        app="flight_telemetry_project",
        cluster_enabled=False,
        verbose=1,
        mode=1,
        raw_scheduler="",
        raw_workers={},
        timestamp="2026-04-30T07:10:00",
    )

    assert state.action.enabled is False
    assert state.runtime_root is None
    assert "Unable to resolve the INSTALL runtime root" in state.action.disabled_reason


def test_orchestrate_install_workflow_state_blocks_hidden_or_missing_command(tmp_path):
    active_app = tmp_path / "apps" / "flight_telemetry_project"

    hidden = orchestrate_page_state.build_orchestrate_install_workflow_state(
        show_install=False,
        cmd="asyncio.run(main())",
        active_app_path=active_app,
        agi_cluster_path=None,
        is_source_env=False,
        is_worker_env=False,
        snippet_tail="asyncio.run(main())",
        app="flight_telemetry_project",
        cluster_enabled=False,
        verbose=1,
        mode=1,
        raw_scheduler="",
        raw_workers={},
        timestamp="2026-04-30T07:15:00",
    )
    missing_command = orchestrate_page_state.build_orchestrate_install_workflow_state(
        show_install=True,
        cmd=None,
        active_app_path=active_app,
        agi_cluster_path=None,
        is_source_env=False,
        is_worker_env=False,
        snippet_tail="asyncio.run(main())",
        app="flight_telemetry_project",
        cluster_enabled=False,
        verbose=1,
        mode=1,
        raw_scheduler="",
        raw_workers={},
        timestamp="2026-04-30T07:15:00",
    )

    assert hidden.action.enabled is False
    assert hidden.action.disabled_reason == "INSTALL controls are hidden."
    assert missing_command.action.enabled is False
    assert "No INSTALL command configured" in missing_command.action.disabled_reason


def test_orchestrate_distribution_workflow_state_is_ready(tmp_path):
    worker_env_path = tmp_path / "wenv" / "flight_worker"

    state = orchestrate_page_state.build_orchestrate_distribution_workflow_state(
        show_distribute=True,
        cmd="print('distribute')",
        worker_env_path=worker_env_path,
    )

    assert state.action.enabled is True
    assert state.command_configured is True
    assert state.distribution_path == worker_env_path / "distribution_tree.json"


def test_orchestrate_distribution_workflow_state_prefers_runtime_distribution_tree(tmp_path):
    worker_env_path = tmp_path / "wenv" / "flight_worker"
    worker_env_path.mkdir(parents=True)
    runtime_plan = worker_env_path / "distribution_tree.json"
    legacy_plan = worker_env_path / "distribution.json"
    legacy_plan.write_text("{}", encoding="utf-8")

    legacy_state = orchestrate_page_state.build_orchestrate_distribution_workflow_state(
        show_distribute=True,
        cmd="print('distribute')",
        worker_env_path=worker_env_path,
    )

    runtime_plan.write_text("{}", encoding="utf-8")
    runtime_state = orchestrate_page_state.build_orchestrate_distribution_workflow_state(
        show_distribute=True,
        cmd="print('distribute')",
        worker_env_path=worker_env_path,
    )

    assert legacy_state.distribution_path == legacy_plan
    assert runtime_state.distribution_path == runtime_plan


def test_orchestrate_distribution_workflow_state_blocks_hidden_missing_command_or_runtime(tmp_path):
    worker_env_path = tmp_path / "wenv" / "flight_worker"

    hidden = orchestrate_page_state.build_orchestrate_distribution_workflow_state(
        show_distribute=False,
        cmd="print('distribute')",
        worker_env_path=worker_env_path,
    )
    missing_command = orchestrate_page_state.build_orchestrate_distribution_workflow_state(
        show_distribute=True,
        cmd=None,
        worker_env_path=worker_env_path,
    )
    missing_runtime = orchestrate_page_state.build_orchestrate_distribution_workflow_state(
        show_distribute=True,
        cmd="print('distribute')",
        worker_env_path=None,
    )

    assert hidden.action.enabled is False
    assert hidden.action.disabled_reason == "CHECK distribute controls are hidden."
    assert missing_command.action.enabled is False
    assert "No CHECK distribute command configured" in missing_command.action.disabled_reason
    assert missing_runtime.action.enabled is False
    assert missing_runtime.distribution_path is None
    assert "Unable to resolve the worker environment path" in missing_runtime.action.disabled_reason


def test_orchestrate_execute_workflow_state_is_ready_when_installed(tmp_path):
    project_path = tmp_path / "project"
    worker_env_path = tmp_path / "wenv"
    (project_path / ".venv").mkdir(parents=True)
    (worker_env_path / ".venv").mkdir(parents=True)

    state = orchestrate_page_state.build_orchestrate_execute_workflow_state(
        show_run_panel=True,
        cmd="print('run')",
        project_path=project_path,
        worker_env_path=worker_env_path,
    )

    assert state.command_configured is True
    assert state.missing_install_paths == ()
    assert state.run_action.enabled is True
    assert state.combo_action.enabled is True
    assert state.blocked_actions == {}


def test_orchestrate_execute_workflow_state_reports_missing_install_paths(tmp_path):
    project_path = tmp_path / "project"
    worker_env_path = tmp_path / "wenv"

    state = orchestrate_page_state.build_orchestrate_execute_workflow_state(
        show_run_panel=True,
        cmd="print('run')",
        project_path=project_path,
        worker_env_path=worker_env_path,
    )

    assert state.run_action.enabled is False
    assert state.combo_action.enabled is False
    assert len(state.missing_install_paths) == 2
    assert f"manager venv `{project_path / '.venv'}`" in state.missing_install_paths
    assert f"worker venv `{worker_env_path / '.venv'}`" in state.missing_install_paths
    assert "installation is incomplete" in state.run_action.disabled_reason
    assert "installation is incomplete" in state.combo_action.disabled_reason


def test_orchestrate_execute_workflow_state_blocks_missing_command(tmp_path):
    project_path = tmp_path / "project"
    worker_env_path = tmp_path / "wenv"
    (project_path / ".venv").mkdir(parents=True)
    (worker_env_path / ".venv").mkdir(parents=True)

    state = orchestrate_page_state.build_orchestrate_execute_workflow_state(
        show_run_panel=True,
        cmd=None,
        project_path=project_path,
        worker_env_path=worker_env_path,
    )

    assert state.command_configured is False
    assert state.missing_install_paths == ()
    assert state.run_action.enabled is False
    assert state.combo_action.enabled is False
    assert "No EXECUTE command configured" in state.run_action.disabled_reason


def test_orchestrate_execute_workflow_state_blocks_serve_mode(tmp_path):
    project_path = tmp_path / "project"
    worker_env_path = tmp_path / "wenv"
    (project_path / ".venv").mkdir(parents=True)
    (worker_env_path / ".venv").mkdir(parents=True)

    state = orchestrate_page_state.build_orchestrate_execute_workflow_state(
        show_run_panel=False,
        cmd="print('run')",
        project_path=project_path,
        worker_env_path=worker_env_path,
    )

    assert state.run_action.enabled is False
    assert state.combo_action.enabled is False
    assert "`Serve` mode selected" in state.run_action.disabled_reason
    assert "`Serve` mode selected" in state.blocked_actions[orchestrate_page_state.OrchestrateExecuteAction.RUN]


def test_orchestrate_run_artifact_state_reports_loaded_dataframe(tmp_path):
    source_path = tmp_path / "result.csv"
    state = orchestrate_page_state.build_orchestrate_run_artifact_state(
        show_run_panel=True,
        loaded_dataframe=pd.DataFrame({"value": [1]}),
        loaded_source_path=source_path,
    )

    assert state.status is orchestrate_page_state.OrchestrateRunArtifactStatus.LOADED
    assert state.loaded_source_path == source_path
    assert state.has_loaded_artifact is True
    assert state.load_action.enabled is True
    assert state.delete_action.enabled is True
    assert state.export_action.enabled is True
    assert state.stats_action.enabled is True
    assert state.blocked_actions == {}


def test_orchestrate_run_artifact_state_blocks_deleted_or_missing_outputs():
    deleted = orchestrate_page_state.build_orchestrate_run_artifact_state(
        show_run_panel=True,
        loaded_dataframe=None,
        dataframe_deleted=True,
    )
    missing = orchestrate_page_state.build_orchestrate_run_artifact_state(
        show_run_panel=True,
        loaded_dataframe=pd.DataFrame(),
    )

    assert deleted.status is orchestrate_page_state.OrchestrateRunArtifactStatus.DELETED
    assert deleted.load_action.enabled is False
    assert "Run EXECUTE again" in deleted.load_action.disabled_reason
    assert deleted.delete_action.enabled is False
    assert deleted.export_action.enabled is False
    assert missing.status is orchestrate_page_state.OrchestrateRunArtifactStatus.MISSING
    assert missing.load_action.enabled is True
    assert missing.delete_action.enabled is False
    assert missing.stats_action.enabled is False


def test_orchestrate_run_artifact_state_allows_graph_delete_but_not_export():
    graph = object()

    state = orchestrate_page_state.build_orchestrate_run_artifact_state(
        show_run_panel=True,
        loaded_graph=graph,
    )

    assert state.status is orchestrate_page_state.OrchestrateRunArtifactStatus.LOADED
    assert state.has_loaded_graph is True
    assert state.delete_action.enabled is True
    assert state.export_action.enabled is False
    assert state.stats_action.enabled is False


def _install_state(tmp_path, *, show_install=True, cmd="asyncio.run(main())"):
    active_app = tmp_path / "src" / "agilab" / "apps" / "flight_telemetry_project"
    return orchestrate_page_state.build_orchestrate_install_workflow_state(
        show_install=show_install,
        cmd=cmd,
        active_app_path=active_app,
        agi_cluster_path=None,
        is_source_env=False,
        is_worker_env=False,
        snippet_tail="asyncio.run(main())",
        app="flight_telemetry_project",
        cluster_enabled=False,
        verbose=1,
        mode=1,
        raw_scheduler="",
        raw_workers={},
        timestamp="2026-04-30T08:00:00",
    )


def _distribution_state(*, show_distribute=True, cmd="print('distribute')", worker_env_path=None):
    return orchestrate_page_state.build_orchestrate_distribution_workflow_state(
        show_distribute=show_distribute,
        cmd=cmd,
        worker_env_path=worker_env_path,
    )


def _execute_state(tmp_path, *, installed: bool, show_run_panel=True, cmd="print('run')"):
    project_path = tmp_path / "project"
    worker_env_path = tmp_path / "wenv"
    if installed:
        (project_path / ".venv").mkdir(parents=True, exist_ok=True)
        (worker_env_path / ".venv").mkdir(parents=True, exist_ok=True)
    return orchestrate_page_state.build_orchestrate_execute_workflow_state(
        show_run_panel=show_run_panel,
        cmd=cmd,
        project_path=project_path,
        worker_env_path=worker_env_path,
    )


def test_orchestrate_combined_workflow_state_reports_install_ready(tmp_path):
    state = orchestrate_page_state.build_orchestrate_combined_workflow_state(
        install_state=_install_state(tmp_path),
        distribution_state=_distribution_state(worker_env_path=tmp_path / "wenv"),
        execute_state=_execute_state(tmp_path, installed=False),
    )

    assert state.phase is orchestrate_page_state.OrchestrateWorkflowPhase.INSTALL_READY
    assert state.install_ready is True
    assert state.installed is False
    assert state.runnable is False


def test_orchestrate_combined_workflow_state_reports_distribute_ready_and_generated(tmp_path):
    distribute_ready = orchestrate_page_state.build_orchestrate_combined_workflow_state(
        install_state=_install_state(tmp_path),
        distribution_state=_distribution_state(worker_env_path=tmp_path / "wenv"),
        execute_state=_execute_state(tmp_path, installed=True),
    )
    generated = orchestrate_page_state.build_orchestrate_combined_workflow_state(
        install_state=_install_state(tmp_path),
        distribution_state=_distribution_state(worker_env_path=tmp_path / "wenv"),
        execute_state=_execute_state(tmp_path, installed=True, cmd=None),
        distribution_generated=True,
    )

    assert distribute_ready.phase is orchestrate_page_state.OrchestrateWorkflowPhase.DISTRIBUTE_READY
    assert distribute_ready.distribute_ready is True
    assert distribute_ready.runnable is False
    assert generated.phase is orchestrate_page_state.OrchestrateWorkflowPhase.DISTRIBUTION_GENERATED
    assert generated.distribution_generated is True
    assert "No EXECUTE command configured" in generated.blocked_reason


def test_orchestrate_combined_workflow_state_reports_runnable(tmp_path):
    state = orchestrate_page_state.build_orchestrate_combined_workflow_state(
        install_state=_install_state(tmp_path),
        distribution_state=_distribution_state(worker_env_path=tmp_path / "wenv"),
        execute_state=_execute_state(tmp_path, installed=True),
        distribution_generated=True,
    )

    assert state.phase is orchestrate_page_state.OrchestrateWorkflowPhase.RUNNABLE
    assert state.installed is True
    assert state.distribution_generated is True
    assert state.runnable is True
    assert state.blocked_reason == ""
