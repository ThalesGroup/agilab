"""HTTP host for AGILAB Python views and locally bundled React controls."""

from __future__ import annotations

import argparse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import os
import ipaddress
from pathlib import Path
import secrets
import socket
import threading
import time
import sys
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urlsplit

from .python_view_session import UIError, ViewSession
from .public_bind_guard import enforce_public_bind_policy


_COOKIE = "agilab_view_session"
_MAX_BODY = 48 * 1024 * 1024
_SESSION_TTL = 8 * 60 * 60


class ReactPythonServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], source: Path | Callable[[], Any], *, argv=None):
        enforce_public_bind_policy(ui_config_getter=lambda option: address[0] if option == "address" else None)
        self.source = source
        self.source_argv = list(argv or [])
        self.sessions: dict[str, tuple[ViewSession, float]] = {}
        self.sessions_lock = threading.RLock()
        if ":" in address[0]: self.address_family = socket.AF_INET6
        super().__init__(address, ReactPythonRequestHandler)

    def get_session(self, cookie: str, *, create: bool = False, path="/", query=None):
        parsed = SimpleCookie()
        try: parsed.load(cookie)
        except Exception: parsed = SimpleCookie()
        token = parsed[_COOKIE].value if _COOKIE in parsed else ""
        now = time.monotonic()
        with self.sessions_lock:
            for key, (_, seen) in list(self.sessions.items()):
                if now - seen > _SESSION_TTL: self.sessions.pop(key)
            if token in self.sessions:
                session = self.sessions[token][0]
                self.sessions[token] = (session, now)
                return session, False
            if not create: return None, False
            session = ViewSession(self.source, path=path, query=query, argv=self.source_argv)
            session.config["server_address"] = self.server_address[0]
            self.sessions[session.session_id] = (session, now)
            return session, True


class ReactPythonRequestHandler(BaseHTTPRequestHandler):
    server: ReactPythonServer

    def log_message(self, *_):
        pass

    def _reply(self, status, data: bytes, mime="application/json", *, cookie=None, filename=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "same-origin")
        if mime == "image/svg+xml":
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; sandbox")
        if cookie: self.send_header("Set-Cookie", f"{_COOKIE}={cookie}; Path=/; HttpOnly; SameSite=Strict")
        if filename: self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(filename, safe=""))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status, payload, **kwargs):
        self._reply(status, json.dumps(payload, allow_nan=False, ensure_ascii=False).encode(), **kwargs)

    def _session(self, **kwargs):
        return self.server.get_session(self.headers.get("Cookie", ""), **kwargs)

    def _valid_host(self):
        bound = self.server.server_address[0]
        try:
            loopback = ipaddress.ip_address(bound).is_loopback
        except ValueError:
            loopback = bound == "localhost"
        if not loopback: return True
        try: hostname = urlsplit("http://" + self.headers.get("Host", "")).hostname
        except ValueError: return False
        return hostname in {"localhost", "127.0.0.1", "::1", bound}

    def do_GET(self):
        if not self._valid_host(): return self._json(403, {"error": "Invalid local host."})
        request = urlsplit(self.path)
        path = request.path
        if path == "/api/health":
            return self._json(200, {"status": "ok", "host": "agilab-react"})
        if path == "/api/progress":
            session, _ = self._session()
            if session is None: return self._json(403, {"error": "No active view session."})
            return self._json(200, session.snapshot())
        if path == "/api/view":
            parameters = parse_qs(request.query, keep_blank_values=True)
            location = parameters.get("path", ["/"])[-1]
            if not location.startswith("/") or location.startswith("//"):
                return self._json(400, {"error": "Invalid application route."})
            query = {key: values[-1] if len(values) == 1 else values for key, values in parameters.items() if key != "path"}
            session, created = self._session(create=True, path=location, query=query)
            with session.lock:
                if not created:
                    if session.routes and location not in session.routes:
                        return self._json(404, {"error": "The requested page is not registered."})
                    session.set_location(location, query)
                payload = session.render()
            return self._json(200, payload, cookie=session.session_id if created else None)
        if path.startswith("/api/assets/"):
            session, _ = self._session()
            key = path.removeprefix("/api/assets/")
            if session is None or key not in session.assets:
                return self._json(404, {"error": "Asset unavailable."})
            content, mime, filename = session.assets[key]
            return self._reply(200, content, mime, filename=filename or None)
        if path in {"/assets/agilab_react_python_host.js", "/assets/agilab_react_python_host.css"}:
            asset = files("agi_web").joinpath("react_python_host_assets", path.rsplit("/", 1)[-1])
            if not asset.is_file(): return self._json(503, {"error": "The React host assets have not been built."})
            return self._reply(200, asset.read_bytes(), "text/javascript" if path.endswith(".js") else "text/css")
        if path.startswith("/api/") or path.startswith("/assets/"):
            return self._json(404, {"error": "Unknown endpoint."})
        document = b'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AGILAB</title><link rel="stylesheet" href="/assets/agilab_react_python_host.css"></head><body><div id="agilab-python-root"></div><script type="module" src="/assets/agilab_react_python_host.js"></script></body></html>'
        return self._reply(200, document, "text/html; charset=utf-8")

    def do_POST(self):
        if not self._valid_host(): return self._json(403, {"error": "Invalid local host."})
        if urlsplit(self.path).path != "/api/action":
            return self._json(404, {"error": "Unknown endpoint."})
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        import os
        origins = {"http://" + host}
        if os.environ.get("AGILAB_TLS_TERMINATED", "").lower() in {"1", "true", "yes", "on"}: origins.add("https://" + host)
        if origin and origin not in origins:
            return self._json(403, {"error": "Cross-origin actions are not allowed."})
        session, _ = self._session()
        if session is None: return self._json(403, {"error": "No active view session."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= _MAX_BODY: raise UIError("Invalid action size.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict) or not isinstance(payload.get("csrf_token"), str) or not secrets.compare_digest(payload["csrf_token"], session.csrf_token):
                return self._json(403, {"error": "Invalid view token."})
            result = session.dispatch(payload)
        except (UIError, ValueError, TypeError) as exc:
            return self._json(422, {"error": str(exc)})
        return self._json(200, result)


def serve(source: str | Path | Callable[[], Any], *, address="127.0.0.1", port=8501, argv=None, open_browser=False):
    """Run an explicitly selected Python view; local binding is the default."""
    if not callable(source):
        source = Path(source).resolve(strict=True)
        if source.suffix != ".py": raise UIError("The view entry point must be a Python file.")
    server = ReactPythonServer((address, port), source, argv=argv)
    hostname = f"[{address}]" if ":" in address else address
    url = f"http://{hostname}:{server.server_port}"
    print(f"AGILAB React interface: {url}", flush=True)
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


def main(argv=None):
    values = list(sys.argv[1:] if argv is None else argv)
    split = values.index("--") if "--" in values else len(values)
    view_args = values[split + 1:]
    parser = argparse.ArgumentParser(description="Serve an AGILAB Python view with React")
    parser.add_argument("script", type=Path)
    parser.add_argument("--address", default=(os.environ.get("AGILAB_UI_HOST", "").strip()
                        or os.environ.get("AGILAB_UI_ADDRESS", "").strip() or "127.0.0.1"))
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(values[:split])
    serve(args.script, address=args.address, port=args.port, argv=view_args, open_browser=not args.no_browser)


if __name__ == "__main__": main()
