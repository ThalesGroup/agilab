"""Python controls and views served by AGILAB's React host.

The view produces a declarative tree. Browser events are validated against the
controls from that session's last render before callbacks or Python code run.
"""

from __future__ import annotations

import base64
from collections import OrderedDict
from collections.abc import MutableMapping
from contextlib import contextmanager
import copy
import datetime as dt
from functools import wraps
import hashlib
import io
from importlib.resources import files
from functools import lru_cache
import json as json_module
import marshal
import mimetypes
import pickle
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from .python_view_session import (
    QueryParameters, RerunView, SessionState, StopRender, UIError, ViewSession,
    Widget, current_session, json_value, script_run_context, session_exists,
)


class _SessionMapping(MutableMapping):
    def __init__(self, attribute: str):
        object.__setattr__(self, "attribute", attribute)

    def _values(self):
        return getattr(current_session(), self.attribute)

    def __getitem__(self, key):
        return self._values()[key]

    def __setitem__(self, key, value):
        self._values()[key] = value

    def __delitem__(self, key):
        del self._values()[key]

    def __iter__(self):
        return iter(self._values())

    def __len__(self):
        return len(self._values())

    def __getattr__(self, name):
        values = self._values()
        if hasattr(type(values), name):
            return getattr(values, name)
        try:
            return values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self._values()[name] = value


session_state = _SessionMapping("state")
query_params = _SessionMapping("query")


class Container:
    def __init__(self, node: dict[str, Any] | None = None, *, sidebar: bool = False, placeholder=False):
        self.node = node
        self.is_sidebar = sidebar
        self.placeholder = placeholder

    def __enter__(self):
        session = current_session()
        session.stack.append(session.roots["sidebar"] if self.is_sidebar else self.node["children"])
        if self.node and self.node["kind"] == "form":
            session.form_stack.append(self.node["id"])
        return self

    def __exit__(self, *_):
        session = current_session()
        session.stack.pop()
        if self.node and self.node["kind"] == "form":
            session.form_stack.pop()

    def __getattr__(self, name):
        function = globals().get(name)
        if not callable(function) or name.startswith("_"):
            raise AttributeError(name)
        def call(*args, **kwargs):
            if self.node and name == "progress" and self.node["kind"] == "progress":
                amount = args[0] if args else kwargs["value"]
                return self.update(value=amount / 100 if isinstance(amount, int) else amount, text=kwargs.get("text"))
            if self.placeholder:
                with current_session().snapshot_lock: self.node["children"].clear()
            with self:
                return function(*args, **kwargs)
        return call

    def empty(self):
        if self.node:
            with current_session().snapshot_lock: self.node["children"].clear()
        return self

    def update(self, **kwargs):
        if self.node:
            with current_session().snapshot_lock: self.node["props"].update(json_value(kwargs))
        return self


sidebar = Container(sidebar=True)


def _node(kind, **props):
    return current_session().add_node(kind, props)


def container(*, key=None, **kwargs):
    return Container(current_session().add_node("container", kwargs, key=key))


def empty():
    return Container(_node("container"), placeholder=True)


def columns(spec, *, gap="small", **kwargs):
    weights = [1] * spec if isinstance(spec, int) else list(spec)
    if not weights or any(value <= 0 for value in weights):
        raise UIError("Column widths must be positive.")
    group = _node("columns", weights=weights, gap=gap, **kwargs)
    with Container(group):
        return [container() for _ in weights]


def tabs(labels, **kwargs):
    group = _node("tabs", labels=list(labels), **kwargs)
    with Container(group):
        return [Container(_node("tab", label=str(label))) for label in labels]


def expander(label, expanded=False, **kwargs):
    return Container(_node("expander", label=str(label), expanded=expanded, **kwargs))


def form(key, *, clear_on_submit=False, **kwargs):
    if current_session().form_stack:
        raise UIError("Forms cannot be nested.")
    return Container(current_session().add_node("form", {"clear_on_submit": clear_on_submit, **kwargs}, key=str(key)))


def _text(kind, body="", **kwargs):
    return Container(_node(kind, body=str(body), **kwargs))


