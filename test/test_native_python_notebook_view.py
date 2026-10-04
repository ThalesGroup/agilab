"""Native Python views stay interactive and isolated when exported to Jupyter."""

from __future__ import annotations

import asyncio
import builtins
from pathlib import Path
import sys

import pytest

from agi_web.notebook_python_view import render_python_view
from agilab.notebooks.notebook_helper_cell import _helper_cell


def _nodes(widget, kind):
    def walk(nodes):
        for node in nodes:
            if node["kind"] == kind:
                yield node
            yield from walk(node["children"])
    return list(walk(widget.payload["nodes"]["main"]))


def _app(root: Path, value="alpha") -> Path:
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "notebook-view-fixture"\nversion = "0.0.0"\n', encoding="utf-8")
    (root / "local_values.py").write_text(f"VALUE = {value!r}\n", encoding="utf-8")
    script = root / "specialized_view.py"
    script.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "from agi_web import python_ui as st\n"
        "from local_values import VALUE\n"
        "st.title(VALUE)\n"
        "st.caption(sys.argv[-1])\n"
        "def save():\n"
        "    Path('submitted.txt').write_text(VALUE)\n"
        "    st.session_state['runs'] = st.session_state.get('runs', 0) + 1\n"
        "st.button('Submit', key='submit', on_click=save)\n"
        "st.metric('Runs', st.session_state.get('runs', 0))\n"
        "st.download_button('Download', b'view-evidence', file_name='view-evidence.txt')\n",
        encoding="utf-8",
    )
    return script


def _deny_streamlit(monkeypatch):
    original_import = builtins.__import__
    def import_without_streamlit(name, *args, **kwargs):
        if name == "streamlit" or name.startswith("streamlit."):
            raise AssertionError("Notebook view imported Streamlit")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", import_without_streamlit)


def test_notebook_event_loop_renders_and_dispatches_with_restored_script_context(tmp_path, monkeypatch):
    _deny_streamlit(monkeypatch)
    previous = (Path.cwd(), sys.path[:], sys.argv[:])

    async def exercise():
        widgets = []
        try:
            for label in ("first", "second"):
                project = tmp_path / label
                script = _app(project, label)
                source = script.read_text(encoding="utf-8")
                source = source.replace("st.title(VALUE)",
                    "import asyncio\n"
                    "async def load_value():\n"
                    "    await asyncio.sleep(0)\n"
                    "    return VALUE\n"
                    "st.title(asyncio.run(load_value()))")
                source = source.replace("write_text(VALUE)", "write_text(asyncio.run(load_value()))")
                script.write_text(source, encoding="utf-8")
                widget = render_python_view(script, active_app=project)
                widgets.append(widget)
                assert widget.payload["error"] == ""
                assert _nodes(widget, "title")[0]["props"]["body"] == label
                messages = []
                widget.send = messages.append
                widget._receive(widget, {"kind": "action", "request_id": label, "value": {
                    "id": _nodes(widget, "button")[0]["id"], "revision": widget.payload["revision"],
                    "value": True, "csrf_token": widget.payload["csrf_token"],
                }}, [])
                assert messages[-1]["payload"]["error"] == ""
                assert (project / "submitted.txt").read_text() == label
                widget._receive(widget, {"kind": "render", "request_id": label, "value": {}}, [])
                assert messages[-1]["payload"]["error"] == ""
                assert widget.view_session.state["runs"] == 1
                assert (Path.cwd(), sys.path, sys.argv) == previous
            assert widgets[0].view_session.state["runs"] == 1
            assert widgets[1].view_session.state["runs"] == 1
        finally:
            for widget in widgets:
                widget.close()

    asyncio.run(exercise())


