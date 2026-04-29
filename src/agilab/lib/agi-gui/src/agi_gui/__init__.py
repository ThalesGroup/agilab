"""AGILAB Streamlit UI package."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _package_version

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
from .widget_registry import (
    WidgetRegistry,
    WidgetSpec,
    default_widget_registry,
    get_widget,
    widget_registry_rows,
)
from .ux_widgets import (
    ActionSpec,
    ActionStyle,
    action_button,
    action_row,
    action_style,
    compact_choice,
    confirm_button,
    empty_state,
    normalize_action_kind,
    normalize_message_state,
    normalize_status_state,
    notice,
    status_container,
    toast,
)

try:
    __version__ = _package_version("agi-gui")
except PackageNotFoundError:
    __version__ = "0+unknown"

__all__ = [
    "FilePickerEntry",
    "FilePickerRoot",
    "ActionSpec",
    "ActionStyle",
    "WidgetRegistry",
    "WidgetSpec",
    "__version__",
    "agi_file_picker",
    "action_button",
    "action_row",
    "action_style",
    "compact_choice",
    "confirm_button",
    "default_widget_registry",
    "empty_state",
    "get_widget",
    "is_path_under_root",
    "list_file_picker_entries",
    "normalize_action_kind",
    "normalize_file_patterns",
    "normalize_file_picker_roots",
    "normalize_message_state",
    "normalize_status_state",
    "notice",
    "resolve_under_roots",
    "safe_upload_target",
    "selected_paths_from_dataframe_state",
    "status_container",
    "toast",
    "widget_registry_rows",
]
