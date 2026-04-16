import getpass
import logging
import os
import shutil
import stat
import subprocess
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path
from typing import Any, Callable, cast

import tomlkit
from packaging.requirements import InvalidRequirement, Requirement

from agi_env import AgiEnv


logger = logging.getLogger(__name__)
FORCE_REMOVE_EXCEPTIONS = (OSError, shutil.Error)
DEPENDENCY_PARSE_EXCEPTIONS = (InvalidRequirement,)
PYPROJECT_PARSE_EXCEPTIONS = (OSError, tomlkit.exceptions.ParseError)


def _force_remove(path: Path, *, env_logger: Any | None = None) -> None:
    """Delete a path robustly, falling back to Windows `rmdir` when needed."""
    if not path.exists():
        return

    def _on_err(func: Callable[..., Any], p: str, exc: tuple[type[BaseException], BaseException, Any]) -> None:
        os.chmod(p, stat.S_IWRITE)
        try:
            func(p)
        except OSError:
            pass

    try:
        shutil.rmtree(path, onerror=_on_err)
    except FORCE_REMOVE_EXCEPTIONS:
        pass

    if path.exists():
        if env_logger is not None:
            env_logger.warn("Path {} still exists, using subprocess cmd to delete it.".format(path))
        subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(path)], shell=True, check=False)


def _cleanup_editable(site_packages: Path) -> None:
    patterns = (
        "__editable__.agi_env*.pth",
        "__editable__.agi_node*.pth",
        "__editable__.agi_core*.pth",
        "__editable__.agi_cluster*.pth",
        "__editable__.agilab*.pth",
    )
    for pattern in patterns:
        for editable in site_packages.glob(pattern):
            try:
                editable.unlink()
            except FileNotFoundError:
                pass


async def _ensure_pip(uv_cmd: str, project: Path, *, run_fn: Callable[..., Any]) -> None:
    cmd = f"{uv_cmd} run --project '{project}' python -m ensurepip --upgrade"
    await run_fn(cmd, project)


def _format_dependency_spec(name: str, extras: set[str], specifiers: list[str]) -> str:
    extras_part = ""
    if extras:
        extras_part = "[" + ",".join(sorted(extras)) + "]"
    spec_part = ""
    if specifiers:
        spec_part = ",".join(specifiers)
    return f"{name}{extras_part}{spec_part}"


def _is_within_repo(path: Path, root: Path | None) -> bool:
    if root is None:
        return False
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError):
        return False


def _infer_repo_root_from_runtime(runtime_file: str) -> Path | None:
    try:
        inferred = Path(runtime_file).resolve().parents[5]
    except IndexError:
        return None
    if (inferred / "core" / "agi-env").exists() and (inferred / "apps").exists():
        return inferred
    return None


def _read_agilab_repo_root() -> Path | None:
    read_agilab_path = cast(Callable[[], Path | None], AgiEnv.read_agilab_path)
    return read_agilab_path()


def _update_pyproject_dependencies(
    pyproject_file: Path,
    dependency_info: dict[str, dict[str, Any]],
    worker_pyprojects: set[str],
    pinned_versions: dict[str, str] | None,
    *,
    filter_to_worker: bool = False,
) -> None:
    try:
        data = tomlkit.parse(pyproject_file.read_text())
    except FileNotFoundError:
        data = tomlkit.document()

    project_tbl = data.get("project")
    if project_tbl is None:
        project_tbl = tomlkit.table()

    deps = project_tbl.get("dependencies")
    if deps is None:
        deps = tomlkit.array()
    else:
        if not isinstance(deps, tomlkit.items.Array):
            arr = tomlkit.array()
            for item in deps:
                arr.append(item)
            deps = arr

    existing = {str(item) for item in deps}
    existing_keys: set[tuple[str, tuple[str, ...]]] = set()
    for item in deps:
        try:
            req = Requirement(str(item))
        except DEPENDENCY_PARSE_EXCEPTIONS:
            continue
        existing_keys.add((req.name.lower(), tuple(sorted(req.extras))))

    for key, meta in dependency_info.items():
        if filter_to_worker and worker_pyprojects and not (meta["sources"] & worker_pyprojects):
            continue
        dep_key = (key, tuple(sorted(meta["extras"])))
        if dep_key in existing_keys:
            continue
        version = (pinned_versions or {}).get(key)
        if version:
            extras_part = ""
            if meta["extras"]:
                extras_part = "[" + ",".join(sorted(meta["extras"])) + "]"
            spec = f"{meta['name']}{extras_part}=={version}"
        else:
            spec = _format_dependency_spec(
                meta["name"],
                meta["extras"],
                meta["specifiers"],
            )
        if spec not in existing:
            deps.append(spec)
            existing.add(spec)
            existing_keys.add(dep_key)

    project_tbl["dependencies"] = deps
    data["project"] = project_tbl
    pyproject_file.write_text(tomlkit.dumps(data))


