from __future__ import annotations

from typing import Any


def normalize_custom_buttons(payload: Any) -> list[Any]:
    """Return the list-shaped button config expected by ``code_editor``."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("buttons"), list):
        return payload["buttons"]
    raise TypeError("custom_buttons payload must be a list or an object with a 'buttons' list")
