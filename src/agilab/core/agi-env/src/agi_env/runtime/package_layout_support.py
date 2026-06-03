"""Package and resource layout helpers extracted from AgiEnv bootstrap."""

from __future__ import annotations

import importlib.util
import importlib.metadata as importlib_metadata
from dataclasses import dataclass
from importlib.abc import Loader
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping


RUNTIME_PACKAGE_ENTRY_POINT_GROUP = "agi_env.runtime_packages"
RUNTIME_PACKAGE_SOURCE_MANIFEST = "agi_env_runtime.py"


@dataclass(frozen=True)
class AgilabPackageContext:
    package_dir: Path
    apps_root_hint: Path
    is_installed: bool


@dataclass(frozen=True)
class PackageLayout:
    agilab_pck: Path
    env_pck: Path
    runtime_packages: dict[str, RuntimePackageLayout]
    cli: Path | None
    worker_pre_install: Path | None
    worker_post_install: Path | None
    worker_post_install_module: str | None
    setup_app_module: str | None


@dataclass(frozen=True)
class RuntimePackageSpec:
    role: str
    project_dir: str
    module_name: str
    order: int = 100
    source_package_rel: str | None = None
    cli_rel: str | None = None
    worker_pre_install_rel: str | None = None
    worker_post_install_rel: str | None = None
    worker_post_install_module: str | None = None
    setup_app_module: str | None = None
    hook_package: str | None = None
    hook_source_rel: str | None = None
    hook_cache_name: str | None = None


@dataclass(frozen=True)
class RuntimePackageLayout:
    spec: RuntimePackageSpec
    package_pck: Path
    project_pck: Path


def resolve_package_dir_from_module_file(module_file: str | Path, package_name: str, *, path_cls=Path) -> Path:
    """Return the nearest package directory named ``package_name`` for a module file."""

    module_path = path_cls(module_file).resolve()
    for parent in module_path.parents:
        if parent.name == package_name and (parent / "__init__.py").exists():
            return parent
    raise FileNotFoundError(f"Unable to locate package directory {package_name!r} from {module_path}")


def resolve_agilab_source_root_from_module_file(
    module_file: str | Path,
    *,
    path_cls=Path,
    legacy_parent_index: int | None = None,
) -> Path | None:
    """Return the source checkout's ``src/agilab`` directory when discoverable."""

    module_path = path_cls(module_file).resolve()
    for parent in module_path.parents:
        if (parent / "core" / "agi-env").exists() and (parent / "apps").exists():
            return parent
    if legacy_parent_index is not None:
        try:
            return module_path.parents[legacy_parent_index]
        except IndexError:
            return None
    return None


def resolve_agilab_package_context(
    *,
    repo_agilab_dir: Path,
    find_spec_fn=None,
    path_cls=Path,
    installed_markers: tuple[str, ...] = ("site-packages", "dist-packages"),
) -> AgilabPackageContext:
    """Resolve the current AGILAB package directory and whether it comes from an install."""
    if find_spec_fn is None:
        find_spec_fn = importlib.util.find_spec

    agilab_spec = find_spec_fn("agilab")
    if agilab_spec and getattr(agilab_spec, "origin", None):
        package_dir = path_cls(agilab_spec.origin).resolve().parent  # ty: ignore[invalid-argument-type]
    else:
        package_dir = repo_agilab_dir
    package_dir = package_dir.resolve()
    apps_root_hint = package_dir.parent.resolve()
    is_installed = any(part in installed_markers for part in package_dir.parts) or any(
        part.startswith(".venv") for part in package_dir.parts
    )
    return AgilabPackageContext(
        package_dir=package_dir,
        apps_root_hint=apps_root_hint,
        is_installed=is_installed,
    )


def _entry_points(group: str):
    entry_points = importlib_metadata.entry_points()
    if hasattr(entry_points, "select"):
        return entry_points.select(group=group)
    return entry_points.get(group, ())