def title(body, **kwargs): return _text("title", body, **kwargs)
def header(body, **kwargs): return _text("header", body, **kwargs)
def subheader(body, **kwargs): return _text("subheader", body, **kwargs)
def caption(body, **kwargs): return _text("caption", body, **kwargs)
def text(body, **kwargs): return _text("text", body, **kwargs)
def markdown(body, *, unsafe_allow_html=False, **kwargs): return _text("html" if unsafe_allow_html else "markdown", body, markdown=True, **kwargs)
def html(body, **kwargs): return _text("html", body, **kwargs)
def code(body, language="python", **kwargs): return _text("code", body, language=language, **kwargs)
def latex(body, **kwargs): return _text("latex", body, **kwargs)
def info(body, **kwargs): return _text("info", body, **kwargs)
def warning(body, **kwargs): return _text("warning", body, **kwargs)
def error(body, **kwargs): return _text("error", body, **kwargs)
def success(body, **kwargs): return _text("success", body, **kwargs)
def exception(value, **kwargs): return _text("exception", f"{type(value).__name__}: {value}", **kwargs)
def divider(): return _node("divider")
def json(body, **kwargs): return _text("json", json_module.dumps(json_value(body), ensure_ascii=False, indent=2) if not isinstance(body, str) else body, **kwargs)
def metric(label, value, delta=None, **kwargs): return _node("metric", label=str(label), value=str(value), delta=None if delta is None else str(delta), **kwargs)
def help(obj): return code(getattr(obj, "__doc__", str(obj)), language="text")


def write(*values, **kwargs):
    for value in values:
        if hasattr(value, "columns") and hasattr(value, "to_dict"):
            dataframe(value)
        elif isinstance(value, (dict, list, tuple)):
            json(value)
        else:
            markdown(value, **kwargs)


def _widget(kind, label, value, *, key=None, on_change=None, on_click=None,
            args=None, kwargs=None, encoder=None, decoder=None, normalize=None, empty_selection=None, **props):
    session = current_session()
    node = session.add_node(kind, {"label": str(label), **props}, key=str(key) if key is not None else None)
    state_key = str(key) if key is not None else node["id"]
    if any(widget.key == state_key for widget in session.widgets.values()):
        raise UIError(f"Control key {state_key!r} is already in use.")
    button_kind = kind in {"button", "form_submit_button"}
    if not button_kind:
        session.state.setdefault(state_key, value)
        if normalize is not None:
            session.state[state_key] = normalize(session.state[state_key])
        value = session.state[state_key]
    else:
        value = bool(session.triggers.get(node["id"], False))
    wire_value = encoder(value) if encoder else value
    if empty_selection is not None:
        session.empty_selections.setdefault(state_key, bool(empty_selection))
        if value is not None or not props.get("allow_none"):
            session.empty_selections[state_key] = False
        if value is None and session.empty_selections[state_key]: wire_value = None
    with session.snapshot_lock:
        node["props"]["value"] = json_value(wire_value)
        node["props"]["key"] = str(key) if key is not None else None
        node["props"]["form"] = session.form_stack[-1] if session.form_stack else None
    session.widgets[node["id"]] = Widget(
        node["id"], kind, state_key, node["props"], on_click or on_change,
        tuple(args or ()), dict(kwargs or {}), node["props"]["form"], decoder=decoder, encoder=encoder,
    )
    return value


def button(label, **kwargs): return _widget("button", label, False, **kwargs)
def form_submit_button(label="Submit", **kwargs):
    if not current_session().form_stack:
        raise UIError("A submit button must belong to a form.")
    return _widget("form_submit_button", label, False, **kwargs)
def checkbox(label, value=False, **kwargs): return _widget("checkbox", label, bool(value), **kwargs)
def toggle(label, value=False, **kwargs): return _widget("toggle", label, bool(value), **kwargs)
def text_input(label, value="", **kwargs): return _widget("text_input", label, str(value), **kwargs)
def text_area(label, value="", height=None, **kwargs): return _widget("text_area", label, str(value), height=height, **kwargs)


