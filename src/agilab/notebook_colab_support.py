"""Helpers for AGILAB Colab notebooks.

These helpers keep the notebook cells short while preserving the repo-local
bootstrap needed to avoid falling back to an older published wheel inside a
reused Colab runtime.
"""

from __future__ import annotations

import importlib
import os
import pathlib
import shutil
import subprocess
import sys
import types
from dataclasses import dataclass
from io import UnsupportedOperation as IOUnsupportedOperation
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class ColabNotebookContext:
    repo_root: Path | None
    apps_path: Path | None
    builtin_root: Path | None
    AGI: Any
    AgiEnv: type
    ensure_app_core_packages: Callable[[Path], None]
    ensure_env_core_packages: Callable[[Any], None]


def configure_local_notebook_environ(
    environ: dict[str, str] | None = None,
    *,
    source_env: bool = True,
) -> None:
    if environ is None:
        environ = os.environ
    if source_env:
        environ["IS_SOURCE_ENV"] = "1"
    else:
        environ.pop("IS_SOURCE_ENV", None)
    environ["AGI_CLUSTER_ENABLED"] = "0"
    environ.pop("IS_WORKER_ENV", None)


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


def ensure_env_core_packages(ensure_app_core_packages: Callable[[Path], None], app_env: Any) -> None:
    ensure_app_core_packages(Path(app_env.active_app))


def resolve_builtin_root(apps_path: Path | None) -> Path | None:
    if apps_path is None:
        return None
    if apps_path.name == "builtin":
        return apps_path
    candidate = apps_path / "builtin"
    if candidate.exists():
        return candidate
    return None


def _noop(*_args: Any, **_kwargs: Any) -> None:
    return None


def installed_apps_path() -> Path:
    import agilab

    return Path(agilab.__file__).resolve().parent / "apps"


def bootstrap_colab_core(repo_root: str | Path = "/content/agilab") -> ColabNotebookContext:
    repo_root = Path(repo_root)
    configure_local_notebook_environ()

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
        ensure_env_core_packages=lambda app_env: ensure_env_core_packages(ensure_app_core_packages, app_env),
    )


def bootstrap_installed_colab(apps_path: str | Path | None = None) -> ColabNotebookContext:
    configure_local_notebook_environ(source_env=False)
    ensure_pathlib_unsupported_operation()
    clear_agilab_core_modules()

    from agi_cluster.agi_distributor import AGI
    from agi_env import AgiEnv

    resolved_apps_path = (
        Path(apps_path).expanduser() if apps_path is not None else installed_apps_path()
    )
    builtin_root = resolve_builtin_root(resolved_apps_path)

    return ColabNotebookContext(
        repo_root=None,
        apps_path=resolved_apps_path,
        builtin_root=builtin_root,
        AGI=AGI,
        AgiEnv=AgiEnv,
        ensure_app_core_packages=_noop,
        ensure_env_core_packages=_noop,
    )


def worker_venv_path(app_env: Any) -> Path:
    return Path.home() / "wenv" / f"{app_env.target}_worker" / ".venv"


def worker_env_ready(
    app_env: Any,
    *,
    run_fn: Callable[..., Any] = subprocess.run,
) -> bool:
    worker_venv = worker_venv_path(app_env)
    if not worker_venv.exists():
        return False

    worker_root = worker_venv.parent
    cmd = [
        "uv",
        "--quiet",
        "run",
        "--no-sync",
        "--project",
        str(worker_root),
    ]
    pyvers_worker = getattr(app_env, "pyvers_worker", None)
    if pyvers_worker:
        cmd.extend(["--python", str(pyvers_worker)])
    cmd.extend(["python", "-c", "import agi_env, agi_node"])
    result = run_fn(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return getattr(result, "returncode", 1) == 0


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

    worker_venv = worker_venv_path(app_env)
    if worker_env_ready(app_env):
        return False

    action = "Installing"
    if worker_venv.parent.exists():
        shutil.rmtree(worker_venv.parent, ignore_errors=True)
        action = "Reinstalling"

    print_fn(f"{action} worker for {app_env.app}...")
    await AGI.install(
        app_env,
        scheduler=scheduler,
        workers=workers,
        modes_enabled=modes_enabled,
    )
    return True