def test_notebook_widget_dispatches_real_callback_with_restored_process_state(tmp_path, monkeypatch):
    _deny_streamlit(monkeypatch)
    project = tmp_path / "project"
    script = _app(project)
    previous = (Path.cwd(), sys.path[:], sys.argv[:])
    widget = render_python_view(script, active_app=project)
    try:
        assert widget.payload["error"] == ""
        assert _nodes(widget, "title")[0]["props"]["body"] == "alpha"
        assert _nodes(widget, "caption")[0]["props"]["body"] == str(project)
        assert _nodes(widget, "download_button")[0]["props"]["url"].startswith("data:")
        assert (Path.cwd(), sys.path[:], sys.argv[:]) == previous
        assert "local_values" not in sys.modules
        messages = []
        monkeypatch.setattr(widget, "send", messages.append)
        button = _nodes(widget, "button")[0]
        widget._receive(widget, {"kind": "action", "request_id": 1, "value": {
            "id": button["id"], "revision": widget.payload["revision"], "value": True,
            "csrf_token": widget.payload["csrf_token"],
        }}, [])
        assert messages[-1]["request_id"] == 1
        assert "error" not in messages[-1]
        assert (project / "submitted.txt").read_text() == "alpha"
        assert _nodes(widget, "metric")[0]["props"]["value"] == "1"
        assert (Path.cwd(), sys.path[:], sys.argv[:]) == previous
        assert "local_values" not in sys.modules
    finally:
        widget.close()


def test_notebook_widgets_keep_project_imports_and_state_separate(tmp_path, monkeypatch):
    _deny_streamlit(monkeypatch)
    first = render_python_view(_app(tmp_path / "first", "first"), active_app=tmp_path / "first")
    second = render_python_view(_app(tmp_path / "second", "second"), active_app=tmp_path / "second")
    try:
        assert _nodes(first, "title")[0]["props"]["body"] == "first"
        assert _nodes(second, "title")[0]["props"]["body"] == "second"
        first.view_session.state["runs"] = 3
        assert second.view_session.state.get("runs", 0) == 0
        messages = []
        monkeypatch.setattr(second, "send", messages.append)
        revision = second.payload["revision"]
        second._receive(second, {"kind": "action", "request_id": 2, "value": {
            "id": "unregistered-widget", "revision": revision, "value": True,
            "csrf_token": second.payload["csrf_token"],
        }}, [])
        assert messages[-1]["error"]
        assert second.payload["revision"] == revision
        assert not (tmp_path / "second" / "submitted.txt").exists()
        second._receive(second, {"kind": "action", "request_id": 3, "value": {
            "id": _nodes(second, "button")[0]["id"], "revision": revision, "value": True,
            "csrf_token": first.payload["csrf_token"],
        }}, [])
        assert messages[-1]["error"] == "Invalid notebook view token."
        assert not (tmp_path / "second" / "submitted.txt").exists()
    finally:
        first.close()
        second.close()


def test_exported_specialized_view_uses_notebook_widget_without_subprocess(tmp_path, monkeypatch):
    _deny_streamlit(monkeypatch)
    project = tmp_path / "project"
    script = _app(project)
    payload = {
        "schema": "agilab.notebook_export.v1", "version": 1,
        "project_name": "project", "module_path": str(project),
        "active_app": str(project), "artifact_dir": str(project), "stages": [],
        "related_pages": [{"name": "specialized", "module": "specialized", "script_path": str(script)}],
    }
    namespace = {}
    exec(_helper_cell(payload), namespace)
    displayed = []
    monkeypatch.setattr("IPython.display.display", displayed.append)
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: pytest.fail("Notebook rendering launched a process"))
    monkeypatch.setattr("agi_env.AgiEnv.session", lambda *args, **kwargs: pytest.fail("Generic view constructed an SDK environment"))
    widget = namespace["render_analysis_page"]("specialized")
    try:
        assert displayed == [widget]
        assert widget.payload["error"] == ""
        assert _nodes(widget, "title")[0]["props"]["body"] == "alpha"
        argv = namespace["analysis_launch_argv"]("specialized", port=9123)
        assert argv[:3] == [sys.executable, "-m", "agi_web.react_python_host"]
        assert "--port" in argv and "9123" in argv
        assert argv[-3:] == ["--", "--active-app", str(project)]
        assert "streamlit" not in namespace["analysis_launch_command"]("specialized")
    finally:
        widget.close()


