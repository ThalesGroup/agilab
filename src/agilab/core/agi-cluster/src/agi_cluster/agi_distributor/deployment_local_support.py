import getpass
import json
import logging
import os
import shutil
import stat
import subprocess
from importlib.metadata import PackageNotFoundError, distribution as pkg_distribution, version as pkg_version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, cast
from urllib.parse import unquote, urlparse

import tomlkit
from packaging.requirements import InvalidRequirement, Requirement

from agi_env import AgiEnv


logger = logging.getLogger(__name__)
FORCE_REMOVE_EXCEPTIONS = (OSError, shutil.Error)
DEPENDENCY_PARSE_EXCEPTIONS = (InvalidRequirement,)
PYPROJECT_PARSE_EXCEPTIONS = (OSError, tomlkit.exceptions.ParseError)


def _latest_glob_match(root: Path, pattern: str) -> Path | None:
    matches = sorted(root.glob(pattern), key=lambda candidate: candidate.name)
    if not matches:
        return None
    return max(matches, key=lambda candidate: (candidate.stat().st_mtime_ns, candidate.name))


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


def _is_python_project(path: Path) -> bool:
    return path.is_dir() and any((path / marker).exists() for marker in ("pyproject.toml", "setup.py"))


def _resolve_distribution_install_spec(package_name: str) -> str | None:
    try:
        distribution = pkg_distribution(package_name)
    except PackageNotFoundError:
        return None

    direct_url_text = distribution.read_text("direct_url.json")
    if direct_url_text:
        try:
            direct_url = json.loads(direct_url_text)
        except json.JSONDecodeError:
            direct_url = None
        if isinstance(direct_url, dict):
            raw_url = direct_url.get("url")
            subdirectory = direct_url.get("subdirectory")
            if isinstance(raw_url, str) and raw_url:
                parsed = urlparse(raw_url)
                if parsed.scheme == "file":
                    local_path = Path(unquote(parsed.path))
                    if _is_python_project(local_path):
                        return str(local_path)

                vcs_info = direct_url.get("vcs_info")
                if isinstance(vcs_info, dict):
                    vcs = vcs_info.get("vcs")
                    if isinstance(vcs, str) and vcs:
                        spec = f"{package_name} @ {vcs}+{raw_url}"
                        requested_revision = vcs_info.get("requested_revision") or vcs_info.get("commit_id")
                        if isinstance(requested_revision, str) and requested_revision:
                            spec += f"@{requested_revision}"
                        if isinstance(subdirectory, str) and subdirectory:
                            spec += f"#subdirectory={subdirectory}"
                        return spec

                spec = f"{package_name} @ {raw_url}"
                if isinstance(subdirectory, str) and subdirectory:
                    spec += f"#subdirectory={subdirectory}"
                return spec

    return f"{package_name}=={distribution.version}"


def _resolve_install_spec(project_path: Path | None, package_name: str) -> str | None:
    if isinstance(project_path, Path) and _is_python_project(project_path):
        return str(project_path)
    return _resolve_distribution_install_spec(package_name)


def _project_venv_python(project: Path, *, os_name: str = os.name) -> Path:
    if os_name == "nt":
        return project / ".venv" / "Scripts" / "python.exe"
    return project / ".venv" / "bin" / "python"


async def _install_into_project_venv(
    uv_cmd: str,
    project: Path,
    package_ref: str | Path,
    *,
    run_fn: Callable[..., Any],
    os_name: str = os.name,
    editable: bool = False,
) -> None:
    venv_python = _project_venv_python(project, os_name=os_name)
    package_spec = str(package_ref)
    editable_flag = "-e " if editable else ""
    cmd = (
        f'{uv_cmd} pip install --python "{venv_python}" '
        f'--upgrade --no-deps {editable_flag}"{package_spec}"'
    )
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
    if root is None or not isinstance(root, Path):
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
    repo_root = read_agilab_path()
    return repo_root if isinstance(repo_root, Path) else None


def _parse_dependency_names(entries: Any) -> set[str]:
    names: set[str] = set()
    if not isinstance(entries, list):
        return names
    for entry in entries:
        if not isinstance(entry, str):
            continue
        try:
            names.add(Requirement(entry).name.lower())
        except DEPENDENCY_PARSE_EXCEPTIONS:
            continue
    return names