def _selection(kind, label, options, index=0, *, default=None, format_func=str, multiple=False, **kwargs):
    options = list(options)
    def encode(value):
        if multiple:
            return [options.index(item) for item in value if item in options]
        return options.index(value) if value in options else None
    def decode(value):
        return [options[item] for item in value] if multiple else options[value]
    value = list(default or []) if multiple else (default if default is not None else options[index] if index is not None and options else None)
    def normalize(previous):
        if multiple:
            return [item for item in previous if item in options]
        return previous if previous in options or previous is None and (index is None or not options) else value
    return _widget(kind, label, value, options=list(range(len(options))),
                   option_labels=[str(format_func(item)) for item in options], allow_none=index is None or not options,
                   encoder=encode, decoder=decode, normalize=normalize,
                   empty_selection=index is None if not multiple else None, **kwargs)


def selectbox(label, options, index=0, **kwargs): return _selection("selectbox", label, options, index, **kwargs)
def radio(label, options, index=0, **kwargs): return _selection("radio", label, options, index, **kwargs)
def multiselect(label, options, default=None, **kwargs): return _selection("multiselect", label, options, default=default, multiple=True, **kwargs)
def pills(label, options, *, selection_mode="single", default=None, **kwargs):
    return _selection("pills", label, options,
                      None if default is None else 0, default=default, multiple=selection_mode == "multi", selection_mode=selection_mode, **kwargs)
def segmented_control(label, options, *, default=None, selection_mode="single", **kwargs):
    return _selection("segmented_control", label, options,
                      None if default is None else 0, default=default, multiple=selection_mode == "multi", selection_mode=selection_mode, **kwargs)
def select_slider(label, options, value=None, **kwargs):
    if isinstance(value, (tuple, list)):
        raise UIError("Use slider for a numeric range or multiselect for multiple choices.")
    return _selection("select_slider", label, options, default=value, **kwargs)


def number_input(label, min_value=None, max_value=None, value="min", step=None, **kwargs):
    if value == "min":
        value = min_value if min_value is not None else (0.0 if isinstance(step, float) else 0)
    integer = isinstance(value, int) and not isinstance(value, bool)
    return _widget("number_input", label, value, min_value=min_value, max_value=max_value,
                   step=step or (1 if integer else 0.01), integer=integer,
                   decoder=int if integer else float, **kwargs)


def slider(label, min_value=None, max_value=None, value=None, step=None, **kwargs):
    value = value if value is not None else min_value if min_value is not None else 0
    is_range = isinstance(value, (tuple, list))
    sample = value[0] if is_range else value
    integer = isinstance(sample, int)
    return _widget("slider", label, value, min_value=0 if min_value is None else min_value,
                   max_value=100 if max_value is None else max_value, range=is_range, integer=integer,
                   step=step or (1 if integer else 0.01), decoder=(lambda values: tuple(values)) if is_range else int if integer else float, **kwargs)


def date_input(label, value="today", min_value=None, max_value=None, **kwargs):
    if value == "today": value = dt.date.today()
    if isinstance(value, dt.datetime): value = value.date()
    multiple = isinstance(value, (tuple, list))
    def decode(raw):
        try:
            values = [dt.date.fromisoformat(item) for item in raw] if multiple else [dt.date.fromisoformat(raw)]
        except (ValueError, TypeError) as exc:
            raise UIError("Expected a date.") from exc
        if (multiple and len(values) not in {1, 2}) or any((min_value and item < min_value) or (max_value and item > max_value) for item in values):
            raise UIError("The date is outside the control's range.")
        return tuple(values) if multiple else values[0]
    return _widget("date_input", label, value, range=multiple, min_value=min_value, max_value=max_value, decoder=decode, **kwargs)


class UploadedFile(io.BytesIO):
    def __init__(self, data: bytes, name: str, mime: str):
        super().__init__(data)
        self.name, self.type, self.size = name, mime, len(data)