def _load_source_manifest(manifest: Path) -> ModuleType | None:
    spec = importlib.util.spec_from_file_location(
        f"_agi_env_runtime_manifest_{abs(hash(str(manifest)))}",
        manifest,
    )
    if spec is None or not isinstance(spec.loader, Loader):
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _coerce_runtime_package_spec(raw_spec: Any) -> RuntimePackageSpec | None:
    if callable(raw_spec) and not isinstance(raw_spec, type):
        raw_spec = raw_spec()
    if raw_spec is None:
        return None
    if isinstance(raw_spec, RuntimePackageSpec):
        return raw_spec
    if isinstance(raw_spec, Mapping):
        return RuntimePackageSpec(**raw_spec)

    data = {
        field: getattr(raw_spec, field)
        for field in RuntimePackageSpec.__dataclass_fields__
        if hasattr(raw_spec, field)
    }
    if data:
        return RuntimePackageSpec(**data)
    return None


def discover_source_runtime_package_specs(
    repo_agilab_dir: Path,
    *,
    path_cls=Path,
    manifest_name: str = RUNTIME_PACKAGE_SOURCE_MANIFEST,
) -> tuple[RuntimePackageSpec, ...]:
    """Load runtime package specs contributed by adjacent source packages."""

    core_root = path_cls(repo_agilab_dir) / "core"
    specs_by_role: dict[str, RuntimePackageSpec] = {}
    for manifest in sorted(core_root.glob(f"*/src/*/{manifest_name}")):
        module = _load_source_manifest(manifest)
        if module is None:
            continue
        raw_spec = getattr(module, "RUNTIME_PACKAGE_SPEC", None)
        spec = _coerce_runtime_package_spec(raw_spec)
        if spec is not None:
            specs_by_role[spec.role] = spec
    return tuple(sorted(specs_by_role.values(), key=lambda spec: (spec.order, spec.role)))


def load_runtime_package_specs(
    *,
    repo_agilab_dir: Path | None,
    include_source: bool,
    entry_points_fn=None,
    path_cls=Path,
) -> tuple[RuntimePackageSpec, ...]:
    """Return runtime package specs without hardcoding package names in ``agi-env``."""

    specs_by_role: dict[str, RuntimePackageSpec] = {}

    if include_source and repo_agilab_dir is not None:
        for spec in discover_source_runtime_package_specs(repo_agilab_dir, path_cls=path_cls):
            specs_by_role[spec.role] = spec
        if specs_by_role:
            return tuple(sorted(specs_by_role.values(), key=lambda spec: (spec.order, spec.role)))

    entry_points_iter = _entry_points if entry_points_fn is None else entry_points_fn
    for entry_point in entry_points_iter(RUNTIME_PACKAGE_ENTRY_POINT_GROUP):
        try:
            raw_spec = entry_point.load()
        except (AttributeError, ImportError, ModuleNotFoundError):
            continue
        spec = _coerce_runtime_package_spec(raw_spec)
        if spec is not None:
            specs_by_role.setdefault(spec.role, spec)

    return tuple(sorted(specs_by_role.values(), key=lambda spec: (spec.order, spec.role)))


def _resolve_source_runtime_package(
    spec: RuntimePackageSpec,
    *,
    core_root: Path,
    path_cls=Path,
) -> RuntimePackageLayout:
    project_pck = path_cls(core_root) / spec.project_dir
    source_package_rel = spec.source_package_rel or f"src/{spec.module_name}"
    package_pck = project_pck / source_package_rel
    return RuntimePackageLayout(spec=spec, package_pck=package_pck, project_pck=project_pck)


def _resolve_installed_runtime_package(
    spec: RuntimePackageSpec,
    *,
    resolve_package_dir_fn,
    find_spec_fn,
    path_cls=Path,
) -> RuntimePackageLayout | None:
    try:
        package_pck = resolve_package_dir_fn(spec.module_name, find_spec_fn=find_spec_fn, path_cls=path_cls)
    except ModuleNotFoundError:
        return None
    return RuntimePackageLayout(spec=spec, package_pck=package_pck, project_pck=path_cls(package_pck).parent)


