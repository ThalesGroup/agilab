import getpass
import logging
import os
import re
import shutil
import stat
import subprocess
import time
from importlib.metadata import (
    PackageNotFoundError,
    distribution as pkg_distribution,
    version as pkg_version,
)
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, cast

import tomlkit
from packaging.requirements import InvalidRequirement, Requirement

from agi_cluster.agi_distributor import deployment_dask_support
from agi_cluster.agi_distributor.deployment_editable_install_support import (
    EDITABLE_INSTALL_CACHE_SCHEMA as EDITABLE_INSTALL_CACHE_SCHEMA,
    EDITABLE_SHADOW_IMPORTS as EDITABLE_SHADOW_IMPORTS,
    _cleanup_editable as _cleanup_editable,
    _cleanup_editable_shadow_packages as _cleanup_editable_shadow_packages,
    _editable_install_cache_hit as _editable_install_cache_hit,
    _editable_install_cache_path as _editable_install_cache_path,
    _editable_install_digest as _editable_install_digest,
    _editable_install_metadata_inputs as _editable_install_metadata_inputs,
    _editable_install_project as _editable_install_project,
    _editable_install_proof_exists as _editable_install_proof_exists,
    _editable_shadow_import_names as _editable_shadow_import_names,
    _load_editable_install_cache as _load_editable_install_cache,
    _record_editable_install_cache as _record_editable_install_cache,
    _remove_site_package_shadow as _remove_site_package_shadow,
    _write_editable_install_cache as _write_editable_install_cache,
)
from agi_cluster.agi_distributor.deployment_install_spec_support import (
    _build_worker_core_add_commands as _build_worker_core_add_commands,
    _deploy_stage_inputs_for_specs as _deploy_stage_inputs_for_specs,
    _is_local_project_install_spec as _is_local_project_install_spec,
    _is_python_project as _is_python_project,
    _resolve_distribution_install_spec as _support_resolve_distribution_install_spec,
)
from agi_cluster.agi_distributor.deployment_resolver_env_support import (
    UV_INDEX_RESOLVER_ENV_VARS as UV_INDEX_RESOLVER_ENV_VARS,
    UV_RESOLVER_PROPAGATED_ENV_VARS as UV_RESOLVER_PROPAGATED_ENV_VARS,
    UV_WHEELHOUSE_RESOLVER_ENV_VARS as UV_WHEELHOUSE_RESOLVER_ENV_VARS,
    _envar_nonempty as _envar_nonempty,
    _envar_value as _envar_value,
    _local_worker_post_install_env_prefix as _local_worker_post_install_env_prefix,
    _shell_env_prefix as _shell_env_prefix,
    _uv_offline_flag as _uv_offline_flag,
    _uv_resolver_env_prefix as _uv_resolver_env_prefix,
    _uv_resolver_mode as _uv_resolver_mode,
)
from agi_cluster.agi_distributor.deployment_stage_cache_support import (
    DEPLOY_COPY_STAMP_FILENAME as DEPLOY_COPY_STAMP_FILENAME,
    DEPLOY_COPY_STAMP_SCHEMA as DEPLOY_COPY_STAMP_SCHEMA,
    DEPLOY_STAGE_CACHE_SCHEMA as DEPLOY_STAGE_CACHE_SCHEMA,
    DEPLOY_TIMING_TRACE_SCHEMA as DEPLOY_TIMING_TRACE_SCHEMA,
    DISABLE_DEPLOY_STAGE_CACHE_ENV as DISABLE_DEPLOY_STAGE_CACHE_ENV,
    REFRESH_LOCKS_ENV as REFRESH_LOCKS_ENV,
    _deploy_copy_stamp_matches as _deploy_copy_stamp_matches,
    _deploy_copy_stamp_path as _deploy_copy_stamp_path,
    _deploy_copy_stamp_payload as _deploy_copy_stamp_payload,
    _deploy_path_key as _deploy_path_key,
    _deploy_stage_cache_enabled as _deploy_stage_cache_enabled,
    _deploy_stage_cache_path as _deploy_stage_cache_path,
    _deploy_stage_directory_fingerprint as _deploy_stage_directory_fingerprint,
    _deploy_stage_file_fingerprint as _deploy_stage_file_fingerprint,
    _deploy_stage_project_inputs as _deploy_stage_project_inputs,
    _deploy_timing_trace_path as _deploy_timing_trace_path,
    _env_truthy as _env_truthy,
    _env_value as _env_value,
    _load_deploy_stage_cache as _load_deploy_stage_cache,
    _write_deploy_copy_stamp as _write_deploy_copy_stamp,
    _write_deploy_stage_cache as _write_deploy_stage_cache,
    _write_deploy_timing_trace as _write_deploy_timing_trace,
)
from agi_cluster.agi_distributor.deployment_stage_plan_support import (
    _DeployPlan as _DeployPlan,
    _DeployPlanNode as _DeployPlanNode,
    _deploy_stage_digest as _deploy_stage_digest,
    _run_cached_deploy_stage as _run_cached_deploy_stage,
)
from agi_cluster.agi_distributor.deployment_venv_support import (
    project_site_packages_dir as _project_site_packages_dir,
    project_venv_cfg_version as _project_venv_cfg_version,
    project_venv_matches as _project_venv_matches,
    project_venv_python as _project_venv_python,
    project_venv_root as _project_venv_root,
    python_version_tuple as _python_version_tuple,
)
from agi_cluster.agi_distributor.deployment_worker_venv_cache_support import (
    SHARED_WORKER_VENV_DIR_ENV as SHARED_WORKER_VENV_DIR_ENV,
    SHARED_WORKER_VENV_ENV as SHARED_WORKER_VENV_ENV,
    _file_fingerprint as _file_fingerprint,
    _shared_worker_venv_cache_key as _shared_worker_venv_cache_key,
    _shared_worker_venv_project as _shared_worker_venv_project,
)
from agi_env import AgiEnv


