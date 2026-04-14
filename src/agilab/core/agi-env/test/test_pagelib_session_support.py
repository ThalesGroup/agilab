from __future__ import annotations

from agi_env.pagelib_session_support import (
    PROJECT_SECTION_LABELS,
    clear_project_session_state,
    reset_project_sections,
)


def test_clear_project_session_state_removes_known_keys_and_prefixes():
    session_state = {
        "is_args_from_ui": True,
        "arg_name_1": "foo",
        "arg_value_1": "bar",
        "view_checkbox_a": True,
        "abc:app_args_form:def": "cleanup",
        "keep_me": "value",
    }

    clear_project_session_state(session_state)

    assert "is_args_from_ui" not in session_state
    assert "arg_name_1" not in session_state
    assert "arg_value_1" not in session_state
    assert "view_checkbox_a" not in session_state
    assert "abc:app_args_form:def" not in session_state
    assert session_state["keep_me"] == "value"


def test_reset_project_sections_sets_expected_labels_to_false():
    session_state = {label: True for label in PROJECT_SECTION_LABELS}
    session_state["keep_me"] = "value"

    reset_project_sections(session_state)

    for label in PROJECT_SECTION_LABELS:
        assert session_state[label] is False
    assert session_state["keep_me"] == "value"
