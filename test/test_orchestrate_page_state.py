from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path


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
    assert state.run_mode == 1
    assert state.run_mode_label == "Run mode 1: pool of process"
    assert state.verbose == 2
    assert state.scheduler == "None"
    assert state.workers == "None"
    assert state.can_run is True


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
        deps=_deps(),
    )

    assert state.status is orchestrate_page_state.OrchestrateWorkflowStatus.BENCHMARK
    assert state.benchmark_enabled is True
    assert state.selected_benchmark_modes == (0, 7, 15)
    assert state.run_mode == [0, 7, 15]
    assert state.run_mode_label == "Run mode benchmark (selected modes: 0, 7, 15)"
    assert state.scheduler == '"tcp://scheduler:8786"'
    assert state.workers == "{'127.0.0.1': 1}"
    assert state.workers_data_path == '"/mnt/shared/agilab"'
    assert state.rapids_enabled is True
    assert state.can_run is True


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
