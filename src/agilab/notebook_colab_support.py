"""Helpers for AGILAB Colab notebooks.

These helpers keep the notebook cells short while preserving the repo-local
bootstrap needed to avoid falling back to an older published wheel inside a
reused Colab runtime.
"""

from __future__ import annotations

import importlib
import os
import pathlib
import subprocess
import sys
import types
from dataclasses import dataclass
from io import UnsupportedOperation as IOUnsupportedOperation
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class ColabNotebookContext:
    repo_root: Path
    apps_path: Path
    builtin_root: Path
    AGI: Any
    AgiEnv: type
    ensure_app_core_packages: Callable[[Path], None]


def ensure_pathlib_unsupported_operation(pathlib_module=pathlib) -> None:
    if not hasattr(pathlib_module, "UnsupportedOperation"):
        pathlib_module.UnsupportedOperation = IOUnsupportedOperation


def clear_agilab_core_modules(module_names: list[str] | None = None) -> None:
    if module_names is None:
        module_names = ["agi_cluster", "agi_env", "agi_node"]

    prefixes = tuple(module_names)
    for name in list(sys.modules):
        if name in prefixes or any(name.startswith(prefix + ".") for prefix in prefixes):
            del sys.modules[name]
    importlib.invalidate_caches()


def prepend_sys_path_entries(entries: list[Path]) -> None:
    for entry in reversed(entries):
        entry_str = str(entry)
        if entry_str not in sys.path:
            sys.path.insert(0, entry_str)


def bootstrap_colab_core(repo_root: str | Path = "/content/agilab") -> ColabNotebookContext:
    repo_root = Path(repo_root)
    os.environ["IS_SOURCE_ENV"] = "1"
    os.environ.pop("IS_WORKER_ENV", None)

    ensure_pathlib_unsupported_operation()
    clear_agilab_core_modules()

    core_node_src = repo_root / "src" / "agilab" / "core" / "agi-node" / "src"
    core_cluster_src = repo_root / "src" / "agilab" / "core" / "agi-cluster" / "src"
    core_env_src = repo_root / "src" / "agilab" / "core" / "agi-env" / "src"
    local_core_paths = [repo_root / "src", core_node_src, core_env_src, core_cluster_src]

    pythonpath_parts = [str(path) for path in local_core_paths]
    if os.environ.get("PYTHONPATH"):
        pythonpath_parts.append(os.environ["PYTHONPATH"])
    os.environ["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    prepend_sys_path_entries(local_core_paths)

    agi_cluster_pkg = types.ModuleType("agi_cluster")
    agi_cluster_pkg.__path__ = [str(core_cluster_src / "agi_cluster")]
    sys.modules["agi_cluster"] = agi_cluster_pkg

    import agi_node  # noqa: F401
    from agi_cluster.agi_distributor import AGI
    from agi_env import AgiEnv

    apps_path = repo_root / "src" / "agilab" / "apps"
    builtin_root = apps_path / "builtin"
    core_packages = [
        repo_root / "src" / "agilab" / "core" / "agi-env",
        repo_root / "src" / "agilab" / "core" / "agi-node",
        repo_root / "src" / "agilab" / "core" / "agi-cluster",
    ]
    ready_apps: set[Path] = set()

    def ensure_app_core_packages(app_root: Path) -> None:
        if app_root in ready_apps:
            return
        cmd = [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "pip",
            "install",
            "--project",
            str(app_root),
            "-e",
            str(core_packages[0]),
            "-e",
            str(core_packages[1]),
            "-e",
            str(core_packages[2]),
        ]
        subprocess.run(cmd, check=True)
        ready_apps.add(app_root)

    return ColabNotebookContext(
        repo_root=repo_root,
        apps_path=apps_path,
        builtin_root=builtin_root,
        AGI=AGI,
        AgiEnv=AgiEnv,
        ensure_app_core_packages=ensure_app_core_packages,
    )


def worker_venv_path(app_env: Any) -> Path:
    return Path.home() / "wenv" / f"{app_env.target}_worker" / ".venv"


async def install_if_needed(
    AGI: Any,
    app_env: Any,
    *,
    scheduler: str = "127.0.0.1",
    workers: dict[str, int] | None = None,
    modes_enabled: int = 0,
    print_fn: Callable[[str], None] = print,
) -> bool:
    if workers is None:
        workers = {"127.0.0.1": 1}

    if worker_venv_path(app_env).exists():
        return False

    print_fn(f"Installing worker for {app_env.app}...")
    await AGI.install(
        app_env,
        scheduler=scheduler,
        workers=workers,
        modes_enabled=modes_enabled,
    )
    return True
