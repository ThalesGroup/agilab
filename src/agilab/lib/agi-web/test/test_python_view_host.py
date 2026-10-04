"""Behavioral coverage for retained Python views on the independent React host."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
import http.client
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from agi_web import python_ui as ui
from agi_web.python_view_session import UIError, ViewSession, session_exists
from agi_web.react_python_host import ReactPythonServer


def nodes(session, kind):
    def visit(items):
        for node in items:
            yield node
            yield from visit(node["children"])
    return [node for node in visit([*session.last_nodes["main"], *session.last_nodes["sidebar"]]) if node["kind"] == kind]


def act(session, node, value, **kwargs):
    return session.dispatch({"id": node["id"], "revision": session.revision, "value": value, **kwargs})


@pytest.mark.parametrize("harness", [False, True])
def test_native_views_and_callbacks_run_inside_notebook_event_loop(harness):
    from agi_web.testing import AppTest

    marker = ContextVar("view_test_marker")
    execution_threads = []
    caller_thread = threading.get_ident()

    async def load_value():
        await asyncio.sleep(0)
        execution_threads.append(threading.get_ident())
        return marker.get()

    def view():
        label = asyncio.run(load_value())
        ui.text(label)

        def save():
            ui.session_state["saved"] = asyncio.run(load_value())
            ui.session_state["runs"] = ui.session_state.get("runs", 0) + 1

        ui.button("Save", key="save", on_click=save)

    async def exercise():
        sessions = []
        for label in ("first", "second"):
            token = marker.set(label)
            try:
                if harness:
                    app = AppTest.from_function(view).run()
                    session = app._session
                    assert not app.exception
                    app.button("save").click().run()
                else:
                    session = ViewSession(view)
                    assert session.render()["error"] == ""
                    assert act(session, nodes(session, "button")[0], True)["error"] == ""
                assert session.state == {"saved": label, "runs": 1}
                assert marker.get() == label
                assert not session_exists()
                sessions.append(session)
            finally:
                marker.reset(token)
        assert sessions[0].state["saved"] == "first"
        assert sessions[1].state["saved"] == "second"

    asyncio.run(exercise())
    assert execution_threads and all(value != caller_thread for value in execution_threads)


def test_native_views_import_with_streamlit_blocked():
    source = Path(ui.__file__).parents[1]
    script = """
import importlib.abc, sys
class Forbidden(importlib.abc.MetaPathFinder):
    def find_spec(self, name, *args):
        if name == 'streamlit' or name.startswith('streamlit.'):
            raise AssertionError('Streamlit was imported')
