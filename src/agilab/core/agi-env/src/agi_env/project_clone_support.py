"""Project-clone and project-copy helpers for ``AgiEnv``."""

from __future__ import annotations

import ast
import os
import shutil
from pathlib import Path
from typing import Any, Callable

import astor
from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern

from .app_provider_registry import aliased_app_runtime_target

try:
    from pathlib import UnsupportedOperation
except ImportError:
    from io import UnsupportedOperation

PATH_RESOLVE_EXCEPTIONS = (OSError, UnsupportedOperation)
PROJECT_COPY_EXCEPTIONS = (OSError, shutil.Error)


def _safe_resolve(path: Path, *, strict: bool = False) -> Path:
    try:
        return path.resolve(strict=strict)
    except PATH_RESOLVE_EXCEPTIONS:
        return path


def create_rename_map(target_project: Path, dest_project: Path) -> dict[str, str]:
    """Create a mapping of old to new names for project clone operations."""

    def cap(value: str) -> str:
        return "".join(part.capitalize() for part in value.split("_"))

    name_tp = target_project.name
    name_dp = dest_project.name

    def strip_suffix(name: str) -> str:
        for suffix in ("_project", "_template"):
            if name.endswith(suffix):
                return name[: -len(suffix)]
        return name

    tp = aliased_app_runtime_target(strip_suffix(name_tp))
    dp = aliased_app_runtime_target(strip_suffix(name_dp))

    tm = tp.replace("-", "_")
    dm = dp.replace("-", "_")
    tc = cap(tm)
    dc = cap(dm)

    rename_map: dict[str, str] = {
        name_tp: name_dp,
        f"src/{tm}_worker": f"src/{dm}_worker",
        f"src/{tm}": f"src/{dm}",
        f"{tm}_worker": f"{dm}_worker",
        tm: dm,
        f"{tc}Worker": f"{dc}Worker",
        f"{tc}Args": f"{dc}Args",
        f"{tc}ArgsTD": f"{dc}ArgsTD",
        tc: dc,
    }

    for suffix in ("_args", "_manager", "_worker", "_distributor", "_project"):
        rename_map.setdefault(f"{tm}{suffix}", f"{dm}{suffix}")
    rename_map.setdefault(f"{tm}_args_td", f"{dm}_args_td")
    rename_map.setdefault(f"{tm}ArgsTD", f"{dm}ArgsTD")

    return rename_map


def copy_existing_projects(
    src_apps: Path,
    dst_apps: Path,
    *,
    ensure_dir_fn: Callable[[str | Path], Path],
    logger: Any,
) -> None:
    """Copy ``*_project`` trees from ``src_apps`` into ``dst_apps`` if missing."""

    if _safe_resolve(src_apps, strict=False) == _safe_resolve(dst_apps, strict=False):
        return

    ensure_dir_fn(dst_apps)

    logger.info(f"copy_existing_projects src={_safe_resolve(src_apps)} dst={_safe_resolve(dst_apps)}")
    candidates = sorted(
        [path for path in src_apps.rglob("*_project") if path.is_dir()],
        key=lambda candidate: candidate.relative_to(src_apps).as_posix(),
    )
    logger.info("Matched projects: " + ", ".join(str(path.relative_to(src_apps)) for path in candidates) or "<none>")

    for item in sorted(
        src_apps.rglob("*_project"),
        key=lambda candidate: candidate.relative_to(src_apps).as_posix(),
    ):
        if not item.is_dir():
            continue

        rel = item.relative_to(src_apps)
        dst_item = dst_apps / rel
        if dst_item.is_symlink():
            try:
                dst_item.unlink()
            except OSError as exc:
                logger.warning(f"Failed to remove dangling project symlink {dst_item}: {exc}")
                continue
        elif dst_item.exists() and not dst_item.is_dir():
            try:
                dst_item.unlink()
            except OSError as exc:
                logger.warning(f"Failed to remove conflicting project file {dst_item}: {exc}")
                continue

        try:
            shutil.copytree(
                item,
                dst_item,
                dirs_exist_ok=True,
                symlinks=True,
                ignore=shutil.ignore_patterns(
                    ".venv",
                    "build",
                    "dist",
                    "__pycache__",
                    ".pytest_cache",
                    ".idea",
                    ".mypy_cache",
                    ".ruff_cache",
                    "*.egg-info",
                ),
            )
        except PROJECT_COPY_EXCEPTIONS as exc:
            logger.error(f"Warning: Could not copy {item} → {dst_item}: {exc}")


