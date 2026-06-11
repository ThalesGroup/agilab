from __future__ import annotations

from types import SimpleNamespace

import pytest

from agilab.projects.project_sidebar_support import (
    PROJECT_EDITOR_ACTIONS,
    PROJECT_STATUS_ACTIONS,
    ensure_project_sidebar_session_defaults,
    normalize_project_sidebar_actions,
)


def test_normalize_project_sidebar_actions_aliases_clone_and_rejects_unknown() -> None:
    assert PROJECT_EDITOR_ACTIONS[0] == "Edit"
    assert "Export" in PROJECT_EDITOR_ACTIONS
    assert "Export" in PROJECT_STATUS_ACTIONS
    assert normalize_project_sidebar_actions(["Overview", "Clone", "Export", "Delete"]) == (
        "Overview",
        "Create",
        "Export",
        "Delete",
    )

    with pytest.raises(ValueError, match="Unsupported PROJECT sidebar action"):
        normalize_project_sidebar_actions(["Overview", "Launch"])


def test_project_sidebar_session_defaults_cover_status_host_state() -> None:
    streamlit = SimpleNamespace(session_state={})
    env = SimpleNamespace(app="flight_telemetry_project")

    ensure_project_sidebar_session_defaults(
        streamlit,
        env,
        PROJECT_STATUS_ACTIONS,
        get_templates=lambda: ["template_project"],
        get_projects_zip=lambda: ["archive.zip"],
    )

    assert streamlit.session_state["env"] is env
    assert streamlit.session_state["_env"] is env
    assert streamlit.session_state["templates"] == ["template_project"]
    assert streamlit.session_state["archives"] == ["-- Select a file --", "archive.zip"]
    assert streamlit.session_state["sidebar_selection"] == "Overview"
    assert streamlit.session_state["show_widgets"] == [True, False]


def test_project_sidebar_session_defaults_preserve_existing_selection() -> None:
    streamlit = SimpleNamespace(session_state={"sidebar_selection": "Rename"})
    env = SimpleNamespace(app="flight_telemetry_project")

    ensure_project_sidebar_session_defaults(
        streamlit,
        env,
        PROJECT_STATUS_ACTIONS,
        get_templates=lambda: [],
        get_projects_zip=lambda: [],
    )

    assert streamlit.session_state["sidebar_selection"] == "Rename"


def test_project_switch_clears_sidebar_action_state_and_result_banners():
    from agi_env.ui.pagelib_session_support import clear_project_session_state

    session_state = {
        "sidebar_selection": "Delete",
        "export_message": "Export completed.",
        "project_imported": True,
        "project_created": True,
        "unrelated": "keep",
    }

    clear_project_session_state(session_state)

    assert "sidebar_selection" not in session_state
    assert "export_message" not in session_state
    assert "project_imported" not in session_state
    assert "project_created" not in session_state
    assert session_state["unrelated"] == "keep"