def _gather_dependency_specs(projects: list[Path | None]) -> tuple[dict[str, dict[str, Any]], set[str]]:
    dependency_info: dict[str, dict[str, Any]] = {}
    worker_pyprojects: set[str] = set()
    seen_pyprojects: set[Path] = set()

    for project_path in projects:
        if not project_path:
            continue
        pyproject_file = project_path / "pyproject.toml"
        try:
            resolved_pyproject = pyproject_file.resolve(strict=True)
        except FileNotFoundError:
            continue
        if resolved_pyproject in seen_pyprojects:
            continue
        seen_pyprojects.add(resolved_pyproject)
        try:
            project_doc = tomlkit.parse(resolved_pyproject.read_text())
        except PYPROJECT_PARSE_EXCEPTIONS:
            continue
        deps = project_doc.get("project", {}).get("dependencies")
        if not deps:
            continue
        worker_pyprojects.add(str(resolved_pyproject))
        for dep in deps:
            try:
                req = Requirement(str(dep))
            except DEPENDENCY_PARSE_EXCEPTIONS:
                continue
            if req.marker and not req.marker.evaluate():
                continue
            normalized = req.name.lower()
            if normalized.startswith("agi-") or normalized == "agilab":
                continue
            meta = dependency_info.setdefault(
                normalized,
                {
                    "name": req.name,
                    "extras": set(),
                    "specifiers": [],
                    "has_exact": False,
                    "sources": set(),
                },
            )
            if req.extras:
                meta["extras"].update(req.extras)
            meta["sources"].add(str(resolved_pyproject))
            if req.specifier:
                for specifier in req.specifier:
                    spec_str = str(specifier)
                    if specifier.operator in {"==", "==="}:
                        meta["has_exact"] = True
                        if not meta["specifiers"] or meta["specifiers"][0] != spec_str:
                            meta["specifiers"] = [spec_str]
                        break
                    if meta["has_exact"]:
                        continue
                    if spec_str not in meta["specifiers"]:
                        meta["specifiers"].append(spec_str)

    return dependency_info, worker_pyprojects