def test_notebook_refresh_keeps_its_project_and_query_location(tmp_path, monkeypatch):
    _deny_streamlit(monkeypatch)
    project = tmp_path / "project"
    widget = render_python_view(_app(project), active_app=project)
    messages = []
    widget.send = messages.append
    try:
        widget.view_session.set_location("/analysis", {"active_app": str(project), "period": ["morning", "evening"]})
        widget._receive(widget, {"request_id": 1, "kind": "render", "value": {}}, [])
        assert not messages[-1].get("error")
        assert messages[-1]["payload"]["path"] == "/analysis"
        assert messages[-1]["payload"]["query"] == {"active_app": str(project), "period": ["morning", "evening"]}
        widget.view_session.routes = {"/analysis": {}}
        widget._receive(widget, {"request_id": 2, "kind": "render", "value": {"path": "/lab", "query": {"token": "jupyter"}}}, [])
        assert messages[-1]["error"] == "The requested notebook page is not registered."
        assert widget.view_session.path == "/analysis"
        assert widget.view_session.query["active_app"] == str(project)
    finally:
        widget.close()


def test_notebook_script_cannot_leave_replaced_process_lists(tmp_path):
    script = tmp_path / "replacing_python_view.py"
    script.write_text(
        "import sys\nfrom agi_web import python_ui as st\n"
        "sys.argv = ['replacement']\nsys.path = ['replacement']\n"
        "st.title('Restored after execution')\n",
        encoding="utf-8",
    )
    previous_path, previous_argv = sys.path, sys.argv
    values = sys.path[:], sys.argv[:]
    widget = render_python_view(script)
    try:
        assert widget.payload["error"] == ""
        assert sys.path is previous_path and sys.argv is previous_argv
        assert (sys.path, sys.argv) == values
    finally:
        widget.close()


def test_notebook_host_state_is_copied_before_first_render(tmp_path):
    host_state = {"runs": 4}
    widget = render_python_view(_app(tmp_path / "project"), session_state=host_state)
    try:
        assert _nodes(widget, "metric")[0]["props"]["value"] == "4"
        widget.view_session.state["runs"] = 5
        assert host_state == {"runs": 4}
    finally:
        widget.close()


def test_exported_app_form_has_isolated_sdk_context_and_saves_changes(tmp_path, monkeypatch):
    from agi_env import AgiEnv

    _deny_streamlit(monkeypatch)
    monkeypatch.setattr("IPython.display.display", lambda value: None)
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: pytest.fail("Notebook rendering launched a process"))
    widgets = []
    try:
        for name in ("first_project", "second_project"):
            project = tmp_path / name
            script = _app(project)
            (project / "src").mkdir()
            (project / "src/app_settings.toml").write_text("[args]\ndemands = 3\n", encoding="utf-8")
            script.write_text(
                "from pathlib import Path\n"
                "from agi_web import python_ui as st\n"
                "env = st.session_state.get('_env')\n"
                "if env is None:\n    st.stop()\n"
                "st.number_input('Demand count', value=3, key='demands')\n"
                "def save():\n"
                "    Path(env.app_settings_file).write_text('[args]\\ndemands = ' + str(st.session_state['demands']) + '\\n')\n"
                "st.button('Save parameters', key='save', on_click=save)\n",
                encoding="utf-8",
            )
            namespace = {}
            exec(_helper_cell({
                "project_name": name, "module_path": str(project),
                "active_app": str(project), "artifact_dir": str(project), "stages": [],
                "related_pages": [{"name": "parameters", "module": "parameters", "script_path": str(script)}],
            }), namespace)
            widget = namespace["render_analysis_page"]("parameters")
            widgets.append(widget)
            assert widget.payload["error"] == "", widget.payload
            assert _nodes(widget, "number_input")[0]["props"]["label"] == "Demand count"
            env = widget.view_session.state["_env"]
            assert isinstance(env, AgiEnv)
            assert env is widget.view_session.state["env"]
            assert Path(env.active_app).resolve() == project.resolve()

        first, second = widgets
        assert first.view_session.state["_env"] is not second.view_session.state["_env"]
        for request_id, (key, value) in enumerate((("demands", 11), ("save", True)), 1):
            control = next(control for control in first.view_session.widgets.values() if control.key == key)
            first._receive(first, {"kind": "action", "request_id": request_id, "value": {
                "id": control.id, "revision": first.payload["revision"], "value": value,
                "csrf_token": first.payload["csrf_token"],
            }}, [])
            assert first.payload["error"] == "", first.payload
        assert "demands = 11" in Path(first.view_session.state["_env"].app_settings_file).read_text()
        assert "demands = 3" in Path(second.view_session.state["_env"].app_settings_file).read_text()
        assert second.view_session.state["demands"] == 3
    finally:
        for widget in widgets:
            widget.close()
