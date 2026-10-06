"""Validate the values the native React client may commit to a view session."""

from datetime import date, time
from pathlib import Path

import pytest

from agi_web import python_ui as ui
from agi_web.python_view_session import (
    QueryParameters, SessionState, UIError, ViewSession, Widget,
    current_session, json_value, script_run_context, use_session,
)


@pytest.mark.parametrize("kind,props,value,message", [
    ("text_input", {"disabled": True}, "value", "disabled"),
    ("checkbox", {}, 1, "boolean"),
    ("button", {}, False, "activation"),
    ("radio", {"options": [0]}, True, "available"),
    ("radio", {"options": [0]}, 2, "available"),
    ("multiselect", {"options": [0, 1]}, "0", "unavailable"),
    ("multiselect", {"options": [0, 1]}, [True], "unavailable"),
    ("multiselect", {"options": [0, 1]}, [0, 0], "unavailable"),
    ("multiselect", {"options": [0, 1], "max_selections": 1}, [0, 1], "Too many"),
    ("text_area", {}, 4, "text"),
    ("text_input", {"max_chars": 2}, "long", "limit"),
    ("slider", {}, float("inf"), "number"),
    ("number_input", {}, True, "number"),
    ("number_input", {"min_value": 0}, -1, "range"),
    ("number_input", {"max_value": 2}, 3, "range"),
    ("number_input", {"integer": True}, 0.5, "integer"),
    ("slider", {"range": True}, 1, "ordered range"),
    ("slider", {"range": True}, [2, 1], "ordered range"),
    ("slider", {"range": True}, [1, 2, 3], "ordered range"),
    ("number_input", {}, [1], "one number"),
])
def test_client_cannot_commit_invalid_control_values(kind, props, value, message):
    widget = Widget("control", kind, "key", props)
    with pytest.raises(UIError, match=message):
        widget.validate(value)


@pytest.mark.parametrize("kind,props,value", [
    ("checkbox", {}, False), ("toggle", {}, True), ("button", {}, True),
    ("form_submit_button", {}, True),
    ("selectbox", {"allow_none": True, "options": []}, None),
    ("radio", {"options": [0, 1]}, 1),
    ("multiselect", {"options": [0, 1]}, [0, 1]),
    ("pills", {"selection_mode": "multi", "options": [0]}, []),
    ("text_input", {"max_chars": 2}, "ok"),
    ("code_editor", {}, "print(1)"),
    ("number_input", {"integer": True}, 2),
    ("slider", {"range": True, "min_value": 0, "max_value": 2}, [0, 2]),
])
def test_valid_control_values_reach_the_decoder(kind, props, value):
    observed = []
    def decode(candidate):
        observed.append(candidate)
        return candidate
    result = Widget("control", kind, "key", props, decoder=decode).validate(value)
    assert result == value
    assert observed == ([] if value is None else [value])


def test_session_state_and_query_parameters_keep_repeated_values():
    state = SessionState()
    state.answer = 42
    assert state.answer == state["answer"] == 42
    with pytest.raises(AttributeError):
        _ = state.missing
    query = QueryParameters({"choice": ["first", "last"], "empty": [], "scalar": 3})
    assert query["choice"] == "last"
    assert query.get_all("choice") == ["first", "last"]
    assert query.get_all("scalar") == ["3"]
    assert query.get_all("missing") == []
    assert query.get("missing", "fallback") == "fallback"
    assert query["empty"] == "[]"
    query.from_dict({"new": ("one", "two")})
    assert query.to_dict() == {"new": "two"}


def test_visible_json_values_handle_scalar_arrays_and_opaque_objects():
    class Array:
        def tolist(self): return [1, float("nan")]
    class Scalar:
        def item(self): return 7
    class Opaque:
        def __str__(self): return "visible label"
    assert json_value({1: (date(2026, 1, 2), time(3, 4), Path("fixture")), "array": Array(), "scalar": Scalar(), "other": Opaque()}) == {
        "1": ["2026-01-02", "03:04:00", "fixture"],
        "array": [1, None], "scalar": 7, "other": "visible label",
    }


def test_session_context_restores_the_previous_session_after_an_error():
    assert script_run_context() is None
    with pytest.raises(UIError, match="active"):
        current_session()
    outer, inner = ViewSession(lambda: None), ViewSession(lambda: None)
    with use_session(outer):
        with pytest.raises(ValueError), use_session(inner):
            assert current_session() is inner
            raise ValueError("fixture")
        assert current_session() is outer
        context = script_run_context()
        assert context.session_id == outer.session_id
        assert context.session_state is outer.state
    assert script_run_context() is None


@pytest.mark.parametrize("route", ["relative", "//external.invalid/path"])
def test_session_rejects_nonlocal_routes(route):
    session = ViewSession(lambda: None, query={"old": "kept"})
    with pytest.raises(UIError, match="route"):
        session.set_location(route, {})
    assert session.path == "/"
    assert session.query == {"old": "kept"}


def test_repeated_reruns_report_a_controlled_error_and_restore_activity():
    session = ViewSession(ui.rerun)
    result = session.render()
    assert "rerun limit" in result["error"]
    assert session.active_operations == 0
    assert result["nodes"]["main"][0]["kind"] == "exception"
    snapshot = session.snapshot()
    assert snapshot["running"] is False
    snapshot["nodes"]["main"].clear()
    assert session.last_nodes["main"]


@pytest.mark.parametrize("action", [
    {"revision": True, "id": "unknown"},
    {"revision": 0, "id": "unknown"},
    {"revision": 1, "id": None},
    {"revision": 1, "id": "unknown"},
])
def test_unknown_or_stale_actions_never_execute_the_view_again(action):
    calls = []
    session = ViewSession(lambda: calls.append("render"))
    session.render()
    with pytest.raises(UIError):
        session.dispatch(action)
    assert calls == ["render"]
    assert session.active_operations == 0


def test_detached_container_cannot_mutate_another_render_tree():
    session = ViewSession(lambda: None)
    with use_session(session):
        session.stack.append([])
        with pytest.raises(UIError, match="no longer active"):
            session.add_node("text", {"body": "stale"})