logger = logging.getLogger(__name__)
FORCE_REMOVE_EXCEPTIONS = (OSError, shutil.Error)
DEPENDENCY_PARSE_EXCEPTIONS = (InvalidRequirement,)
PYPROJECT_PARSE_EXCEPTIONS = (OSError, tomlkit.exceptions.ParseError)  # ty: ignore[possibly-missing-submodule]
PERF_TRACE_ENV = "AGILAB_PERF_TRACE"
DEPENDENCY_MODULE_ALIASES: dict[str, tuple[str, ...]] = {
    "pillow": ("PIL",),
    "python-dotenv": ("dotenv",),
    "pyyaml": ("yaml",),
    "scikit-learn": ("sklearn",),
}


def _latest_glob_match(root: Path, pattern: str) -> Path | None:
    matches = sorted(root.glob(pattern), key=lambda candidate: candidate.name)
    if not matches:
        return None
    return max(
        matches, key=lambda candidate: (candidate.stat().st_mtime_ns, candidate.name)
    )


def _force_remove(path: Path, *, env_logger: Any | None = None) -> None:
    """Delete a path robustly, falling back to Windows `rmdir` when needed."""
    if path.is_symlink():
        path.unlink()
        return
    if not path.exists():
        return

    def _on_err(
        func: Callable[..., Any],
        p: str,
        exc: tuple[type[BaseException], BaseException, Any],
    ) -> None:
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
            env_logger.warn(
                "Path {} still exists, using subprocess cmd to delete it.".format(path)
            )
        subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(path)], check=False)


def _resolve_distribution_install_spec(package_name: str) -> str | None:
    return _support_resolve_distribution_install_spec(
        package_name,
        distribution_fn=pkg_distribution,
    )


def _resolve_install_spec(project_path: Path | None, package_name: str) -> str | None:
    if isinstance(project_path, Path) and _is_python_project(project_path):
        return str(project_path)
    return _resolve_distribution_install_spec(package_name)


def _remove_project_venv_if_mismatched(
    project: Path,
    *,
    env_logger: Any | None = None,
    os_name: str = os.name,
    python_version: str | None = None,
) -> bool:
    if _project_venv_matches(project, os_name=os_name, python_version=python_version):
        return False

    venv_root = project / ".venv"
    if venv_root.exists() or venv_root.is_symlink():
        _force_remove(venv_root, env_logger=env_logger)
        return True
    return False


async def _ensure_project_venv(
    uv_cmd: str,
    project: Path,
    *,
    run_fn: Callable[..., Any],
    os_name: str = os.name,
    python_version: str | None = None,
    venv_project: Path | None = None,
) -> None:
    effective_venv_project = venv_project or project
    if _project_venv_matches(
        effective_venv_project,
        os_name=os_name,
        python_version=python_version,
    ):
        return
    _remove_project_venv_if_mismatched(
        effective_venv_project,
        os_name=os_name,
        python_version=python_version,
    )
    python_arg = f" --python {python_version}" if python_version else ""
    cmd = f'{uv_cmd} venv --allow-existing{python_arg} "{_project_venv_root(effective_venv_project)}"'
    await run_fn(cmd, project)


def _copy_package_resources(
    resources_src: Path,
    resources_dest: Path,
    *,
    env_logger: Any | None = None,
    copy_cache_enabled: bool = True,
) -> None:
    if not resources_src.exists():
        return
    stamp_path = _deploy_copy_stamp_path(resources_dest, directory=True)
    stamp_payload = _deploy_copy_stamp_payload(
        kind="package-resources",
        source=resources_src,
        destination=resources_dest,
        source_fingerprint=_deploy_stage_directory_fingerprint(resources_src),
    )
    if copy_cache_enabled and _deploy_copy_stamp_matches(
        stamp_path,
        stamp_payload,
        output_probe=resources_dest.is_dir,
    ):
        return
    resources_dest.parent.mkdir(parents=True, exist_ok=True)
    if resources_dest.exists():
        _force_remove(resources_dest, env_logger=env_logger)
    shutil.copytree(resources_src, resources_dest, dirs_exist_ok=True)
    if copy_cache_enabled and resources_dest.is_dir():
        _write_deploy_copy_stamp(stamp_path, stamp_payload)


