"""Small compatibility wrappers for recent Streamlit UX primitives."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Callable, Iterable


_TOAST_FALLBACKS = {
    "complete": "success",
    "success": "success",
    "error": "error",
    "warning": "warning",
    "info": "info",
    "running": "info",
}


def _session_state(streamlit: Any) -> Any:
    state = getattr(streamlit, "session_state", None)
    if callable(state):
        state = None
    streamlit_module = getattr(type(streamlit), "__module__", "")
    if state is None and streamlit_module.startswith("streamlit."):
        try:
            import streamlit as native_streamlit

            state = getattr(native_streamlit, "session_state", None)
        except Exception:
            state = None
    if state is None:
        state = {}
        try:
            setattr(streamlit, "session_state", state)
        except (AttributeError, TypeError):
            pass
    return state


def _state_get(state: Any, key: str, default: Any = None) -> Any:
    try:
        return state.get(key, default)
    except AttributeError:
        return getattr(state, key, default)


def _state_contains(state: Any, key: str) -> bool:
    try:
        return key in state
    except TypeError:
        return hasattr(state, key)


def _state_set(state: Any, key: str, value: Any) -> None:
    try:
        state[key] = value
    except TypeError:
        setattr(state, key, value)


def _state_pop(state: Any, key: str, default: Any = None) -> Any:
    try:
        return state.pop(key, default)
    except AttributeError:
        if hasattr(state, key):
            value = getattr(state, key)
            delattr(state, key)
            return value
        return default


def _call_message(streamlit: Any, state: str, message: str) -> None:
    method_name = _TOAST_FALLBACKS.get(state, "info")
    method = getattr(streamlit, method_name, None) or getattr(streamlit, "info", None)
    if callable(method):
        method(message)


@dataclass
class _FallbackStatus(AbstractContextManager):
    streamlit: Any
    label: str
    state: str = "running"

    def __post_init__(self) -> None:
        _call_message(self.streamlit, self.state, self.label)

    def __enter__(self) -> "_FallbackStatus":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    def update(
        self,
        *,
        label: str | None = None,
        state: str | None = None,
        expanded: bool | None = None,
    ) -> None:
        if label:
            _call_message(self.streamlit, state or self.state, label)
        if state:
            self.state = state


def status_container(
    streamlit: Any,
    label: str,
    *,
    state: str = "running",
    expanded: bool = True,
) -> AbstractContextManager:
    """Return a status context using ``st.status`` when available."""
    native_status = getattr(streamlit, "status", None)
    if callable(native_status):
        try:
            return native_status(label, state=state, expanded=expanded)
        except TypeError:
            return native_status(label)

    spinner = getattr(streamlit, "spinner", None)
    if state == "running" and callable(spinner):
        try:
            return spinner(label)
        except TypeError:
            pass
    return _FallbackStatus(streamlit, label, state)


def toast(
    streamlit: Any,
    message: str,
    *,
    icon: str | None = None,
    state: str = "info",
) -> None:
    """Show a toast when supported, otherwise fall back to a regular message."""
    native_toast = getattr(streamlit, "toast", None)
    if callable(native_toast):
        try:
            native_toast(message, icon=icon)
            return
        except TypeError:
            native_toast(message)
            return
    _call_message(streamlit, state, message)


def _option_index(options: list[Any], selected: Any, fallback: int) -> int:
    try:
        return options.index(selected)
    except ValueError:
        if 0 <= fallback < len(options):
            return fallback
        return 0


def compact_choice(
    streamlit: Any,
    label: str,
    options: Iterable[Any],
    *,
    key: str | None = None,
    default: Any = None,
    index: int = 0,
    format_func: Callable[[Any], str] = str,
    help: str | None = None,
    on_change: Callable[..., Any] | None = None,
    args: tuple[Any, ...] | None = None,
    kwargs: dict[str, Any] | None = None,
    label_visibility: str = "visible",
    width: str = "stretch",
    disabled: bool = False,
    inline_limit: int | None = 8,
    fallback: str = "selectbox",
) -> Any:
    """Render a compact single-choice control with backwards-compatible fallbacks."""
    option_list = list(options)
    if not option_list:
        return None

    selected_default = default if default in option_list else option_list[_option_index(option_list, default, index)]
    keyed_state_exists = key is not None and _state_contains(_session_state(streamlit), key)
    use_inline = inline_limit is None or len(option_list) <= inline_limit
    if use_inline:
        for method_name in ("segmented_control", "pills"):
            method = getattr(streamlit, method_name, None)
            if not callable(method):
                continue
            try:
                widget_kwargs = {
                    "key": key,
                    "format_func": format_func,
                    "help": help,
                    "on_change": on_change,
                    "args": args,
                    "kwargs": kwargs,
                    "label_visibility": label_visibility,
                    "width": width,
                    "disabled": disabled,
                }
                if not keyed_state_exists:
                    widget_kwargs["default"] = selected_default
                result = method(label, option_list, **widget_kwargs)
                return selected_default if result is None else result
            except TypeError:
                try:
                    widget_kwargs = {"key": key, "format_func": format_func}
                    if not keyed_state_exists:
                        widget_kwargs["default"] = selected_default
                    result = method(label, option_list, **widget_kwargs)
                    return selected_default if result is None else result
                except TypeError:
                    continue

    selected_index = _option_index(option_list, selected_default, index)
    if fallback == "radio":
        radio = getattr(streamlit, "radio", None)
        if callable(radio):
            try:
                widget_kwargs = {
                    "key": key,
                    "format_func": format_func,
                    "help": help,
                    "on_change": on_change,
                    "args": args,
                    "kwargs": kwargs,
                    "label_visibility": label_visibility,
                    "horizontal": True,
                    "disabled": disabled,
                }
                if not keyed_state_exists:
                    widget_kwargs["index"] = selected_index
                return radio(label, option_list, **widget_kwargs)
            except TypeError:
                widget_kwargs = {"key": key}
                if not keyed_state_exists:
                    widget_kwargs["index"] = selected_index
                return radio(label, option_list, **widget_kwargs)

    selectbox = getattr(streamlit, "selectbox", None)
    if callable(selectbox):
        try:
            widget_kwargs = {
                "key": key,
                "format_func": format_func,
                "help": help,
                "on_change": on_change,
                "args": args,
                "kwargs": kwargs,
                "label_visibility": label_visibility,
                "disabled": disabled,
            }
            if not keyed_state_exists:
                widget_kwargs["index"] = selected_index
            return selectbox(label, option_list, **widget_kwargs)
        except TypeError:
            widget_kwargs = {"key": key}
            if not keyed_state_exists:
                widget_kwargs["index"] = selected_index
            return selectbox(label, option_list, **widget_kwargs)

    return selected_default


def confirm_button(
    streamlit: Any,
    label: str,
    *,
    key: str,
    message: str,
    confirm_label: str = "Confirm",
    cancel_label: str = "Cancel",
    help: str | None = None,
    type: str = "secondary",
    confirm_type: str = "primary",
    width: str = "stretch",
    use_dialog: bool = True,
) -> bool:
    """Render a button that requires explicit confirmation before returning True."""
    state = _session_state(streamlit)
    open_key = f"{key}__dialog_open"
    confirmed_key = f"{key}__confirmed"

    native_dialog = getattr(streamlit, "dialog", None)
    if use_dialog and callable(native_dialog):
        if streamlit.button(label, key=key, help=help, type=type, width=width):
            _state_set(state, open_key, True)

        if _state_get(state, open_key, False):
            @native_dialog(label)
            def _confirm_dialog() -> None:
                warning = getattr(streamlit, "warning", None) or getattr(streamlit, "info", None)
                if callable(warning):
                    warning(message)
                confirm_clicked = streamlit.button(
                    confirm_label,
                    key=f"{key}__confirm",
                    type=confirm_type,
                    width=width,
                )
                cancel_clicked = streamlit.button(
                    cancel_label,
                    key=f"{key}__cancel",
                    type="secondary",
                    width=width,
                )
                if confirm_clicked:
                    _state_pop(state, open_key, None)
                    _state_set(state, confirmed_key, True)
                    rerun = getattr(streamlit, "rerun", None)
                    if callable(rerun):
                        rerun()
                elif cancel_clicked:
                    _state_pop(state, open_key, None)
                    rerun = getattr(streamlit, "rerun", None)
                    if callable(rerun):
                        rerun()

            _confirm_dialog()
        return bool(_state_pop(state, confirmed_key, False))

    armed_key = f"{key}__armed"
    if not _state_get(state, armed_key, False):
        if streamlit.button(label, key=key, help=help, type=type, width=width):
            _state_set(state, armed_key, True)
            rerun = getattr(streamlit, "rerun", None)
            if callable(rerun):
                rerun()
        return False

    warning = getattr(streamlit, "warning", None) or getattr(streamlit, "info", None)
    if callable(warning):
        warning(message)
    confirm_clicked = streamlit.button(
        confirm_label,
        key=f"{key}__confirm",
        type=confirm_type,
        width=width,
    )
    cancel_clicked = streamlit.button(
        cancel_label,
        key=f"{key}__cancel",
        type="secondary",
        width=width,
    )
    if confirm_clicked:
        _state_pop(state, armed_key, None)
        return True
    if cancel_clicked:
        _state_pop(state, armed_key, None)
        rerun = getattr(streamlit, "rerun", None)
        if callable(rerun):
            rerun()
    return False
