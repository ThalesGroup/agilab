"""Session and action protocol for Python views rendered by the React host."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import copy
from dataclasses import dataclass, field
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import runpy
import secrets
import sys
import threading
import traceback
from types import SimpleNamespace
from typing import Any, Callable, Iterator, Mapping


class UIError(RuntimeError):
    """An invalid Python view operation or browser action."""


class StopRender(BaseException):
    pass


class RerunView(BaseException):
    pass


class SessionState(dict[str, Any]):
    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


class QueryParameters(SessionState):
    def __getitem__(self, key: str) -> str:
        value = super().__getitem__(key)
        return str(value[-1]) if isinstance(value, (list, tuple)) and value else str(value)

    def get(self, key: str, default: Any = None) -> Any:
        return self[key] if key in self else default

    def get_all(self, key: str) -> list[str]:
        value = super().get(key, [])
        return list(value) if isinstance(value, (list, tuple)) else [str(value)]

    def from_dict(self, values: Mapping[str, Any]) -> None:
        self.clear()
        self.update(values)

    def to_dict(self) -> dict[str, Any]:
        return {key: self[key] for key in self}


def json_value(value: Any) -> Any:
    """Convert visible view values without serializing application objects."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return None if isinstance(value, float) and not math.isfinite(value) else value
    if isinstance(value, (dt.date, dt.time, Path)):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_value(item) for item in value]
    if hasattr(value, "tolist"):
        return json_value(value.tolist())
    if hasattr(value, "item"):
        return json_value(value.item())
    return str(value)


@dataclass
class Widget:
    id: str
    kind: str
    key: str
    props: dict[str, Any]
    callback: Callable[..., Any] | None = None
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    form: str | None = None
    component_callbacks: dict[str, Callable[..., Any] | None] = field(default_factory=dict)
    decoder: Callable[[Any], Any] | None = None
    encoder: Callable[[Any], Any] | None = None

    def validate(self, value: Any) -> Any:
        if self.props.get("disabled"):
            raise UIError("This control is disabled.")
        if self.kind in {"checkbox", "toggle", "button", "form_submit_button"}:
            if not isinstance(value, bool):
                raise UIError("Expected a boolean control value.")
            if self.kind in {"button", "form_submit_button"} and value is not True:
                raise UIError("Expected a button activation.")
        elif self.kind in {"selectbox", "radio", "pills", "segmented_control", "select_slider"} and self.props.get("selection_mode") != "multi":
            if value is None and self.props.get("allow_none"):
                return None
            if not isinstance(value, int) or isinstance(value, bool) or value not in self.props.get("options", []):
                raise UIError("The selected option is no longer available.")
        elif self.kind == "multiselect" or self.props.get("selection_mode") == "multi":
            options = self.props.get("options", [])
            if not isinstance(value, list) or any(not isinstance(item, int) or isinstance(item, bool) or item not in options for item in value) or len(set(value)) != len(value):
                raise UIError("The selection contains an unavailable option.")
            if self.props.get("max_selections") is not None and len(value) > self.props["max_selections"]:
                raise UIError("Too many selected options.")
        elif self.kind in {"text_input", "text_area", "code_editor"}:
            if not isinstance(value, str):
                raise UIError("Expected text.")
            limit = self.props.get("max_chars")
            if limit is not None and len(value) > limit:
                raise UIError("The text exceeds the control's limit.")
        elif self.kind in {"number_input", "slider"}:
            values = value if isinstance(value, list) else [value]
            if any(not isinstance(item, (int, float)) or isinstance(item, bool) or not math.isfinite(item) for item in values):
                raise UIError("Expected a number.")
            lower, upper = self.props.get("min_value"), self.props.get("max_value")
            if any((lower is not None and item < lower) or (upper is not None and item > upper) for item in values):
                raise UIError("The number is outside the control's range.")
            if self.props.get("integer") and any(not float(item).is_integer() for item in values):
                raise UIError("Expected an integer.")
            if self.props.get("range"):
                if not isinstance(value, list) or len(value) != 2 or value[0] > value[1]:
                    raise UIError("Expected an ordered range.")
            elif isinstance(value, list):
                raise UIError("Expected one number.")
        return self.decoder(value) if self.decoder else value


_CURRENT: ContextVar[ViewSession | None] = ContextVar("agilab_python_view_session", default=None)


