# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Compatibility wrapper for the optional Streamlit code editor component."""

from __future__ import annotations

from importlib import metadata
import re
from typing import Any

_component_code_editor: Any | None = None
_component_import_attempted = False
CODE_EDITOR_IMPORT_ERROR: Exception | None = None


def _streamlit_minor_version() -> tuple[int, int] | None:
    try:
        raw_version = metadata.version("streamlit")
    except metadata.PackageNotFoundError:
        return None
    parts = raw_version.split(".")[:2]
    if len(parts) < 2:
        return None
    parsed: list[int] = []
    for part in parts:
        match = re.match(r"\d+", part)
        if match is None:
            return None
        parsed.append(int(match.group(0)))
    return parsed[0], parsed[1]


def _streamlit_requires_fallback() -> bool:
    version = _streamlit_minor_version()
    return version is not None and version >= (1, 57)


def _load_component_code_editor() -> Any | None:
    global CODE_EDITOR_IMPORT_ERROR, _component_code_editor, _component_import_attempted

    if _component_import_attempted:
        return _component_code_editor
    _component_import_attempted = True
    if _streamlit_requires_fallback():
        CODE_EDITOR_IMPORT_ERROR = RuntimeError(
            "streamlit_code_editor is disabled for Streamlit >=1.57; using text-area fallback"
        )
        return None
    try:
        from code_editor import code_editor as imported_code_editor
    except Exception as exc:  # pragma: no cover - exercised by component/runtime drift
        CODE_EDITOR_IMPORT_ERROR = exc
        _component_code_editor = None
    else:
        CODE_EDITOR_IMPORT_ERROR = None
        _component_code_editor = imported_code_editor
    return _component_code_editor


def _fallback_code_editor(body: str, **kwargs: Any) -> dict[str, Any]:
    import streamlit as st

    label = str(kwargs.get("label") or kwargs.get("key") or "Code")
    text = st.text_area(
        f"{label} (fallback editor)",
        value=body or "",
        height=kwargs.get("height"),
        key=kwargs.get("key"),
    )
    return {
        "text": text,
        "type": "fallback",
        "component_error": str(CODE_EDITOR_IMPORT_ERROR or "code editor unavailable"),
    }


def code_editor(body: str, **kwargs: Any) -> Any:
    component_code_editor = _load_component_code_editor()
    if component_code_editor is not None:
        return component_code_editor(body, **kwargs)
    return _fallback_code_editor(body, **kwargs)
