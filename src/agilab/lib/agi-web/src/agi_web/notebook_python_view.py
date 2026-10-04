"""Render retained Python views inside Jupyter through the native React host."""

from __future__ import annotations

import base64
from contextlib import contextmanager
from importlib.resources import files
import json
import os
from pathlib import Path
import runpy
import secrets
import sys
from typing import Any

from .python_view_session import UIError, ViewSession, run_view_operation


@contextmanager
def _script_context(script: Path, active_app: Path | None):
    """Restore notebook process state after each script execution, including imports."""
    roots = tuple(root for root in (script.parent, active_app) if root is not None)
    names = {path.stem for root in roots for path in root.glob("*.py")}
    names.update(path.name for root in roots for path in root.iterdir() if path.is_dir())
    saved_modules = {name: module for name, module in sys.modules.copy().items()
                     if name.split(".", 1)[0] in names}
    saved_path, path_values, saved_argv, saved_cwd = sys.path, sys.path[:], sys.argv, Path.cwd()
    for name in saved_modules:
        sys.modules.pop(name, None)
    sys.path[:0] = [str(root) for root in roots]
    sys.argv = [str(script)]
    if active_app is not None:
        sys.argv.extend(["--active-app", str(active_app)])
    try:
        os.chdir(active_app or script.parent)
        yield
    finally:
        os.chdir(saved_cwd)
        sys.path = saved_path
        sys.path[:] = path_values
        sys.argv = saved_argv
        for name in list(sys.modules):
            if name.split(".", 1)[0] in names:
                sys.modules.pop(name, None)
        sys.modules.update(saved_modules)


def _inline_assets(value: Any, session: ViewSession) -> Any:
    """Embed only assets registered by this view, so no HTTP server is required."""
    if isinstance(value, dict):
        return {key: _inline_assets(item, session) for key, item in value.items()}
    if isinstance(value, list):
        return [_inline_assets(item, session) for item in value]
    if isinstance(value, str) and value.startswith("/api/assets/"):
        record = session.assets.get(value.rsplit("/", 1)[-1])
        if record is None:
            raise UIError("A notebook view referenced an unavailable asset.")
        data, mime, _filename = record
        return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
    return value


_WIDGET_CLASS = None


