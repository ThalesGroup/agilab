"""Pure helpers for resolving shared worker hook scripts."""

from __future__ import annotations

import importlib.resources as importlib_resources
import importlib.util
import shutil
import tempfile
from functools import lru_cache
from pathlib import Path

HOOK_REPO_FALLBACK_EXCEPTIONS = (IndexError, OSError)


@lru_cache(maxsize=None)
def resolve_worker_hook(filename: str, *, module_file: str) -> Path | None:
    """Return the path to the shared worker hook."""

    try:
        spec = importlib.util.find_spec("agi_node.agi_dispatcher")
    except ModuleNotFoundError:
        spec = None

    candidates: list[Path] = []
    if spec is not None:
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

    here = Path(module_file).resolve()
    try:
        repo_agilab_dir = here.parents[4]
        core_root = repo_agilab_dir / "core"
        src_hook = core_root / "agi-node/src/agi_node/agi_dispatcher" / filename
        pkg_hook = core_root / "agi-node/agi_dispatcher" / filename
        for candidate in (src_hook, pkg_hook):
            if candidate.exists():
                return candidate
    except HOOK_REPO_FALLBACK_EXCEPTIONS:
        pass

    try:
        package_root = importlib_resources.files("agi_node.agi_dispatcher")
    except (ModuleNotFoundError, AttributeError):
        return None

    resource = package_root / filename
    if not resource.is_file():
        return None

    cache_dir = Path(tempfile.gettempdir()) / "agi_node_hooks"
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
        f"Unable to resolve {hook_label} script: expected {local_candidate} or shared agi-node copy."
    )
