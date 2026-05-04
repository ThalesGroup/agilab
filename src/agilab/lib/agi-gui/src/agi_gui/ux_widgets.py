"""Small compatibility wrappers for recent Streamlit UX primitives."""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from typing import Any, Callable, Iterable


_TOAST_FALLBACKS = {
    "blocked": "warning",
    "complete": "success",
    "completed": "success",
    "disabled": "info",
    "done": "success",
    "success": "success",
    "failed": "error",
    "failure": "error",
    "error": "error",
    "idle": "info",
    "ready": "success",
    "warning": "warning",
    "info": "info",
    "running": "info",
    "stale": "warning",
}

_STATUS_STATE_ALIASES = {
    "complete": "complete",
    "completed": "complete",
    "done": "complete",
    "success": "complete",
    "error": "error",
    "failed": "error",
    "failure": "error",
    "running": "running",
    "working": "running",
}

_ACTION_KIND_ALIASES = {
    "add": "primary",
    "apply": "primary",
    "cancel": "secondary",
    "check": "secondary",
    "clean": "destructive",
    "clear": "destructive",
    "confirm": "primary",
    "delete": "destructive",
    "destructive": "destructive",
    "download": "secondary",
    "execute": "primary",
    "generate": "primary",
    "import": "primary",
    "install": "primary",
    "open": "secondary",
    "preview": "secondary",
    "primary": "primary",
    "refresh": "secondary",
    "remove": "destructive",
    "reset": "destructive",
    "revert": "secondary",
    "run": "primary",
    "save": "primary",
    "secondary": "secondary",
    "select": "secondary",
    "stop": "destructive",
}


@dataclass(frozen=True)
class ActionStyle:
    """Normalized Streamlit button defaults for a class of UI actions."""

    kind: str
    button_type: str = "secondary"
    width: str = "stretch"
    status_state: str = "info"


@dataclass(frozen=True)
class ActionSpec:
    """Declarative action metadata for normalized button rows and empty states."""

    label: str
    key: str
    kind: str | None = None
    help: str | None = None
    disabled: bool = False
    width: str | None = None
    type: str | None = None
    icon: str | None = None
    on_click: Callable[..., Any] | None = None
    args: tuple[Any, ...] | None = None
    kwargs: dict[str, Any] | None = None


