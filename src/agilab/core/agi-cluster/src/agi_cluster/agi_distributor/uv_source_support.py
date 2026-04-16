import logging
import os
import posixpath
import shutil
from pathlib import Path, PurePosixPath
from typing import Any, Optional, Set

import tomlkit


logger = logging.getLogger(__name__)
ENV_LOOKUP_EXCEPTIONS = (AttributeError, RuntimeError, TypeError)
RELPATH_FALLBACK_EXCEPTIONS = (OSError, ValueError)


def _iter_local_uv_source_paths(pyproject_path: Path) -> list[tuple[str, Path]]:
    """Return existing local ``tool.uv.sources.*.path`` entries from a pyproject."""
    try:
        data = tomlkit.parse(pyproject_path.read_text())
    except FileNotFoundError:
        return []

    sources = (
        data.get("tool", {}).get("uv", {}).get("sources")
        if isinstance(data, dict)
        else None
    )
    if not isinstance(sources, dict):
        return []

    resolved_entries: list[tuple[str, Path]] = []
    for name, meta in sources.items():
        if not isinstance(meta, dict):
            continue
        path_value = meta.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            continue

        candidate = Path(path_value).expanduser()
        if not candidate.is_absolute():
            candidate = (pyproject_path.parent / candidate).resolve(strict=False)
        else:
            candidate = candidate.resolve(strict=False)
        if candidate.exists():
            resolved_entries.append((str(name), candidate))

    return resolved_entries


def envar_truthy(envars: dict[str, Any], key: str) -> bool:
    """Return True when an env var value is truthy."""
    try:
        raw = envars.get(key)
    except ENV_LOOKUP_EXCEPTIONS:
        return False
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        try:
            return int(raw) == 1
        except (TypeError, ValueError):
            return False
    value = str(raw).strip().lower()
    return value in {"1", "true", "yes", "on"}


def ensure_optional_extras(pyproject_file: Path, extras: Set[str]) -> None:
    """Ensure ``[project.optional-dependencies]`` contains the requested extras."""
    if not extras:
        return

    try:
        doc = tomlkit.parse(pyproject_file.read_text())
    except FileNotFoundError:
        doc = tomlkit.document()

    project_tbl = doc.get("project")
    if project_tbl is None:
        project_tbl = tomlkit.table()

    optional_tbl = project_tbl.get("optional-dependencies")
    if optional_tbl is None or not isinstance(optional_tbl, tomlkit.items.Table):
        optional_tbl = tomlkit.table()

    for extra in sorted({e for e in extras if isinstance(e, str) and e.strip()}):
        if extra not in optional_tbl:
            optional_tbl[extra] = tomlkit.array()

    project_tbl["optional-dependencies"] = optional_tbl
    doc["project"] = project_tbl
    pyproject_file.write_text(tomlkit.dumps(doc))


def rewrite_uv_sources_paths_for_copied_pyproject(
    *,
    src_pyproject: Path,
    dest_pyproject: Path,
    log_rewrites: bool = False,
    log: Any = logger,
) -> None:
    """Rewrite ``[tool.uv.sources.*].path`` entries after copying a worker pyproject."""
    try:
        src_data = tomlkit.parse(src_pyproject.read_text())
        dest_data = tomlkit.parse(dest_pyproject.read_text())
    except FileNotFoundError:
        return

    src_sources = (
        src_data.get("tool", {}).get("uv", {}).get("sources")
        if isinstance(src_data, dict)
        else None
    )
    dest_sources = (
        dest_data.get("tool", {}).get("uv", {}).get("sources")
        if isinstance(dest_data, dict)
        else None
    )
    if not isinstance(src_sources, dict) or not isinstance(dest_sources, dict):
        return

    dest_dir = dest_pyproject.parent
    rewrites: list[tuple[str, str, str]] = []
    for name, src_meta in src_sources.items():
        if not isinstance(src_meta, dict):
            continue
        src_path_value = src_meta.get("path")
        if not isinstance(src_path_value, str) or not src_path_value.strip():
            continue

        src_path = Path(src_path_value).expanduser()
        if not src_path.is_absolute():
            src_path = (src_pyproject.parent / src_path).resolve(strict=False)
        else:
            src_path = src_path.resolve(strict=False)
        if not src_path.exists():
            continue

        dest_meta = dest_sources.get(name)
        if not isinstance(dest_meta, dict):
            continue
        dest_path_value = dest_meta.get("path")

        dest_path = None
        if isinstance(dest_path_value, str) and dest_path_value.strip():
            dest_path = Path(dest_path_value).expanduser()
            if not dest_path.is_absolute():
                dest_path = (dest_dir / dest_path).resolve(strict=False)
            else:
                dest_path = dest_path.resolve(strict=False)
        if dest_path is not None and dest_path.exists():
            continue

        try:
            new_path_value = os.path.relpath(src_path, start=dest_dir)
        except RELPATH_FALLBACK_EXCEPTIONS:
            new_path_value = str(src_path)

        if dest_path_value != new_path_value:
            dest_meta["path"] = new_path_value
            rewrites.append((name, str(dest_path_value or ""), new_path_value))

    if not rewrites:
        return

    dest_pyproject.write_text(tomlkit.dumps(dest_data))
    if log_rewrites:
        for name, old, new in rewrites:
            log.info("Rewrote uv source '%s' path: %s -> %s", name, old or "<unset>", new)