sys.meta_path.insert(0, Forbidden())
sys.path.insert(0, sys.argv[1])
from agi_web import python_ui as ui
from agi_web.python_view_session import ViewSession
from agi_web.react_python_host import ReactPythonServer
session = ViewSession(lambda: ui.title('Independent view'))
assert not session.render()['error']
assert not any(name.startswith('streamlit') for name in sys.modules)
"""
    subprocess.run([sys.executable, "-I", "-c", script, str(source)], check=True, capture_output=True, text=True)


def test_button_callback_precedes_render_and_is_one_shot():
    observed = []
    def view():
        ui.button("Run", key="run", on_click=lambda: ui.session_state.update(count=ui.session_state.get("count", 0) + 1))
        observed.append(ui.session_state.get("count", 0))
    session = ViewSession(view)
    session.render()
    node = nodes(session, "button")[0]
    old_revision = session.revision
    act(session, node, True)
    assert observed == [0, 1]
    assert nodes(session, "button")[0]["props"]["value"] is True
    session.render()
    assert nodes(session, "button")[0]["props"]["value"] is False
    with pytest.raises(UIError, match="older view"):
        session.dispatch({"revision": old_revision, "id": node["id"], "value": True})


def test_form_commit_is_atomic_and_decodes_python_options(tmp_path):
    left, right = tmp_path / "first", tmp_path / "second"
    commits = []
    def view():
        with ui.form("pipeline"):
            path = ui.selectbox("Destination", [left, right], key="destination")
            count = ui.number_input("Workers", min_value=1, max_value=8, value=2, key="workers")
            if ui.form_submit_button("Save pipeline"):
                commits.append((path, count))
    session = ViewSession(view); session.render()
    selection, number, submit = nodes(session, "selectbox")[0], nodes(session, "number_input")[0], nodes(session, "form_submit_button")[0]
    with pytest.raises(UIError, match="range"):
        act(session, submit, True, form_values={selection["id"]: 1, number["id"]: 99})
    assert session.state["destination"] == left and session.state["workers"] == 2 and not commits
    with pytest.raises(UIError, match="submitted together"):
        act(session, selection, 1)
    act(session, submit, True, form_values={selection["id"]: 1, number["id"]: 4})
    assert commits == [(right, 4)]
    assert isinstance(session.state["destination"], Path)


def test_cannot_submit_another_forms_controls():
    def view():
        with ui.form("first"):
            ui.text_input("First", key="first")
            ui.form_submit_button("Save first")
        with ui.form("second"):
            ui.text_input("Second", key="second")
            ui.form_submit_button("Save second")
    session = ViewSession(view); session.render()
    with pytest.raises(UIError, match="unrelated"):
        act(session, nodes(session, "form_submit_button")[0], True, form_values={nodes(session, "text_input")[1]["id"]: "forged"})
    assert session.state["second"] == ""


def test_component_events_keep_state_but_expire_triggers():
    seen = []
    component = ui.components.v2.component("native-test", js="export default function() {}")
    def view():
        seen.append(dict(component(data={"project": "first"}, on_selection_change=lambda: None, on_action_change=lambda: None)))
    session = ViewSession(view); session.render()
    node = nodes(session, "component")[0]
    act(session, node, {"rows": [2]}, field="selection")
    act(session, node, {"kind": "open"}, field="action", trigger=True)
    assert seen[-1] == {"selection": {"rows": [2]}, "action": {"kind": "open"}}
    session.render()
    assert seen[-1] == {"selection": {"rows": [2]}, "action": None}
    with pytest.raises(UIError, match="Unknown component"):
        act(session, node, {}, field="forged")


def test_switch_page_uses_registered_routes_and_preserves_query():
    second = ui.Page(lambda: ui.title("Pipeline editor"), title="Pipeline", url_path="WORKFLOW")
    def home(): ui.button("Edit pipeline", on_click=lambda: ui.switch_page(second))
    first = ui.Page(home, title="Home", default=True)
    def view(): ui.navigation([first, second], position="hidden").run()
    session = ViewSession(view, query={"active_app": "example"}); session.render()
    act(session, nodes(session, "button")[0], True)
    assert session.path == "/WORKFLOW" and session.query["active_app"] == "example"
    assert nodes(session, "title")[0]["props"]["body"] == "Pipeline editor"


def test_sessions_do_not_share_controls_components_or_assets():
    def view(): ui.text_input("Project", key="project")
    first, second = ViewSession(view), ViewSession(view)
    first.render(); second.render()
    act(first, nodes(first, "text_input")[0], "first-project")
    assert second.state["project"] == ""
    assert first.csrf_token != second.csrf_token
    url = first.add_asset(b"private", "text/plain")
    assert url.rsplit("/", 1)[-1] not in second.assets


def test_cache_data_copies_results_resource_retains_identity_and_clear_works():
    count = []
    @ui.cache_data
    def values(argument, _context=None):
        count.append(argument); return [argument]
    first = values(2, _context="first"); first.append(3)
    assert values(2, _context="second") == [2] and count == [2]
    values.clear(); assert values(2) == [2] and count == [2, 2]
    @ui.cache_resource
    def resource(): return object()
    assert resource() is resource()


def test_cache_clear_targets_one_argument_set_and_keeps_other_roots():
    calls = []
    @ui.cache_data
    def scan(root, pattern="*.json", _context=None):
        calls.append(root)
        return len(calls)
    assert scan("first", _context="initial") == 1
    assert scan("second") == 2
    scan.clear(root="first", _context="refresh")
    assert scan("second") == 2
    assert scan("first") == 3
    assert calls == ["first", "second", "first"]


def test_cached_view_code_survives_runpy_renders_and_invalidates_changed_code(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "cache_data", ui._Cache())
    counter = tmp_path / "computations.txt"
    view = tmp_path / "cached_view.py"
    source = """from pathlib import Path
