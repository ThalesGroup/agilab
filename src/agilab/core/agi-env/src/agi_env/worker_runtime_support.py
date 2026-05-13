"""Worker-runtime bootstrap helpers extracted from ``AgiEnv``."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any, Callable

import tomlkit


def _refresh_worker_paths(env_obj: Any, *, target: str, target_worker: str) -> None:
    env_obj.app_src = env_obj.active_app / "src"
    env_obj.manager_pyproject = env_obj.active_app / "pyproject.toml"
    env_obj.uvproject = env_obj.active_app / "uv_config.toml"
    env_obj.worker_path = env_obj.app_src / target_worker / f"{target_worker}.py"
    env_obj.manager_path = env_obj.app_src / target / f"{target}.py"
    env_obj.worker_pyproject = env_obj.worker_path.parent / "pyproject.toml"
    env_obj.dataset_archive = env_obj.worker_path.parent / "dataset.7z"


def _append_sys_path(path: Path, *, normalize_path_fn, sys_path: list[str]) -> None:
    normalized = normalize_path_fn(path)
    if normalized not in sys_path:
        sys_path.append(normalized)


def _resolve_builtin_worker_paths(
    env_obj: Any,
    *,
    target: str,
    target_worker: str,
    apps_path: Path | None,
    apps_root: Path,
    requested_active_app: Path,
    logger: Any,
) -> None:
    if env_obj.worker_path.exists() or env_obj.is_worker_env:
        return

    candidate_apps: list[Path] = []
    expected_project_names = {str(env_obj.app), f"{target}_project"}
    for project_path in getattr(env_obj, "installed_app_project_paths", ()):
        try:
            project = Path(project_path)
        except (TypeError, ValueError):
            continue
        if project.name in expected_project_names:
            candidate_apps.append(project)

    builtin_roots: list[Path] = []
    if env_obj.builtin_apps_path is not None:
        builtin_roots.append(env_obj.builtin_apps_path)
    if apps_path is not None:
        builtin_roots.append(apps_path / "builtin")
    builtin_roots.append(apps_root / "builtin")
    builtin_roots.append(env_obj.agilab_pck / "apps" / "builtin")

    for builtin_root in builtin_roots:
        try:
            candidate_apps.append(builtin_root / env_obj.app)
        except TypeError:
            continue

    for candidate_app in candidate_apps:
        candidate_worker = candidate_app / "src" / target_worker / f"{target_worker}.py"
        if not candidate_worker.exists():
            continue
        try:
            env_obj.active_app = candidate_app.resolve(strict=False)
        except OSError:
            env_obj.active_app = candidate_app
        _refresh_worker_paths(env_obj, target=target, target_worker=target_worker)
        env_obj.builtin_apps_path = builtin_root
        logger.info(
            "Resolved builtin app %s from %s after missing worker path in %s",
            env_obj.app,
            candidate_app,
            requested_active_app,
        )
        break


def _copy_missing_worker_sources(
    env_obj: Any,
    *,
    target_worker: str,
    apps_path: Path | None,
    apps_root: Path,
    logger: Any,
    copytree_fn,
) -> None:
    if env_obj.worker_path.exists():
        return

    copied_packaged_worker = False
    wenv_worker_src = env_obj.wenv_abs / "src" / target_worker / f"{target_worker}.py"
    wenv_worker_pyproject = wenv_worker_src.parent / "pyproject.toml"
    if wenv_worker_src.exists() and wenv_worker_pyproject.exists():
        env_obj.app_src = env_obj.wenv_abs / "src"
        env_obj.worker_path = wenv_worker_src
        env_obj.worker_pyproject = env_obj.worker_path.parent / "pyproject.toml"
        env_obj.dataset_archive = env_obj.worker_path.parent / "dataset.7z"
        copied_packaged_worker = True

    if not copied_packaged_worker:
        if env_obj._ensure_repository_app_link():
            _refresh_worker_paths(env_obj, target=env_obj.target, target_worker=target_worker)
        else:
            packaged_app = env_obj.agilab_pck / "apps" / env_obj.app
            if not env_obj.is_worker_env and packaged_app.exists():
                try:
                    same_app = packaged_app.resolve(strict=False) == env_obj.active_app.resolve(strict=False)
                except OSError:
                    same_app = False

                if not same_app:
                    try:
                        copytree_fn(packaged_app, env_obj.active_app, dirs_exist_ok=True)
                        copied_packaged_worker = True
                        logger.info(
                            "Copied packaged app %s into %s",
                            packaged_app,
                            env_obj.active_app,
                        )
                    except (OSError, shutil.Error) as exc:
                        logger.warning(
                            "Unable to copy packaged worker app from %s to %s: %s",
                            packaged_app,
                            env_obj.active_app,
                            exc,
                        )
            elif not env_obj.is_worker_env and apps_root.exists():
                env_obj.copy_existing_projects(apps_root, apps_path)

        if (
            not env_obj.is_worker_env
            and not env_obj.worker_path.exists()
            and apps_root.exists()
            and env_obj.app.endswith("_worker")
        ):
            project_name = env_obj.app.replace("_worker", "_project")
            project_worker_dir = apps_root / project_name / "src" / env_obj.app
            if project_worker_dir.exists():
                dest_worker_dir = env_obj.active_app / "src" / env_obj.app
                try:
                    copytree_fn(project_worker_dir, dest_worker_dir, dirs_exist_ok=True)
                    logger.info(
                        "Copied project worker sources %s into %s",
                        project_worker_dir,
                        dest_worker_dir,
                    )
                except (OSError, shutil.Error) as exc:
                    logger.warning(
                        "Failed to copy worker sources from %s: %s",
                        project_worker_dir,
                        exc,
                    )
                else:
                    copied_packaged_worker = True

        if copied_packaged_worker:
            _refresh_worker_paths(env_obj, target=env_obj.target, target_worker=target_worker)


def _configure_worker_python_runtime(
    env_obj: Any,
    *,
    envars: dict,
    parse_int_env_value_fn,
    python_supports_free_threading_fn,
) -> None:
    distribution_tree = env_obj.wenv_abs / "distribution_tree.json"
    if distribution_tree.exists():
        distribution_tree.unlink()
    env_obj.distribution_tree = distribution_tree

    pythonpath_entries = env_obj._collect_pythonpath_entries()
    env_obj._configure_pythonpath(pythonpath_entries)

    env_obj.python_version = envars.get("AGI_PYTHON_VERSION", "3.13")
    env_obj.pyvers_worker = env_obj.python_version
    requested_free_threading = bool(parse_int_env_value_fn(envars, "AGI_PYTHON_FREE_THREADED", 0))
    env_obj.is_free_threading_available = (
        requested_free_threading and python_supports_free_threading_fn()
    )
    if env_obj.worker_pyproject.exists():
        with open(env_obj.worker_pyproject, "r", encoding="utf-8") as handle:
            data = tomlkit.parse(handle.read())
        try:
            use_freethread = data["tool"]["freethread_info"]["is_app_freethreaded"]
            if use_freethread and env_obj.is_free_threading_available:
                env_obj.uv_worker = "PYTHON_GIL=0 " + env_obj.uv
                env_obj.pyvers_worker = env_obj.pyvers_worker + "t"
            else:
                env_obj.uv_worker = env_obj.uv
        except KeyError:
            env_obj.uv_worker = env_obj.uv
    else:
        env_obj.uv_worker = env_obj.uv


def configure_worker_runtime(
    env_obj: Any,
    *,
    target: str,
    home_abs: Path,
    apps_path: Path | None,
    apps_root: Path,
    envars: dict,
    requested_active_app: Path,
    ensure_dir_fn: Callable[[str | Path], Path],
    normalize_path_fn,
    parse_int_env_value_fn,
    python_supports_free_threading_fn,
    logger: Any,
    sys_path: list[str] | None = None,
    copytree_fn=shutil.copytree,
) -> None:
    """Configure worker-related paths, source fallbacks, and Python runtime settings."""
    if sys_path is None:
        sys_path = sys.path

    env_obj.target = target
    wenv_root = Path("wenv")
    target_worker = f"{target}_worker"
    env_obj.target_worker = target_worker
    env_obj.wenv_rel = wenv_root / target_worker
    target_class = "".join(part.title() for part in target.split("_"))
    env_obj.target_class = target_class
    env_obj.target_worker_class = target_class + "Worker"

    env_obj.dist_rel = env_obj.wenv_rel / "dist"
    env_obj.wenv_abs = home_abs / env_obj.wenv_rel
    ensure_dir_fn(env_obj.wenv_abs)

    env_obj.pre_install = env_obj.node_pck / "agi_dispatcher/pre_install.py"
    env_obj.post_install = env_obj.node_pck / "agi_dispatcher/post_install.py"
    env_obj.post_install_rel = "agi_node.agi_dispatcher.post_install"

    env_obj.dist_abs = env_obj.wenv_abs / "dist"
    _append_sys_path(env_obj.dist_abs, normalize_path_fn=normalize_path_fn, sys_path=sys_path)

    _refresh_worker_paths(env_obj, target=target, target_worker=target_worker)
    is_local_worker = env_obj.has_agilab_anywhere_under_home(env_obj.agilab_pck)
    worker_src_abs = env_obj.wenv_abs / "src"
    if env_obj.is_worker_env and not is_local_worker:
        env_obj.app_src = env_obj.agilab_pck / "src"
        env_obj.worker_path = worker_src_abs / target_worker / f"{target_worker}.py"
        env_obj.manager_path = worker_src_abs / target / f"{target}.py"

    env_obj.worker_pyproject = env_obj.worker_path.parent / "pyproject.toml"
    env_obj.uvproject = env_obj.active_app / "uv_config.toml"
    env_obj.dataset_archive = env_obj.worker_path.parent / "dataset.7z"

    _append_sys_path(env_obj.app_src, normalize_path_fn=normalize_path_fn, sys_path=sys_path)

    _resolve_builtin_worker_paths(
        env_obj,
        target=target,
        target_worker=target_worker,
        apps_path=apps_path,
        apps_root=apps_root,
        requested_active_app=requested_active_app,
        logger=logger,
    )
    _copy_missing_worker_sources(
        env_obj,
        target_worker=target_worker,
        apps_path=apps_path,
        apps_root=apps_root,
        logger=logger,
        copytree_fn=copytree_fn,
    )

    env_obj.apps_path = apps_path
    _configure_worker_python_runtime(
        env_obj,
        envars=envars,
        parse_int_env_value_fn=parse_int_env_value_fn,
        python_supports_free_threading_fn=python_supports_free_threading_fn,
    )
