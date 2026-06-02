"""Shared PROJECT sidebar action contracts and session defaults."""

from __future__ import annotations

from typing import Any, Callable, Iterable

PROJECT_EDIT_ACTIONS = ("Edit", "Create", "Import", "Rename", "Delete")
PROJECT_STATUS_ACTIONS = ("Overview", "Create", "Import", "Rename", "Delete")


def normalize_project_sidebar_actions(actions: Iterable[Any]) -> tuple[str, ...]:
    """Return canonical PROJECT sidebar action names without duplicates."""
    normalized: list[str] = []
    aliases = {"Clone": "Create"}
    allowed = set(PROJECT_EDIT_ACTIONS) | {"Overview"}
    for raw_action in actions:
        action = aliases.get(str(raw_action or "").strip(), str(raw_action or "").strip())
        if action not in allowed:
            raise ValueError(f"Unsupported PROJECT sidebar action: {raw_action!r}")
        if action not in normalized:
            normalized.append(action)
    return tuple(normalized)


def ensure_project_sidebar_session_defaults(
    streamlit: Any,
    env: Any,
    actions: tuple[str, ...],
    *,
    get_templates: Callable[[], list[str]],
    get_projects_zip: Callable[[], list[str]],
) -> None:
    """Initialize state required by PROJECT sidebar handlers in any host page."""
    streamlit.session_state.setdefault("env", env)
    streamlit.session_state.setdefault("_env", env)
    streamlit.session_state.setdefault("orchest_functions", ["build_distribution"])
    streamlit.session_state.setdefault("templates", get_templates())
    streamlit.session_state.setdefault("archives", ["-- Select a file --"] + get_projects_zip())
    streamlit.session_state.setdefault("export_message", "")
    streamlit.session_state.setdefault("project_imported", False)
    streamlit.session_state.setdefault("project_created", False)
    streamlit.session_state.setdefault("show_widgets", [True, False])
    streamlit.session_state.setdefault("pages", [])
    streamlit.session_state.setdefault("switch_to_edit", False)
    if actions:
        streamlit.session_state.setdefault("sidebar_selection", actions[0])