def _copy_archive_with_stamp(
    archive_path: Path, destination: Path, *, copy_cache_enabled: bool = True
) -> bool:
    stamp_path = _deploy_copy_stamp_path(destination, directory=False)
    stamp_payload = _deploy_copy_stamp_payload(
        kind="dataset-archive",
        source=archive_path,
        destination=destination,
        source_fingerprint=_deploy_stage_file_fingerprint(archive_path),
    )
    if copy_cache_enabled and _deploy_copy_stamp_matches(
        stamp_path,
        stamp_payload,
        output_probe=destination.is_file,
    ):
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(archive_path, destination)
    if copy_cache_enabled and destination.is_file():
        _write_deploy_copy_stamp(stamp_path, stamp_payload)
    return True


def _remove_legacy_app_resource_copy(
    app_path: Path, *, env_logger: Any | None = None
) -> None:
    legacy_resources = app_path / "agilab/core/agi-env/src/agi_env/resources"
    if not legacy_resources.exists():
        return
    _force_remove(legacy_resources, env_logger=env_logger)
    stop = app_path.resolve(strict=False)
    current = legacy_resources.parent
    while current != app_path and current.resolve(strict=False).is_relative_to(stop):
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


async def _install_into_project_venv(
    uv_cmd: str,
    project: Path,
    package_ref: str | Path,
    *,
    run_fn: Callable[..., Any],
    os_name: str = os.name,
    editable: bool = False,
    no_deps: bool = True,
    python_version: str | None = None,
    venv_project: Path | None = None,
    install_cache_enabled: bool = True,
) -> None:
    effective_venv_project = venv_project or project
    await _ensure_project_venv(
        uv_cmd,
        project,
        run_fn=run_fn,
        os_name=os_name,
        python_version=python_version,
        venv_project=effective_venv_project,
    )
    package_project = _editable_install_project(package_ref) if editable else None
    if editable and package_project is not None:
        _cleanup_editable_shadow_packages(
            effective_venv_project,
            [package_project],
            os_name=os_name,
            python_version=python_version,
        )
    if (
        install_cache_enabled
        and package_project is not None
        and _editable_install_cache_hit(
            uv_cmd=uv_cmd,
            package_project=package_project,
            venv_project=effective_venv_project,
            editable=editable,
            no_deps=no_deps,
            python_version=python_version,
            os_name=os_name,
        )
    ):
        return

    venv_python = _project_venv_python(effective_venv_project, os_name=os_name)
    package_spec = str(package_ref)
    editable_flag = "-e " if editable else ""
    no_deps_flag = "--no-deps " if no_deps else ""
    cmd = (
        f'{uv_cmd} pip install --python "{venv_python}" '
        f'--upgrade {no_deps_flag}{editable_flag}"{package_spec}"'
    )
    await run_fn(cmd, project)
    if install_cache_enabled and package_project is not None:
        _record_editable_install_cache(
            uv_cmd=uv_cmd,
            package_project=package_project,
            venv_project=effective_venv_project,
            editable=editable,
            no_deps=no_deps,
            python_version=python_version,
            os_name=os_name,
        )


