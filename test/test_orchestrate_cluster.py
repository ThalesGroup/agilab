from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types


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


orchestrate_cluster = _import_agilab_module("agilab.orchestrate_cluster")


def test_compute_cluster_mode_uses_expected_bitmask():
    result = orchestrate_cluster.compute_cluster_mode(
        {"pool": True, "cython": True, "rapids": True},
        cluster_enabled=True,
    )

    assert result == 15


def test_persist_env_var_if_changed_ignores_same_value():
    calls: list[tuple[str, str]] = []

    orchestrate_cluster.persist_env_var_if_changed(
        key="CLUSTER_CREDENTIALS",
        value="user",
        set_env_var=lambda key, value: calls.append((key, value)),
        agi_env_envars={"CLUSTER_CREDENTIALS": "user"},
    )

    assert calls == []


def test_persist_env_var_if_changed_updates_changed_value():
    calls: list[tuple[str, str]] = []

    orchestrate_cluster.persist_env_var_if_changed(
        key="AGI_SSH_KEY_PATH",
        value="~/.ssh/id_rsa",
        set_env_var=lambda key, value: calls.append((key, value)),
        agi_env_envars={"AGI_SSH_KEY_PATH": ""},
    )

    assert calls == [("AGI_SSH_KEY_PATH", "~/.ssh/id_rsa")]
