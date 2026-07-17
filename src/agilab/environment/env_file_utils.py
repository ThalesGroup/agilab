from __future__ import annotations

import os
import time
from pathlib import Path


_WINDOWS_FILE_SHARING_RETRY_TIMEOUT_SECONDS = 0.5
_WINDOWS_FILE_SHARING_RETRY_INTERVAL_SECONDS = 0.01


def _is_windows() -> bool:
    return os.name == "nt"


def read_mutable_env_text(path: Path, *, errors: str | None = None) -> str:
    """Read a replace-in-place dotenv file across Windows sharing windows.

    This base-package helper intentionally keeps its retry local: importing the
    equivalent agi-env helper here would make the optional UI/core package a
    base-package dependency.
    """

    deadline = time.monotonic() + _WINDOWS_FILE_SHARING_RETRY_TIMEOUT_SECONDS
    while True:
        try:
            return path.read_text(encoding="utf-8", errors=errors)
        except PermissionError:
            if not _is_windows():
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(_WINDOWS_FILE_SHARING_RETRY_INTERVAL_SECONDS, remaining))


def _strip_env_value_quotes(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def load_env_file_map(path: Path, *, include_commented: bool = True) -> dict[str, str]:
    """Return a key/value mapping from a .env-like file."""
    env_map: dict[str, str] = {}
    try:
        for raw in read_mutable_env_text(path).splitlines():
            stripped = raw.strip()
            if not stripped or "=" not in stripped:
                continue
            if stripped.startswith("#"):
                if not include_commented:
                    continue
                target = stripped.lstrip("#").strip()
            else:
                target = stripped
            key, val = target.split("=", 1)
            key = key.strip()
            if key:
                env_map[key] = _strip_env_value_quotes(val)
    except FileNotFoundError:
        pass
    return env_map