async def _install_many_into_project_venv(
    uv_cmd: str,
    project: Path,
    package_refs: list[str | Path],
    *,
    run_fn: Callable[..., Any],
    os_name: str = os.name,
    editable: bool = False,
    no_deps: bool = True,
    python_version: str | None = None,
    venv_project: Path | None = None,
    install_cache_enabled: bool = True,
) -> None:
    if not package_refs:
        return
    effective_venv_project = venv_project or project
    await _ensure_project_venv(
        uv_cmd,
        project,
        run_fn=run_fn,
        os_name=os_name,
        python_version=python_version,
        venv_project=effective_venv_project,
    )
    package_projects = (
        [_editable_install_project(package_ref) for package_ref in package_refs]
        if editable
        else []
    )
    if editable and package_projects:
        _cleanup_editable_shadow_packages(
            effective_venv_project,
            [package_project for package_project in package_projects if package_project],
            os_name=os_name,
            python_version=python_version,
        )
    package_refs_to_install = package_refs
    package_projects_to_record = package_projects
    if (
        install_cache_enabled
        and package_projects
        and all(package_project is not None for package_project in package_projects)
    ):
        uncached_refs: list[str | Path] = []
        uncached_projects: list[Path | None] = []
        for package_ref, package_project in zip(package_refs, package_projects):
            cache_hit = package_project is not None and _editable_install_cache_hit(
                uv_cmd=uv_cmd,
                package_project=package_project,
                venv_project=effective_venv_project,
                editable=editable,
                no_deps=no_deps,
                python_version=python_version,
                os_name=os_name,
            )
            if cache_hit:
                continue
            uncached_refs.append(package_ref)
            uncached_projects.append(package_project)
        if not uncached_refs:
            return
        package_refs_to_install = uncached_refs
        package_projects_to_record = uncached_projects

    venv_python = _project_venv_python(effective_venv_project, os_name=os_name)
    editable_flag = "-e " if editable else ""
    no_deps_flag = "--no-deps " if no_deps else ""
    package_specs = " ".join(
        f'{editable_flag}"{str(package_ref)}"' for package_ref in package_refs_to_install
    )
    cmd = f'{uv_cmd} pip install --python "{venv_python}" --upgrade {no_deps_flag}{package_specs}'
    await run_fn(cmd, project)
    if install_cache_enabled:
        for package_project in package_projects_to_record:
            if package_project is None:
                continue
            _record_editable_install_cache(
                uv_cmd=uv_cmd,
                package_project=package_project,
                venv_project=effective_venv_project,
                editable=editable,
                no_deps=no_deps,
                python_version=python_version,
                os_name=os_name,
            )


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
        # uv expects POSIX separators in ``tool.uv.sources`` paths.
        overlay_sources[package_name] = package_path.resolve(strict=False).as_posix()
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
    if tool is None or not isinstance(tool, tomlkit.items.Table):  # ty: ignore[possibly-missing-submodule]
        tool = tomlkit.table()
    uv = tool.get("uv")
    if uv is None or not isinstance(uv, tomlkit.items.Table):  # ty: ignore[possibly-missing-submodule]
        uv = tomlkit.table()
    sources = uv.get("sources")
    if sources is None or not isinstance(sources, tomlkit.items.Table):  # ty: ignore[possibly-missing-submodule]
        sources = tomlkit.table()

    if isinstance(project_name, str):
        existing_self_source = sources.get(project_name)
        if (
            isinstance(existing_self_source, dict)
            and existing_self_source.get("workspace") is True
        ):
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
        # uv expects POSIX separators in ``tool.uv.sources`` path values.
        meta["path"] = resolved.as_posix()

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
        if not isinstance(deps, tomlkit.items.Array):  # ty: ignore[possibly-missing-submodule]
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
        if (
            filter_to_worker
            and worker_pyprojects
            and not (meta["sources"] & worker_pyprojects)
        ):
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


def _gather_dependency_specs(
    projects: list[Path | None],
) -> tuple[dict[str, dict[str, Any]], set[str]]:
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


def _dependency_modules_from_info(
    dependency_info: dict[str, dict[str, Any]],
) -> tuple[str, ...]:
    modules: list[str] = []
    for key, meta in dependency_info.items():
        if key.startswith("agi-") or key == "agilab":
            continue
        extras = {
            str(item).strip().lower()
            for item in meta.get("extras", set())
            if str(item).strip()
        }
        modules.extend(
            DEPENDENCY_MODULE_ALIASES.get(
                key,
                (str(meta.get("name") or key).replace("-", "_"),),
            )
        )
        if key == "dask" and "distributed" in extras:
            modules.append("distributed")
    return tuple(dict.fromkeys(modules))


def _pth_import_roots(site_packages: Path) -> tuple[Path, ...]:
    roots: list[Path] = []
    try:
        pth_files = sorted(site_packages.glob("*.pth"))
    except OSError:
        return ()
    for pth_file in pth_files:
        try:
            lines = pth_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            value = line.strip()
            if not value or value.startswith("#") or value.startswith("import "):
                continue
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                candidate = site_packages / candidate
            candidate = candidate.resolve(strict=False)
            if candidate.is_dir():
                roots.append(candidate)
    return tuple(dict.fromkeys(roots))


def _module_available_on_root(root: Path, module: str) -> bool:
    package_path = root / module
    if package_path.exists():
        return True
    return any((root / f"{module}{suffix}").exists() for suffix in (".py", ".so", ".pyd", ".dylib"))