def _manager_dependency_names(pyproject_file: Path) -> set[str]:
    try:
        data = tomlkit.parse(pyproject_file.read_text())
    except PYPROJECT_PARSE_EXCEPTIONS:
        return set()
    project = data.get("project", {})
    return _parse_dependency_names(project.get("dependencies"))


def _manager_overlay_core_sources(
    pyproject_file: Path,
    local_core_paths: dict[str, Path],
) -> dict[str, str]:
    dependency_names = _manager_dependency_names(pyproject_file)
    if not dependency_names:
        return {}

    try:
        data = tomlkit.parse(pyproject_file.read_text())
    except PYPROJECT_PARSE_EXCEPTIONS:
        data = tomlkit.document()

    uv_sources = data.get("tool", {}).get("uv", {}).get("sources")
    if not isinstance(uv_sources, dict):
        uv_sources = {}

    overlay_sources: dict[str, str] = {}
    for package_name, package_path in sorted(local_core_paths.items()):
        if package_name not in dependency_names:
            continue
        existing = uv_sources.get(package_name)
        if isinstance(existing, dict):
            existing_path = existing.get("path")
            if isinstance(existing_path, str) and existing_path.strip():
                continue
        overlay_sources[package_name] = str(package_path.resolve(strict=False))
    return overlay_sources


def _write_manager_sync_overlay(
    source_pyproject: Path,
    overlay_dir: Path,
    *,
    local_core_sources: dict[str, str],
) -> Path:
    doc = tomlkit.parse(source_pyproject.read_text())

    project = doc.get("project")
    if project is None:
        project = tomlkit.table()
    project_name = project.get("name")

    tool = doc.get("tool")
    if tool is None or not isinstance(tool, tomlkit.items.Table):
        tool = tomlkit.table()
    uv = tool.get("uv")
    if uv is None or not isinstance(uv, tomlkit.items.Table):
        uv = tomlkit.table()
    sources = uv.get("sources")
    if sources is None or not isinstance(sources, tomlkit.items.Table):
        sources = tomlkit.table()

    if isinstance(project_name, str):
        existing_self_source = sources.get(project_name)
        if isinstance(existing_self_source, dict) and existing_self_source.get("workspace") is True:
            del sources[project_name]

    for source_name in list(sources):
        meta = sources.get(source_name)
        if not isinstance(meta, dict):
            continue
        path_value = meta.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            continue
        resolved = Path(path_value).expanduser()
        if not resolved.is_absolute():
            resolved = (source_pyproject.parent / resolved).resolve(strict=False)
        else:
            resolved = resolved.resolve(strict=False)
        meta["path"] = str(resolved)

    for package_name, package_path in sorted(local_core_sources.items()):
        inline = tomlkit.inline_table()
        inline["path"] = package_path
        sources[package_name] = inline

    uv["sources"] = sources
    tool["uv"] = uv
    doc["tool"] = tool

    overlay_dir.mkdir(parents=True, exist_ok=True)
    overlay_pyproject = overlay_dir / "pyproject.toml"
    overlay_pyproject.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return overlay_dir


def _shell_env_prefix(env_overrides: dict[str, str], *, os_name: str = os.name) -> str:
    if not env_overrides:
        return ""
    if os_name == "nt":
        return "".join(f'set "{key}={value}" && ' for key, value in env_overrides.items())
    return "".join(f"{key}={value} " for key, value in env_overrides.items())


def _uv_offline_flag(envars: Any) -> str:
    raw = os.environ.get("AGI_INTERNET_ON")
    if raw is None:
        try:
            raw = envars.get("AGI_INTERNET_ON")
        except (AttributeError, RuntimeError, TypeError):
            raw = None
    if raw is None:
        return ""
    if isinstance(raw, bool):
        return "" if raw else "--offline "
    if isinstance(raw, (int, float)):
        try:
            return "" if int(raw) == 1 else "--offline "
        except (TypeError, ValueError):
            return "--offline "
    return "" if str(raw).strip().lower() in {"1", "true", "yes", "on"} else "--offline "


