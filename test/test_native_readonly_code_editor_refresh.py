"""Native editor regressions for changing output and preserved editable drafts."""

from agi_web import python_ui
from agi_web.python_view_session import ViewSession

from agilab.components.code_editor_component import code_editor
from agilab.ui.pinned_expander import list_pinned_expanders, render_pinnable_code_editor


def _nodes(payload):
    def walk(nodes):
        for node in nodes:
            yield node
            yield from walk(node.get("children", []))

    return list(walk(payload["nodes"]["main"]))


def test_readonly_output_refreshes_and_pin_uses_current_run():
    current = {"body": "run_first.log\nRunning stage 1"}

    def render():
        render_pinnable_code_editor(
            python_ui,
            code_editor,
            "workflow-run-logs",
            title="Workflow logs",
            body=current["body"],
            key="workflow-run-logs",
            language="text",
        )

    session = ViewSession(render)
    first = session.render()
    assert first["error"] == ""
    first_text = next(n for n in _nodes(first) if n["kind"] == "text_area")
    assert first_text["props"]["value"] == current["body"]

    current["body"] = "run_second.log\nRunning stage 4\nWorkflow complete"
    second = session.render()
    assert second["error"] == ""
    second_text = next(n for n in _nodes(second) if n["kind"] == "text_area")
    assert second_text["id"] == first_text["id"]
    assert second_text["props"]["value"] == current["body"]
    assert second_text["props"]["disabled"] is True
    pin = next(n for n in _nodes(second) if n["kind"] == "form_submit_button")
    assert not pin["props"]["disabled"]
    result = session.dispatch(
        {
            "revision": session.revision,
            "id": pin["id"],
            "value": True,
        }
    )
    assert result["error"] == ""
    assert list_pinned_expanders(session.state)[0]["body"] == current["body"]


def test_editable_editor_preserves_draft_when_source_body_changes():
    current = {"body": "original source"}
    outputs = []

    def render():
        outputs.append(code_editor(current["body"], key="editable-code"))

    session = ViewSession(render)
    assert session.render()["error"] == ""
    session.state["editable-code:text"] = "unsaved user draft"
    current["body"] = "updated source default"
    payload = session.render()
    assert payload["error"] == ""
    editor = next(n for n in _nodes(payload) if n["kind"] == "text_area")
    assert editor["props"]["value"] == "unsaved user draft"
    assert not editor["props"]["disabled"]
    assert outputs[-1]["text"] == "unsaved user draft"