def copy_uv_source_tree(src_path: Path, dest_path: Path) -> None:
    """Copy a local uv source dependency into a self-contained staging area."""
    if dest_path.exists():
        if dest_path.is_dir():
            shutil.rmtree(dest_path, ignore_errors=True)
        else:
            try:
                dest_path.unlink()
            except FileNotFoundError:
                pass

    if src_path.is_dir():
        ignore = shutil.ignore_patterns(
            ".venv",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            "build",
            "dist",
        )
        shutil.copytree(src_path, dest_path, ignore=ignore, dirs_exist_ok=True)
    else:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest_path)


def _stage_uv_source_dependency(
    *,
    name: str,
    src_path: Path,
    stage_root: Path,
    log_rewrites: bool = False,
    log: Any = logger,
    seen: set[tuple[str, str]] | None = None,
) -> Path:
    """Stage one local uv source and recursively stage its nested local sources."""
    staged_target = stage_root / name
    stage_key = (name, str(src_path.resolve(strict=False)))
    if seen is None:
        seen = set()
    if stage_key in seen:
        return staged_target
    seen.add(stage_key)

    copy_uv_source_tree(src_path, staged_target)

    source_pyproject = src_path / "pyproject.toml"
    staged_pyproject = staged_target / "pyproject.toml"
    if not source_pyproject.exists() or not staged_pyproject.exists():
        return staged_target

    try:
        staged_data = tomlkit.parse(staged_pyproject.read_text())
    except FileNotFoundError:
        return staged_target

    staged_sources = (
        staged_data.get("tool", {}).get("uv", {}).get("sources")
        if isinstance(staged_data, dict)
        else None
    )
    if not isinstance(staged_sources, dict):
        return staged_target

    rewrites: list[tuple[str, str, str]] = []
    for nested_name, nested_src_path in _iter_local_uv_source_paths(source_pyproject):
        staged_nested_target = _stage_uv_source_dependency(
            name=nested_name,
            src_path=nested_src_path,
            stage_root=stage_root,
            log_rewrites=log_rewrites,
            log=log,
            seen=seen,
        )
        staged_meta = staged_sources.get(nested_name)
        if not isinstance(staged_meta, dict):
            continue
        try:
            new_path_value = os.path.relpath(staged_nested_target, start=staged_target)
        except RELPATH_FALLBACK_EXCEPTIONS:
            new_path_value = str(staged_nested_target)
        old_path_value = staged_meta.get("path")
        if old_path_value != new_path_value:
            staged_meta["path"] = new_path_value
            rewrites.append((nested_name, str(old_path_value or ""), new_path_value))

    if rewrites:
        staged_pyproject.write_text(tomlkit.dumps(staged_data))
        if log_rewrites:
            for nested_name, old, new in rewrites:
                log.info("Staged uv source '%s' path: %s -> %s", nested_name, old or "<unset>", new)

    return staged_target