def _local_worker_post_install_env_prefix(agi_cls: Any, *, os_name: str = os.name) -> str:
    mode = int(getattr(agi_cls, "_mode", 0) or 0)
    dask_mode = int(getattr(agi_cls, "DASK_MODE", 0) or 0)
    if dask_mode and (mode & dask_mode):
        return ""
    return _shell_env_prefix({"AGI_CLUSTER_ENABLED": "0"}, os_name=os_name)


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
    offline_flag = _uv_offline_flag(getattr(env, "envars", {}))
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

    manager_core_paths: dict[str, Path] = {}
    if env.install_type == 0:
        for package_name, project_path in (
            ("agi-env", env_project),
            ("agi-node", node_project),
            ("agi-core", core_project),
            ("agi-cluster", cluster_project),
            ("agilab", agilab_project),
        ):
            if isinstance(project_path, Path) and _is_python_project(project_path):
                manager_core_paths[package_name] = project_path

    manager_sync_project = app_path
    manager_sync_uses_overlay = False
    manager_overlay_sources: dict[str, str] = {}
    if offline_flag and (not env.is_source_env) and (not env.is_worker_env):
        manager_overlay_sources = _manager_overlay_core_sources(manager_pyproject, manager_core_paths)
        manager_sync_uses_overlay = bool(manager_overlay_sources)

    extra_indexes = ""
    if (not offline_flag) and str(run_type).strip().startswith("sync") and agi_version_missing_on_pypi_fn(app_path):
        extra_indexes = (
            "PIP_INDEX_URL=https://test.pypi.org/simple "
            "PIP_EXTRA_INDEX_URL=https://pypi.org/simple "
        )

    _force_remove(app_path / ".venv", env_logger=getattr(env, "logger", None))
    try:
        (app_path / "uv.lock").unlink()
    except FileNotFoundError:
        pass

    if manager_sync_uses_overlay:
        with TemporaryDirectory(prefix="agilab-manager-sync-") as staged_root:
            manager_sync_project = _write_manager_sync_overlay(
                manager_pyproject,
                Path(staged_root),
                local_core_sources=manager_overlay_sources,
            )
            if hw_rapids_capable:
                cmd_manager = (
                    f"{extra_indexes}{uv} {offline_flag}{run_type} --config-file uv_config.toml "
                    f"--project '{manager_sync_project}' --active --no-install-project"
                )
            else:
                cmd_manager = (
                    f"{extra_indexes}{uv} {offline_flag}{run_type} --project '{manager_sync_project}' "
                    f"--active --no-install-project"
                )
            if env.verbose > 0:
                log.info(f"Installing manager via staged overlay: {cmd_manager}")
            await run_fn(cmd_manager, app_path)
    else:
        if hw_rapids_capable:
            cmd_manager = (
                f"{extra_indexes}{uv} {offline_flag}{run_type} --config-file uv_config.toml --project '{app_path}'"
            )
        else:
            cmd_manager = f"{extra_indexes}{uv} {offline_flag}{run_type} --project '{app_path}'"
        if env.verbose > 0:
            log.info(f"Installing manager: {cmd_manager}")
        await run_fn(cmd_manager, app_path)

    if (not env.is_source_env) and (not env.is_worker_env):
        if manager_sync_uses_overlay:
            await _install_into_project_venv(
                uv,
                app_path,
                app_path,
                run_fn=run_fn,
                editable=True,
            )
        install_targets = (
            (agilab_project, "agilab"),
            (env_project, "agi-env"),
            (node_project, "agi-node"),
            (core_project, "agi-core"),
            (cluster_project, "agi-cluster"),
        )
        for project_path, package_name in install_targets:
            if project_path and project_path.exists():
                if repo_agilab_root and project_path.resolve() == repo_agilab_root.resolve():
                    continue
            install_spec = _resolve_install_spec(project_path, package_name)
            if install_spec:
                await _install_into_project_venv(uv, app_path, install_spec, run_fn=run_fn)

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
        cmd = f"{uv} {offline_flag}pip install -e '{env.agi_env}'"
        await run_fn(cmd, app_path)
        cmd = f"{uv} {offline_flag}pip install -e '{env.agi_node}'"
        await run_fn(cmd, app_path)
        cmd = f"{uv} {offline_flag}pip install -e '{env.agi_cluster}'"
        await run_fn(cmd, app_path)
        cmd = f"{uv} pip install --no-deps -e ."
        await run_fn(cmd, app_path)

    await agi_cls._build_lib_local()

    uv_worker = cmd_prefix + env.uv_worker
    pyvers_worker = env.pyvers_worker

    worker_extra_indexes = ""
    if (not offline_flag) and str(run_type).strip().startswith("sync") and agi_version_missing_on_pypi_fn(wenv_abs):
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

    worker_core_add_specs: list[str] = []
    if env.is_source_env:
        worker_core_add_specs = [str(env.agi_env), str(env.agi_node)]
    elif (
        (not env.is_worker_env)
        and env.install_type == 0
        and env_project
        and node_project
        and env_project.exists()
        and node_project.exists()
    ):
        worker_core_add_specs = [
            spec
            for spec in (
                _resolve_install_spec(env_project, "agi-env"),
                _resolve_install_spec(node_project, "agi-node"),
            )
            if spec
        ]

    if worker_core_add_specs:
        quoted_specs = " ".join(f"\"{spec}\"" for spec in worker_core_add_specs)
        cmd_worker = f"{worker_extra_indexes}{uv_worker} {offline_flag}--project {wenv_abs} add {quoted_specs}"
        await run_fn(cmd_worker, wenv_abs)
    else:
        cmd_worker = f"{worker_extra_indexes}{uv_worker} --project {wenv_abs} add agi-env"
        await run_fn(cmd_worker, wenv_abs)
        cmd_worker = f"{worker_extra_indexes}{uv_worker} --project {wenv_abs} add agi-node"
        await run_fn(cmd_worker, wenv_abs)

    if hw_rapids_capable:
        cmd_worker = (
            f"{worker_extra_indexes}{uv_worker} {offline_flag}{run_type} --python {pyvers_worker} "
            f"--config-file uv_config.toml --project \"{wenv_abs}\""
        )
    else:
        cmd_worker = (
            f"{worker_extra_indexes}{uv_worker} {offline_flag}{run_type} {options_worker} "
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

        install_targets = (
            (agilab_project, "agilab"),
            (env_project, "agi-env"),
            (node_project, "agi-node"),
            (core_project, "agi-core"),
            (cluster_project, "agi-cluster"),
        )
        for project_path, package_name in install_targets:
            if project_path and project_path.exists():
                if repo_agilab_root and project_path.resolve() == repo_agilab_root.resolve():
                    continue
            install_spec = _resolve_install_spec(project_path, package_name)
            if install_spec:
                await _install_into_project_venv(
                    uv_worker,
                    wenv_abs,
                    install_spec,
                    run_fn=run_fn,
                )

        python_dirs = env.pyvers_worker.split(".")
        if python_dirs[-1].endswith("t"):
            python_dir = f"{python_dirs[0]}.{python_dirs[1].removesuffix('t')}t"
        else:
            python_dir = f"{python_dirs[0]}.{python_dirs[1]}"
        site_packages_worker = wenv_abs / ".venv" / "lib" / f"python{python_dir}" / "site-packages"
        _cleanup_editable(site_packages_worker)
    else:
        editable_flags = "--no-deps " if env.is_source_env else ""
        menv = env.agi_env
        cmd = f"{uv} {offline_flag}--project \"{menv}\" build --wheel"
        await run_fn(cmd, menv)
        src = menv / "dist"
        env_whl = _latest_glob_match(src, "agi_env*.whl")
        if env_whl is None:
            raise RuntimeError(cmd)

        cmd = f"{uv_worker} {offline_flag}pip install --project \"{wenv_abs}\" {editable_flags}-e \"{env.agi_env}\""
        await run_fn(cmd, wenv_abs)

        menv = env.agi_node
        cmd = f"{uv} {offline_flag}--project \"{menv}\" build --wheel"
        await run_fn(cmd, menv)
        src = menv / "dist"
        whl = _latest_glob_match(src, "agi_node*.whl")
        if whl is None:
            raise RuntimeError(cmd)
        shutil.copy2(whl, wenv_abs)

        cmd = f"{uv_worker} {offline_flag}pip install --project \"{wenv_abs}\" {editable_flags}-e \"{env.agi_node}\""
        await run_fn(cmd, wenv_abs)

    editable_flags = "--no-deps " if env.is_source_env else ""
    cmd = f"{uv_worker} pip install --project \"{wenv_abs}\" {editable_flags}-e \"{env.active_app}\""
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
            for candidate in sorted(active_src.rglob("Trajectory.7z"), key=lambda path: path.as_posix()):
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
            for archive_path in sorted(archives, key=lambda path: path.as_posix()):
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
        f"{_local_worker_post_install_env_prefix(agi_cls)}"
        f"{uv_worker} run --no-sync --project \"{wenv_abs}\" "
        f"--python {pyvers_worker} python -m {env.post_install_rel} "
        f"\"{env.active_app}\""
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
