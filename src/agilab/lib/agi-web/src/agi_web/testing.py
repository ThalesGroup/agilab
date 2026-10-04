"""Exercise Python views with the same sessions and actions as the React host."""

from __future__ import annotations

from collections.abc import Sequence
import base64
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from typing import Any

from .python_view_session import RerunView, StopRender, UIError, ViewSession, run_view_operation, use_session


def _walk(nodes):
    for node in nodes:
        yield node
        yield from _walk(node["children"])


class Element:
    def __init__(self, app, node):
        self.app, self.node = app, node

    def __repr__(self): return f"{self.type}({self.label or str(self.value)[:400]!r})"

    @property
    def type(self): return self.node["kind"]
    @property
    def key(self): return self.node["props"].get("key")
    @property
    def label(self): return self.node["props"].get("label", "")
    @property
    def value(self):
        if self.node["id"] in self.app._session.display_values:
            value = self.app._session.display_values[self.node["id"]]
            if hasattr(value, "columns"): return value
            try:
                import pandas as pd
            except ModuleNotFoundError:
                return value
            return pd.DataFrame(value)
        widget = self.app._session.widgets.get(self.node["id"])
        if widget and widget.kind not in {"button", "form_submit_button", "component"}:
            return self.app._pending.get(self.node["id"], self.app._session.state.get(widget.key))
        props = self.node["props"]
        return props.get("value", props.get("body", props.get("message", "")))
    @property
    def options(self): return self.node["props"].get("option_labels", [])
    @property
    def proto(self):
        props = self.node["props"]
        return SimpleNamespace(**{**props, "json": json.dumps(props.get("data", {})), "exception_type": "UIError", "message": props.get("body", props.get("message", "")), "stack_trace": self.app._session.last_traceback.splitlines()})
    @property
    def stack_trace(self): return self.app._session.last_traceback.splitlines()
    @property
    def disabled(self): return bool(self.node["props"].get("disabled"))

    def set_value(self, value):
        self.app._pending_wire.pop(self.node["id"], None)
        self.app._pending[self.node["id"]] = value
        return self

    def input(self, value): return self.set_value(value)
    def upload(self, name, data, mime="application/octet-stream"):
        from .python_ui import UploadedFile
        uploaded = UploadedFile(bytes(data), str(name), str(mime))
        return self.set_value([uploaded] if self.node["props"].get("multiple") else uploaded)
    def click(self): return self.set_value(True)
    def check(self): return self.set_value(True)
    def uncheck(self): return self.set_value(False)
    def select(self, value):
        if self.type == "multiselect":
            return self.set_value([*self.value] if value in self.value else [*self.value, value])
        if value is None:
            widget = self.app._session.widgets[self.node["id"]]
            for index in widget.props.get("options", []):
                if widget.decoder(index) is None: return self.select_index(index)
        return self.set_value(value)
    def select_index(self, index):
        widget = self.app._session.widgets[self.node["id"]]
        self.set_value(widget.decoder(index) if index is not None else None)
        self.app._pending_wire[self.node["id"]] = index
        return self
    def unselect(self, value): return self.set_value([item for item in self.value if item != value])
    def run(self, **kwargs): return self.app.run(**kwargs)
    def get(self, kind): return self.app._elements(kind, self.node["children"])
    def __iter__(self): return iter(Element(self.app, node) for node in _walk(self.node["children"]))
    def __getattr__(self, name):
        if name in {"min", "max"}: return self.node["props"].get(name + "_value")
        if name in self.node["props"]: return self.node["props"][name]
        return self.get("tab" if name == "tabs" else name)


class ElementList(Sequence):
    def __init__(self, values): self.values = list(values)
    def __len__(self): return len(self.values)
    def __getitem__(self, key): return self.values[key]
    def __repr__(self): return repr(self.values)
    def __call__(self, key=None):
        if isinstance(key, int): return self.values[key]
        found = [value for value in self.values if value.key == key]
        if len(found) != 1: raise KeyError(key)
        return found[0]


class ElementTree:
    def __init__(self, app, nodes): self.app, self.nodes = app, nodes
    def get(self, kind): return self.app._elements(kind, self.nodes)
    def __getattr__(self, name): return self.get("tab" if name == "tabs" else name)
    def __iter__(self): return iter(Element(self.app, node) for node in self.nodes)
    def __getitem__(self, key): return Element(self.app, self.nodes[key])