async def deploy_local_worker(
    agi_cls: Any,
    src: Path,
    wenv_rel: Path,
    options_worker: str,
    *,
    agi_version_missing_on_pypi_fn: Callable[[Path], bool],
    worker_site_packages_dir_fn: Callable[..., Path],
    write_staged_uv_sources_pth_fn: Callable[..., Any],
    runtime_file: str,
    run_fn: Callable[..., Any] = AgiEnv.run,
    set_env_var_fn: Callable[..., Any] = AgiEnv.set_env_var,
    log: Any = logger,
) -> None:
    env = agi_cls.env
    run_type = agi_cls._run_type
    if (not env.is_source_env) and (not env.is_worker_env) and isinstance(run_type, str) and "--dev" in run_type:
        run_type = " ".join(part for part in run_type.split() if part != "--dev")
    ip = "127.0.0.1"
    hw_rapids_capable = agi_cls._hardware_supports_rapids() and agi_cls._rapids_enabled
    env.hw_rapids_capable = hw_rapids_capable

    repo_root: Path | None = None
    repo_env_project: Path | None = None
    repo_node_project: Path | None = None
    repo_core_project: Path | None = None
    repo_cluster_project: Path | None = None
    repo_agilab_root: Path | None = None
    dependency_info: dict[str, dict[str, Any]] = {}
    dep_versions: dict[str, str] = {}
    worker_pyprojects: set[str] = set()

    if env.install_type == 0:
        repo_root = _read_agilab_repo_root()
        if repo_root is None:
            repo_root = _infer_repo_root_from_runtime(runtime_file)
        if repo_root:
            repo_env_project = repo_root / "core" / "agi-env"
            repo_node_project = repo_root / "core" / "agi-node"
            repo_core_project = repo_root / "core" / "agi-core"
            repo_cluster_project = repo_root / "core" / "agi-cluster"
            try:
                repo_agilab_root = repo_root.parents[1]
            except IndexError:
                repo_agilab_root = None

        env_project = repo_env_project if repo_env_project and repo_env_project.exists() else env.agi_env
        node_project = repo_node_project if repo_node_project and repo_node_project.exists() else env.agi_node
        core_project = repo_core_project if repo_core_project and repo_core_project.exists() else None
        cluster_project = (
            repo_cluster_project if repo_cluster_project and repo_cluster_project.exists() else None
        )
        agilab_project = repo_agilab_root if repo_agilab_root and repo_agilab_root.exists() else None

        projects_for_specs = [
            agilab_project,
            env_project,
            node_project,
            core_project,
            cluster_project,
        ]
        dependency_info, worker_pyprojects = _gather_dependency_specs(projects_for_specs)
    else:
        env_project = env.agi_env
        node_project = env.agi_node
        core_project = None
        cluster_project = None
        agilab_project = None

    wenv_abs = env.wenv_abs
    cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")
    uv = cmd_prefix + env.uv
    pyvers = env.python_version

    if hw_rapids_capable:
        set_env_var_fn(ip, "hw_rapids_capable")
    else:
        set_env_var_fn(ip, "no_rapids_hw")

    if env.verbose > 0:
        log.info(f"Rapids-capable GPU[{ip}]: {hw_rapids_capable}")

    app_path = env.active_app
    manager_pyproject = app_path / "pyproject.toml"
    manager_pyproject_is_repo_file = _is_within_repo(manager_pyproject, repo_root)
    if (not env.is_source_env) and (not env.is_worker_env) and dependency_info:
        if manager_pyproject_is_repo_file:
            log.info(
                "Skipping dependency rewrite for %s to avoid mutating source checkout.",
                manager_pyproject,
            )
        else:
            _update_pyproject_dependencies(
                manager_pyproject,
                dependency_info,
                worker_pyprojects,
                pinned_versions=None,
                filter_to_worker=False,
            )

    extra_indexes = ""
    if str(run_type).strip().startswith("sync") and agi_version_missing_on_pypi_fn(app_path):
        extra_indexes = (
            "PIP_INDEX_URL=https://test.pypi.org/simple "
            "PIP_EXTRA_INDEX_URL=https://pypi.org/simple "
        )
    if hw_rapids_capable:
        cmd_manager = f"{extra_indexes}{uv} {run_type} --config-file uv_config.toml --project '{app_path}'"
    else:
        cmd_manager = f"{extra_indexes}{uv} {run_type} --project '{app_path}'"

    _force_remove(app_path / ".venv", env_logger=getattr(env, "logger", None))
    try:
        (app_path / "uv.lock").unlink()
    except FileNotFoundError:
        pass

    if env.verbose > 0:
        log.info(f"Installing manager: {cmd_manager}")
    await run_fn(cmd_manager, app_path)

    if (not env.is_source_env) and (not env.is_worker_env):
        await _ensure_pip(uv, app_path, run_fn=run_fn)

        for project_path in (agilab_project, env_project, node_project, core_project, cluster_project):
            if project_path and project_path.exists():
                if repo_agilab_root and project_path.resolve() == repo_agilab_root.resolve():
                    continue
                cmd = (
                    f"{uv} run --project '{app_path}' python -m pip install "
                    f"--upgrade --no-deps '{project_path}'"
                )
                await run_fn(cmd, app_path)

        resources_src = env_project / "src/agi_env/resources"
        if not resources_src.exists():
            resources_src = env.env_pck / "resources"
        manager_resources = app_path / "agilab/core/agi-env/src/agi_env/resources"
        if resources_src.exists():
            log.info(f"mkdir {manager_resources.parent}")
            manager_resources.parent.mkdir(parents=True, exist_ok=True)
            if manager_resources.exists():
                _force_remove(manager_resources, env_logger=getattr(env, "logger", None))
            shutil.copytree(resources_src, manager_resources, dirs_exist_ok=True)

        site_packages_manager = env.env_pck.parent
        _cleanup_editable(site_packages_manager)

        if dependency_info:
            dep_versions = {}
            for key, meta in dependency_info.items():
                try:
                    dep_versions[key] = pkg_version(meta["name"])
                except PackageNotFoundError:
                    log.debug("Dependency %s not installed in manager environment", meta["name"])

    if env.is_source_env:
        cmd = f"{uv} pip install -e '{env.agi_env}'"
        await run_fn(cmd, app_path)
        cmd = f"{uv} pip install -e '{env.agi_node}'"
        await run_fn(cmd, app_path)
        cmd = f"{uv} pip install -e '{env.agi_cluster}'"
        await run_fn(cmd, app_path)
        cmd = f"{uv} pip install -e ."
        await run_fn(cmd, app_path)

    await agi_cls._build_lib_local()

    uv_worker = cmd_prefix + env.uv_worker
    pyvers_worker = env.pyvers_worker

    worker_extra_indexes = ""
    if str(run_type).strip().startswith("sync") and agi_version_missing_on_pypi_fn(wenv_abs):
        worker_extra_indexes = (
            "PIP_INDEX_URL=https://test.pypi.org/simple; "
            "PIP_EXTRA_INDEX_URL=https://pypi.org/simple; "
        )

    if (not env.is_source_env) and (not env.is_worker_env) and dep_versions:
        _update_pyproject_dependencies(
            wenv_abs / "pyproject.toml",
            dependency_info,
            worker_pyprojects,
            dep_versions,
            filter_to_worker=True,
        )

    _force_remove(wenv_abs / ".venv", env_logger=getattr(env, "logger", None))

    worker_core_add_paths: list[Path] = []
    if env.is_source_env:
        worker_core_add_paths = [env.agi_env, env.agi_node]
    elif (
        (not env.is_worker_env)
        and env.install_type == 0
        and env_project
        and node_project
        and env_project.exists()
        and node_project.exists()
    ):
        worker_core_add_paths = [env_project, node_project]

    if worker_core_add_paths:
        quoted_paths = " ".join(f"\"{path}\"" for path in worker_core_add_paths)
        cmd_worker = f"{worker_extra_indexes}{uv_worker} --project {wenv_abs} add {quoted_paths}"
        await run_fn(cmd_worker, wenv_abs)
    else:
        cmd_worker = f"{worker_extra_indexes}{uv_worker} --project {wenv_abs} add agi-env"
        await run_fn(cmd_worker, wenv_abs)
        cmd_worker = f"{worker_extra_indexes}{uv_worker} --project {wenv_abs} add agi-node"
        await run_fn(cmd_worker, wenv_abs)

    if hw_rapids_capable:
        cmd_worker = (
            f"{worker_extra_indexes}{uv_worker} {run_type} --python {pyvers_worker} "
            f"--config-file uv_config.toml --project \"{wenv_abs}\""
        )
    else:
        cmd_worker = (
            f"{worker_extra_indexes}{uv_worker} {run_type} {options_worker} "
            f"--python {pyvers_worker} --project \"{wenv_abs}\""
        )

    if env.verbose > 0:
        log.info(f"Installing workers: {cmd_worker}")
    await run_fn(cmd_worker, wenv_abs)

    write_staged_uv_sources_pth_fn(
        worker_site_packages_dir_fn(wenv_abs, env.pyvers_worker, windows=(os.name == "nt")),
        wenv_abs / "_uv_sources",
    )

    if (not env.is_source_env) and (not env.is_worker_env):
        await _ensure_pip(uv_worker, wenv_abs, run_fn=run_fn)

        worker_resources_src = env_project / "src/agi_env/resources"
        if not worker_resources_src.exists():
            worker_resources_src = env.env_pck / "resources"
        resources_dest = wenv_abs / "agilab/core/agi-env/src/agi_env/resources"
        log.info(f"mkdir {resources_dest.parent}")
        resources_dest.parent.mkdir(parents=True, exist_ok=True)
        if resources_dest.exists():
            _force_remove(resources_dest, env_logger=getattr(env, "logger", None))
        if worker_resources_src.exists():
            shutil.copytree(worker_resources_src, resources_dest, dirs_exist_ok=True)

        for project_path in (agilab_project, env_project, node_project, core_project, cluster_project):
            if project_path and project_path.exists():
                if repo_agilab_root and project_path.resolve() == repo_agilab_root.resolve():
                    continue
                cmd = (
                    f"{uv_worker} run --project \"{wenv_abs}\" python -m pip install "
                    f"--upgrade --no-deps \"{project_path}\""
                )
                await run_fn(cmd, wenv_abs)

        python_dirs = env.pyvers_worker.split(".")
        if python_dirs[-1].endswith("t"):
            python_dir = f"{python_dirs[0]}.{python_dirs[1].removesuffix('t')}t"
        else:
            python_dir = f"{python_dirs[0]}.{python_dirs[1]}"
        site_packages_worker = wenv_abs / ".venv" / "lib" / f"python{python_dir}" / "site-packages"
        _cleanup_editable(site_packages_worker)
    else:
        menv = env.agi_env
        cmd = f"{uv} --project \"{menv}\" build --wheel"
        await run_fn(cmd, menv)
        src = menv / "dist"
        try:
            next(iter(src.glob("agi_env*.whl")))
        except StopIteration:
            raise RuntimeError(cmd)

        cmd = f"{uv_worker} pip install --project \"{wenv_abs}\" -e \"{env.agi_env}\""
        await run_fn(cmd, wenv_abs)

        menv = env.agi_node
        cmd = f"{uv} --project \"{menv}\" build --wheel"
        await run_fn(cmd, menv)
        src = menv / "dist"
        try:
            whl = next(iter(src.glob("agi_node*.whl")))
            shutil.copy2(whl, wenv_abs)
        except StopIteration:
            raise RuntimeError(cmd)

        cmd = f"{uv_worker} pip install --project \"{wenv_abs}\" -e \"{env.agi_node}\""
        await run_fn(cmd, wenv_abs)

    cmd = f"{uv_worker} pip install --project \"{wenv_abs}\" -e \"{env.active_app}\""
    await run_fn(cmd, wenv_abs)

    dest = wenv_abs / "src" / env.target_worker
    os.makedirs(dest, exist_ok=True)

    archives: list[Path] = []
    dataset_archive = env.dataset_archive
    if isinstance(dataset_archive, Path) and dataset_archive.exists():
        archives.append(dataset_archive)

    try:
        active_src = Path(env.active_app) / "src"
        if active_src.exists():
            for candidate in active_src.rglob("Trajectory.7z"):
                if candidate.is_file():
                    archives.append(candidate)
    except OSError:
        pass

    if archives:
        try:
            share_root = env.share_root_path()
            install_dataset_dir = share_root
            log.info(f"mkdir {install_dataset_dir}")
            os.makedirs(install_dataset_dir, exist_ok=True)

            seen_archives: set[str] = set()
            for archive_path in archives:
                if archive_path.name == "Trajectory.7z":
                    try:
                        sat_trajectory_root = (Path(share_root) / "sat_trajectory").resolve(strict=False)
                        candidates = (
                            sat_trajectory_root / "dataframe" / "Trajectory",
                            sat_trajectory_root / "dataset" / "Trajectory",
                        )
                        has_samples = False
                        for candidate in candidates:
                            if candidate.is_dir():
                                samples: list[Path] = []
                                for pattern in ("*.csv", "*.parquet", "*.pq", "*.parq"):
                                    samples.extend(candidate.glob(pattern))
                                    if len(samples) >= 2:
                                        has_samples = True
                                        break
                            if has_samples:
                                break
                        if has_samples:
                            log.info(
                                "Skipping %s copy; sat_trajectory trajectories already available at %s.",
                                archive_path.name,
                                sat_trajectory_root,
                            )
                            continue
                    except OSError:
                        pass

                key = str(archive_path)
                if key in seen_archives:
                    continue
                seen_archives.add(key)
                shutil.copy2(archive_path, dest / archive_path.name)
        except (FileNotFoundError, PermissionError, RuntimeError) as exc:
            log.warning(
                "Skipping dataset archive copy to %s: %s",
                install_dataset_dir if "install_dataset_dir" in locals() else "<share root>",
                exc,
            )

    post_install_cmd = (
        f"{uv_worker} run --no-sync --project \"{wenv_abs}\" "
        f"--python {pyvers_worker} python -m {env.post_install_rel} "
        f"{wenv_rel.stem}"
    )

    if env.user and env.user != getpass.getuser():
        try:
            await agi_cls.exec_ssh("127.0.0.1", post_install_cmd)
        except ConnectionError as exc:
            log.warning("SSH execution failed on localhost (%s), falling back to local run.", exc)
            await run_fn(post_install_cmd, wenv_abs)
    else:
        await run_fn(post_install_cmd, wenv_abs)

    await agi_cls._uninstall_modules()
    agi_cls._install_done_local = True

    cli = wenv_abs.parent / "cli.py"
    if not cli.exists():
        try:
            shutil.copy(env.cluster_pck / "agi_distributor/cli.py", cli)
        except FileNotFoundError as exc:
            log.error("Missing cli.py for local worker: %s", exc)
            raise
    cmd = f"{uv_worker} run --no-sync --project \"{wenv_abs}\" python \"{cli}\" threaded"
    await run_fn(cmd, wenv_abs)