def clone_project(
    target_project: Path,
    dest_project: Path,
    *,
    apps_path: Path,
    home_abs: Path,
    projects: list[Any],
    logger: Any,
    create_rename_map_fn: Callable[[Path, Path], dict[str, str]],
    clone_directory_fn: Callable[[Path, Path, dict[str, str], PathSpec, Path], None],
    cleanup_rename_fn: Callable[[Path, dict[str, str]], None],
    copytree_fn: Callable[..., Any] = shutil.copytree,
) -> None:
    """Clone a project by copying files/directories and applying rename rules."""

    templates_root = apps_path / "templates"

    if not target_project.name.endswith("_project"):
        candidate = target_project.with_name(target_project.name + "_project")
        if (apps_path / candidate).exists() or (templates_root / candidate).exists():
            target_project = candidate

    if not dest_project.name.endswith("_project"):
        dest_project = dest_project.with_name(dest_project.name + "_project")

    rename_map = create_rename_map_fn(target_project, dest_project)

    def _strip(name: Path) -> str:
        base = name.name
        for suffix in ("_project", "_template"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
        return base.replace("-", "_")

    tm = _strip(target_project)
    dm = _strip(dest_project)
    source_root = apps_path / target_project
    if not source_root.exists() and templates_root.exists():
        source_root = templates_root / target_project
    dest_root = apps_path / dest_project

    if not source_root.exists():
        logger.info(f"Source project '{target_project}' does not exist.")
        return
    if dest_root.exists():
        logger.info(f"Destination project '{dest_project}' already exists.")
        return

    ignore_patterns = [".git", ".git/", ".git/**"]
    gitignore_candidates: list[Path] = []
    seen_gitignore_dirs: set[Path] = set()
    for ancestor in [source_root, *source_root.parents]:
        gitignore_path = ancestor / ".gitignore"
        if gitignore_path.exists() and ancestor not in seen_gitignore_dirs:
            gitignore_candidates.append(gitignore_path)
            seen_gitignore_dirs.add(ancestor)

    for gitignore_path in gitignore_candidates:
        try:
            lines = gitignore_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            logger.debug(f"Unable to read {gitignore_path}: {exc}")
            continue
        ignore_patterns.extend(line for line in lines if line.strip())

    spec = PathSpec.from_lines(GitWildMatchPattern, ignore_patterns)

    try:
        if not dest_root.exists():
            logger.info(f"mkdir {dest_root}")
            dest_root.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        logger.error(f"Could not create '{dest_root}': {exc}")
        return

    clone_directory_fn(source_root, dest_root, rename_map, spec, source_root)
    cleanup_rename_fn(dest_root, rename_map)
    projects.insert(0, dest_project)

    src_data_dir = home_abs / "data" / tm
    dest_data_dir = home_abs / "data" / dm
    try:
        if src_data_dir.exists() and not dest_data_dir.exists():
            copytree_fn(src_data_dir, dest_data_dir)
    except PROJECT_COPY_EXCEPTIONS as exc:
        logger.info(f"Unable to copy data directory '{src_data_dir}' to '{dest_data_dir}': {exc}")


def clone_directory(
    source_dir: Path,
    dest_dir: Path,
    rename_map: dict[str, str],
    spec: PathSpec,
    source_root: Path,
    *,
    ensure_dir_fn: Callable[[str | Path], Path],
    content_renamer_cls: type[Any],
    replace_content_fn: Callable[[str, dict[str, str]], str],
) -> None:
    """Recursively clone a directory while applying filename/content renames."""

    for item in source_dir.iterdir():
        rel = item.relative_to(source_root).as_posix()
        if spec.match_file(rel + ("/" if item.is_dir() else "")):
            continue

        parts = rel.split("/")
        for idx, seg in enumerate(parts):
            for old, new in sorted(rename_map.items(), key=lambda kv: -len(kv[0])):
                if seg == old:
                    parts[idx] = new
                    break

        new_rel = "/".join(parts)
        dst = dest_dir / new_rel
        ensure_dir_fn(dst.parent)

        if item.is_symlink():
            try:
                target = os.readlink(item)
            except OSError:
                target = str(_safe_resolve(item))
            try:
                os.symlink(target, dst, target_is_directory=item.is_dir())
            except FileExistsError:
                pass
            continue

        if item.is_dir():
            if item.name == ".venv":
                os.symlink(item, dst, target_is_directory=True)
            else:
                clone_directory(
                    item,
                    dest_dir,
                    rename_map,
                    spec,
                    source_root,
                    ensure_dir_fn=ensure_dir_fn,
                    content_renamer_cls=content_renamer_cls,
                    replace_content_fn=replace_content_fn,
                )
            continue

        if not item.is_file():
            continue

        suffix = item.suffix.lower()
        base = item.stem

        if base in rename_map:
            dst = dst.with_name(rename_map[base] + item.suffix)

        if suffix in (".7z", ".zip"):
            shutil.copy2(item, dst)
            continue

        if suffix == ".py":
            source_text = item.read_text(encoding="utf-8")
            try:
                tree = ast.parse(source_text)
                renamer = content_renamer_cls(rename_map)
                new_tree = renamer.visit(tree)
                ast.fix_missing_locations(new_tree)
                output = astor.to_source(new_tree)
            except SyntaxError:
                output = source_text
            output = replace_content_fn(output, rename_map)
            dst.write_text(output, encoding="utf-8")
            continue

        if suffix in (".toml", ".md", ".txt", ".json", ".yaml", ".yml"):
            text = item.read_text(encoding="utf-8")
            text = replace_content_fn(text, rename_map)
            dst.write_text(text, encoding="utf-8")
            continue

        shutil.copy2(item, dst)


def cleanup_rename(
    root: Path,
    rename_map: dict[str, str],
    *,
    replace_content_fn: Callable[[str, dict[str, str]], str],
) -> None:
    """Rename remaining basename leftovers and rewrite text references."""

    simple_map = {old: new for old, new in rename_map.items() if "/" not in old}
    sorted_simple = sorted(simple_map.items(), key=lambda kv: len(kv[0]), reverse=True)

    for path in sorted(root.rglob("*"), key=lambda candidate: len(candidate.parts), reverse=True):
        old_name = path.name
        for old, new in sorted_simple:
            if old_name == old or old_name == f"{old}_worker" or old_name == f"{old}_project":
                new_name = old_name.replace(old, new, 1)
                path.rename(path.with_name(new_name))
                break
            if path.is_file() and old_name.startswith(old + "."):
                new_name = new + old_name[len(old):]
                path.rename(path.with_name(new_name))
                break

    text_suffixes = {".py", ".toml", ".md", ".txt", ".json", ".yaml", ".yml"}
    for file in root.rglob("*"):
        if not file.is_file() or file.suffix.lower() not in text_suffixes:
            continue
        text = file.read_text(encoding="utf-8")
        new_text = replace_content_fn(text, rename_map)
        if new_text != text:
            file.write_text(new_text, encoding="utf-8")
