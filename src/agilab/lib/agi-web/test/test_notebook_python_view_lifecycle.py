"""Exercise notebook views without starting a second web application."""

from __future__ import annotations

import asyncio
import base64
import importlib
from pathlib import Path
import sys
from types import ModuleType

import pytest

from agi_web import notebook_python_view as notebook
from agi_web.python_view_session import UIError, ViewSession


@pytest.fixture
def widget_factory(tmp_path, monkeypatch):
    # Every widget uses the actual optional AnyWidget implementation.
    monkeypatch.setattr(notebook, "_WIDGET_CLASS", None)
    widgets = []

    def create(*, project=False, state=None):
        script = tmp_path / "view.py"
        script.write_text(
            "from agi_web import python_ui as ui\n"
            "ui.session_state.setdefault('count', 0)\n"
            "def increment():\n"
            "    ui.session_state['count'] += 1\n"
            "ui.text(str(ui.session_state['count']))\n"
            "ui.button('Increment', key='increment', on_click=increment)\n"
            "ui.download_button('Export', b'notebook data', 'view.ipynb')\n",
            encoding="utf-8",
        )
        active_app = tmp_path / "project" if project else None
        if active_app is not None:
            active_app.mkdir(exist_ok=True)
        widget = notebook.render_python_view(script, active_app=active_app, session_state=state)
        widgets.append(widget)
        assert widget.payload["error"] == ""
        messages = []
        monkeypatch.setattr(widget, "send", messages.append)
        return widget, messages

    yield create
    for widget in widgets:
        widget.close()


@pytest.mark.parametrize("project", [False, True])
def test_notebook_initial_render_keeps_state_and_embeds_downloads(widget_factory, project):
    widget, _ = widget_factory(project=project, state={"count": 4})
    assert widget.view_session.state["count"] == 4
    assert widget.payload["revision"] == 1
    assert widget.payload["query"] == (
        {"active_app": str(widget.active_app)} if project else {}
    )
    download = next(
        node for node in widget.payload["nodes"]["main"]
        if node["kind"] == "download_button"
    )
    url = download["props"]["url"]
    assert url.startswith("data:")
    assert base64.b64decode(url.split(";base64,", 1)[1]) == b"notebook data"
    assert widget._css == ""
    assert isinstance(widget, notebook._widget_class())
    assert notebook._widget_class() is notebook._widget_class()


@pytest.mark.parametrize("async_caller", [False, True])
def test_notebook_action_preserves_kernel_process_state_and_rerenders(widget_factory, async_caller):
    widget, messages = widget_factory(project=True, state={"count": 4})
    button = next(
        node for node in widget.payload["nodes"]["main"] if node["kind"] == "button"
    )
    path, path_values, argv, cwd = sys.path, sys.path[:], sys.argv, Path.cwd()
    action = {
        "kind": "action", "request_id": 7,
        "value": {
            "id": button["id"], "revision": widget.payload["revision"],
            "value": True, "csrf_token": widget.payload["csrf_token"],
        },
    }

    async def receive():
        widget._receive(widget, action, [])

    if async_caller:
        asyncio.run(receive())
    else:
        widget._receive(widget, action, [])
    assert widget.view_session.state["count"] == 5
    assert widget.payload["revision"] == 2
    assert messages == [{"request_id": 7, "payload": widget.payload}]
    assert sys.path is path and sys.path == path_values
    assert sys.argv is argv and Path.cwd() == cwd


@pytest.mark.parametrize(
    "message,error",
    [
        ([], "Invalid notebook view request"),
        ({}, "Invalid notebook view payload"),
        ({"kind": "render", "value": []}, "Invalid notebook view payload"),
        ({"kind": "unknown", "value": {}}, "Unknown notebook view request"),
        ({"kind": "action", "value": {}}, "Invalid notebook view token"),
        ({"kind": "action", "value": {"csrf_token": 1}}, "Invalid notebook view token"),
        ({"kind": "action", "value": {"csrf_token": "wrong"}}, "Invalid notebook view token"),
        ({"kind": "render", "value": {"path": 3}}, "Invalid notebook view location"),
        ({"kind": "render", "value": {"query": []}}, "Invalid notebook view location"),
        ({"kind": "render", "value": {"path": "//external"}}, "Invalid application route"),
    ],
)
def test_notebook_invalid_messages_do_not_modify_state(widget_factory, message, error):
    widget, messages = widget_factory(state={"count": 4})
    before = widget.payload.copy()
    widget._receive(widget, message, [])
    assert error in messages[-1]["error"]
    assert messages[-1]["request_id"] is None
    assert widget.payload == before
    assert widget.view_session.state["count"] == 4


