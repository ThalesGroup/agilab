"""Project and resource initialization helpers for :mod:`agi_env.agi_env`."""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


@dataclass(frozen=True)
class AppFileInitialization:
    """Paths prepared while activating an app project."""

    app_settings_source_file: Path
    app_settings_file: Path
    app_args_form: Path
    gitignore_file: Path


def initialize_resources(
    resources_src: Path,
    *,
    resources_path: Path,
    st_resources: Path,
    is_source_env: bool,
    ensure_dir_fn: Callable[[str | Path], Path],
    logger,
) -> None:
    """Replicate packaged resource seeds into the managed ``.agilab`` tree."""

    src_env_path = resources_src / ".env"
    dest_env_file = resources_path / ".env"
    if not dest_env_file.exists():
        ensure_dir_fn(dest_env_file.parent)
        shutil.copy(src_env_path, dest_env_file)

    for root, _dirs, files in os.walk(resources_src):
        for file in sorted(files):
            src_file = Path(root) / file
            relative_path = src_file.relative_to(resources_src)
            dest_file = resources_path / relative_path
            ensure_dir_fn(dest_file.parent)
            if not dest_file.exists():
                shutil.copy(src_file, dest_file)

    extras = [
        "custom_buttons.json",
        "info_bar.json",
        "code_editor.scss",
    ]
    if not is_source_env:
        for extra in extras:
            src_extra = st_resources / extra
            dest_extra = resources_path / extra
            if src_extra.exists() and not dest_extra.exists():
                ensure_dir_fn(dest_extra.parent)
                shutil.copy(src_extra, dest_extra)
        return

    for extra in extras:
        dest_extra = resources_path / extra
        try:
            if dest_extra.exists():
                dest_extra.unlink()
        except OSError:
            if logger:
                logger.warning(f"Could not remove legacy resource {dest_extra}")


def discover_projects(
    paths: Iterable[Path | None],
    *,
    installed_app_project_paths: Iterable[Path] = (),
    logger,
) -> list[str]:
    """Return unique ``*_project`` directory names from source and installed roots."""

    projects: list[str] = []
    seen: set[str] = set()

    for path in paths:
        if path is None:
            continue
        try:
            base = Path(path)
        except (TypeError, ValueError):
            continue
        if not base.exists():
            continue

        for project_path in sorted(base.glob("*_project"), key=lambda candidate: candidate.name):
            if project_path.is_symlink() and not project_path.exists():
                try:
                    project_path.unlink()
                    if logger:
                        logger.info(f"Removed dangling project symlink: {project_path}")
                except OSError as exc:
                    if logger:
                        logger.warning(f"Failed to remove dangling project symlink {project_path}: {exc}")
                continue

            if project_path.is_dir():
                _append_unique_project(projects, seen, project_path.name)

    for project_path in _sorted_existing_paths(installed_app_project_paths):
        name = project_path.name
        if name.endswith("_project"):
            _append_unique_project(projects, seen, name)

    return projects


def initialize_app_files(
    *,
    app_src: Path,
    active_app: Path,
    resources_path: Path,
    agilab_pck: Path,
    find_source_app_settings_file_fn: Callable[[], Path | None],
    resolve_user_app_settings_file_fn: Callable[[], Path],
) -> AppFileInitialization:
    """Prepare app settings, args-form, gitignore, and resource seed files."""

    app_settings_source_file = find_source_app_settings_file_fn() or (app_src / "app_settings.toml")
    app_settings_file = resolve_user_app_settings_file_fn()

    app_args_form = app_src / "app_args_form.py"
    app_args_form.touch(exist_ok=True)

    src = agilab_pck / "resources"
    if src.exists():
        resources_path.mkdir(parents=True, exist_ok=True)
        for file in sorted(src.iterdir(), key=lambda candidate: candidate.name):
            if not file.is_file():
                continue
            dest_file = resources_path / file.name
            if not dest_file.exists():
                shutil.copy(file, dest_file)

    return AppFileInitialization(
        app_settings_source_file=app_settings_source_file,
        app_settings_file=app_settings_file,
        app_args_form=app_args_form,
        gitignore_file=active_app / ".gitignore",
    )


def copy_file_if_missing(src_item: Path, dst_item: Path, *, logger) -> None:
    """Copy ``src_item`` to ``dst_item`` if the destination does not exist."""

    if dst_item.exists():
        return
    if not src_item.exists():
        if logger:
            logger.info(f"[WARN] Source file missing (skipped): {src_item}")
        return
    try:
        shutil.copy2(src_item, dst_item)
    except (OSError, shutil.Error) as exc:
        if logger:
            logger.error(f"[WARN] Could not copy {src_item} -> {dst_item}: {exc}")


def _append_unique_project(projects: list[str], seen: set[str], name: str) -> None:
    if name not in seen:
        projects.append(name)
        seen.add(name)


def _sorted_existing_paths(paths: Iterable[Path]) -> list[Path]:
    candidates: list[Path] = []
    for path in paths:
        try:
            candidates.append(Path(path))
        except (TypeError, ValueError):
            continue
    return sorted(candidates, key=lambda candidate: candidate.name)
