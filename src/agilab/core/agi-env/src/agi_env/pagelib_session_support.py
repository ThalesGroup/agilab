"""Session-state utilities for project switches in pagelib."""

from __future__ import annotations


PROJECT_SESSION_STATE_KEYS_TO_CLEAR = (
    "is_args_from_ui",
    "args_default",
    "toggle_edit",
    "toggle_edit_ui",
    "app_args_form_refresh_nonce",
    "df_file_selectbox",
    "app_settings",
    "input_datadir",
    "preview_tree",
    "loaded_df",
    "wenv_abs",
    "projects",
    "log_text",
    "run_log_cache",
    "lab_dir_selectbox",
    "lab_dir",
    "index_page",
    "stages_file",
    "df_file",
    "df_file_in",
    "df_file_out",
    "stages_files",
    "df_files",
    "df_dir",
    "lab_prompt",
    "lab_selected_venv",
    "pipeline_config_snapshot",
)
PROJECT_SESSION_STATE_PREFIXES = ("arg_name", "arg_value", "view_checkbox")
PROJECT_SECTION_LABELS = (
    "PYTHON-ENV",
    "PYTHON-ENV-EXTRA",
    "MANAGER",
    "WORKER",
    "EXPORT-APP-FILTER",
    "APP-SETTINGS",
    "ARGS-UI",
    "PRE-PROMPT",
)


def clear_project_session_state(session_state) -> None:
    """Remove project-scoped keys from Streamlit session state."""
    for key in PROJECT_SESSION_STATE_KEYS_TO_CLEAR:
        session_state.pop(key, None)

    keys_to_delete = [
        key
        for key in session_state
        if key.startswith(PROJECT_SESSION_STATE_PREFIXES) or ":app_args_form:" in key
    ]
    for key in keys_to_delete:
        session_state.pop(key, None)


def reset_project_sections(session_state) -> None:
    """Reset expandable section toggles when switching project."""
    for label in PROJECT_SECTION_LABELS:
        session_state[label] = False
