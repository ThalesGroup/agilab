from __future__ import annotations

from typing import Any

TERMINAL_LOG_WIDTH = 360
LOG_PATH_LIMIT = 120
LOG_DETAIL_LIMIT = 220
_ELLIPSIS = "..."


def bound_log_value(value: Any, limit: int = TERMINAL_LOG_WIDTH) -> str:
    """Return a single-line string bounded for compact terminal logging."""
    try:
        text = str(value)
    except Exception as exc:  # pragma: no cover - defensive formatting boundary
        text = f"<unprintable {type(value).__name__}: {exc}>"

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\n", "\\n").replace("\t", "\\t")
    if limit <= 0:
        return ""
    if len(normalized) <= limit:
        return normalized
    if limit <= len(_ELLIPSIS):
        return _ELLIPSIS[:limit]
    return normalized[: limit - len(_ELLIPSIS)] + _ELLIPSIS
