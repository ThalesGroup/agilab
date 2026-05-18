"""Helpers for applying AGILAB's Streamlit theme before Streamlit starts."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping, MutableMapping
from pathlib import Path

STREAMLIT_CONFIG_FILE_ENV = "STREAMLIT_CONFIG_FILE"
STREAMLIT_THEME_ENV_KEYS = {
    "base": "STREAMLIT_THEME_BASE",
    "primaryColor": "STREAMLIT_THEME_PRIMARY_COLOR",
    "backgroundColor": "STREAMLIT_THEME_BACKGROUND_COLOR",
    "secondaryBackgroundColor": "STREAMLIT_THEME_SECONDARY_BACKGROUND_COLOR",
    "textColor": "STREAMLIT_THEME_TEXT_COLOR",
}


def packaged_streamlit_config_path(module_file: str | Path) -> Path:
    return Path(module_file).resolve().parent / "resources" / "config.toml"


def load_streamlit_theme_values(config_path: str | Path) -> dict[str, str]:
    try:
        payload = tomllib.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}

    theme = payload.get("theme")
    if not isinstance(theme, Mapping):
        return {}

    values: dict[str, str] = {}
    for key in STREAMLIT_THEME_ENV_KEYS:
        value = theme.get(key)
        if value is not None:
            values[key] = str(value)
    return values


def apply_streamlit_theme_environment(
    config_path: str | Path,
    environ: MutableMapping[str, str] = os.environ,
) -> None:
    path = Path(config_path)
    environ.setdefault(STREAMLIT_CONFIG_FILE_ENV, str(path))
    values = load_streamlit_theme_values(path)
    for key, env_key in STREAMLIT_THEME_ENV_KEYS.items():
        value = values.get(key)
        if value:
            environ.setdefault(env_key, value)
