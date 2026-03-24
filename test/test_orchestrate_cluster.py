from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    module_path = Path("src/agilab/orchestrate_cluster.py")
    spec = importlib.util.spec_from_file_location("agilab_orchestrate_cluster_tests", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compute_cluster_mode_uses_expected_bitmask():
    module = _load_module()

    result = module.compute_cluster_mode(
        {"pool": True, "cython": True, "rapids": True},
        cluster_enabled=True,
    )

    assert result == 15


def test_persist_env_var_if_changed_ignores_same_value():
    module = _load_module()
    calls: list[tuple[str, str]] = []

    module.persist_env_var_if_changed(
        key="CLUSTER_CREDENTIALS",
        value="user",
        set_env_var=lambda key, value: calls.append((key, value)),
        agi_env_envars={"CLUSTER_CREDENTIALS": "user"},
    )

    assert calls == []


def test_persist_env_var_if_changed_updates_changed_value():
    module = _load_module()
    calls: list[tuple[str, str]] = []

    module.persist_env_var_if_changed(
        key="AGI_SSH_KEY_PATH",
        value="~/.ssh/id_rsa",
        set_env_var=lambda key, value: calls.append((key, value)),
        agi_env_envars={"AGI_SSH_KEY_PATH": ""},
    )

    assert calls == [("AGI_SSH_KEY_PATH", "~/.ssh/id_rsa")]