def file_uploader(label, type=None, accept_multiple_files=False, **kwargs):
    extensions = [type] if isinstance(type, str) else list(type or [])
    multiple = bool(accept_multiple_files)
    def decode(raw):
        if not isinstance(raw, list) or (not multiple and len(raw) > 1):
            raise UIError("Invalid upload list.")
        files = []
        for item in raw:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not isinstance(item.get("data"), str):
                raise UIError("Invalid uploaded file.")
            name = Path(item["name"].replace("\\", "/")).name
            if extensions and Path(name).suffix.lower().lstrip(".") not in [ext.lower().lstrip(".") for ext in extensions]:
                raise UIError("Unsupported uploaded file type.")
            try: data = base64.b64decode(item["data"], validate=True)
            except ValueError as exc: raise UIError("Invalid uploaded data.") from exc
            if len(data) > 32 * 1024 * 1024: raise UIError("The uploaded file is too large.")
            files.append(UploadedFile(data, name, str(item.get("type", "application/octet-stream"))))
        return files if multiple else files[0] if files else None
    return _widget("file_uploader", label, [] if multiple else None, extensions=extensions,
                   multiple=multiple, decoder=decode, encoder=lambda _: [], **kwargs)


def _table_data(data):
    if hasattr(data, "reset_index") and hasattr(data, "to_dict"):
        return {"columns": [str(column) for column in data.columns], "rows": json_value(data.to_numpy().tolist())}
    if isinstance(data, Mapping):
        columns = list(data)
        values = [list(data[column]) if isinstance(data[column], (list, tuple)) or hasattr(data[column], "tolist") else [data[column]] for column in columns]
        return {"columns": [str(column) for column in columns], "rows": json_value(list(zip(*values)))}
    values = list(data) if data is not None else []
    if values and isinstance(values[0], Mapping):
        columns = list(values[0])
        return {"columns": list(map(str, columns)), "rows": json_value([[row.get(column) for column in columns] for row in values])}
    return {"columns": ["Value"], "rows": [[json_value(value)] for value in values]}


def dataframe(data=None, *, on_select="ignore", selection_mode="multi-row", key=None, **kwargs):
    payload = _table_data(data)
    if on_select == "ignore":
        node = _node("dataframe", **payload, **kwargs)
        current_session().display_values[node["id"]] = data
        return Container(node)
    def decode(raw):
        if not isinstance(raw, dict) or not isinstance(raw.get("rows"), list) or any(type(index) is not int or index < 0 or index >= len(payload["rows"]) for index in raw["rows"]):
            raise UIError("Invalid table selection.")
        if selection_mode == "single-row" and len(raw["rows"]) > 1: raise UIError("Choose one row.")
        return SessionState(selection=SessionState(rows=raw["rows"], columns=[]))
    default = SessionState(selection=SessionState(rows=[], columns=[]))
    return _widget("dataframe", "", default, key=key, on_change=on_select if callable(on_select) else None,
                   selection_mode=selection_mode, decoder=decode, encoder=lambda value: value.selection,
                   **payload, **kwargs)


def table(data=None, **kwargs): return dataframe(data, **kwargs)


def image(data, caption=None, **kwargs):
    items = list(data) if isinstance(data, (list, tuple)) else [data]
    urls = []
    for item in items:
        if isinstance(item, str) and urlsplit(item).scheme in {"http", "https", "data"}: urls.append(item)
        else:
            mime = "image/png"
            if hasattr(item, "save"):
                buffer = io.BytesIO(); item.save(buffer, format="PNG"); content = buffer.getvalue()
            elif isinstance(item, str) and item.lstrip().startswith(("<svg", "<?xml")) and "<svg" in item:
                content = item.encode()
            elif isinstance(item, (str, Path)):
                content = Path(item).read_bytes()
                guessed = mimetypes.guess_type(str(item))[0]
                if guessed and guessed.startswith("image/"): mime = guessed
            elif isinstance(item, bytes): content = item
            elif hasattr(item, "read"): content = item.read()
            else:
                from PIL import Image
                buffer = io.BytesIO(); Image.fromarray(item).save(buffer, format="PNG"); content = buffer.getvalue()
            if isinstance(content, str): content = content.encode()
            stripped = content.lstrip()
            if stripped.startswith((b"<svg", b"<?xml")) and b"<svg" in stripped: mime = "image/svg+xml"
            elif content.startswith(b"\xff\xd8\xff"): mime = "image/jpeg"
            elif content.startswith((b"GIF87a", b"GIF89a")): mime = "image/gif"
            elif content.startswith(b"RIFF") and content[8:12] == b"WEBP": mime = "image/webp"
            urls.append(current_session().add_asset(content, mime))
    return _node("image", urls=urls, caption=caption, **kwargs)


