from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "shared_core_strict_typing.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("shared_core_strict_typing", MODULE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_resolve_modules_appends_unique_extra_modules():
    module = _load_module()

    modules = module.resolve_modules(
        "support-first",
        [
            "agi_cluster.agi_distributor.entrypoint_support",
            "agi_env.defaults",
        ],
    )

    assert modules == [
        "agi_cluster.agi_distributor.background_jobs_support",
        "agi_node.agi_dispatcher.base_worker_path_support",
        "agi_node.agi_dispatcher.base_worker_execution_support",
        "agi_node.agi_dispatcher.base_worker_runtime_support",
        "agi_node.agi_dispatcher.base_worker_service_support",
        "agi_cluster.agi_distributor.cleanup_support",
        "agi_cluster.agi_distributor.deployment_build_support",
        "agi_cluster.agi_distributor.deployment_local_support",
        "agi_cluster.agi_distributor.deployment_orchestration_support",
        "agi_cluster.agi_distributor.deployment_prepare_support",
        "agi_cluster.agi_distributor.deployment_remote_support",
        "agi_cluster.agi_distributor.entrypoint_support",
        "agi_cluster.agi_distributor.runtime_misc_support",
        "agi_cluster.agi_distributor.runtime_distribution_support",
        "agi_cluster.agi_distributor.scheduler_io_support",
        "agi_cluster.agi_distributor.service_runtime_support",
        "agi_cluster.agi_distributor.service_state_support",
        "agi_cluster.agi_distributor.transport_support",
        "agi_cluster.agi_distributor.uv_source_support",
        "agi_env.defaults",
    ]


def test_build_mypy_env_combines_required_source_roots():
    module = _load_module()

    env = module.build_mypy_env(
        [
            "agi_env.defaults",
            "agi_node.agi_dispatcher.base_worker_service_support",
            "agi_cluster.agi_distributor.entrypoint_support",
        ],
        base_env={"MYPYPATH": "/tmp/existing"},
    )

    parts = env["MYPYPATH"].split(module.os.pathsep)
    assert str(module.SOURCE_ROOTS["agi_env"]) in parts
    assert str(module.SOURCE_ROOTS["agi_node"]) in parts
    assert str(module.SOURCE_ROOTS["agi_cluster"]) in parts
    assert "/tmp/existing" in parts


def test_print_only_emits_command_and_mypypath():
    completed = subprocess.run(
        [sys.executable, str(MODULE_PATH), "--print-only"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "MYPYPATH=" in completed.stdout
    assert "-m mypy --strict" in completed.stdout
    assert "agi_node.agi_dispatcher.base_worker_execution_support" in completed.stdout
