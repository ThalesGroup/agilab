"""Reusable Streamlit UI helpers for AGILAB workflow pages."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import Any, Iterable

MAX_INLINE_DOWNLOAD_BYTES = 5 * 1024 * 1024


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _call_container_method(container: Any, name: str, *args: Any, **kwargs: Any) -> Any:
    method = getattr(container, name, None)
    if callable(method):
        return method(*args, **kwargs)
    return None


def render_page_context(streamlit: Any, *, page_label: str, env: Any | None = None) -> None:
    """Render a compact persistent context rail in the sidebar."""
    sidebar = getattr(streamlit, "sidebar", streamlit)
    expander_factory = getattr(sidebar, "expander", None)
    context_manager = (
        expander_factory("Context", expanded=False)
        if callable(expander_factory)
        else nullcontext(sidebar)
    )
    with context_manager as context:
        _call_container_method(context, "caption", f"Page: {page_label}")
        app_name = _as_text(getattr(env, "app", ""))
        target_name = _as_text(getattr(env, "target", ""))
        mode = _as_text(getattr(env, "mode", ""))
        if app_name:
            _call_container_method(context, "caption", f"Project: {app_name}")
        if target_name and target_name != app_name:
            _call_container_method(context, "caption", f"Target: {target_name}")
        if mode:
            _call_container_method(context, "caption", f"Mode: {mode}")


def _download_log_button(
    container: Any,
    *,
    body: str,
    key: str,
    file_name: str,
) -> None:
    download_button = getattr(container, "download_button", None)
    if not callable(download_button):
        return
    download_button(
        "Download logs",
        data=body,
        file_name=file_name,
        mime="text/plain",
        key=key,
        disabled=not bool(body.strip()),
        width="stretch",
    )


def render_log_actions(
    streamlit: Any,
    *,
    body: str,
    download_key: str,
    file_name: str,
    clear_key: str | None = None,
    clear_label: str = "Clear logs",
) -> bool:
    """Render standard log actions and return whether clear was requested."""
    text = str(body or "")
    if clear_key:
        download_col, clear_col = streamlit.columns([1, 1])
        _download_log_button(download_col, body=text, key=download_key, file_name=file_name)
        return bool(
            clear_col.button(
                clear_label,
                key=clear_key,
                type="secondary",
                disabled=not bool(text.strip()),
                help="Clear the current log panel.",
                width="stretch",
            )
        )
    _download_log_button(streamlit, body=text, key=download_key, file_name=file_name)
    return False


def render_action_readiness(
    streamlit: Any,
    *,
    actions: Iterable[tuple[str, bool, str]],
    title: str = "Action status",
) -> None:
    """Show enabled/blocked action state in a consistent compact expander."""
    entries = [(label, enabled, _as_text(reason)) for label, enabled, reason in actions]
    if not entries:
        return
    expander = streamlit.expander(title, expanded=False)
    with expander:
        for label, enabled, reason in entries:
            status = "Ready" if enabled else reason or "Unavailable"
            _call_container_method(expander, "caption", f"{label}: {status}")


def _path_from(value: Any) -> Path | None:
    try:
        return Path(value) if value else None
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _dataframe_shape(dataframe: Any) -> tuple[int, int] | None:
    if getattr(dataframe, "empty", True):
        return None
    shape = getattr(dataframe, "shape", None)
    if not isinstance(shape, tuple) or len(shape) < 2:
        return None
    try:
        return int(shape[0]), int(shape[1])
    except (TypeError, ValueError):
        return None


def _graph_shape(graph: Any) -> tuple[int, int] | None:
    number_of_nodes = getattr(graph, "number_of_nodes", None)
    number_of_edges = getattr(graph, "number_of_edges", None)
    if not callable(number_of_nodes) or not callable(number_of_edges):
        return None
    try:
        return int(number_of_nodes()), int(number_of_edges())
    except (TypeError, ValueError):
        return None


def _render_output_download(streamlit: Any, *, path: Path, key: str) -> None:
    download_button = getattr(streamlit, "download_button", None)
    if not callable(download_button) or not path.is_file():
        return
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size > MAX_INLINE_DOWNLOAD_BYTES:
        streamlit.caption(f"Output file is too large for inline download: {path.name}")
        return
    try:
        data = path.read_bytes()
    except OSError:
        return
    download_button(
        "Download output",
        data=data,
        file_name=path.name,
        key=key,
        width="stretch",
    )


def render_latest_outputs(
    streamlit: Any,
    *,
    source_path: Any = None,
    dataframe: Any = None,
    graph: Any = None,
    key_prefix: str,
) -> None:
    """Render a compact latest-output summary with an optional direct download."""
    df_shape = _dataframe_shape(dataframe)
    graph_shape = _graph_shape(graph)
    path = _path_from(source_path)
    if df_shape is None and graph_shape is None and path is None:
        return

    expander = streamlit.expander("Latest outputs", expanded=False)
    with expander:
        if df_shape is not None:
            rows, columns = df_shape
            _call_container_method(expander, "caption", f"Dataframe: {rows} row(s), {columns} column(s)")
        if graph_shape is not None:
            nodes, edges = graph_shape
            _call_container_method(expander, "caption", f"Graph: {nodes} node(s), {edges} edge(s)")
        if path is not None:
            _call_container_method(expander, "caption", f"Source: {path}")
            _render_output_download(expander, path=path, key=f"{key_prefix}:download_output")