def download_button(label, data, file_name=None, mime=None, **kwargs):
    content = data.read() if hasattr(data, "read") else data.encode() if isinstance(data, str) else bytes(data)
    url = current_session().add_asset(content, mime or "application/octet-stream", file_name or "download")
    _node("download_button", label=str(label), url=url, filename=file_name or "download", **kwargs)
    return False


def link_button(label, url, **kwargs): return _node("link_button", label=str(label), url=str(url), **kwargs)
def iframe(src, height=400, **kwargs): return _node("iframe", src=str(src), height=height, **kwargs)


def plotly_chart(figure_or_data, **kwargs):
    import plotly.io as pio
    from plotly.offline import get_plotlyjs
    library = current_session().add_asset(get_plotlyjs().encode(), "text/javascript")
    return _node("plotly_chart", figure=json_module.loads(pio.to_json(figure_or_data)), library=library, **kwargs)


def pyplot(fig=None, **kwargs):
    import matplotlib.pyplot as plt
    fig = fig if fig is not None else plt.gcf()
    buffer = io.BytesIO(); fig.savefig(buffer, format="png", bbox_inches="tight")
    return image(buffer.getvalue(), **kwargs)


def altair_chart(chart, **kwargs):
    specification = chart.to_dict() if hasattr(chart, "to_dict") else dict(chart)
    library = current_session().add_asset(_vega_asset(), "text/javascript")
    return _node("altair_chart", spec=specification, library=library, **kwargs)


@lru_cache(maxsize=1)
def _vega_asset():
    return files("agi_web").joinpath("react_python_host_assets", "agilab_react_vega.js").read_bytes()


def pydeck_chart(chart, **kwargs):
    return _node("html_frame", body=chart.to_html(as_string=True), **kwargs)


def graphviz_chart(figure_or_dot, **kwargs):
    source = figure_or_dot.source if hasattr(figure_or_dot, "source") else str(figure_or_dot)
    library = current_session().add_asset(_graphviz_asset(), "text/javascript")
    return _node("graphviz_chart", source=source, library=library, **kwargs)


@lru_cache(maxsize=1)
def _graphviz_asset():
    return files("agi_web").joinpath("react_python_host_assets", "agilab_react_graphviz.js").read_bytes()


def _simple_chart(kind, data, x=None, y=None, **kwargs):
    import plotly.express as px
    function = px.bar if kind == "bar" else px.line
    return plotly_chart(function(data, x=x, y=y), **kwargs)


def line_chart(data=None, x=None, y=None, **kwargs): return _simple_chart("line", data, x, y, **kwargs)
def bar_chart(data=None, x=None, y=None, **kwargs): return _simple_chart("bar", data, x, y, **kwargs)


def progress(value, text=None, **kwargs):
    amount = value / 100 if isinstance(value, int) else value
    return Container(_node("progress", value=amount, text=text, **kwargs))


def status(label, *, state="running", expanded=False, **kwargs):
    return Container(_node("status", label=str(label), state=state, expanded=expanded, **kwargs))


@contextmanager
def spinner(text="In progress...", **kwargs):
    with Container(_node("status", label=str(text), state="running", **kwargs)) as value:
        yield value
    value.update(state="complete")


def set_page_config(**kwargs): current_session().config.update(kwargs)
def stop(): raise StopRender()
def rerun(*, scope="app"):
    if scope == "app": current_session().active_dialog = None
    raise RerunView()


class Page:
    def __init__(self, page, *, title=None, icon=None, url_path=None, default=False, visibility="visible"):
        self.page, self.default, self.icon = page, default, icon
        self.visibility = visibility
        self.script_path = Path(page).resolve() if isinstance(page, (str, Path)) else getattr(page, "__agilab_view_path__", None)
        self.title = title or (Path(page).stem if isinstance(page, (str, Path)) else getattr(page, "__name__", "View"))
        self.url_path = str(url_path).strip("/") if url_path is not None else ("" if default else self.title.replace(" ", "_"))
        self._script_hash = hashlib.sha256(self.url_path.encode()).hexdigest()

    def run(self):
        if callable(self.page): self.page()
        else: __import__("runpy").run_path(str(Path(self.page).resolve()), run_name="__main__")


