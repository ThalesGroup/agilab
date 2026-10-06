"""Changing render assets stay bounded while published and saved URLs survive."""

from http.client import HTTPConnection
import json
import threading

import pytest

from agi_web import python_ui as ui
from agi_web import react_python_host as host
from agi_web.python_view_session import ViewSession, current_session


def asset_key(url):
    return url.removeprefix("/api/assets/")


def downloads(payload):
    return [node["props"]["url"] for node in payload["nodes"]["main"]
            if node["kind"] == "download_button"]


def test_changing_downloads_retain_current_and_previous_payload_only():
    def view():
        session = current_session()
        generation = session.state.get("generation", 0) + 1
        session.state["generation"] = generation
        ui.download_button("Current export", str(generation).encode() + b":" + b"x" * 65536)

    session = ViewSession(view)
    previous = None
    for _ in range(32):
        payload = session.render()
        current = downloads(payload)[0]
        assert session.assets[asset_key(current)][0].endswith(b"x" * 65536)
        expected = {asset_key(current)} | ({asset_key(previous)} if previous else set())
        assert set(session.assets) == expected
        previous = current
    assert sum(len(record[0]) for record in session.assets.values()) <= 2 * 65540


def test_cached_html_and_chart_library_urls_are_not_pruned_while_reused():
    cached = {}

    def view():
        session = current_session()
        if not cached:
            cached["image"] = session.add_asset(b"cached image", "image/png")
            cached["library"] = session.add_asset(b"cached chart library", "text/javascript")
        ui.html(f'<img src="{cached["image"]}"><script src="{cached["library"]}"></script>')
        session.state["generation"] = session.state.get("generation", 0) + 1
        ui.download_button("Current export", str(session.state["generation"]))

    session = ViewSession(view)
    for _ in range(8):
        assert session.render()["error"] == ""
        assert session.assets[asset_key(cached["image"])][0] == b"cached image"
        assert session.assets[asset_key(cached["library"])][0] == b"cached chart library"
        assert len(session.assets) <= 4


def test_registered_html_asset_keeps_its_referenced_image_available():
    cached = {}

    def view():
        session = current_session()
        if not cached:
            cached["image"] = session.add_asset(b"nested image", "image/png")
            cached["frame"] = session.add_asset(
                f'<img src="{cached["image"]}">'.encode(), "text/html; charset=utf-8"
            )
        ui.iframe(cached["frame"])

    session = ViewSession(view)
    for _ in range(5):
        assert session.render()["error"] == ""
        assert session.assets[asset_key(cached["image"])][0] == b"nested image"
        assert len(session.assets) == 2


def test_saved_asset_url_remains_readable_while_referenced_by_the_published_view():
    def view():
        session = current_session()
        session.state["generation"] = session.state.get("generation", 0) + 1
        if "saved_url" not in session.state:
            session.state["saved_url"] = session.add_asset(b"saved data", "application/octet-stream")
        ui.iframe(session.state["saved_url"])
        ui.download_button("Current export", str(session.state["generation"]))

    session = ViewSession(view)
    for _ in range(6):
        payload = session.render()
        assert payload["error"] == ""
        assert session.assets[asset_key(session.state["saved_url"])][0] == b"saved data"
        assert len(session.assets) <= 3
    assert payload["nodes"]["main"][0]["props"]["src"] == session.state["saved_url"]


def test_unpublished_assets_do_not_accumulate_across_rerun_limit_errors():
    def view():
        session = current_session()
        generation = session.state.get("generation", 0) + 1
        session.state["generation"] = generation
        session.add_asset(str(generation).encode(), "application/octet-stream")
        ui.rerun()

    session = ViewSession(view)
    for _ in range(4):
        assert session.render()["error"] == "The view exceeded its rerun limit."
        assert session.assets == {}


def test_visible_assets_survive_render_errors_with_bounded_history():
    def view():
        session = current_session()
        session.state["generation"] = session.state.get("generation", 0) + 1
        ui.download_button("Latest result", str(session.state["generation"]))
        raise RuntimeError("analysis failed after producing a result")

    session = ViewSession(view)
    for _ in range(5):
        payload = session.render()
        assert payload["error"] == "RuntimeError: analysis failed after producing a result"
        assert asset_key(downloads(payload)[0]) in session.assets
        assert len(session.assets) <= 2