def _first_spec_path(
    runtime_packages: Mapping[str, RuntimePackageLayout],
    attr_name: str,
    *,
    path_cls=Path,
) -> Path | None:
    for runtime_package in runtime_packages.values():
        rel_path = getattr(runtime_package.spec, attr_name)
        if rel_path:
            return path_cls(runtime_package.package_pck) / rel_path
    return None


def _first_spec_value(runtime_packages: Mapping[str, RuntimePackageLayout], attr_name: str) -> str | None:
    for runtime_package in runtime_packages.values():
        value = getattr(runtime_package.spec, attr_name)
        if value:
            return value
    return None


def resolve_package_layout(
    *,
    is_source_env: bool,
    repo_agilab_dir: Path,
    installed_package_dir: Path,
    resolve_package_dir_fn,
    find_spec_fn=None,
    path_cls=Path,
    runtime_package_specs: tuple[RuntimePackageSpec, ...] | None = None,
) -> PackageLayout:
    """Resolve the package roots used by AgiEnv for source and installed layouts."""
    if find_spec_fn is None:
        find_spec_fn = importlib.util.find_spec
    if runtime_package_specs is None:
        runtime_package_specs = load_runtime_package_specs(
            repo_agilab_dir=repo_agilab_dir,
            include_source=is_source_env,
            path_cls=path_cls,
        )

    if is_source_env:
        core_root = repo_agilab_dir / "core"
        runtime_packages = {
            runtime_spec.role: _resolve_source_runtime_package(runtime_spec, core_root=core_root, path_cls=path_cls)
            for runtime_spec in runtime_package_specs
        }
        return PackageLayout(
            agilab_pck=repo_agilab_dir,
            env_pck=core_root / "agi-env/src/agi_env",
            runtime_packages=runtime_packages,
            cli=_first_spec_path(runtime_packages, "cli_rel", path_cls=path_cls),
            worker_pre_install=_first_spec_path(runtime_packages, "worker_pre_install_rel", path_cls=path_cls),
            worker_post_install=_first_spec_path(runtime_packages, "worker_post_install_rel", path_cls=path_cls),
            worker_post_install_module=_first_spec_value(runtime_packages, "worker_post_install_module"),
            setup_app_module=_first_spec_value(runtime_packages, "setup_app_module"),
        )

    env_pck = resolve_package_dir_fn("agi_env", find_spec_fn=find_spec_fn, path_cls=path_cls)
    runtime_packages = {}
    for runtime_spec in runtime_package_specs:
        runtime_package = _resolve_installed_runtime_package(
            runtime_spec,
            resolve_package_dir_fn=resolve_package_dir_fn,
            find_spec_fn=find_spec_fn,
            path_cls=path_cls,
        )
        if runtime_package is not None:
            runtime_packages[runtime_spec.role] = runtime_package

    return PackageLayout(
        agilab_pck=installed_package_dir,
        env_pck=env_pck,
        runtime_packages=runtime_packages,
        cli=_first_spec_path(runtime_packages, "cli_rel", path_cls=path_cls),
        worker_pre_install=_first_spec_path(runtime_packages, "worker_pre_install_rel", path_cls=path_cls),
        worker_post_install=_first_spec_path(runtime_packages, "worker_post_install_rel", path_cls=path_cls),
        worker_post_install_module=_first_spec_value(runtime_packages, "worker_post_install_module"),
        setup_app_module=_first_spec_value(runtime_packages, "setup_app_module"),
    )


def resolve_resource_root(agilab_pck: Path, *, path_cls=Path) -> Path:
    """Return the preferred resources directory for the current AGILAB layout."""
    candidates = [
        path_cls(agilab_pck) / "resources",
        path_cls(agilab_pck) / "agilab/resources",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]