def stage_uv_sources_for_copied_pyproject(
    *,
    src_pyproject: Path,
    dest_pyproject: Path,
    stage_root: Path,
    log_rewrites: bool = False,
    log: Any = logger,
) -> list[Path]:
    """Stage local ``tool.uv.sources.*.path`` entries next to the copied pyproject."""
    try:
        src_data = tomlkit.parse(src_pyproject.read_text())
        dest_data = tomlkit.parse(dest_pyproject.read_text())
    except FileNotFoundError:
        return []

    src_sources = (
        src_data.get("tool", {}).get("uv", {}).get("sources")
        if isinstance(src_data, dict)
        else None
    )
    dest_sources = (
        dest_data.get("tool", {}).get("uv", {}).get("sources")
        if isinstance(dest_data, dict)
        else None
    )
    if not isinstance(src_sources, dict) or not isinstance(dest_sources, dict):
        return []

    dest_dir = dest_pyproject.parent
    staged_root = stage_root / "_uv_sources"
    rewrites: list[tuple[str, str, str]] = []
    staged_any = False

    seen: set[tuple[str, str]] = set()
    for name, src_path in _iter_local_uv_source_paths(src_pyproject):
        dest_meta = dest_sources.get(name)
        if not isinstance(dest_meta, dict):
            continue

        staged_target = _stage_uv_source_dependency(
            name=name,
            src_path=src_path,
            stage_root=staged_root,
            log_rewrites=log_rewrites,
            log=log,
            seen=seen,
        )
        staged_any = True

        try:
            new_path_value = os.path.relpath(staged_target, start=dest_dir)
        except RELPATH_FALLBACK_EXCEPTIONS:
            new_path_value = str(staged_target)

        old_path_value = dest_meta.get("path")
        if old_path_value != new_path_value:
            dest_meta["path"] = new_path_value
            rewrites.append((name, str(old_path_value or ""), new_path_value))

    if rewrites:
        dest_pyproject.write_text(tomlkit.dumps(dest_data))
        if log_rewrites:
            for name, old, new in rewrites:
                log.info("Staged uv source '%s' path: %s -> %s", name, old or "<unset>", new)

    return [staged_root] if staged_any and staged_root.exists() else []


def missing_uv_source_paths(pyproject_path: Path) -> list[tuple[str, str]]:
    """Return unresolved ``tool.uv.sources.*.path`` entries from a copied pyproject."""
    try:
        data = tomlkit.parse(pyproject_path.read_text())
    except FileNotFoundError:
        return []

    sources = (
        data.get("tool", {}).get("uv", {}).get("sources")
        if isinstance(data, dict)
        else None
    )
    if not isinstance(sources, dict):
        return []

    missing: list[tuple[str, str]] = []
    root = pyproject_path.parent
    for name, meta in sources.items():
        if not isinstance(meta, dict):
            continue
        path_value = meta.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            continue
        candidate = Path(path_value).expanduser()
        if not candidate.is_absolute():
            candidate = (root / candidate).resolve(strict=False)
        else:
            candidate = candidate.resolve(strict=False)
        if not candidate.exists():
            missing.append((str(name), path_value))

    return missing


def validate_worker_uv_sources(pyproject_path: Path) -> None:
    """Fail fast when a copied worker pyproject still points at missing local sources."""
    missing = missing_uv_source_paths(pyproject_path)
    if not missing:
        return

    details = ", ".join(f"{name} -> {path}" for name, path in missing[:4])
    if len(missing) > 4:
        details += f", +{len(missing) - 4} more"
    raise RuntimeError(
        "Worker environment is using unresolved local uv sources "
        f"from {pyproject_path}: {details}. "
        "This worker install is stale or incomplete. Rerun AGI.install for the app "
        "after updating AGILab so worker dependencies are staged into _uv_sources."
    )


def worker_site_packages_dir(
    wenv_root: Path | PurePosixPath,
    pyvers: str,
    *,
    windows: bool = False,
) -> Path | PurePosixPath:
    """Return the worker venv site-packages path for the given Python version."""
    if windows:
        return wenv_root / ".venv" / "Lib" / "site-packages"

    parts = str(pyvers).split(".")
    major = parts[0] if parts else "3"
    minor_raw = parts[1] if len(parts) > 1 else "13"
    suffix = "t" if minor_raw.endswith("t") else ""
    minor = minor_raw[:-1] if suffix else minor_raw
    return wenv_root / ".venv" / "lib" / f"python{major}.{minor}{suffix}" / "site-packages"


def staged_uv_sources_pth_content(
    site_packages_dir: Path | PurePosixPath,
    uv_sources_root: Path | PurePosixPath,
) -> str:
    """Return a relative `.pth` entry that exposes staged uv sources."""
    if isinstance(site_packages_dir, PurePosixPath) or isinstance(uv_sources_root, PurePosixPath):
        rel = posixpath.relpath(
            PurePosixPath(uv_sources_root).as_posix(),
            start=PurePosixPath(site_packages_dir).as_posix(),
        )
    else:
        rel = os.path.relpath(str(uv_sources_root), start=str(site_packages_dir))
    return f"{rel}\n"


def write_staged_uv_sources_pth(
    site_packages_dir: Path,
    uv_sources_root: Path,
) -> Optional[Path]:
    """Write a `.pth` file so staged uv-source trees are importable at runtime."""
    pth_path = site_packages_dir / "agilab_uv_sources.pth"
    if not uv_sources_root.exists():
        try:
            pth_path.unlink()
        except FileNotFoundError:
            pass
        return None

    site_packages_dir.mkdir(parents=True, exist_ok=True)
    pth_path.write_text(
        staged_uv_sources_pth_content(site_packages_dir, uv_sources_root),
        encoding="utf-8",
    )
    return pth_path
