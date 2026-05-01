"""Pinned sidebar panels for Streamlit expanders with serializable content."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Mapping

PINNED_EXPANDERS_KEY = "agilab:pinned_expanders"
DEFAULT_MAX_BODY_CHARS = 20000
CODE_EDITOR_PIN_RESPONSE = "pin_to_sidebar"
CODE_EDITOR_UNPIN_RESPONSE = "unpin_from_sidebar"


def _panel_store(session_state: Any) -> dict[str, dict[str, str]]:
    panels = session_state.get(PINNED_EXPANDERS_KEY)
    if not isinstance(panels, dict):
        panels = {}
        session_state[PINNED_EXPANDERS_KEY] = panels
    return panels


def _button_key(action: str, panel_id: str) -> str:
    safe_id = str(panel_id).replace(" ", "_")
    return f"pinned_expander:{action}:{safe_id}"


def _request_rerun(streamlit: Any) -> None:
    rerun = getattr(streamlit, "rerun", None)
    if callable(rerun):
        rerun()


def _copy_toolbar_button() -> dict[str, Any]:
    return {
        "name": "Copy",
        "feather": "Copy",
        "hasText": True,
        "alwaysOn": True,
        "commands": [
            "copyAll",
            [
                "infoMessage",
                {
                    "text": "Copied to clipboard!",
                    "timeout": 2500,
                    "classToggle": "show",
                },
            ],
        ],
        "style": {
            "top": "-0.25rem",
            "right": "0.4rem",
            "backgroundColor": "#ffffff",
            "borderColor": "#4A90E2",
            "color": "#4A90E2",
        },
    }


def code_editor_pin_buttons(
    base_buttons: Mapping[str, Any] | None = None,
    *,
    pinned: bool,
    pin_response: str = CODE_EDITOR_PIN_RESPONSE,
    unpin_response: str = CODE_EDITOR_UNPIN_RESPONSE,
) -> dict[str, Any]:
    """Return code-editor toolbar buttons with Copy plus Pin/Unpin."""
    buttons = deepcopy(dict(base_buttons or {"buttons": [_copy_toolbar_button()]}))
    toolbar_buttons = buttons.setdefault("buttons", [])
    response_type = unpin_response if pinned else pin_response
    pin_button = {
        "name": "Unpin" if pinned else "Pin",
        "feather": "Bookmark",
        "hasText": True,
        "alwaysOn": True,
        "commands": [
            "save-state",
            [
                "response",
                response_type,
            ],
        ],
        "style": {
            "top": "-0.25rem",
            "right": "6.8rem",
            "backgroundColor": "#ffffff",
            "borderColor": "#4A90E2",
            "color": "#4A90E2",
        },
    }
    insert_at = 1 if toolbar_buttons else 0
    toolbar_buttons.insert(insert_at, pin_button)
    return buttons


def _code_editor_height(text: str, explicit_height: int | None) -> int:
    if explicit_height is not None:
        return explicit_height
    return min(max(len(text.splitlines()), 6), 30)


def is_pinned_expander(session_state: Any, panel_id: str) -> bool:
    """Return whether the panel is currently pinned."""
    return panel_id in _panel_store(session_state)


def remove_pinned_expander(session_state: Any, panel_id: str) -> bool:
    """Remove a pinned panel, returning whether anything changed."""
    return _panel_store(session_state).pop(panel_id, None) is not None


def upsert_pinned_expander(
    session_state: Any,
    panel_id: str,
    *,
    title: str,
    body: str,
    body_format: str = "code",
    language: str = "",
    source: str = "",
    caption: str = "",
    max_body_chars: int = DEFAULT_MAX_BODY_CHARS,
) -> dict[str, str]:
    """Create or refresh a pinned panel in session state."""
    text = str(body or "")
    truncation_caption = ""
    if max_body_chars > 0 and len(text) > max_body_chars:
        text = text[-max_body_chars:]
        truncation_caption = f"Showing last {max_body_chars} characters."
    final_caption = " ".join(part for part in (caption, truncation_caption) if part).strip()
    panel = {
        "id": str(panel_id),
        "title": str(title or panel_id),
        "body": text,
        "body_format": str(body_format or "code"),
        "language": str(language or ""),
        "source": str(source or ""),
        "caption": final_caption,
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    _panel_store(session_state)[str(panel_id)] = panel
    return panel


def refresh_pinned_expander(
    session_state: Any,
    panel_id: str,
    *,
    title: str,
    body: str,
    body_format: str = "code",
    language: str = "",
    source: str = "",
    caption: str = "",
    max_body_chars: int = DEFAULT_MAX_BODY_CHARS,
) -> bool:
    """Refresh an existing pinned panel without creating a new one."""
    if not is_pinned_expander(session_state, panel_id):
        return False
    upsert_pinned_expander(
        session_state,
        panel_id,
        title=title,
        body=body,
        body_format=body_format,
        language=language,
        source=source,
        caption=caption,
        max_body_chars=max_body_chars,
    )
    return True


def list_pinned_expanders(session_state: Any) -> list[Mapping[str, str]]:
    """Return pinned panels in deterministic title/id order."""
    panels = _panel_store(session_state)
    return sorted(
        panels.values(),
        key=lambda panel: (panel.get("title", ""), panel.get("id", "")),
    )


def render_pin_button(
    streamlit: Any,
    panel_id: str,
    *,
    title: str,
    body: str,
    body_format: str = "code",
    language: str = "",
    source: str = "",
    caption: str = "",
    max_body_chars: int = DEFAULT_MAX_BODY_CHARS,
) -> bool:
    """Render a Pin/Unpin button for serializable expander content."""
    session_state = streamlit.session_state
    pinned = is_pinned_expander(session_state, panel_id)
    if pinned:
        refresh_pinned_expander(
            session_state,
            panel_id,
            title=title,
            body=body,
            body_format=body_format,
            language=language,
            source=source,
            caption=caption,
            max_body_chars=max_body_chars,
        )

    has_body = bool(str(body or "").strip())
    clicked = streamlit.button(
        "Unpin from sidebar" if pinned else "Pin to sidebar",
        key=_button_key("toggle", panel_id),
        type="secondary",
        disabled=not pinned and not has_body,
        help=(
            "Remove this pinned panel from the sidebar."
            if pinned
            else (
                "Keep this panel visible in the sidebar while you change pages."
                if has_body
                else "This panel has no content to pin yet."
            )
        ),
    )
    if not clicked:
        return pinned

    if pinned:
        remove_pinned_expander(session_state, panel_id)
        _request_rerun(streamlit)
        return False

    upsert_pinned_expander(
        session_state,
        panel_id,
        title=title,
        body=body,
        body_format=body_format,
        language=language,
        source=source,
        caption=caption,
        max_body_chars=max_body_chars,
    )
    _request_rerun(streamlit)
    return True


def render_pinnable_code_editor(
    streamlit: Any,
    code_editor_fn: Any,
    panel_id: str,
    *,
    title: str,
    body: str,
    key: str,
    body_format: str = "code",
    language: str = "",
    source: str = "",
    caption: str = "",
    empty_message: str = "No content available.",
    info_name: str = "",
    height: int | None = None,
    max_body_chars: int = DEFAULT_MAX_BODY_CHARS,
) -> Any:
    """Render read-only code-editor content with toolbar-level Pin/Unpin."""
    session_state = streamlit.session_state
    text = str(body or "")
    if not text.strip():
        caption_fn = getattr(streamlit, "caption", None)
        if callable(caption_fn):
            caption_fn(empty_message)
        return None

    pinned = is_pinned_expander(session_state, panel_id)
    if pinned:
        refresh_pinned_expander(
            session_state,
            panel_id,
            title=title,
            body=text,
            body_format=body_format,
            language=language,
            source=source,
            caption=caption,
            max_body_chars=max_body_chars,
        )

    response = code_editor_fn(
        text,
        height=_code_editor_height(text, height),
        theme="contrast",
        buttons=code_editor_pin_buttons(pinned=pinned),
        lang=language or "text",
        info={"info": [{"name": info_name or title}]},
        component_props={},
        props={"readOnly": True},
        key=key,
    )
    if not isinstance(response, dict):
        return response

    response_type = response.get("type")
    if response_type == CODE_EDITOR_PIN_RESPONSE:
        upsert_pinned_expander(
            session_state,
            panel_id,
            title=title,
            body=response.get("text", text),
            body_format=body_format,
            language=language,
            source=source,
            caption=caption,
            max_body_chars=max_body_chars,
        )
        _request_rerun(streamlit)
    elif response_type == CODE_EDITOR_UNPIN_RESPONSE:
        remove_pinned_expander(session_state, panel_id)
        _request_rerun(streamlit)
    return response


def render_pinned_expanders(
    streamlit: Any,
    *,
    container: Any | None = None,
    session_state: Any | None = None,
) -> None:
    """Render all pinned panels in a stable sidebar container."""
    state = streamlit.session_state if session_state is None else session_state
    panels = list_pinned_expanders(state)
    if not panels:
        return

    target = container if container is not None else getattr(streamlit, "sidebar", streamlit)
    divider = getattr(target, "divider", None)
    if callable(divider):
        divider()
    markdown = getattr(target, "markdown", None)
    if callable(markdown):
        markdown("#### Pinned panels")

    for panel in panels:
        panel_id = str(panel.get("id", ""))
        title = str(panel.get("title", panel_id))
        expander = target.expander(title, expanded=True)
        with expander:
            source = str(panel.get("source", "")).strip()
            caption = str(panel.get("caption", "")).strip()
            if source:
                expander.caption(source)
            if caption:
                expander.caption(caption)
            body = str(panel.get("body", ""))
            body_format = str(panel.get("body_format", "code"))
            if body_format == "markdown":
                expander.markdown(body)
            elif body_format == "text":
                expander.write(body)
            else:
                expander.code(body, language=str(panel.get("language", "")) or None)
            if expander.button(
                "Unpin from sidebar",
                key=_button_key("sidebar_unpin", panel_id),
                type="secondary",
                help="Remove this pinned panel from the sidebar.",
            ):
                remove_pinned_expander(state, panel_id)
                _request_rerun(streamlit)
