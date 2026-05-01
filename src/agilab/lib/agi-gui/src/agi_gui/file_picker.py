"""Streamlit file picker helpers for AGILAB pages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any, Literal


PathLike = str | Path
SelectionMode = Literal["single", "multi"]


@dataclass(frozen=True)
class FilePickerRoot:
    """Named filesystem root exposed by the file picker."""

    label: str
    path: Path


@dataclass(frozen=True)
class FilePickerEntry:
    """A file or directory row rendered by the file picker."""

    name: str
    type: str
    relative_path: str
    path: str
    size: str
    modified: str

    def as_row(self) -> dict[str, str]:
        return {
            "name": self.name,
            "type": self.type,
            "relative_path": self.relative_path,
            "path": self.path,
            "size": self.size,
            "modified": self.modified,
        }


def normalize_file_picker_roots(
    roots: Mapping[str, PathLike] | Sequence[PathLike | FilePickerRoot],
) -> tuple[FilePickerRoot, ...]:
    """Normalize a root mapping or path sequence into deterministic picker roots."""

    if isinstance(roots, Mapping):
        items = roots.items()
    else:
        items = (
            (root.label, root.path)
            if isinstance(root, FilePickerRoot)
            else (Path(root).expanduser().name or str(root), root)
            for root in roots
        )

    normalized: list[FilePickerRoot] = []
    seen_labels: set[str] = set()
    for label, raw_path in items:
        label_text = str(label).strip()
        if not label_text:
            label_text = Path(raw_path).expanduser().name or str(raw_path)
        if label_text in seen_labels:
            raise ValueError(f"Duplicate file picker root label: {label_text}")
        seen_labels.add(label_text)
        normalized.append(FilePickerRoot(label=label_text, path=Path(raw_path).expanduser().resolve(strict=False)))

    if not normalized:
        raise ValueError("At least one file picker root is required")
    return tuple(normalized)


def normalize_file_patterns(patterns: str | Sequence[str] | None) -> tuple[str, ...]:
    """Normalize file patterns to non-empty glob-style strings."""

    if patterns is None:
        return ("*",)
    if isinstance(patterns, str):
        raw_patterns = [patterns]
    else:
        raw_patterns = list(patterns)
    normalized = tuple(pattern.strip() for pattern in raw_patterns if str(pattern).strip())
    return normalized or ("*",)


def is_path_under_root(path: PathLike, root: PathLike) -> bool:
    """Return whether ``path`` resolves inside ``root``."""

    resolved_path = Path(path).expanduser().resolve(strict=False)
    resolved_root = Path(root).expanduser().resolve(strict=False)
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError:
        return False
    return True


def resolve_under_roots(
    path: PathLike,
    roots: Mapping[str, PathLike] | Sequence[PathLike | FilePickerRoot],
    *,
    must_exist: bool = True,
) -> Path:
    """Resolve ``path`` and require it to stay inside one of ``roots``."""

    normalized_roots = normalize_file_picker_roots(roots)
    raw_path = Path(path).expanduser()
    candidates = [raw_path] if raw_path.is_absolute() else [root.path / raw_path for root in normalized_roots]

    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=must_exist)
        except FileNotFoundError:
            if must_exist:
                continue
            resolved = candidate.resolve(strict=False)
        for root in normalized_roots:
            if is_path_under_root(resolved, root.path):
                return resolved

    root_labels = ", ".join(root.label for root in normalized_roots)
    raise ValueError(f"Path must exist under one of the configured roots: {root_labels}")


def list_file_picker_entries(
    root: PathLike,
    *,
    patterns: str | Sequence[str] | None = None,
    allow_files: bool = True,
    allow_dirs: bool = False,
    recursive: bool = True,
    include_hidden: bool = False,
    max_entries: int = 1000,
) -> list[FilePickerEntry]:
    """List picker entries below ``root`` in deterministic display order."""

    root_path = Path(root).expanduser().resolve(strict=False)
    if max_entries < 1:
        raise ValueError("max_entries must be >= 1")
    if not root_path.exists() or not root_path.is_dir():
        return []

    normalized_patterns = normalize_file_patterns(patterns)
    iterator = root_path.rglob("*") if recursive else root_path.iterdir()
    candidates = sorted(
        iterator,
        key=lambda path: (
            0 if path.is_dir() else 1,
            _safe_relative_posix(path, root_path).casefold(),
        ),
    )

    entries: list[FilePickerEntry] = []
    for candidate in candidates:
        try:
            relative = candidate.relative_to(root_path)
        except ValueError:
            continue
        if not include_hidden and _has_hidden_part(relative):
            continue
        is_dir = candidate.is_dir()
        is_file = candidate.is_file()
        if is_dir and not allow_dirs:
            continue
        if is_file and not allow_files:
            continue
        if is_file and not _matches_patterns(relative, normalized_patterns):
            continue
        if not is_dir and not is_file:
            continue
        entries.append(_entry_from_path(candidate, root_path, is_dir=is_dir))
        if len(entries) >= max_entries:
            break

    return entries


def selected_paths_from_dataframe_state(state: Any, rows: Sequence[Mapping[str, str]]) -> list[str]:
    """Extract selected absolute paths from a Streamlit dataframe selection state."""

    selected_rows = _selected_row_indices(state)
    paths: list[str] = []
    for index in selected_rows:
        if 0 <= index < len(rows):
            selected_path = rows[index].get("path")
            if selected_path:
                paths.append(str(selected_path))
    return paths


def safe_upload_target(
    upload_dir: PathLike,
    uploaded_name: str,
    roots: Mapping[str, PathLike] | Sequence[PathLike | FilePickerRoot],
) -> Path:
    """Return a safe upload destination below ``upload_dir`` and configured roots."""

    upload_root = resolve_under_roots(upload_dir, roots, must_exist=True)
    parts = [part for part in PurePosixPath(uploaded_name.replace("\\", "/")).parts if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        raise ValueError(f"Unsafe upload filename: {uploaded_name}")
    target = (upload_root / Path(*parts)).resolve(strict=False)
    if not is_path_under_root(target, upload_root):
        raise ValueError(f"Unsafe upload filename: {uploaded_name}")
    return target


def agi_file_picker(
    label: str,
    *,
    roots: Mapping[str, PathLike] | Sequence[PathLike | FilePickerRoot],
    key: str,
    patterns: str | Sequence[str] | None = None,
    default: PathLike | Sequence[PathLike] | None = None,
    selection_mode: SelectionMode = "single",
    allow_files: bool = True,
    allow_dirs: bool = False,
    recursive: bool = True,
    include_hidden: bool = False,
    allow_upload: bool = False,
    upload_dir: PathLike | None = None,
    upload_types: str | Sequence[str] | None = None,
    max_entries: int = 1000,
    help: str | None = None,
    container: Any | None = None,
) -> str | list[str] | None:
    """Render a Streamlit popover file picker and return selected absolute paths."""

    if selection_mode not in {"single", "multi"}:
        raise ValueError("selection_mode must be 'single' or 'multi'")

    import streamlit as st

    root_items = normalize_file_picker_roots(roots)
    root_by_label = {root.label: root for root in root_items}
    root_labels = tuple(root_by_label)
    state_key = f"{key}:selected_paths"
    root_key = f"{key}:root"
    query_key = f"{key}:query"
    hidden_key = f"{key}:include_hidden"
    manual_key = f"{key}:manual_path"
    table_key = f"{key}:table"
    upload_key = f"{key}:upload"

    st.session_state.setdefault(state_key, _initial_selection(default, root_items, selection_mode))
    if st.session_state.get(root_key) not in root_by_label:
        st.session_state[root_key] = root_labels[0]
    st.session_state.setdefault(query_key, "")
    st.session_state.setdefault(hidden_key, include_hidden)
    st.session_state.setdefault(manual_key, "")

    target = container if container is not None else st
    current_selection = _validated_selection(st.session_state.get(state_key), root_items, selection_mode)
    st.session_state[state_key] = current_selection

    button_label = _button_label(label, current_selection, selection_mode)
    with target.popover(button_label, icon=":material/folder_open:", help=help, width="stretch"):
        if len(root_labels) > 1:
            selected_root = st.pills(
                "Root",
                root_labels,
                key=root_key,
                selection_mode="single",
                required=True,
                label_visibility="collapsed",
            )
        else:
            selected_root = root_labels[0]
        if selected_root not in root_by_label:
            selected_root = root_labels[0]

        search_text = st.text_input(
            "Filter files",
            key=query_key,
            placeholder="Filter by name or path",
            label_visibility="collapsed",
        ).strip()
        show_hidden = bool(
            st.checkbox(
                "Show hidden files",
                key=hidden_key,
            )
        )

        active_root = root_by_label[str(selected_root)]
        rows = [
            entry.as_row()
            for entry in list_file_picker_entries(
                active_root.path,
                patterns=patterns,
                allow_files=allow_files,
                allow_dirs=allow_dirs,
                recursive=recursive,
                include_hidden=show_hidden,
                max_entries=max_entries,
            )
        ]
        if search_text:
            lowered_search = search_text.casefold()
            rows = [
                row
                for row in rows
                if lowered_search in row["name"].casefold()
                or lowered_search in row["relative_path"].casefold()
                or lowered_search in row["type"].casefold()
            ]

        if rows:
            selection_state = st.dataframe(
                rows,
                key=table_key,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row" if selection_mode == "single" else "multi-row",
                column_order=("relative_path", "type", "size", "modified"),
                height=min(420, 36 * (len(rows) + 1)),
                width="stretch",
            )
            selected_paths = selected_paths_from_dataframe_state(selection_state, rows)
            if selected_paths:
                st.session_state[state_key] = selected_paths[:1] if selection_mode == "single" else selected_paths
        else:
            st.caption("No matching files.")

        manual_path = st.text_input(
            "Path",
            key=manual_key,
            placeholder="Paste a path under the selected roots",
        ).strip()
        if st.button("Use path", key=f"{key}:use_manual_path", disabled=not manual_path):
            try:
                selected_manual = resolve_under_roots(manual_path, root_items, must_exist=True)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.session_state[state_key] = [str(selected_manual)]
                st.rerun()

        if allow_upload:
            uploaded_files = st.file_uploader(
                "Upload",
                type=upload_types,
                accept_multiple_files=True,
                key=upload_key,
            )
            if uploaded_files and upload_dir is not None:
                saved_paths = _save_uploaded_files(uploaded_files, upload_dir, root_items)
                if saved_paths:
                    st.session_state[state_key] = saved_paths[:1] if selection_mode == "single" else saved_paths
                    st.rerun()

    final_selection = _validated_selection(st.session_state.get(state_key), root_items, selection_mode)
    st.session_state[state_key] = final_selection
    if selection_mode == "multi":
        return final_selection
    return final_selection[0] if final_selection else None


def _initial_selection(
    default: PathLike | Sequence[PathLike] | None,
    roots: Sequence[FilePickerRoot],
    selection_mode: SelectionMode,
) -> list[str]:
    if default is None:
        return []
    defaults: Sequence[PathLike]
    if isinstance(default, (str, Path)):
        defaults = [default]
    else:
        defaults = default
    selected: list[str] = []
    for raw_path in defaults:
        try:
            selected.append(str(resolve_under_roots(raw_path, roots, must_exist=False)))
        except ValueError:
            continue
    return selected[:1] if selection_mode == "single" else selected


def _validated_selection(selection: Any, roots: Sequence[FilePickerRoot], selection_mode: SelectionMode) -> list[str]:
    if isinstance(selection, (str, Path)):
        raw_selection = [selection]
    elif isinstance(selection, Sequence):
        raw_selection = list(selection)
    else:
        raw_selection = []

    validated: list[str] = []
    for raw_path in raw_selection:
        try:
            resolved = resolve_under_roots(raw_path, roots, must_exist=False)
        except ValueError:
            continue
        validated.append(str(resolved))
    return validated[:1] if selection_mode == "single" else validated


def _save_uploaded_files(uploaded_files: Sequence[Any], upload_dir: PathLike, roots: Sequence[FilePickerRoot]) -> list[str]:
    saved_paths: list[str] = []
    for uploaded_file in uploaded_files:
        target = safe_upload_target(upload_dir, uploaded_file.name, roots)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(uploaded_file.getbuffer())
        saved_paths.append(str(target))
    return saved_paths


def _entry_from_path(path: Path, root: Path, *, is_dir: bool) -> FilePickerEntry:
    stat_result = path.stat()
    relative = path.relative_to(root).as_posix()
    return FilePickerEntry(
        name=path.name,
        type="dir" if is_dir else (path.suffix.lower().lstrip(".") or "file"),
        relative_path=relative,
        path=str(path),
        size="" if is_dir else _format_size(stat_result.st_size),
        modified=datetime.fromtimestamp(stat_result.st_mtime).strftime("%Y-%m-%d %H:%M"),
    )


def _format_size(size: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def _matches_patterns(relative: Path, patterns: Sequence[str]) -> bool:
    name = relative.name.casefold()
    rel = relative.as_posix().casefold()
    for pattern in patterns:
        normalized = pattern.casefold()
        if fnmatch(name, normalized) or fnmatch(rel, normalized):
            return True
    return False


def _safe_relative_posix(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _has_hidden_part(relative: Path) -> bool:
    return any(part.startswith(".") for part in relative.parts)


def _selected_row_indices(state: Any) -> list[int]:
    if isinstance(state, Mapping):
        selection = state.get("selection", {})
        raw_rows = selection.get("rows", []) if isinstance(selection, Mapping) else []
    else:
        selection = getattr(state, "selection", None)
        raw_rows = getattr(selection, "rows", []) if selection is not None else []
    try:
        return [int(row) for row in raw_rows]
    except TypeError:
        return []


def _button_label(label: str, selection: Sequence[str], selection_mode: SelectionMode) -> str:
    if not selection:
        return label
    if selection_mode == "multi":
        return f"{label} ({len(selection)})"
    return f"{label}: {Path(selection[0]).name}"