def test_notebook_render_request_updates_query_and_rejects_unregistered_routes(widget_factory):
    widget, messages = widget_factory(project=True)
    widget._receive(widget, {"kind": "render", "request_id": 1, "value": {}}, [])
    assert widget.payload["revision"] == 2
    assert widget.payload["query"] == {"active_app": str(widget.active_app)}
    widget._receive(
        widget,
        {"kind": "render", "request_id": 2, "value": {"path": "/analysis", "query": {"x": "1"}}},
        [],
    )
    assert widget.payload["path"] == "/analysis"
    assert widget.payload["query"] == {"x": "1"}
    assert messages[-1] == {"request_id": 2, "payload": widget.payload}
    widget.view_session.routes = {"/analysis": object()}
    widget._receive(
        widget, {"kind": "render", "request_id": 3, "value": {"path": "/missing"}}, []
    )
    assert messages[-1] == {
        "request_id": 3, "error": "The requested notebook page is not registered."
    }
    assert widget.payload["path"] == "/analysis"


@pytest.mark.parametrize("project", [False, True])
@pytest.mark.parametrize("fails", [False, True])
def test_script_context_restores_imports_argv_cwd_and_path(tmp_path, monkeypatch, project, fails):
    script = tmp_path / "view.py"
    script.write_text("", encoding="utf-8")
    helper_name = "agilab_notebook_test_helper"
    (tmp_path / (helper_name + ".py")).write_text("value = 'temporary'\n", encoding="utf-8")
    package_name = "agilab_notebook_test_package"
    package = tmp_path / package_name
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "nested.py").write_text("value = 2\n", encoding="utf-8")
    saved = ModuleType(helper_name)
    saved.value = "original"
    monkeypatch.setitem(sys.modules, helper_name, saved)
    active_app = tmp_path / "project" if project else None
    if active_app is not None:
        active_app.mkdir()
    path, values, argv, cwd = sys.path, sys.path[:], sys.argv, Path.cwd()

    def execute():
        with notebook._script_context(script, active_app):
            assert Path.cwd() == (active_app or tmp_path)
            assert sys.argv == ([str(script), "--active-app", str(active_app)] if project else [str(script)])
            assert importlib.import_module(helper_name).value == "temporary"
            assert importlib.import_module(package_name + ".nested").value == 2
            sys.path = ["temporary replacement"]
            sys.argv = ["temporary replacement"]
            if fails:
                raise RuntimeError("view failure")

    if fails:
        with pytest.raises(RuntimeError, match="view failure"):
            execute()
    else:
        execute()
    assert sys.path is path and sys.path == values
    assert sys.argv is argv and Path.cwd() == cwd
    assert sys.modules[helper_name] is saved
    assert package_name not in sys.modules
    assert package_name + ".nested" not in sys.modules


def test_inline_assets_only_resolves_assets_owned_by_the_view():
    session = ViewSession(lambda: None)
    url = session.add_asset(b"content", "text/plain", "artifact.txt")
    expected = "data:text/plain;base64,Y29udGVudA=="
    assert notebook._inline_assets({"assets": [url, {"url": url}], "value": 3}, session) == {
        "assets": [expected, {"url": expected}], "value": 3,
    }
    assert notebook._inline_assets("https://example.com/image.png", session) == "https://example.com/image.png"
    with pytest.raises(UIError, match="unavailable asset"):
        notebook._inline_assets("/api/assets/not-owned", session)


@pytest.mark.parametrize("entrypoint", ["directory", "text"])
def test_notebook_rejects_non_python_entrypoints(tmp_path, entrypoint):
    path = tmp_path / entrypoint
    if entrypoint == "directory":
        path.mkdir()
    else:
        path.write_text("not Python", encoding="utf-8")
    with pytest.raises(UIError, match="must be a Python file"):
        notebook.render_python_view(path)


def test_notebook_rejects_file_as_active_project(tmp_path):
    script = tmp_path / "view.py"
    script.write_text("", encoding="utf-8")
    with pytest.raises(UIError, match="active app must be a directory"):
        notebook.render_python_view(script, active_app=script)


def test_notebook_missing_optional_dependency_reports_install_remedy(monkeypatch):
    monkeypatch.setattr(notebook, "_WIDGET_CLASS", None)
    monkeypatch.setitem(sys.modules, "anywidget", None)
    with pytest.raises(ModuleNotFoundError, match="AGILAB notebook extra"):
        notebook._widget_class()