def current_session() -> ViewSession:
    session = _CURRENT.get()
    if session is None:
        raise UIError("Python UI commands require an active AGILAB view session.")
    return session


def session_exists() -> bool:
    return _CURRENT.get() is not None


@contextmanager
def use_session(session: ViewSession) -> Iterator[ViewSession]:
    token = _CURRENT.set(session)
    try:
        yield session
    finally:
        _CURRENT.reset(token)


class ViewSession:
    """Own one browser's state, routes, registered controls and render revisions."""

    def __init__(self, source: Path | Callable[[], Any], *, path: str = "/", query: Mapping[str, Any] | None = None, argv: list[str] | None = None):
        self.source = source
        self.argv = list(argv or [])
        self.session_id = secrets.token_urlsafe(32)
        self.csrf_token = secrets.token_urlsafe(32)
        self.state = SessionState()
        self.query = QueryParameters(query or {})
        self.path = path
        self.revision = 0
        self.lock = threading.RLock()
        self.snapshot_lock = threading.RLock()
        self.active_operations = 0
        self.config: dict[str, Any] = {}
        self.roots: dict[str, list[dict[str, Any]]] = {"main": [], "sidebar": []}
        self.stack: list[list[dict[str, Any]]] = [self.roots["main"]]
        self.form_stack: list[str] = []
        self.widgets: dict[str, Widget] = {}
        self.empty_selections: dict[str, bool] = {}
        self.routes: dict[str, Any] = {}
        self.component_state: dict[str, dict[str, Any]] = {}
        self.triggers: dict[str, Any] = {}
        self.assets: dict[str, tuple[bytes, str, str]] = {}
        self.last_error: str = ""
        self.last_traceback: str = ""
        self.last_nodes: dict[str, list[dict[str, Any]]] = self.roots
        self.active_dialog: tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any], str] | None = None
        self.auto_refresh: float | None = None
        self.display_values: dict[str, Any] = {}
        self.render_lock = _SCRIPT_LOCK

    def add_node(self, kind: str, props: Mapping[str, Any] | None = None, *, key: str | None = None) -> dict[str, Any]:
        parent = self.stack[-1]
        identity = f"{kind}:{key}" if key is not None else f"{kind}:{_node_path(self.roots, parent)}:{len(parent)}"
        node_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        node = {"id": node_id, "kind": kind, "props": json_value(dict(props or {})), "children": []}
        with self.snapshot_lock: parent.append(node)
        return node

    def add_asset(self, data: bytes, mime: str, filename: str = "") -> str:
        digest = hashlib.sha256(data).hexdigest()
        self.assets[digest] = (data, mime, filename)
        return f"/api/assets/{digest}"

    def set_location(self, path: str, query: Mapping[str, Any]) -> None:
        if not path.startswith("/") or path.startswith("//"):
            raise UIError("Invalid application route.")
        with self.snapshot_lock:
            self.path = path
            self.query.from_dict(query)

    def _execute(self) -> None:
        if callable(self.source):
            self.source()
        else:
            previous = sys.argv
            try:
                sys.argv = [str(Path(self.source).resolve()), *self.argv]
                runpy.run_path(sys.argv[0], run_name="__main__")
            finally:
                sys.argv = previous

    def render(self) -> dict[str, Any]:
        with self.lock, self.render_lock, use_session(self), self.activity():
            self.last_error = ""
            self.last_traceback = ""
            for _ in range(20):
                with self.snapshot_lock: self.roots = {"main": [], "sidebar": []}
                self.stack = [self.roots["main"]]
                self.form_stack = []
                self.widgets = {}
                self.display_values = {}
                self.auto_refresh = None
                try:
                    self._execute()
                    if self.active_dialog:
                        function, args, kwargs, title = self.active_dialog
                        node = self.add_node("dialog", {"title": title})
                        self.stack.append(node["children"])
                        try:
                            function(*args, **kwargs)
                        finally:
                            self.stack.pop()
                except RerunView:
                    self.triggers.clear()
                    continue
                except StopRender:
                    pass
                except Exception as exc:
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    self.last_traceback = traceback.format_exc()
                    self.add_node("exception", {"message": self.last_error})
                break
            else:
                self.last_error = "The view exceeded its rerun limit."
                self.add_node("exception", {"message": self.last_error})
            self.triggers.clear()
            self.last_nodes = self.roots
            self.revision += 1
            return self.payload()

    def payload(self) -> dict[str, Any]:
        return {
            "revision": self.revision, "csrf_token": self.csrf_token,
            "path": self.path, "query": json_value(dict(self.query)),
            "config": json_value(dict(self.config)), "nodes": self.last_nodes,
            "error": self.last_error,
            "auto_refresh": self.auto_refresh,
        }

    @contextmanager
    def activity(self):
        with self.snapshot_lock: self.active_operations += 1
        try: yield
        finally:
            with self.snapshot_lock: self.active_operations -= 1

    def snapshot(self):
        """Read progress while Python owns the execution lock; never run the view."""
        with self.snapshot_lock:
            payload = self.payload()
            payload["nodes"] = copy.deepcopy(self.roots if self.active_operations else self.last_nodes)
            payload["running"] = bool(self.active_operations)
            return payload

    def commit_widget_value(self, widget: Widget, value: Any, wire_value: Any) -> None:
        self.state[widget.key] = value
        if widget.kind in {"selectbox", "radio", "select_slider", "pills", "segmented_control"}:
            self.empty_selections[widget.key] = wire_value is None

    def dispatch(self, action: Mapping[str, Any]) -> dict[str, Any]:
        with self.lock, self.render_lock, use_session(self), self.activity():
            if type(action.get("revision")) is not int or action["revision"] != self.revision:
                raise UIError("This action belongs to an older view. Refresh the controls.")
            node_id = action.get("id")
            if not isinstance(node_id, str):
                raise UIError("Invalid control identifier.")
            widget = self.widgets.get(node_id)
            if widget is None:
                raise UIError("This control is no longer registered.")
            field_name = action.get("field")
            if widget.kind == "component":
                if not isinstance(field_name, str) or field_name not in widget.component_callbacks:
                    raise UIError("Unknown component event.")
                value = action.get("value")
                if action.get("trigger") is True:
                    self.triggers[widget.id] = {field_name: value}
                else:
                    self.component_state.setdefault(widget.id, {})[field_name] = value
                callback = widget.component_callbacks[field_name]
            else:
                if widget.form and widget.kind != "form_submit_button":
                    raise UIError("Form controls must be submitted together.")
                values = action.get("form_values", {})
                prepared: list[tuple[Widget, Any, Any]] = []
                if values:
                    if widget.kind != "form_submit_button" or not isinstance(values, dict):
                        raise UIError("Only a form submission can update form values.")
                    for node_id, value in values.items():
                        candidate = self.widgets.get(node_id)
                        if candidate is None or candidate.form != widget.form or candidate.kind == "form_submit_button":
                            raise UIError("The form contains an unrelated control.")
                        prepared.append((candidate, candidate.validate(value), value))
                value = widget.validate(action.get("value"))
                for candidate, item, wire_value in prepared:
                    self.commit_widget_value(candidate, item, wire_value)
                if widget.kind in {"button", "form_submit_button"}:
                    self.triggers[widget.id] = value
                else:
                    self.commit_widget_value(widget, value, action.get("value"))
                callback = widget.callback
            try:
                if callback:
                    callback(*widget.args, **widget.kwargs)
            except (RerunView, StopRender):
                pass
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                self.last_traceback = traceback.format_exc()
                self.add_node("exception", {"message": self.last_error})
                self.triggers.clear()
                self.last_nodes = self.roots
                self.revision += 1
                return self.payload()
            return self.render()


_SCRIPT_LOCK = threading.RLock()


def _node_path(roots: Mapping[str, list[dict[str, Any]]], target: list[dict[str, Any]]) -> str:
    def walk(nodes: list[dict[str, Any]], prefix: str) -> str | None:
        if nodes is target:
            return prefix
        for index, node in enumerate(nodes):
            found = walk(node["children"], f"{prefix}/{index}")
            if found is not None:
                return found
        return None
    for name, nodes in roots.items():
        found = walk(nodes, name)
        if found is not None:
            return found
    raise UIError("The UI container is no longer active.")


def script_run_context() -> SimpleNamespace | None:
    if not session_exists():
        return None
    session = current_session()
    return SimpleNamespace(session_id=session.session_id, query_string="", session_state=session.state,
                           pages_manager=SimpleNamespace(current_page_script_hash=session.path))