_ACTION_STYLES = {
    "primary": ActionStyle("primary", button_type="primary", status_state="running"),
    "secondary": ActionStyle("secondary"),
    "destructive": ActionStyle("destructive", button_type="secondary", status_state="warning"),
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
    method_name = _TOAST_FALLBACKS.get(normalize_message_state(state), "info")
    method = getattr(streamlit, method_name, None) or getattr(streamlit, "info", None)
    if callable(method):
        method(message)


def notice(
    streamlit: Any,
    message: str,
    *,
    state: str = "info",
    icon: str | None = None,
) -> None:
    """Show a normalized inline message with compatibility for legacy Streamlit."""
    method_name = _TOAST_FALLBACKS.get(normalize_message_state(state), "info")
    method = getattr(streamlit, method_name, None) or getattr(streamlit, "info", None)
    if not callable(method):
        return
    try:
        if icon is None:
            method(message)
        else:
            method(message, icon=icon)
    except TypeError:
        method(message)


def normalize_message_state(state: str | None) -> str:
    """Return the canonical message state used by notices and toast fallbacks."""
    if not state:
        return "info"
    normalized = str(state).strip().lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in _TOAST_FALLBACKS else "info"


def normalize_status_state(state: str | None) -> str:
    """Return a Streamlit-compatible status state."""
    if not state:
        return "running"
    normalized = str(state).strip().lower().replace("-", "_").replace(" ", "_")
    return _STATUS_STATE_ALIASES.get(normalized, "running")


def normalize_action_kind(kind: str | None) -> str:
    """Return the canonical AGILAB action kind for button styling."""
    if not kind:
        return "secondary"
    normalized = str(kind).strip().lower().replace("-", "_").replace(" ", "_")
    return _ACTION_KIND_ALIASES.get(normalized, "secondary")


def action_style(kind: str | None = None) -> ActionStyle:
    """Return normalized button defaults for an AGILAB action kind."""
    return _ACTION_STYLES[normalize_action_kind(kind)]


def _call_button(streamlit: Any, label: str, widget_kwargs: dict[str, Any]) -> bool:
    button = getattr(streamlit, "button", None)
    if not callable(button):
        return False

    attempts = [
        widget_kwargs,
        {key: value for key, value in widget_kwargs.items() if key != "icon"},
        {
            key: value
            for key, value in widget_kwargs.items()
            if key not in {"icon", "width"}
        },
        {
            key: value
            for key, value in widget_kwargs.items()
            if key in {"key", "help", "type", "disabled"}
        },
        {key: value for key, value in widget_kwargs.items() if key == "key"},
    ]
    seen: set[tuple[str, ...]] = set()
    for attempt in attempts:
        signature = tuple(sorted(attempt))
        if signature in seen:
            continue
        seen.add(signature)
        try:
            return bool(button(label, **attempt))
        except TypeError:
            continue
    return bool(button(label, key=widget_kwargs.get("key")))


def action_button(
    streamlit: Any,
    label: str,
    *,
    key: str,
    kind: str | None = None,
    help: str | None = None,
    disabled: bool = False,
    width: str | None = None,
    type: str | None = None,
    icon: str | None = None,
    on_click: Callable[..., Any] | None = None,
    args: tuple[Any, ...] | None = None,
    kwargs: dict[str, Any] | None = None,
) -> bool:
    """Render a button using normalized AGILAB action defaults."""
    style = action_style(kind)
    widget_kwargs: dict[str, Any] = {
        "key": key,
        "help": help,
        "type": type or style.button_type,
        "width": width or style.width,
        "disabled": disabled,
    }
    if icon is not None:
        widget_kwargs["icon"] = icon
    if on_click is not None:
        widget_kwargs["on_click"] = on_click
        if args is not None:
            widget_kwargs["args"] = args
        if kwargs is not None:
            widget_kwargs["kwargs"] = kwargs
    return _call_button(streamlit, label, widget_kwargs)


def _coerce_action_spec(action: ActionSpec | dict[str, Any]) -> ActionSpec:
    if isinstance(action, ActionSpec):
        return action
    return ActionSpec(**action)


def _columns(streamlit: Any, count_or_specs: Any, *, gap: str = "small") -> list[Any]:
    columns = getattr(streamlit, "columns", None)
    if not callable(columns):
        count = count_or_specs if isinstance(count_or_specs, int) else len(count_or_specs)
        return [streamlit for _ in range(int(count))]
    try:
        return list(columns(count_or_specs, gap=gap))
    except TypeError:
        return list(columns(count_or_specs))


def _container_context(container: Any) -> AbstractContextManager:
    if hasattr(container, "__enter__") and hasattr(container, "__exit__"):
        return container
    return nullcontext(container)


def action_row(
    streamlit: Any,
    actions: Iterable[ActionSpec | dict[str, Any]],
    *,
    columns: Any | None = None,
    gap: str = "small",
) -> dict[str, bool]:
    """Render a normalized row of action buttons and return clicks keyed by action key."""
    specs = [_coerce_action_spec(action) for action in actions]
    if not specs:
        return {}

    containers = _columns(streamlit, columns or len(specs), gap=gap)
    if len(containers) < len(specs):
        containers.extend(streamlit for _ in range(len(specs) - len(containers)))
    results: dict[str, bool] = {}
    for container, spec in zip(containers, specs):
        with _container_context(container) as target:
            results[spec.key] = action_button(
                target,
                spec.label,
                key=spec.key,
                kind=spec.kind,
                help=spec.help,
                disabled=spec.disabled,
                width=spec.width,
                type=spec.type,
                icon=spec.icon,
                on_click=spec.on_click,
                args=spec.args,
                kwargs=spec.kwargs,
            )
    return results


def empty_state(
    streamlit: Any,
    title: str,
    *,
    body: str | None = None,
    state: str = "info",
    icon: str | None = None,
    action: ActionSpec | dict[str, Any] | None = None,
) -> bool:
    """Render a normalized empty-state notice with an optional single action."""
    message = title if not body else f"{title}\n\n{body}"
    notice(streamlit, message, state=state, icon=icon)
    if action is None:
        return False
    spec = _coerce_action_spec(action)
    return action_button(
        streamlit,
        spec.label,
        key=spec.key,
        kind=spec.kind,
        help=spec.help,
        disabled=spec.disabled,
        width=spec.width,
        type=spec.type,
        icon=spec.icon,
        on_click=spec.on_click,
        args=spec.args,
        kwargs=spec.kwargs,
    )


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
    status_state = normalize_status_state(state)
    native_status = getattr(streamlit, "status", None)
    if callable(native_status):
        try:
            return native_status(label, state=status_state, expanded=expanded)
        except TypeError:
            return native_status(label)

    spinner = getattr(streamlit, "spinner", None)
    if status_state == "running" and callable(spinner):
        try:
            return spinner(label)
        except TypeError:
            pass
    return _FallbackStatus(streamlit, label, normalize_message_state(state))


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
