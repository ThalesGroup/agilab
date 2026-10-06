"""Keep the synchronous view client aligned with native control actions."""

from datetime import date
import sys
from types import SimpleNamespace

import pytest

from agi_web import python_ui as ui
from agi_web.python_view_session import StopRender, UIError
from agi_web.testing import AppTest


def test_client_function_arguments_tree_lookup_and_control_properties():
    def view(label, *, suffix):
        with ui.sidebar:
            ui.checkbox(label + suffix, key="enabled", disabled=False)
        with ui.tabs(["First", "Second"])[0]:
            ui.slider("Range", min_value=1, max_value=3, value=2, key="range")
            ui.markdown("body")
    app = AppTest.from_function(view, args=["Enable"], kwargs={"suffix": " feature"}).run()
    checkbox = app.checkbox("enabled")
    assert checkbox.type == "checkbox" and checkbox.key == "enabled"
    assert checkbox.label == "Enable feature" and not checkbox.disabled
    assert "Enable feature" in repr(checkbox)
    assert checkbox.check().run().session_state.enabled is True
    assert checkbox.uncheck().run().session_state.enabled is False
    assert app.slider[0].min == 1 and app.slider[0].max == 3
    assert app.slider[0].step == 1
    assert len(app.sidebar.checkbox) == 1
    assert app.main[0].type == "tabs"
    assert [node.type for node in app.main] == ["tabs"]
    assert app.main.tabs[0].label == "First"
    assert app.tabs[0].get("markdown")[0].value == "body"
    assert any(node.type == "slider" for node in app.tabs[0])
    assert app.markdown[0].proto.message == "body"
    assert app.markdown[0].proto.exception_type == "UIError"
    assert app.markdown[0].stack_trace == []
    assert len(list(app)) > 4
    assert "checkbox" in repr(app.checkbox)
    assert app.checkbox(0).node == app.checkbox[0].node
    with pytest.raises(KeyError):
        app.checkbox("missing")
    with pytest.raises(AttributeError):
        _ = app._unknown_attribute


def test_client_string_and_file_factories_run_real_owned_source(tmp_path):
    source = tmp_path / "owned_view.py"
    source.write_text("from agi_web import python_ui as ui\nui.text('file body')\n")
    file_app = AppTest.from_file(source, default_timeout=4).run()
    assert file_app.default_timeout == 4
    assert file_app.text[0].value == "file body"
    app = AppTest.from_string("from agi_web import python_ui as ui\nui.text('string body')\n")
    try:
        app.query_params = {"filter": ["first", "last"]}
        assert app.run(timeout=1).text[0].value == "string body"
        assert app.query_params["filter"] == "last"
    finally:
        app._temporary.cleanup()
    with pytest.raises(FileNotFoundError):
        AppTest.from_file(tmp_path / "missing.py")


def test_client_selection_upload_dates_and_ranges_round_trip_python_values():
    def view():
        ui.multiselect("Many", ["a", "b"], default=["a"], key="many")
        ui.selectbox("Choice", [None, "other"], index=None, key="choice")
        ui.radio("Named", [1, 2], format_func=lambda value: "label" + str(value), key="named")
        ui.slider("Range", value=(1, 2), key="range")
        ui.date_input("Date", value=date(2026, 1, 1), key="day")
        ui.file_uploader("File", key="file")
        ui.file_uploader("Files", accept_multiple_files=True, key="files")
    app = AppTest.from_function(view).run()
    assert app.multiselect[0].options == ["a", "b"]
    app.multiselect[0].select("a").select("b").unselect("a")
    app.selectbox[0].select(None)
    app.radio[0].set_value("label2")
    app.slider[0].set_value((2, 3))
    app.date_input[0].set_value(date(2026, 1, 2))
    app.file_uploader[0].upload("fixture.txt", b"one", "text/plain")
    app.file_uploader[1].upload("fixture.txt", b"two")
    app.run()
    assert app.session_state.many == ["b"]
    assert app.session_state.choice is None and app.session_state.named == 2
    assert app.session_state.range == (2, 3)
    assert app.session_state.day == date(2026, 1, 2)
    assert app.session_state.file.getvalue() == b"one"
    assert app.session_state.files[0].getvalue() == b"two"
    app.file_uploader[0].set_value(None)
    app.run()
    assert app.session_state.file is None


def test_display_values_keep_dataframe_identity_or_convert_records(monkeypatch):
    records = [{"value": 1}]
    app = AppTest.from_function(lambda: ui.dataframe(records)).run()
    monkeypatch.setitem(sys.modules, "pandas", None)
    assert app.dataframe[0].value is records
    converted = SimpleNamespace(columns=["value"])
    monkeypatch.setitem(sys.modules, "pandas", SimpleNamespace(DataFrame=lambda value: converted if value is records else None))
    assert app.dataframe[0].value is converted
    class Frame:
        columns = ["value"]
        def reset_index(self): return self
        def to_dict(self): return {"value": [1]}
        def to_numpy(self): return SimpleNamespace(tolist=lambda: [[1]])
    frame = Frame()
    app = AppTest.from_function(lambda: ui.dataframe(frame)).run()
    assert app.dataframe[0].value is frame


def test_client_reports_errors_and_rejects_actions_for_removed_controls():
    def view():
        raise ValueError("owned failure")
    app = AppTest.from_function(view).run()
    assert "ValueError: owned failure" in app.exception[0].value
    assert app.exception[0].stack_trace
    assert app.exception[0].proto.stack_trace == app.exception[0].stack_trace
    app._pending["removed_control"] = "forged"
    with pytest.raises(UIError, match="no longer registered"):
        app.run()


def test_callback_stop_render_is_controlled_and_component_aliases_match():
    component = ui.components.v2.component("client_alias_fixture", js="export default () => {}")
    def callback(): raise StopRender()
    def view():
        ui.button("Apply", on_click=callback)
        component(key="client_component")
        ui.text("render survives")
    app = AppTest.from_function(view).run()
    app.button[0].click().run()
    assert not app.exception
    assert app.text[0].value == "render survives"
    assert app.component_instance[0].node == app.bidi_component[0].node
    assert app.component_instance[0].node == app.get("component")[0].node


def test_client_switch_page_rerenders_the_registered_destination(tmp_path):
    destination = tmp_path / "destination.py"
    destination.write_text("from agi_web import python_ui as ui\nui.text('destination')\n")
    def view():
        page = ui.navigation([ui.Page(lambda: ui.text("home"), default=True), ui.Page(destination)])
        page.run()
    app = AppTest.from_function(view).run()
    assert app.text[0].value == "home"
    assert app.switch_page(destination).run().text[0].value == "destination"