def _project_venv_has_modules(
    project: Path,
    modules: tuple[str, ...],
    *,
    python_version: str | None = None,
) -> bool:
    if not modules:
        return True
    site_packages = _project_site_packages_dir(project, python_version=python_version)
    roots = tuple(dict.fromkeys((site_packages, *_pth_import_roots(site_packages))))
    return all(
        any(_module_available_on_root(root, module) for root in roots)
        for module in modules
    )


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
    if (
        (not env.is_source_env)
        and (not env.is_worker_env)
        and isinstance(run_type, str)
        and "--dev" in run_type
    ):
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

        env_project = (
            repo_env_project
            if repo_env_project and repo_env_project.exists()
            else env.agi_env
        )
        node_project = (
            repo_node_project
            if repo_node_project and repo_node_project.exists()
            else env.agi_node
        )
        core_project = (
            repo_core_project
            if repo_core_project and repo_core_project.exists()
            else None
        )
        cluster_project = (
            repo_cluster_project
            if repo_cluster_project and repo_cluster_project.exists()
            else None
        )
        agilab_project = (
            repo_agilab_root if repo_agilab_root and repo_agilab_root.exists() else None
        )

        projects_for_specs = [
            agilab_project,
            env_project,
            node_project,
            core_project,
            cluster_project,
        ]
        dependency_info, worker_pyprojects = _gather_dependency_specs(
            projects_for_specs
        )
    else:
        env_project = env.agi_env
        node_project = env.agi_node
        core_project = getattr(env, "agi_core", None) if env.is_source_env else None
        cluster_project = (
            getattr(env, "agi_cluster", None) if env.is_source_env else None
        )
        if env.is_source_env:
            repo_root = _read_agilab_repo_root()
            if repo_root is None:
                repo_root = _infer_repo_root_from_runtime(runtime_file)
            if repo_root:
                try:
                    repo_agilab_root = repo_root.parents[1]
                except IndexError:
                    repo_agilab_root = None
        agilab_project = (
            repo_agilab_root if repo_agilab_root and repo_agilab_root.exists() else None
        )

    wenv_abs = env.wenv_abs
    cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")
    envars = getattr(env, "envars", {})
    resolver_env_prefix = _uv_resolver_env_prefix(envars)
    uv = resolver_env_prefix + cmd_prefix + env.uv
    offline_flag = _uv_offline_flag(envars)
    pyvers = env.python_version
    stage_cache_enabled = _deploy_stage_cache_enabled(getattr(env, "envars", {}))
    stage_cache_path = _deploy_stage_cache_path(wenv_abs)
    stage_cache_state = (
        _load_deploy_stage_cache(stage_cache_path)
        if stage_cache_enabled
        else {"schema": DEPLOY_STAGE_CACHE_SCHEMA, "stages": {}}
    )
    deploy_plan = _DeployPlan(
        run_fn=run_fn,
        cache_enabled=stage_cache_enabled,
        cache_state=stage_cache_state,
        cache_path=stage_cache_path,
        log=log,
    )

    if hw_rapids_capable:
        set_env_var_fn(ip, "hw_rapids_capable")
    else:
        set_env_var_fn(ip, "no_rapids_hw")

    if env.verbose > 0:
        log.info(f"Rapids-capable GPU[{ip}]: {hw_rapids_capable}")

    app_path = env.active_app
    manager_probe_dependency_info, _ = _gather_dependency_specs(
        [env_project, node_project, core_project, cluster_project, app_path]
    )
    manager_probe_modules = _dependency_modules_from_info(manager_probe_dependency_info)

    def worker_probe_modules() -> tuple[str, ...]:
        worker_probe_dependency_info, _ = _gather_dependency_specs(
            [env_project, node_project, wenv_abs]
        )
        return _dependency_modules_from_info(worker_probe_dependency_info)

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
    if offline_flag and (not env.is_worker_env):
        manager_overlay_sources = _manager_overlay_core_sources(
            manager_pyproject, manager_core_paths
        )
        manager_sync_uses_overlay = bool(manager_overlay_sources)

    extra_indexes = ""
    if (
        (not offline_flag)
        and str(run_type).strip().startswith("sync")
        and agi_version_missing_on_pypi_fn(app_path)
    ):
        extra_indexes = (
            "PIP_INDEX_URL=https://test.pypi.org/simple "
            "PIP_EXTRA_INDEX_URL=https://pypi.org/simple "
        )

    _remove_project_venv_if_mismatched(
        app_path,
        env_logger=getattr(env, "logger", None),
        python_version=pyvers,
    )
    if _env_truthy(getattr(env, "envars", {}), REFRESH_LOCKS_ENV):
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
            cmd_manager = f"{extra_indexes}{uv} {offline_flag}{run_type} --config-file uv_config.toml --project '{app_path}'"
        else:
            cmd_manager = (
                f"{extra_indexes}{uv} {offline_flag}{run_type} --project '{app_path}'"
            )
        if env.verbose > 0:
            log.info(f"Installing manager: {cmd_manager}")
        await deploy_plan.run(
            _DeployPlanNode(
                name="manager-sync",
                cmd=cmd_manager,
                cwd=app_path,
                inputs=_deploy_stage_project_inputs(
                    app_path, *manager_core_paths.values()
                ),
                output_probe=lambda: _project_venv_matches(
                    app_path, python_version=pyvers
                )
                and _project_venv_has_modules(
                    app_path,
                    manager_probe_modules,
                    python_version=pyvers,
                ),
            )
        )

    source_worker_app_installed = False
    if (not env.is_source_env) and (not env.is_worker_env):
        if manager_sync_uses_overlay:
            await _install_into_project_venv(
                uv,
                app_path,
                app_path,
                run_fn=run_fn,
                editable=True,
                install_cache_enabled=stage_cache_enabled,
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
                if (
                    repo_agilab_root
                    and project_path.resolve() == repo_agilab_root.resolve()
                ):
                    continue
            install_spec = _resolve_install_spec(project_path, package_name)
            if install_spec:
                await _install_into_project_venv(
                    uv,
                    app_path,
                    install_spec,
                    run_fn=run_fn,
                    no_deps=package_name not in {"agi-env", "agi-node", "agi-cluster"},
                    install_cache_enabled=stage_cache_enabled,
                )

        resources_src = env_project / "src/agi_env/resources"
        if not resources_src.exists():
            resources_src = env.env_pck / "resources"
        _remove_legacy_app_resource_copy(
            app_path, env_logger=getattr(env, "logger", None)
        )
        manager_resources = (
            worker_site_packages_dir_fn(
                app_path, env.python_version, windows=(os.name == "nt")
            )
            / "agi_env"
            / "resources"
        )
        log.info(f"mkdir {manager_resources.parent}")
        _copy_package_resources(
            resources_src,
            manager_resources,
            env_logger=getattr(env, "logger", None),
            copy_cache_enabled=stage_cache_enabled,
        )

        site_packages_manager = env.env_pck.parent
        _cleanup_editable(site_packages_manager)

        if dependency_info:
            dep_versions = {}
            for key, meta in dependency_info.items():
                try:
                    dep_versions[key] = pkg_version(meta["name"])
                except PackageNotFoundError:
                    log.debug(
                        "Dependency %s not installed in manager environment",
                        meta["name"],
                    )

    if env.is_source_env:
        await _install_many_into_project_venv(
            f"{uv} {offline_flag}".strip(),
            app_path,
            [env.agi_env, env.agi_node, env.agi_cluster, app_path],
            run_fn=run_fn,
            editable=True,
            no_deps=True,
            python_version=pyvers,
            install_cache_enabled=stage_cache_enabled,
        )

    started_at = time.perf_counter()
    await agi_cls._build_lib_local()
    deploy_plan.record_timing(
        "worker-build-lib",
        "ran",
        time.perf_counter() - started_at,
    )

    uv_worker = resolver_env_prefix + cmd_prefix + env.uv_worker
    pyvers_worker = env.pyvers_worker

    worker_extra_indexes = ""
    if (
        (not offline_flag)
        and str(run_type).strip().startswith("sync")
        and agi_version_missing_on_pypi_fn(wenv_abs)
    ):
        worker_extra_indexes = (
            "PIP_INDEX_URL=https://test.pypi.org/simple; "
            "PIP_EXTRA_INDEX_URL=https://pypi.org/simple; "
        )

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

    worker_venv_project = _shared_worker_venv_project(
        getattr(env, "envars", {}),
        active_app=app_path,
        wenv_abs=wenv_abs,
        python_version=pyvers_worker,
        run_type=run_type,
        options_worker=options_worker,
        worker_core_add_specs=worker_core_add_specs,
        hw_rapids_capable=hw_rapids_capable,
    )
    if worker_venv_project is None:
        worker_venv_project = wenv_abs
    else:
        worker_venv_project.mkdir(parents=True, exist_ok=True)
        _force_remove(wenv_abs / ".venv", env_logger=getattr(env, "logger", None))
        uv_worker = (
            resolver_env_prefix
            + cmd_prefix
            + _shell_env_prefix(
                {"UV_PROJECT_ENVIRONMENT": str(_project_venv_root(worker_venv_project))}
            )
            + env.uv_worker
        )
        if env.verbose > 0:
            log.info(
                "Using shared worker venv cache at %s",
                _project_venv_root(worker_venv_project),
            )

    if (
        (not env.is_source_env)
        and (not env.is_worker_env)
        and dep_versions
        and not worker_core_add_specs
    ):
        _update_pyproject_dependencies(
            wenv_abs / "pyproject.toml",
            dependency_info,
            worker_pyprojects,
            dep_versions,
            filter_to_worker=True,
        )

    _remove_project_venv_if_mismatched(
        worker_venv_project,
        env_logger=getattr(env, "logger", None),
        python_version=pyvers_worker,
    )

    if worker_core_add_specs:
        worker_dependency_names: list[str] = []
        worker_stage_inputs = _deploy_stage_project_inputs(
            wenv_abs,
            app_path,
            env_project,
            node_project,
            core_project,
            cluster_project,
            agilab_project,
        ) + _deploy_stage_inputs_for_specs(worker_core_add_specs)
        worker_core_add_commands = _build_worker_core_add_commands(
            uv_worker,
            wenv_abs,
            worker_core_add_specs,
            offline_flag=offline_flag,
            prefix=worker_extra_indexes,
        )
        for index, cmd_worker in enumerate(worker_core_add_commands):
            stage_name = f"worker-core-add-{index}"
            stage_dependencies = (
                (worker_dependency_names[-1],)
                if worker_dependency_names
                else (() if manager_sync_uses_overlay else ("manager-sync",))
            )
            await deploy_plan.run(
                _DeployPlanNode(
                    name=stage_name,
                    cmd=cmd_worker,
                    cwd=wenv_abs,
                    inputs=worker_stage_inputs,
                    output_probe=lambda: _project_venv_matches(
                        worker_venv_project,
                        python_version=pyvers_worker,
                    ),
                    dependencies=stage_dependencies,
                )
            )
            worker_dependency_names.append(stage_name)
    else:
        worker_dependency_names = ["worker-add-agi-env", "worker-add-agi-node"]
        worker_stage_inputs = _deploy_stage_project_inputs(wenv_abs, app_path)
        cmd_worker = (
            f"{worker_extra_indexes}{uv_worker} --project {wenv_abs} add agi-env"
        )
        await deploy_plan.run(
            _DeployPlanNode(
                name="worker-add-agi-env",
                cmd=cmd_worker,
                cwd=wenv_abs,
                inputs=worker_stage_inputs,
                output_probe=lambda: _project_venv_matches(
                    worker_venv_project,
                    python_version=pyvers_worker,
                ),
                dependencies=() if manager_sync_uses_overlay else ("manager-sync",),
            )
        )
        cmd_worker = (
            f"{worker_extra_indexes}{uv_worker} --project {wenv_abs} add agi-node"
        )
        await deploy_plan.run(
            _DeployPlanNode(
                name="worker-add-agi-node",
                cmd=cmd_worker,
                cwd=wenv_abs,
                inputs=worker_stage_inputs,
                output_probe=lambda: _project_venv_matches(
                    worker_venv_project,
                    python_version=pyvers_worker,
                ),
                dependencies=("worker-add-agi-env",),
            )
        )

    if hw_rapids_capable:
        cmd_worker = (
            f"{worker_extra_indexes}{uv_worker} {offline_flag}{run_type} --python {pyvers_worker} "
            f'--config-file uv_config.toml --project "{wenv_abs}"'
        )
    else:
        cmd_worker = (
            f"{worker_extra_indexes}{uv_worker} {offline_flag}{run_type} {options_worker} "
            f'--python {pyvers_worker} --project "{wenv_abs}"'
        )

    if env.verbose > 0:
        log.info(f"Installing workers: {cmd_worker}")
    await deploy_plan.run(
        _DeployPlanNode(
            name="worker-sync",
            cmd=cmd_worker,
            cwd=wenv_abs,
            inputs=_deploy_stage_project_inputs(
                wenv_abs,
                app_path,
                env_project,
                node_project,
                core_project,
                cluster_project,
                agilab_project,
            ),
            output_probe=lambda: _project_venv_matches(
                worker_venv_project,
                python_version=pyvers_worker,
            )
            and _project_venv_has_modules(
                worker_venv_project,
                worker_probe_modules(),
                python_version=pyvers_worker,
            ),
            dependencies=tuple(worker_dependency_names),
        )
    )

    if deployment_dask_support.dask_mode_enabled(agi_cls):
        cmd_worker = deployment_dask_support.dask_runtime_install_command(
            uv_worker,
            wenv_abs,
            offline_flag=offline_flag,
        )
        if env.verbose > 0:
            log.info(f"Installing Dask worker runtime: {cmd_worker}")
        await deploy_plan.run(
            _DeployPlanNode(
                name="worker-dask-runtime",
                cmd=cmd_worker,
                cwd=wenv_abs,
                inputs=_deploy_stage_project_inputs(wenv_abs),
                output_probe=lambda: _project_venv_matches(
                    worker_venv_project,
                    python_version=pyvers_worker,
                ),
                dependencies=("worker-sync",),
            )
        )

    write_staged_uv_sources_pth_fn(
        worker_site_packages_dir_fn(
            worker_venv_project, env.pyvers_worker, windows=(os.name == "nt")
        ),
        wenv_abs / "_uv_sources",
    )

    if (not env.is_source_env) and (not env.is_worker_env):
        worker_resources_src = env_project / "src/agi_env/resources"
        if not worker_resources_src.exists():
            worker_resources_src = env.env_pck / "resources"
        resources_dest = wenv_abs / "agilab/core/agi-env/src/agi_env/resources"
        log.info(f"mkdir {resources_dest.parent}")
        _copy_package_resources(
            worker_resources_src,
            resources_dest,
            env_logger=getattr(env, "logger", None),
            copy_cache_enabled=stage_cache_enabled,
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
                if (
                    repo_agilab_root
                    and project_path.resolve() == repo_agilab_root.resolve()
                ):
                    continue
            install_spec = _resolve_install_spec(project_path, package_name)
            if install_spec:
                await _install_into_project_venv(
                    uv_worker,
                    wenv_abs,
                    install_spec,
                    run_fn=run_fn,
                    venv_project=worker_venv_project,
                    install_cache_enabled=stage_cache_enabled,
                )

        python_dirs = env.pyvers_worker.split(".")
        if python_dirs[-1].endswith("t"):
            python_dir = f"{python_dirs[0]}.{python_dirs[1].removesuffix('t')}t"
        else:
            python_dir = f"{python_dirs[0]}.{python_dirs[1]}"
        site_packages_worker = (
            worker_venv_project
            / ".venv"
            / "lib"
            / f"python{python_dir}"
            / "site-packages"
        )
        _cleanup_editable(site_packages_worker)
    else:
        editable_flags = "--no-deps " if env.is_source_env else ""
        menv = env.agi_env
        cmd = f'{uv} {offline_flag}--project "{menv}" build --wheel'
        await run_fn(cmd, menv)
        src = menv / "dist"
        env_whl = _latest_glob_match(src, "agi_env*.whl")
        if env_whl is None:
            raise RuntimeError(cmd)

        menv = env.agi_node
        cmd = f'{uv} {offline_flag}--project "{menv}" build --wheel'
        await run_fn(cmd, menv)
        src = menv / "dist"
        whl = _latest_glob_match(src, "agi_node*.whl")
        if whl is None:
            raise RuntimeError(cmd)
        shutil.copy2(whl, wenv_abs)

        if env.is_source_env:
            uv_worker_install = f"{uv_worker} {offline_flag}".rstrip()
            await _install_many_into_project_venv(
                uv_worker_install,
                wenv_abs,
                [env.agi_env, env.agi_node, env.active_app],
                run_fn=run_fn,
                editable=True,
                no_deps=bool(editable_flags),
                python_version=env.pyvers_worker,
                venv_project=worker_venv_project,
                install_cache_enabled=stage_cache_enabled,
            )
            source_worker_app_installed = True
        else:
            uv_worker_install = f"{uv_worker} {offline_flag}".rstrip()
            await _install_into_project_venv(
                uv_worker_install,
                wenv_abs,
                env.agi_env,
                run_fn=run_fn,
                editable=True,
                no_deps=False,
                python_version=env.pyvers_worker,
                venv_project=worker_venv_project,
                install_cache_enabled=stage_cache_enabled,
            )
            await _install_into_project_venv(
                uv_worker_install,
                wenv_abs,
                env.agi_node,
                run_fn=run_fn,
                editable=True,
                no_deps=False,
                python_version=env.pyvers_worker,
                venv_project=worker_venv_project,
                install_cache_enabled=stage_cache_enabled,
            )

    if not source_worker_app_installed:
        await _install_into_project_venv(
            uv_worker,
            wenv_abs,
            env.active_app,
            run_fn=run_fn,
            editable=True,
            no_deps=False,
            python_version=env.pyvers_worker,
            venv_project=worker_venv_project,
            install_cache_enabled=stage_cache_enabled,
        )

    dest = wenv_abs / "src" / env.target_worker
    os.makedirs(dest, exist_ok=True)

    archives: list[Path] = []
    dataset_archive = env.dataset_archive
    if isinstance(dataset_archive, Path) and dataset_archive.exists():
        archives.append(dataset_archive)

    try:
        active_src = Path(env.active_app) / "src"
        if active_src.exists():
            for candidate in sorted(
                active_src.rglob("Trajectory.7z"), key=lambda path: path.as_posix()
            ):
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
                        sat_trajectory_root = (
                            Path(share_root) / "sat_trajectory"
                        ).resolve(strict=False)
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
                _copy_archive_with_stamp(
                    archive_path,
                    dest / archive_path.name,
                    copy_cache_enabled=stage_cache_enabled,
                )
        except (FileNotFoundError, PermissionError, RuntimeError) as exc:
            log.warning(
                "Skipping dataset archive copy to %s: %s",
                install_dataset_dir
                if "install_dataset_dir" in locals()
                else "<share root>",
                exc,
            )

    post_install_cmd = (
        f"{_local_worker_post_install_env_prefix(agi_cls)}"
        f'{uv_worker} run --no-sync --project "{wenv_abs}" '
        f"--python {pyvers_worker} python -m {env.post_install_rel} "
        f'"{env.active_app}"'
    )

    started_at = time.perf_counter()
    if env.user and env.user != getpass.getuser():
        try:
            await agi_cls.exec_ssh("127.0.0.1", post_install_cmd)
        except ConnectionError as exc:
            log.warning(
                "SSH execution failed on localhost (%s), falling back to local run.",
                exc,
            )
            await run_fn(post_install_cmd, wenv_abs)
    else:
        await run_fn(post_install_cmd, wenv_abs)
    deploy_plan.record_timing(
        "worker-post-install",
        "ran",
        time.perf_counter() - started_at,
    )

    await agi_cls._uninstall_modules()
    agi_cls._install_done_local = True

    cli = wenv_abs.parent / "cli.py"
    if not cli.exists():
        try:
            shutil.copy(env.cluster_pck / "agi_distributor/cli.py", cli)
        except FileNotFoundError as exc:
            log.error("Missing cli.py for local worker: %s", exc)
            raise
    cmd = f'{uv_worker} run --no-sync --project "{wenv_abs}" python "{cli}" threaded'
    started_at = time.perf_counter()
    await run_fn(cmd, wenv_abs)
    deploy_plan.record_timing(
        "worker-cli-threaded",
        "ran",
        time.perf_counter() - started_at,
    )
    agi_cls._deploy_stage_results = dict(deploy_plan.results)
    agi_cls._deploy_stage_timings = list(deploy_plan.timings)
    if _env_truthy(getattr(env, "envars", {}), PERF_TRACE_ENV):
        _write_deploy_timing_trace(
            _deploy_timing_trace_path(wenv_abs),
            stages=deploy_plan.timings,
            results=deploy_plan.results,
            app_path=app_path,
            worker_project=worker_venv_project,
        )