def navigation(pages, *, position="sidebar", **kwargs):
    entries = [(group, page) for group, values in pages.items() for page in values] if isinstance(pages, dict) else [(None, page) for page in pages]
    if not entries: raise UIError("No application pages are registered.")
    session = current_session()
    session.routes = {"/" + page.url_path: page for _, page in entries}
    fallback = next((page for _, page in entries if page.default), entries[0][1])
    selected = session.routes.get(session.path, fallback)
    if position != "hidden":
        destination = sidebar if position == "sidebar" else container()
        with destination:
            for group, page in entries:
                if page.visibility != "hidden": page_link(page, label=page.title, icon=page.icon)
    return selected


def switch_page(page, *, query_params=None):
    session = current_session()
    if isinstance(page, Page):
        target = next((path for path, item in session.routes.items() if item is page), None)
    else:
        base = Path(session.source).resolve().parent if isinstance(session.source, (str, Path)) else Path.cwd()
        candidates = {Path(page).resolve(), (base / page).resolve()}
        target = next((path for path, item in session.routes.items() if item.script_path in candidates), None)
    if target is None: raise UIError("The requested page is not registered.")
    if query_params is not None:
        if not isinstance(query_params, Mapping): raise UIError("Invalid route query parameters.")
        session.query.from_dict(query_params)
    session.path = target
    raise RerunView()


def page_link(page, *, label=None, icon=None, **kwargs):
    if isinstance(page, Page): url = "/" + page.url_path
    elif isinstance(page, str) and urlsplit(page).scheme in {"http", "https"}: url = page
    else:
        session = current_session()
        url = next((path for path, item in session.routes.items() if isinstance(item.page, (str, Path)) and Path(item.page).resolve() == Path(page).resolve()), None)
        if url is None: raise UIError("The requested page is not registered.")
    return _node("page_link", label=label or getattr(page, "title", str(page)), url=url, icon=icon, **kwargs)


def dialog(title, **options):
    def decorate(function):
        @wraps(function)
        def open_dialog(*args, **kwargs):
            current_session().active_dialog = (function, args, kwargs, str(title))
        return open_dialog
    return decorate


def fragment(function=None, *, run_every=None):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if run_every is not None and session_exists():
                seconds = run_every.total_seconds() if isinstance(run_every, dt.timedelta) else float(str(run_every).removesuffix("s"))
                session = current_session()
                session.auto_refresh = min(session.auto_refresh or seconds, seconds)
            return fn(*args, **kwargs)
        return wrapped
    return decorate(function) if function else decorate


class _Cache:
    def __init__(self, resource=False):
        self.resource = resource
        self.entries = OrderedDict()
        self.registry_lock = threading.RLock()

    def _identity(self, function, ttl, max_entries):
        code = getattr(function, "__code__", None)
        code_hash = hashlib.sha256(marshal.dumps(code)).digest() if code else id(function)
        def scope(value):
            if isinstance(value, (str, bytes, int, float, bool, type(None), Path)):
                return (type(value).__name__, str(value) if isinstance(value, Path) else value)
            if isinstance(value, tuple): return tuple(scope(item) for item in value)
            return (type(value).__name__, id(value))
        captures = []
        for cell in getattr(function, "__closure__", None) or ():
            try: captures.append(scope(cell.cell_contents))
            except ValueError: captures.append(("empty", id(cell)))
        return (getattr(function, "__module__", ""), getattr(function, "__qualname__", ""),
                code_hash, tuple(captures), ttl, max_entries)

    def __call__(self, function=None, *, ttl=None, max_entries=None, **options):
        def decorate(fn):
            seconds = ttl.total_seconds() if isinstance(ttl, dt.timedelta) else ttl
            identity = self._identity(fn, seconds, max_entries)
            with self.registry_lock:
                if identity not in self.entries:
                    self.entries[identity] = ({}, threading.RLock())
                    if len(self.entries) > 256: self.entries.popitem(last=False)
                self.entries.move_to_end(identity)
                values, lock = self.entries[identity]
            def argument_key(args, kwargs):
                import inspect
                bound = inspect.signature(fn).bind(*args, **kwargs); bound.apply_defaults()
                relevant = {name: value for name, value in bound.arguments.items() if not name.startswith("_")}
                try: return hashlib.sha256(pickle.dumps(relevant, protocol=5)).digest()
                except (TypeError, pickle.PicklingError): return None
            @wraps(fn)
            def wrapped(*args, **kwargs):
                key = argument_key(args, kwargs)
                if key is None: return fn(*args, **kwargs)
                with lock:
                    if key not in values or (seconds is not None and time.monotonic() - values[key][0] >= seconds):
                        result = fn(*args, **kwargs)
                        if max_entries and len(values) >= max_entries: values.pop(next(iter(values)))
                        values[key] = (time.monotonic(), result if self.resource else copy.deepcopy(result))
                    result = values[key][1]
                    return result if self.resource else copy.deepcopy(result)
            def clear(*args, **kwargs):
                key = argument_key(args, kwargs) if args or kwargs else None
                with lock:
                    if args or kwargs: values.pop(key, None)
                    else: values.clear()
            wrapped.clear = clear
            return wrapped
        return decorate(function) if function else decorate

    def clear(self):
        with self.registry_lock: entries = list(self.entries.values())
        for values, lock in entries:
            with lock: values.clear()


