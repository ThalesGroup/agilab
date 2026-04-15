"""Pure dotenv and environment-file helpers for AGILAB."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, set_key

ENV_MAPPING_EXCEPTIONS = (AttributeError, TypeError)


def _normalize_env_value(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def clean_envar_value(
    envars: dict | None,
    key: str,
    *,
    fallback_to_process: bool = False,
) -> str | None:
    """Return a stripped env value or ``None`` when unset/blank."""

    raw = None
    try:
        raw = envars.get(key) if envars is not None else None
    except ENV_MAPPING_EXCEPTIONS:
        raw = None
    value = _normalize_env_value(raw)
    if value is not None:
        return value
    if fallback_to_process:
        return _normalize_env_value(os.environ.get(key))
    return None


def load_dotenv_values(dotenv_path: Path, *, verbose: bool = False) -> dict[str, str]:
    """Load dotenv values while treating blank assignments as unset."""

    loaded = dotenv_values(dotenv_path=dotenv_path, verbose=verbose)
    normalized: dict[str, str] = {}
    for key, value in loaded.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        normalized[str(key)] = value
    return normalized


def write_env_updates(env_file: Path, updates: dict[str, object]) -> None:
    """Persist updates into a dotenv file without shell-style quoting."""

    env_file.parent.mkdir(parents=True, exist_ok=True)
    for key, value in updates.items():
        set_key(str(env_file), key, str(value), quote_mode="never")
