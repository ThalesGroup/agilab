"""Helpers for classifying API-key placeholder values."""

from __future__ import annotations


_PLACEHOLDER_LITERALS = {
    "EMPTY",
    "None",
    "none",
    "null",
    "NULL",
    "your-key",
    "sk-your-key",
    "sk-XXXX",
}


def looks_placeholder_secret(value: object | None, *, min_length: int = 12) -> bool:
    """Return true for missing, redacted, example, or visibly invalid secrets."""
    if value is None:
        return True
    cleaned = str(value).strip()
    if not cleaned:
        return True
    upper_value = cleaned.upper()
    if cleaned in _PLACEHOLDER_LITERALS:
        return True
    if "***" in cleaned or "..." in cleaned or "…" in cleaned:
        return True
    if "YOUR-API-KEY" in upper_value or "YOUR_API_KEY" in upper_value:
        return True
    return len(cleaned) < min_length
