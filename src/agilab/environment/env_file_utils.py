from __future__ import annotations

from pathlib import Path


def _strip_env_value_quotes(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def load_env_file_map(path: Path, *, include_commented: bool = True) -> dict[str, str]:
    """Return a key/value mapping from a .env-like file."""
    env_map: dict[str, str] = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
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