def test_callback_errors_prune_unpublished_assets():
    def view():
        def callback():
            session = current_session()
            session.state["generation"] = session.state.get("generation", 0) + 1
            session.add_asset(str(session.state["generation"]).encode(), "application/octet-stream")
            raise RuntimeError("callback failed")

        ui.button("Fail", key="fail", on_click=callback)

    session = ViewSession(view)
    session.render()
    for _ in range(5):
        control = next(iter(session.widgets))
        result = session.dispatch({"id": control, "revision": session.revision, "value": True})
        assert result["error"] == "RuntimeError: callback failed"
        assert session.assets == {}


def test_published_and_progress_assets_remain_readable_during_another_render():
    entered, release = threading.Event(), threading.Event()

    def view():
        session = current_session()
        session.state["generation"] = session.state.get("generation", 0) + 1
        ui.download_button("Latest result", str(session.state["generation"]))
        if session.state["generation"] == 2:
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test render was not released")

    session = ViewSession(view)
    published = downloads(session.render())[0]
    worker = threading.Thread(target=session.render)
    worker.start()
    try:
        assert entered.wait(5)
        progress = session.snapshot()
        assert progress["running"] is True
        assert session.assets[asset_key(published)][0] == b"1"
        assert session.assets[asset_key(downloads(progress)[0])][0] == b"2"
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert session.snapshot()["running"] is False
    assert session.assets[asset_key(published)][0] == b"1"
    latest = downloads(session.render())[0]
    assert session.assets[asset_key(latest)][0] == b"3"
    assert asset_key(published) not in session.assets


def get_response(server, path, cookie=""):
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request("GET", path, headers={"Cookie": cookie} if cookie else {})
        response = connection.getresponse()
        return response.status, response.read(), response.getheader("Set-Cookie")
    finally:
        connection.close()


@pytest.fixture
def served_download():
    def view():
        session = current_session()
        session.state["generation"] = session.state.get("generation", 0) + 1
        ui.download_button("Latest result", str(session.state["generation"]))

    server = host.ReactPythonServer(("127.0.0.1", 0), view)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
    worker.start()
    try:
        status, body, cookie = get_response(server, "/api/view")
        assert status == 200
        session, created = server.get_session(cookie)
        assert created is False
        yield server, session, cookie, downloads(json.loads(body))[0]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(5)
        assert not worker.is_alive()


def test_http_asset_lookup_cannot_race_a_generation_prune(served_download):
    server, session, cookie, url = served_download
    lookup_started, release = threading.Event(), threading.Event()

    class PausingMembership(dict):
        def __contains__(self, key):
            present = super().__contains__(key)
            if key == asset_key(url) and present:
                lookup_started.set()
                if not release.wait(5):
                    raise RuntimeError("test asset membership check was not released")
            return present

        def get(self, key, default=None):
            record = super().get(key, default)
            if key == asset_key(url) and record is not None:
                lookup_started.set()
            return record

    session.assets = PausingMembership(session.assets)
    results, errors = [], []

    def request():
        try:
            results.append(get_response(server, url, cookie))
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=request)
    worker.start()
    try:
        # Both implementations acknowledge the lookup before the render can prune.
        assert lookup_started.wait(5), "the asset request did not start its lookup"
        session.render()
        session.render()
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert errors == []
    assert results == [(200, b"1", None)]
    assert get_response(server, url, cookie)[:2] == (404, b'{"error": "Asset unavailable."}')


def test_http_serves_captured_asset_bytes_while_two_new_renders_prune_it(
    served_download, monkeypatch
):
    server, session, cookie, url = served_download
    captured, release = threading.Event(), threading.Event()
    original_reply = host.ReactPythonRequestHandler._reply

    def paused_reply(handler, status, data, mime="application/json", **kwargs):
        if handler.path == url:
            captured.set()
            if not release.wait(5):
                raise RuntimeError("test captured asset was not released")
        return original_reply(handler, status, data, mime, **kwargs)

    monkeypatch.setattr(host.ReactPythonRequestHandler, "_reply", paused_reply)
    results = []
    worker = threading.Thread(target=lambda: results.append(get_response(server, url, cookie)))
    worker.start()
    try:
        assert captured.wait(5)
        session.render()
        session.render()
        assert asset_key(url) not in session.assets
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert results == [(200, b"1", None)]
