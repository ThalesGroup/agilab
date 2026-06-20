from __future__ import annotations

import importlib
import subprocess
import sys
import textwrap

import pytest


SHIM_MODULES = (
    "agi_cluster.agi_distributor.agi_distributor",
    "agi_cluster.agi_distributor.background_jobs_support",
    "agi_cluster.agi_distributor.capacity_support",
    "agi_cluster.agi_distributor.cleanup_support",
    "agi_cluster.agi_distributor.cli",
    "agi_cluster.agi_distributor.deployment_build_support",
    "agi_cluster.agi_distributor.deployment_dask_support",
    "agi_cluster.agi_distributor.deployment_editable_install_support",
    "agi_cluster.agi_distributor.deployment_install_spec_support",
    "agi_cluster.agi_distributor.deployment_local_support",
    "agi_cluster.agi_distributor.deployment_orchestration_support",
    "agi_cluster.agi_distributor.deployment_prepare_support",
    "agi_cluster.agi_distributor.deployment_remote_support",
    "agi_cluster.agi_distributor.deployment_resolver_env_support",
    "agi_cluster.agi_distributor.deployment_stage_cache_support",
    "agi_cluster.agi_distributor.deployment_stage_plan_support",
    "agi_cluster.agi_distributor.deployment_venv_support",
    "agi_cluster.agi_distributor.deployment_worker_venv_cache_support",
    "agi_cluster.agi_distributor.entrypoint_support",
    "agi_cluster.agi_distributor.run_request_support",
    "agi_cluster.agi_distributor.runtime_distribution_support",
    "agi_cluster.agi_distributor.runtime_misc_support",
    "agi_cluster.agi_distributor.scheduler_io_support",
    "agi_cluster.agi_distributor.service_lifecycle_support",
    "agi_cluster.agi_distributor.service_runtime_support",
    "agi_cluster.agi_distributor.service_state_support",
    "agi_cluster.agi_distributor.transport_support",
    "agi_cluster.agi_distributor.uv_source_support",
)


def test_distributor_import_does_not_require_sklearn() -> None:
    code = textwrap.dedent(
        """
        import importlib.abc
        import sys

        class BlockSklearn(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "sklearn" or fullname.startswith("sklearn."):
                    raise ModuleNotFoundError(fullname)
                return None

        sys.meta_path.insert(0, BlockSklearn())

        from agi_cluster.agi_distributor import AGI

        assert AGI is not None
        print("ok")
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip() == "ok"


@pytest.mark.parametrize("module_name", SHIM_MODULES)
def test_agi_cluster_legacy_shim_imports_target_module(module_name: str) -> None:
    module = importlib.import_module(module_name)

    assert module.__name__ == module_name
    assert module.__dict__.get("_COMPAT_TARGET_MODULE") is not None or hasattr(module, "USAGE")
