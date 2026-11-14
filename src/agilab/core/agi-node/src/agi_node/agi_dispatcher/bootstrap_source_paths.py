"""Bootstrap repo-local source paths for dispatcher scripts."""

from __future__ import annotations

import os
from pathlib import Path
import sys


def resolve_core_source_root(*, source_file: str | Path | None = None) -> Path | None:
    """Return the repository ``src/agilab/core`` root for a dispatcher source file."""
    try:
        source_path = Path(source_file or __file__).resolve()
    except (OSError, RuntimeError):
        return None
    # A wheel may live anywhere inside a checkout, including beneath core/.
    # Only the executing SDK package's own source layout selects that checkout.
    if {"site-packages", "dist-packages"}.intersection(source_path.parts):
        return None
    for package_root in source_path.parents:
        core_root = package_root.parent
        if (
            package_root.name in {"agi-env", "agi-node", "agi-cluster"}
            and core_root.name == "core"
            and core_root.parent.name == "agilab"
            and source_path.relative_to(package_root).parts[:2]
            == ("src", package_root.name.replace("-", "_"))
        ):
            return core_root
    return None


def _source_environment_selection(selected: bool | None) -> bool | None:
    """Use the established explicit selector without consulting global markers."""
    if selected is not None:
        return selected
    raw = os.environ.get("IS_SOURCE_ENV")
    if raw is None:
        return None
    return raw.strip().lower() not in {"", "0", "false", "no"}


def package_source_path_candidates(
    package_dir_name: str,
    *,
    sys_prefix: str | os.PathLike[str] | None = None,
    source_file: str | os.PathLike[str] | None = None,
    is_source_env: bool | None = None,
) -> tuple[Path, ...]:
    """Return SDK source roots only for source execution or explicit source mode."""
    selected = _source_environment_selection(is_source_env)
    if selected is False:
        return ()
    core_root = resolve_core_source_root(source_file=source_file)
    if core_root is not None:
        return (core_root / package_dir_name / "src",)
    if selected is not True:
        return ()

    prefix_root = Path(sys_prefix or sys.prefix)
    try:
        source_root = Path(source_file or __file__).resolve()
    except (OSError, RuntimeError):
        return ()
    candidates: list[Path] = []
    for root in (prefix_root, *prefix_root.parents, source_root, *source_root.parents):
        candidates.extend(
            [
                root / package_dir_name / "src",
                root / "src" / package_dir_name / "src",
                root / "src" / "agilab" / "core" / package_dir_name / "src",
            ]
        )
    return tuple(dict.fromkeys(candidates))


def resolve_node_source_path(
    *,
    sys_prefix: str | os.PathLike[str] | None = None,
    source_file: str | os.PathLike[str] | None = None,
    is_source_env: bool | None = None,
) -> Path | None:
    """Return the selected source environment's ``agi-node/src`` path."""
    for candidate in package_source_path_candidates(
        "agi-node",
        sys_prefix=sys_prefix,
        source_file=source_file,
        is_source_env=is_source_env,
    ):
        if candidate.is_dir():
            return candidate
    return None


def bootstrap_core_source_paths(
    *, source_file: str | Path | None = None
) -> tuple[Path, ...]:
    """Insert repo-local ``agi-node`` source roots and declared source deps."""
    core_root = resolve_core_source_root(source_file=source_file)
    if core_root is None or _source_environment_selection(None) is False:
        return ()

    candidates = (
        core_root / "agi-env" / "src",
        core_root / "agi-node" / "src",
    )
    added: list[Path] = []
    for candidate in reversed(candidates):
        if candidate.is_dir():
            candidate_str = str(candidate)
            sys.path[:] = [entry for entry in sys.path if entry != candidate_str]
            sys.path.insert(0, candidate_str)
            added.append(candidate)
    return tuple(reversed(added))


def resolve_source_checkout_root(source_file: str | Path) -> Path | None:
    """Return the AGILAB source checkout root that owns ``source_file``."""
    try:
        source_path = Path(source_file).resolve()
    except (OSError, RuntimeError):
        return None
    for parent in (source_path.parent, *source_path.parents):
        if (parent / "src" / "agilab" / "main_page.py").exists():
            return parent
    return None


def resolve_checkout_root_for_site_packages(candidate: Path) -> Path | None:
    """Return the checkout root that owns a managed ``site-packages`` path."""
    try:
        candidate_path = candidate.resolve()
    except (OSError, RuntimeError):
        candidate_path = candidate
    for parent in candidate_path.parents:
        if parent.name != ".venv":
            continue
        checkout_root = parent.parent
        if (checkout_root / "src" / "agilab" / "main_page.py").exists():
            return checkout_root.resolve()
        return None
    return None


def shared_site_package_candidates(
    *,
    home: str | Path | None = None,
    version_info=None,
) -> tuple[Path, ...]:
    """Return legacy shared AGILAB virtualenv site-packages candidates."""
    selected_home = Path.home() if home is None else Path(home).expanduser()
    selected_version = sys.version_info if version_info is None else version_info
    version = f"python{selected_version.major}.{selected_version.minor}"
    return (
        selected_home / "agilab/.venv/lib" / version / "site-packages",
        selected_home / ".agilab/.venv/lib" / version / "site-packages",
    )


def append_shared_site_packages(
    *,
    source_file: str | Path = __file__,
    sys_path: list[str] | None = None,
    home: str | Path | None = None,
    version_info=None,
) -> tuple[Path, ...]:
    """Append compatible shared AGILAB site-packages candidates to ``sys.path``."""
    target_sys_path = sys.path if sys_path is None else sys_path
    current_checkout_root = resolve_source_checkout_root(source_file)
    added: list[Path] = []
    for candidate in shared_site_package_candidates(home=home, version_info=version_info):
        candidate_checkout_root = resolve_checkout_root_for_site_packages(candidate)
        if (
            current_checkout_root is not None
            and candidate_checkout_root is not None
            and candidate_checkout_root != current_checkout_root
        ):
            continue
        path_str = str(candidate)
        if path_str not in target_sys_path:
            target_sys_path.append(path_str)
            added.append(candidate)
    return tuple(added)
