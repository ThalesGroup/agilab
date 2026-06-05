"""Pure helpers for resolving shared worker hook scripts."""

from __future__ import annotations

import importlib.resources as importlib_resources
import importlib.util
import shutil
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from agi_env.runtime.package_layout_support import (
    RuntimePackageSpec,
    load_runtime_package_specs,
    resolve_agilab_source_root_from_module_file,
)

HOOK_REPO_FALLBACK_EXCEPTIONS = (IndexError, OSError)


@lru_cache(maxsize=None)
def resolve_worker_hook(filename: str, *, module_file: str) -> Path | None:
    """Return the path to the shared worker hook."""

    repo_agilab_dir = resolve_agilab_source_root_from_module_file(
        module_file,
        legacy_parent_index=4,
    )
    runtime_specs = load_runtime_package_specs(
        repo_agilab_dir=repo_agilab_dir,
        include_source=repo_agilab_dir is not None,
    )
    return resolve_worker_hook_from_specs(filename, repo_agilab_dir=repo_agilab_dir, runtime_specs=runtime_specs)


def resolve_worker_hook_from_specs(
    filename: str,
    *,
    repo_agilab_dir: Path | None,
    runtime_specs: Iterable[RuntimePackageSpec],
) -> Path | None:
    """Return a worker hook from package-owned runtime specs."""

    for runtime_spec in runtime_specs:
        if not runtime_spec.hook_package:
            continue
        installed_hook = _resolve_installed_hook(filename, runtime_spec)
        if installed_hook is not None:
            return installed_hook

        source_hook = _resolve_source_hook(filename, runtime_spec, repo_agilab_dir=repo_agilab_dir)
        if source_hook is not None:
            return source_hook

        resource_hook = _resolve_resource_hook(filename, runtime_spec)
        if resource_hook is not None:
            return resource_hook

    return None


def _resolve_installed_hook(filename: str, runtime_spec: RuntimePackageSpec) -> Path | None:
    try:
        spec = importlib.util.find_spec(runtime_spec.hook_package)
    except ModuleNotFoundError:
        spec = None

    candidates: list[Path] = []
    if spec is None:
        return None

    search_locations = list(spec.submodule_search_locations or [])
    for location in search_locations:
        if location:
            candidates.append(Path(location) / filename)

    if spec.origin:
        origin_path = Path(spec.origin)
        if origin_path.name == "__init__.py":
            candidates.append(origin_path.parent / filename)
        else:
            candidates.append(origin_path.with_name(filename))

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _resolve_source_hook(
    filename: str,
    runtime_spec: RuntimePackageSpec,
    *,
    repo_agilab_dir: Path | None,
) -> Path | None:
    if repo_agilab_dir is None or not runtime_spec.hook_source_rel:
        return None
    try:
        hook_root = repo_agilab_dir / "core" / runtime_spec.project_dir / runtime_spec.hook_source_rel
        candidate = hook_root / filename
        if candidate.exists():
            return candidate
    except HOOK_REPO_FALLBACK_EXCEPTIONS:
        return None
    return None


def _resolve_resource_hook(filename: str, runtime_spec: RuntimePackageSpec) -> Path | None:
    try:
        package_root = importlib_resources.files(runtime_spec.hook_package)
    except (ModuleNotFoundError, AttributeError):
        return None

    resource = package_root / filename
    if not resource.is_file():
        return None

    cache_name = runtime_spec.hook_cache_name or f"agi_{runtime_spec.role}_hooks"
    cache_dir = Path(tempfile.gettempdir()) / cache_name
    cache_dir.mkdir(exist_ok=True)
    cached = cache_dir / filename
    try:
        with importlib_resources.as_file(resource) as resource_path:
            if resource_path != cached:
                shutil.copy2(resource_path, cached)
    except FileNotFoundError:
        return None

    return cached if cached.exists() else None


def select_hook(
    local_candidate: Path,
    fallback_filename: str,
    hook_label: str,
    *,
    resolve_hook,
) -> tuple[Path, bool]:
    """Return the hook to execute and whether it comes from the shared baseline."""

    if local_candidate.exists():
        return local_candidate, False

    fallback = resolve_hook(fallback_filename)
    if fallback and fallback.exists():
        return fallback, True

    raise FileNotFoundError(
        f"Unable to resolve {hook_label} script: expected {local_candidate} or shared runtime hook copy."
    )
