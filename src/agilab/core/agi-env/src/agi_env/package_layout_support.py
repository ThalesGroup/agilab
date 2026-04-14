"""Package and resource layout helpers extracted from AgiEnv bootstrap."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgilabPackageContext:
    package_dir: Path
    apps_root_hint: Path
    is_installed: bool


@dataclass(frozen=True)
class PackageLayout:
    agilab_pck: Path
    env_pck: Path
    node_pck: Path
    core_pck: Path
    cluster_pck: Path
    cli: Path


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
        package_dir = path_cls(agilab_spec.origin).resolve().parent
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


def resolve_package_layout(
    *,
    is_source_env: bool,
    repo_agilab_dir: Path,
    installed_package_dir: Path,
    resolve_package_dir_fn,
    find_spec_fn=None,
    path_cls=Path,
) -> PackageLayout:
    """Resolve the package roots used by AgiEnv for source and installed layouts."""
    if find_spec_fn is None:
        find_spec_fn = importlib.util.find_spec

    if is_source_env:
        core_root = repo_agilab_dir / "core"
        return PackageLayout(
            agilab_pck=repo_agilab_dir,
            env_pck=core_root / "agi-env/src/agi_env",
            node_pck=core_root / "agi-node/src/agi_node",
            core_pck=core_root / "agi-core/src/agi_core",
            cluster_pck=core_root / "agi-cluster/src/agi_cluster",
            cli=core_root / "agi-cluster/src/agi_cluster/agi_distributor/cli.py",
        )

    env_pck = resolve_package_dir_fn("agi_env", find_spec_fn=find_spec_fn, path_cls=path_cls)
    node_pck = resolve_package_dir_fn("agi_node", find_spec_fn=find_spec_fn, path_cls=path_cls)
    try:
        core_pck = resolve_package_dir_fn("agi_core", find_spec_fn=find_spec_fn, path_cls=path_cls)
    except ModuleNotFoundError:
        core_pck = path_cls(env_pck).parent

    try:
        cluster_pck = resolve_package_dir_fn("agi_cluster", find_spec_fn=find_spec_fn, path_cls=path_cls)
    except ModuleNotFoundError:
        cluster_pck = core_pck

    try:
        cli_spec = find_spec_fn("agi_cluster.agi_distributor.cli")
    except ModuleNotFoundError:
        cli_spec = None
    cli = path_cls(cli_spec.origin) if cli_spec and getattr(cli_spec, "origin", None) else cluster_pck / "agi_distributor/cli.py"

    return PackageLayout(
        agilab_pck=installed_package_dir,
        env_pck=env_pck,
        node_pck=node_pck,
        core_pck=core_pck,
        cluster_pck=cluster_pck,
        cli=cli,
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
