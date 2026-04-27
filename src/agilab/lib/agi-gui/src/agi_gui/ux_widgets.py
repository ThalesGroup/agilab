"""Small compatibility wrappers for recent Streamlit UX primitives."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any


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
