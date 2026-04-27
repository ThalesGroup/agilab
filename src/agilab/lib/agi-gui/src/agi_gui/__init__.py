"""AGILAB Streamlit UI package."""

from __future__ import annotations

from .file_picker import (
    FilePickerEntry,
    FilePickerRoot,
    agi_file_picker,
    is_path_under_root,
    list_file_picker_entries,
    normalize_file_patterns,
    normalize_file_picker_roots,
    resolve_under_roots,
    safe_upload_target,
    selected_paths_from_dataframe_state,
)
from .ux_widgets import compact_choice, confirm_button, status_container, toast

__version__ = "2026.4.27.post6"

__all__ = [
    "FilePickerEntry",
    "FilePickerRoot",
    "__version__",
    "agi_file_picker",
    "compact_choice",
    "confirm_button",
    "is_path_under_root",
    "list_file_picker_entries",
    "normalize_file_patterns",
    "normalize_file_picker_roots",
    "resolve_under_roots",
    "safe_upload_target",
    "selected_paths_from_dataframe_state",
    "status_container",
    "toast",
]