class AppTest:
    """A synchronous view client; form values commit only with their submit button.

    Values set on controls are validated by the production Widget protocol.
    ``run`` evaluates real application code without an HTTP listener or browser.
    """

    def __init__(self, source, *, default_timeout=3):
        self._session = ViewSession(source, argv=sys.argv[1:])
        self._session.config["server_address"] = "127.0.0.1"
        self._pending, self._form_drafts = {}, {}
        self._pending_wire = {}
        self._pending_page = None
        self.default_timeout = default_timeout
        self._temporary = None

    @classmethod
    def from_file(cls, script_path, *, default_timeout=3): return cls(Path(script_path).resolve(strict=True), default_timeout=default_timeout)

    @classmethod
    def from_string(cls, script, *, default_timeout=3):
        directory = tempfile.TemporaryDirectory(prefix="agilab_python_view_test_")
        source = Path(directory.name) / "agilab_python_view_test_entry.py"
        source.write_text(script, encoding="utf-8")
        app = cls(source, default_timeout=default_timeout); app._temporary = directory
        return app

    @classmethod
    def from_function(cls, function, *, args=None, kwargs=None, default_timeout=3):
        return cls(lambda: function(*(args or ()), **(kwargs or {})), default_timeout=default_timeout)

    @property
    def session_state(self): return self._session.state
    @property
    def query_params(self): return self._session.query
    @query_params.setter
    def query_params(self, values): self._session.query.from_dict(values)
    @property
    def main(self): return ElementTree(self, self._session.last_nodes["main"])
    @property
    def sidebar(self): return ElementTree(self, self._session.last_nodes["sidebar"])

    def _elements(self, kind, roots=None):
        roots = roots if roots is not None else [*self._session.last_nodes["main"], *self._session.last_nodes["sidebar"]]
        matching = "component" if kind in {"component_instance", "bidi_component"} else kind
        return ElementList(Element(self, node) for node in _walk(roots) if node["kind"] == matching
                           or (matching == "button" and node["kind"] == "form_submit_button")
                           or (matching == "markdown" and node["kind"] == "html" and node["props"].get("markdown")))

    def get(self, kind): return self._elements(kind)
    def __iter__(self): return iter(Element(self, node) for node in _walk([*self._session.last_nodes["main"], *self._session.last_nodes["sidebar"]]))
    def __getattr__(self, name):
        if name.startswith("_"): raise AttributeError(name)
        return self.get("tab" if name == "tabs" else name)

    def _wire_value(self, widget, value):
        if value is None and widget.props.get("allow_none"): return None
        if widget.kind == "file_uploader":
            files = value if isinstance(value, list) else [] if value is None else [value]
            return [{"name": file.name, "type": file.type,
                     "data": base64.b64encode(file.getvalue()).decode("ascii")} for file in files]
        if widget.encoder:
            encoded = widget.encoder(value)
            if encoded is None and value is not None and value in widget.props.get("option_labels", []):
                return widget.props["option_labels"].index(value)
            return encoded
        if isinstance(value, tuple): return list(value)
        if hasattr(value, "isoformat"): return value.isoformat()
        return value

    def run(self, *, timeout=None):
        return run_view_operation(self._run)

    def _run(self):
        session = self._session
        with session.lock, session.render_lock, use_session(session):
            prepared, buttons = [], []
            for node_id, value in self._pending.items():
                widget = session.widgets.get(node_id)
                if not widget: raise UIError("This control is no longer registered.")
                wire = self._pending_wire[node_id] if node_id in self._pending_wire else self._wire_value(widget, value)
                checked = widget.validate(wire)
                if widget.kind in {"button", "form_submit_button"}: buttons.append(widget)
                elif widget.form: self._form_drafts[node_id] = wire
                else: prepared.append((widget, checked, wire))
            for widget in buttons:
                if widget.kind == "form_submit_button":
                    for node_id, value in list(self._form_drafts.items()):
                        candidate = session.widgets.get(node_id)
                        if candidate and candidate.form == widget.form:
                            prepared.append((candidate, candidate.validate(value), value))
                            self._form_drafts.pop(node_id)
            for widget, value, wire in prepared: session.commit_widget_value(widget, value, wire)
            for widget in buttons: session.triggers[widget.id] = True
            self._pending.clear()
            self._pending_wire.clear()
            try:
                for widget in [*(item for item, _, _ in prepared), *buttons]:
                    if widget.callback: widget.callback(*widget.args, **widget.kwargs)
            except (RerunView, StopRender): pass
            session.render()
            if self._pending_page is not None:
                from .python_ui import switch_page
                page, self._pending_page = self._pending_page, None
                try: switch_page(page)
                except RerunView: pass
                session.render()
        return self

    def switch_page(self, page):
        self._pending_page = page
        return self