cache_data, cache_resource = _Cache(), _Cache(resource=True)


_COMPONENTS: dict[str, dict[str, Any]] = {}
_COMPONENT_MANAGER = object()


def _component(name, *, js, css="", isolate_styles=True, **options):
    definition = {"js": js, "css": css, "isolate_styles": isolate_styles}
    _COMPONENTS[name] = definition
    def mount(*, key=None, data=None, default=None, **kwargs):
        session = current_session()
        source = session.add_asset(js.encode(), "text/javascript")
        style = session.add_asset(css.encode(), "text/css")
        node = session.add_node("component", {"name": name, "js": source, "css": style,
                               "isolate_styles": isolate_styles, "data": data, **{k: v for k, v in kwargs.items() if not k.startswith("on_")}}, key=key or name)
        if node["id"] in session.widgets: raise UIError("This component key is already in use.")
        callbacks = {key[3:-7]: value for key, value in kwargs.items() if key.startswith("on_") and key.endswith("_change")}
        state = {**{field: None for field in callbacks}, **dict(default or {}), **session.component_state.get(node["id"], {}), **session.triggers.get(node["id"], {})}
        session.widgets[node["id"]] = Widget(node["id"], "component", key or name, node["props"], component_callbacks=callbacks)
        return SessionState(state)
    return mount


components = SimpleNamespace(v2=SimpleNamespace(component=_component), v1=SimpleNamespace(html=lambda body, **kwargs: _node("html_frame", body=body, **kwargs), iframe=iframe))
runtime = SimpleNamespace(exists=session_exists, get_instance=lambda: SimpleNamespace(bidi_component_registry=_COMPONENT_MANAGER))
def get_script_run_ctx(suppress_warning=False): return script_run_context()
RerunException = RerunView


class _Config:
    def get_option(self, name):
        import os
        if name in {"address", "server.address"}:
            if session_exists(): return current_session().config.get("server_address", "127.0.0.1")
            return (os.environ.get("AGILAB_UI_HOST", "").strip()
                    or os.environ.get("AGILAB_UI_ADDRESS", "").strip() or "127.0.0.1")
        return None


config = _Config()
get_option = config.get_option


class _ColumnConfig:
    def __getattr__(self, name):
        return lambda label=None, **kwargs: {"kind": name, "label": label, **kwargs}


column_config = _ColumnConfig()


class _Secrets(Mapping):
    def _load(self):
        import os, tomllib
        path = Path(os.environ.get("AGILAB_SECRETS_FILE", ".agilab/secrets.toml"))
        return tomllib.loads(path.read_text()) if path.is_file() else {}
    def __iter__(self): return iter(self._load())
    def __len__(self): return len(self._load())
    def __getitem__(self, key): return self._load()[key]
    def __getattr__(self, key):
        try: return self[key]
        except KeyError as exc: raise AttributeError(key) from exc


secrets = _Secrets()
