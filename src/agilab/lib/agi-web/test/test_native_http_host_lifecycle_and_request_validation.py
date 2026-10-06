"""Exercise the native HTTP host with owned loopback sockets and sessions."""

from __future__ import annotations

import http.client
import json
import socket
import sys
import threading
from types import SimpleNamespace

import pytest

from agi_web import python_ui as ui
from agi_web import react_python_host as host_module


@pytest.fixture
def native_host():
    def view():
        ui.session_state.setdefault("count", 0)
        def increment():
            ui.session_state["count"] += 1
        ui.button("Increment", key="increment", on_click=increment)

    server = host_module.ReactPythonServer(("127.0.0.1", 0), view, argv=["--example"])
    thread = threading.Thread(
        target=lambda: server.serve_forever(poll_interval=0.01), daemon=True
    )
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def request(server, method, path, *, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def rendered_session(server):
    status, headers, body = request(server, "GET", "/api/view")
    assert status == 200
    payload = json.loads(body)
    cookie = headers["Set-Cookie"].split(";", 1)[0]
    session = server.sessions[cookie.split("=", 1)[1]][0]
    return payload, cookie, session


def test_http_static_bundles_document_and_unknown_endpoints(native_host):
    for path, mime in (
        ("/", "text/html; charset=utf-8"),
        ("/assets/agilab_react_python_host.js", "text/javascript"),
        ("/assets/agilab_react_python_host.css", "text/css"),
    ):
        status, headers, body = request(native_host, "GET", path)
        assert status == 200 and body
        assert headers["Content-Type"] == mime
        assert headers["Cache-Control"] == "no-store"
        assert headers["X-Content-Type-Options"] == "nosniff"
    status, _, body = request(native_host, "GET", "/api/health")
    assert status == 200
    assert json.loads(body) == {"status": "ok", "host": "agilab-react"}
    for path in ("/api/missing", "/assets/missing", "/api/assets/not-owned"):
        assert request(native_host, "GET", path)[0] == 404
    assert request(native_host, "POST", "/api/missing")[0] == 404
    assert request(native_host, "POST", "/api/action")[0] == 403


def test_http_missing_bundle_has_actionable_service_error(native_host, tmp_path, monkeypatch):
    monkeypatch.setattr(host_module, "files", lambda _: tmp_path)
    status, _, body = request(native_host, "GET", "/assets/agilab_react_python_host.js")
    assert status == 503
    assert json.loads(body) == {"error": "The React host assets have not been built."}


def test_http_rejects_invalid_hosts_and_routes_before_creating_session(native_host):
    for method in ("GET", "POST"):
        for host in ("attacker.example", "[invalid"):
            assert request(native_host, method, "/api/view", headers={"Host": host})[0] == 403
    for location in ("relative", "%2F%2Fexternal"):
        assert request(native_host, "GET", "/api/view?path=" + location)[0] == 400
    assert native_host.sessions == {}


def test_http_reuses_session_and_query_but_rejects_unregistered_page(native_host):
    _, cookie, session = rendered_session(native_host)
    status, headers, body = request(
        native_host, "GET", "/api/view?path=%2Fanalysis&filter=a&filter=b&empty=",
        headers={"Cookie": cookie},
    )
    assert status == 200 and "Set-Cookie" not in headers
    payload = json.loads(body)
    assert payload["path"] == "/analysis"
    assert payload["query"] == {"filter": ["a", "b"], "empty": ""}
    assert len(native_host.sessions) == 1
    session.routes = {"/analysis": object()}
    status, _, body = request(
        native_host, "GET", "/api/view?path=%2Funknown", headers={"Cookie": cookie}
    )
    assert status == 404
    assert json.loads(body) == {"error": "The requested page is not registered."}
    assert session.path == "/analysis"


def test_expired_session_cannot_be_reused_and_new_session_preserves_view_args(native_host, monkeypatch):
    _, cookie, old = rendered_session(native_host)
    monkeypatch.setattr(host_module, "time", SimpleNamespace(monotonic=lambda: 100.0))
    native_host.sessions[old.session_id] = (old, 99.0)
    reused, created = native_host.get_session(cookie)
    assert reused is old and created is False
    assert native_host.sessions[old.session_id][1] == 100.0
    native_host.sessions[old.session_id] = (old, 100.0 - host_module._SESSION_TTL - 1)
    assert native_host.get_session(cookie) == (None, False)
    assert old.session_id not in native_host.sessions
    new, created = native_host.get_session(cookie, create=True, path="/new", query={"x": "1"})
    assert created is True and new is not old
    assert new.path == "/new" and dict(new.query) == {"x": "1"}
    assert new.argv == ["--example"]
    assert new.config["server_address"] == "127.0.0.1"


@pytest.mark.parametrize(
    "body,length,status",
    [(b"", "0", 422), (b"x", "-1", 422), (b"x", "invalid", 422),
     (b"x" * 17, "17", 422), (b"{", "1", 422),
     (b"[]", "2", 403), (b'{"csrf_token":0}', "16", 403)],
)
def test_http_invalid_action_bodies_do_not_execute_controls(native_host, monkeypatch, body, length, status):
    payload, cookie, session = rendered_session(native_host)
    monkeypatch.setattr(host_module, "_MAX_BODY", 16)
    code, _, response = request(
        native_host, "POST", "/api/action", body=body,
        headers={"Cookie": cookie, "Content-Length": length},
    )
    assert code == status and "error" in json.loads(response)
    assert session.state["count"] == 0
    assert session.revision == payload["revision"]


@pytest.mark.parametrize("tls_terminated", [False, True])
def test_https_origin_requires_declared_tls_termination(native_host, monkeypatch, tls_terminated):
    payload, cookie, session = rendered_session(native_host)
    monkeypatch.setenv("AGILAB_TLS_TERMINATED", "true" if tls_terminated else "false")
    button = next(node for node in payload["nodes"]["main"] if node["kind"] == "button")
    action = {
        "id": button["id"], "revision": payload["revision"],
        "value": True, "csrf_token": payload["csrf_token"],
    }
    status, _, body = request(
        native_host, "POST", "/api/action", body=json.dumps(action),
        headers={"Cookie": cookie, "Origin": "https://127.0.0.1:" + str(native_host.server_port)},
    )
    assert status == (200 if tls_terminated else 403)
    assert session.state["count"] == (1 if tls_terminated else 0)
    assert "error" in json.loads(body)


@pytest.mark.parametrize("address", ["127.0.0.1", "::1"])
def test_serve_closes_owned_socket_on_interrupt_and_formats_browser_url(tmp_path, monkeypatch, capsys, address):
    if address == "::1" and not socket.has_ipv6:
        pytest.skip("This platform has no IPv6 sockets.")
    script = tmp_path / "view.py"
    script.write_text("", encoding="utf-8")
    owned = []
    original_server = host_module.ReactPythonServer

    class InterruptedServer(original_server):
        def serve_forever(self):
            owned.append(self)
            raise KeyboardInterrupt

    urls = []
    monkeypatch.setattr(host_module, "ReactPythonServer", InterruptedServer)
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", urls.append)
    host_module.serve(script, address=address, port=0, argv=["--active-app", "project"], open_browser=True)
    assert len(owned) == 1
    server = owned[0]
    expected = "http://" + ("[::1]" if address == "::1" else address) + ":" + str(server.server_port)
    assert urls == [expected]
    assert capsys.readouterr().out.splitlines() == [f"AGILAB React interface: {expected}"]
    assert server.source == script.resolve()
    assert server.source_argv == ["--active-app", "project"]
    assert server.socket.fileno() == -1


def test_serve_rejects_non_python_file_before_binding_socket(tmp_path, monkeypatch):
    entrypoint = tmp_path / "view.txt"
    entrypoint.write_text("not Python", encoding="utf-8")
    def unexpected_server(*args, **kwargs):
        pytest.fail("Invalid entrypoint must be rejected before opening a socket.")
    monkeypatch.setattr(host_module, "ReactPythonServer", unexpected_server)
    with pytest.raises(host_module.UIError, match="must be a Python file"):
        host_module.serve(entrypoint)


def test_cli_preserves_arguments_after_separator_without_opening_browser(tmp_path, monkeypatch):
    script = tmp_path / "view.py"
    calls = []
    monkeypatch.setattr(host_module, "serve", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(sys, "argv", [
        "native-host", str(script), "--address", "::1", "--port", "9020",
        "--no-browser", "--", "--active-app", "project", "--option", "value",
    ])
    host_module.main()
    assert calls == [((script,), {
        "address": "::1", "port": 9020, "open_browser": False,
        "argv": ["--active-app", "project", "--option", "value"],
    })]