def _widget_class():
    global _WIDGET_CLASS
    if _WIDGET_CLASS is not None:
        return _WIDGET_CLASS
    try:
        import anywidget
        import traitlets
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Python views in notebooks require the AGILAB notebook extra "
            "(anywidget and ipywidgets)."
        ) from exc
    assets = files("agi_web").joinpath("react_python_host_assets")
    script = assets.joinpath("agilab_react_python_host.js").read_text(encoding="utf-8")
    style = assets.joinpath("agilab_react_python_host.css").read_text(encoding="utf-8")
    # The host bundle owns React and its renderer. The bridge transports actions
    # over Jupyter comms and never opens a second web application.
    bridge = """
export async function render({model, el}) {
  const root = el.shadowRoot || el.attachShadow({mode: 'open'});
  const style = document.createElement('style');
  style.textContent = HOST_STYLE.replaceAll(':root', ':host');
  const view = document.createElement('div');
  root.append(style, view);
  const moduleURL = URL.createObjectURL(new Blob([HOST_SOURCE], {type: 'text/javascript'}));
  let mountPythonView;
  try { ({mountPythonView} = await import(moduleURL)); }
  finally { URL.revokeObjectURL(moduleURL); }
  const assetURLs = new Map();
  const prepare = value => {
    if (Array.isArray(value)) return value.map(prepare);
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, prepare(item)]));
    if (typeof value !== 'string' || !value.startsWith('data:') || !value.includes(';base64,')) return value;
    if (!assetURLs.has(value)) {
      const [header, encoded] = value.split(';base64,', 2);
      const bytes = Uint8Array.from(atob(encoded), character => character.charCodeAt(0));
      assetURLs.set(value, URL.createObjectURL(new Blob([bytes], {type: header.slice(5)})));
    }
    return assetURLs.get(value);
  };
  let serial = 0;
  const pending = new Map();
  const receive = message => {
    const request = pending.get(message.request_id);
    if (!request) return;
    pending.delete(message.request_id);
    if (message.error) request.reject(new Error(message.error));
    else request.resolve(prepare(message.payload));
  };
  model.on('msg:custom', receive);
  const request = (kind, value) => new Promise((resolve, reject) => {
    const request_id = ++serial;
    pending.set(request_id, {resolve, reject});
    model.send({kind, value, request_id});
  });
  const cleanup = mountPythonView(view, {
    initialPayload: prepare(model.get('payload')),
    transport: {
      render: value => request('render', value),
      action: value => request('action', value),
    },
  });
  return () => {
    cleanup();
    view.remove();
    style.remove();
    model.off('msg:custom', receive);
    for (const request of pending.values()) request.reject(new Error('Notebook view closed.'));
    pending.clear();
    for (const url of assetURLs.values()) URL.revokeObjectURL(url);
    assetURLs.clear();
  };
}
"""

    class PythonNotebookView(anywidget.AnyWidget):
        _esm = "const HOST_SOURCE = " + json.dumps(script) + ";\nconst HOST_STYLE = " + json.dumps(style) + ";\n" + bridge
        # AnyWidget's _css is global. Keep the complete host stylesheet inside
        # this view's shadow root so Jupyter and earlier outputs retain theirs.
        _css = ""
        payload = traitlets.Dict().tag(sync=True)

        def __init__(self, session: ViewSession, script_path: Path, active_app: Path | None, **kwargs):
            self.view_session = session
            self.script_path, self.active_app = script_path, active_app
            super().__init__(payload=_inline_assets(session.render(), session), **kwargs)
            self.on_msg(self._receive)

        def _receive(self, _widget, message, _buffers):
            return run_view_operation(lambda: self._receive_sync(message))

        def _receive_sync(self, message):
            request_id = message.get("request_id") if isinstance(message, dict) else None
            try:
                if not isinstance(message, dict):
                    raise UIError("Invalid notebook view request.")
                value = message.get("value")
                if not isinstance(value, dict):
                    raise UIError("Invalid notebook view payload.")
                with self.view_session.render_lock, _script_context(self.script_path, self.active_app):
                    if message.get("kind") == "action":
                        token = value.get("csrf_token")
                        if not isinstance(token, str) or not secrets.compare_digest(token, self.view_session.csrf_token):
                            raise UIError("Invalid notebook view token.")
                        result = self.view_session.dispatch(value)
                    elif message.get("kind") == "render":
                        path = value.get("path", self.view_session.path)
                        query = value.get("query", dict(self.view_session.query))
                        if not isinstance(path, str) or not isinstance(query, dict):
                            raise UIError("Invalid notebook view location.")
                        if self.view_session.routes and path not in self.view_session.routes:
                            raise UIError("The requested notebook page is not registered.")
                        self.view_session.set_location(path, query)
                        result = self.view_session.render()
                    else:
                        raise UIError("Unknown notebook view request.")
                self.payload = _inline_assets(result, self.view_session)
                self.send({"request_id": request_id, "payload": self.payload})
            except (UIError, ValueError, TypeError) as exc:
                self.send({"request_id": request_id, "error": str(exc)})

    _WIDGET_CLASS = PythonNotebookView
    return _WIDGET_CLASS


def render_python_view(script: str | Path, *, active_app: str | Path | None = None):
    """Return an interactive notebook widget for an explicitly selected Python file."""
    path = Path(script).expanduser().resolve(strict=True)
    if not path.is_file() or path.suffix != ".py":
        raise UIError("The notebook view entry point must be a Python file.")
    project = Path(active_app).expanduser().resolve(strict=True) if active_app else None
    if project is not None and not project.is_dir():
        raise UIError("The active app must be a directory.")

    def run_script():
        with _script_context(path, project):
            runpy.run_path(str(path), run_name="__main__")

    query = {"active_app": str(project)} if project else {}
    return _widget_class()(ViewSession(run_script, query=query), path, project)