from agi_web import python_ui as ui
@ui.cache_data
def calculate(value, _counter):
    path = Path(_counter)
    path.write_text(path.read_text() + 'call\\n' if path.exists() else 'call\\n')
    return [value]
ui.json(calculate(2, COUNTER))
""".replace("COUNTER", repr(str(counter)))
    view.write_text(source)
    session = ViewSession(view)
    before = len(ui.cache_data.entries)
    for _ in range(3): assert not session.render()["error"]
    assert counter.read_text().splitlines() == ["call"]
    assert len(ui.cache_data.entries) == before + 1
    view.write_text(source.replace("return [value]", "return [value + 1]"))
    session.render()
    assert counter.read_text().splitlines() == ["call", "call"]
    assert json.loads(nodes(session, "json")[0]["props"]["body"]) == [3]
    ui.cache_data.clear()
    session.render()
    assert len(counter.read_text().splitlines()) == 3


def test_cached_closure_scopes_do_not_mix_captured_projects():
    def project_loader(project):
        @ui.cache_data
        def load(): return project
        return load
    first, second = project_loader("first"), project_loader("second")
    assert first() == "first" and second() == "second"


@pytest.mark.parametrize("host,address,expected", [("localhost", "0.0.0.0", "localhost"), (" ", "::1", "::1"), ("", "", "127.0.0.1")])
def test_native_cli_host_uses_canonical_host_and_address_alias(monkeypatch, tmp_path, host, address, expected):
    from agi_web import react_python_host
    monkeypatch.setenv("AGILAB_UI_HOST", host)
    monkeypatch.setenv("AGILAB_UI_ADDRESS", address)
    calls = []
    monkeypatch.setattr(react_python_host, "serve", lambda source, **kwargs: calls.append(kwargs))
    react_python_host.main([str(tmp_path / "view.py"), "--no-browser"])
    assert calls[0]["address"] == expected
    react_python_host.main([str(tmp_path / "view.py"), "--address", "127.0.0.2"])
    assert calls[1]["address"] == "127.0.0.2"


@pytest.fixture
def host():
    server = ReactPythonServer(("127.0.0.1", 0), lambda: (ui.text_input("Project", key="project"), ui.download_button("Export", "notebook data", "project.ipynb")))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield server
    finally: server.shutdown(); server.server_close(); thread.join(timeout=5)


def request(host, method, path, payload=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", host.server_port, timeout=5)
    connection.request(method, path, json.dumps(payload) if payload is not None else None, headers or {})
    response = connection.getresponse(); body = response.read(); result = response.status, dict(response.getheaders()), body
    connection.close(); return result


def test_http_tokens_origin_revision_and_session_assets(host):
    status, headers, body = request(host, "GET", "/api/view?path=/&active_app=first")
    assert status == 200
    cookie = headers["Set-Cookie"].split(";", 1)[0]
    payload = json.loads(body)
    session = next(iter(host.sessions.values()))[0]
    node = nodes(session, "text_input")[0]
    action = {"id": node["id"], "value": "saved", "revision": payload["revision"], "csrf_token": payload["csrf_token"]}
    assert request(host, "POST", "/api/action", action)[0] == 403
    assert request(host, "POST", "/api/action", {**action, "csrf_token": "wrong"}, {"Cookie": cookie})[0] == 403
    assert request(host, "POST", "/api/action", action, {"Cookie": cookie, "Origin": "https://unrelated.example"})[0] == 403
    assert session.state["project"] == ""
    assert request(host, "POST", "/api/action", action, {"Cookie": cookie})[0] == 200
    assert session.state["project"] == "saved"
    assert request(host, "POST", "/api/action", action, {"Cookie": cookie})[0] == 422
    url = nodes(session, "download_button")[0]["props"]["url"]
    assert request(host, "GET", url)[0] == 404
    status, headers, body = request(host, "GET", url, headers={"Cookie": cookie})
    assert status == 200 and body == b"notebook data"
    assert "project.ipynb" in headers["Content-Disposition"]


def test_inline_svg_and_image_formats_are_private_assets(host, tmp_path):
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><circle cx="12" cy="12" r="10"/></svg>'
    svg_path = tmp_path / "diagram.svg"
    svg_path.write_text(svg)
    session = ViewSession(lambda: (ui.image(svg), ui.image(svg_path), ui.image(b"GIF89aexample")))
    session.render()
    assets = [session.assets[node["props"]["urls"][0].rsplit("/", 1)[-1]] for node in nodes(session, "image")]
    assert [(content, mime) for content, mime, _ in assets] == [
        (svg.encode(), "image/svg+xml"), (svg.encode(), "image/svg+xml"), (b"GIF89aexample", "image/gif")]
    _, headers, _ = request(host, "GET", "/api/view")
    cookie = headers["Set-Cookie"].split(";", 1)[0]
    hosted = next(iter(host.sessions.values()))[0]
    url = hosted.add_asset(svg.encode(), "image/svg+xml")
    assert request(host, "GET", url)[0] == 404
    status, headers, body = request(host, "GET", url, headers={"Cookie": cookie})
    assert (status, body, headers["Content-Type"]) == (200, svg.encode(), "image/svg+xml")
    assert "default-src 'none'" in headers["Content-Security-Policy"]
    assert "sandbox" in headers["Content-Security-Policy"]


def test_tab_harness_exposes_labeled_tabs_and_their_children():
    from agi_web.testing import AppTest
    app = AppTest.from_string('''
from agi_web import python_ui as ui
for tab, label in zip(ui.tabs(["Catalogue", "Learning"]), ["First", "Second"]):
    with tab:
        ui.text_input(label)
with ui.sidebar:
    for tab in ui.tabs(["Help"]):
        with tab:
            ui.write("Sidebar tab")
''').run()
    assert [tab.label for tab in app.tabs] == ["Catalogue", "Learning", "Help"]
    assert [field.label for field in app.tabs[1].text_input] == ["Second"]
    assert [tab.label for tab in app.sidebar.tabs] == ["Help"]


def test_changed_selection_options_discard_removed_values():
    available = ["old", "shared"]
    def render():
        ui.selectbox("Single", available, key="single")
        ui.multiselect("Multiple", available, default=["old", "shared"], key="multiple")
    session = ViewSession(render)
    session.render()
    assert session.state["single"] == "old"
    available[:] = ["new", "shared"]
    session.render()
    assert session.state["single"] == "new"
    assert session.state["multiple"] == ["shared"]
    act(session, nodes(session, "selectbox")[0], 1)
    available[:] = ["newer", "shared"]
    session.render()
    assert session.state["single"] == "shared"


@pytest.mark.parametrize("kind", ["selectbox", "radio", "select_slider"])
def test_selected_none_option_keeps_its_label_and_survives_rerenders(kind):
    values = []
    session = ViewSession(lambda: values.append(getattr(ui, kind)("Nullable", [None, "Other"], key="nullable")))
    session.render()
    assert nodes(session, kind)[0]["props"]["value"] == 0
    assert nodes(session, kind)[0]["props"]["option_labels"] == ["None", "Other"]
    act(session, nodes(session, kind)[0], 1)
    assert values[-1] == "Other"
    act(session, nodes(session, kind)[0], 0)
    assert values[-1] is None
    session.render()
    assert nodes(session, kind)[0]["props"]["value"] == 0


@pytest.mark.parametrize("kind", ["selectbox", "radio", "pills", "segmented_control"])
def test_none_option_and_empty_selection_are_distinct(kind):
    options = {"index": None} if kind in {"selectbox", "radio"} else {}
    session = ViewSession(lambda: getattr(ui, kind)("Nullable", [None, "Other"], key="nullable", **options))
    session.render()
    assert nodes(session, kind)[0]["props"]["value"] is None
    act(session, nodes(session, kind)[0], 0)
    assert session.state["nullable"] is None
    session.render()
    assert nodes(session, kind)[0]["props"]["value"] == 0
    act(session, nodes(session, kind)[0], None)
    assert session.state["nullable"] is None
    session.render()
    assert nodes(session, kind)[0]["props"]["value"] is None


@pytest.mark.parametrize("kind", ["selectbox", "radio", "pills", "segmented_control"])
def test_harness_can_select_none_option_clear_it_and_replace_pending_choice(kind):
    from agi_web.testing import AppTest
    options = {"index": None} if kind in {"selectbox", "radio"} else {}
    app = AppTest.from_function(lambda: getattr(ui, kind)("Nullable", [None, "Other"], key="nullable", **options)).run()
    assert app.get(kind)[0].proto.value is None
    app.get(kind)[0].select(None).run()
    assert app.get(kind)[0].value is None and app.get(kind)[0].proto.value == 0
    app.get(kind)[0].select_index(None).run()
    assert app.get(kind)[0].value is None and app.get(kind)[0].proto.value is None
    app.get(kind)[0].set_value(None).run()
    assert app.get(kind)[0].proto.value is None
    app.get(kind)[0].set_value(None).select(None).run()
    assert app.get(kind)[0].proto.value == 0
    app.get(kind)[0].select(None).set_value(None).run()
    assert app.get(kind)[0].proto.value is None
    app.get(kind)[0].select(None).select_index(None).run()
    assert app.get(kind)[0].proto.value is None


@pytest.mark.parametrize("kind", ["selectbox", "radio", "select_slider"])
def test_harness_none_value_selects_real_option_when_empty_selection_is_forbidden(kind):
    from agi_web.testing import AppTest
    app = AppTest.from_function(lambda: getattr(ui, kind)("Nullable", [None, "Other"], key="nullable")).run()
    app.get(kind)[0].select("Other").run()
    assert app.get(kind)[0].value == "Other"
    app.get(kind)[0].set_value(None).run()
    assert app.get(kind)[0].value is None and app.get(kind)[0].proto.value == 0
    with pytest.raises(UIError, match="selected option"):
        app.get(kind)[0].select_index(None).run()
    assert app.get(kind)[0].proto.value == 0


@pytest.mark.parametrize("kind", ["selectbox", "radio"])
def test_harness_rejects_selecting_none_when_it_is_not_an_option(kind):
    from agi_web.testing import AppTest
    app = AppTest.from_function(lambda: getattr(ui, kind)("Required", ["First", "Other"], key="required")).run()
    with pytest.raises(UIError, match="selected option"):
        app.get(kind)[0].select(None).run()
    assert app.session_state["required"] == "First" and app.get(kind)[0].proto.value == 0


def test_nullable_form_rejects_invalid_submission_without_changing_selection():
    commits = []
    def view():
        with ui.form("nullable-form"):
            selected = ui.selectbox("Nullable", [None, "Other"], index=None, key="nullable")
            workers = ui.number_input("Workers", min_value=1, max_value=4, value=2, key="workers")
            if ui.form_submit_button("Save"):
                commits.append((selected, workers))
    session = ViewSession(view)
    session.render()
    selection, workers, submit = (nodes(session, kind)[0] for kind in ["selectbox", "number_input", "form_submit_button"])
    with pytest.raises(UIError, match="range"):
        act(session, submit, True, form_values={selection["id"]: 0, workers["id"]: 99})
    assert session.state["nullable"] is None and session.state["workers"] == 2 and not commits
    session.render()
    assert nodes(session, "selectbox")[0]["props"]["value"] is None
    act(session, nodes(session, "form_submit_button")[0], True,
        form_values={nodes(session, "selectbox")[0]["id"]: 0, nodes(session, "number_input")[0]["id"]: 3})
    assert commits == [(None, 3)]
    assert nodes(session, "selectbox")[0]["props"]["value"] == 0
    with pytest.raises(UIError, match="range"):
        act(session, nodes(session, "form_submit_button")[0], True,
            form_values={nodes(session, "selectbox")[0]["id"]: None, nodes(session, "number_input")[0]["id"]: 99})
    session.render()
    assert nodes(session, "selectbox")[0]["props"]["value"] == 0
    act(session, nodes(session, "form_submit_button")[0], True,
        form_values={nodes(session, "selectbox")[0]["id"]: None, nodes(session, "number_input")[0]["id"]: 4})
    assert commits == [(None, 3), (None, 4)]
    assert nodes(session, "selectbox")[0]["props"]["value"] is None


def test_harness_nullable_form_drafts_keep_none_choice_until_atomic_submit():
    from agi_web.testing import AppTest
    commits = []
    def view():
        with ui.form("nullable-form"):
            value = ui.selectbox("Nullable", [None, "Other"], index=None, key="nullable")
            if ui.form_submit_button("Save", key="save"):
                commits.append(value)
    app = AppTest.from_function(view).run()
    app.selectbox[0].select(None).run()
    assert not commits and app.selectbox[0].proto.value is None
    app.button("save").click().run()
    assert commits == [None] and app.selectbox[0].proto.value == 0
    app.selectbox[0].select_index(None).run()
    assert commits == [None] and app.selectbox[0].proto.value == 0
    app.button("save").click().run()
    assert commits == [None, None] and app.selectbox[0].proto.value is None


@pytest.mark.parametrize("value", [True, "0", {}, -1, 9])
def test_selection_rejects_forged_options(value):
    session = ViewSession(lambda: ui.selectbox("Project", ["first", "second"], key="project")); session.render()
    with pytest.raises(UIError): act(session, nodes(session, "selectbox")[0], value)
    assert session.state["project"] == "first"


def test_progress_snapshot_exposes_latest_placeholder_without_executing_again():
    ready, release = threading.Event(), threading.Event()
    calls = []
    def view():
        calls.append(1)
        placeholder = ui.empty()
        placeholder.text("Starting")
        placeholder.text("Working")
        bar = ui.progress(0)
        bar.progress(50, text="Half done")
        ready.set()
        assert release.wait(5)
        bar.progress(100, text="Done")
    session = ViewSession(view)
    thread = threading.Thread(target=session.render)
    thread.start()
    try:
        assert ready.wait(5)
        snapshot = session.snapshot()
        assert snapshot["running"] is True
        assert calls == [1]
        placeholder, bar = snapshot["nodes"]["main"]
        assert [child["props"]["body"] for child in placeholder["children"]] == ["Working"]
        assert bar["props"]["value"] == .5
        assert bar["props"]["text"] == "Half done"
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert session.snapshot()["running"] is False
    assert nodes(session, "progress")[0]["props"]["value"] == 1


def test_callback_failure_does_not_execute_success_body():
    def fail(): raise ValueError("save failed")
    def view():
        if ui.button("Save", on_click=fail): ui.success("Saved")
    session = ViewSession(view)
    session.render()
    payload = act(session, nodes(session, "button")[0], True)
    assert payload["error"] == "ValueError: save failed"
    assert not nodes(session, "success")
    assert not session.triggers
    session.render()
    assert not session.last_error


def test_registered_page_can_replace_query_parameters_atomically():
    first = ui.Page(lambda: ui.text("First"), title="First", default=True)
    second = ui.Page(lambda: ui.text("Second"), title="Second")
    def change(): ui.switch_page(second, query_params={"active_app": "second", "filter": ["a", "b"]})
    def view():
        ui.navigation([first, second], position="hidden").run()
        ui.button("Switch", on_click=change)
    session = ViewSession(view, query={"stale": "remove", "active_app": "first"})
    session.render()
    payload = act(session, nodes(session, "button")[0], True)
    assert payload["path"] == "/Second"
    assert payload["query"] == {"active_app": "second", "filter": ["a", "b"]}
    assert nodes(session, "text")[0]["props"]["body"] == "Second"


def test_upload_harness_uses_production_upload_validation():
    from agi_web.testing import AppTest
    app = AppTest.from_string("from agi_web import python_ui as ui\nui.file_uploader('Notebook', type=['ipynb'], key='upload')").run()
    app.file_uploader[0].upload("project.ipynb", b'{"cells": []}', "application/x-ipynb+json").run()
    assert app.session_state["upload"].name == "project.ipynb"
    assert app.session_state["upload"].getvalue() == b'{"cells": []}'
    app.file_uploader[0].upload("project.exe", b"bad")
    with pytest.raises(UIError, match="Unsupported uploaded file type"):
        app.run()


def test_http_rejects_dns_rebinding_and_requires_progress_session(host):
    assert request(host, "GET", "/api/health", headers={"Host": "attacker.example"})[0] == 403
    assert request(host, "GET", "/api/progress")[0] == 403
    _, headers, _ = request(host, "GET", "/api/view")
    status, _, body = request(host, "GET", "/api/progress", headers={"Cookie": headers["Set-Cookie"].split(";", 1)[0]})
    assert status == 200 and json.loads(body)["running"] is False
