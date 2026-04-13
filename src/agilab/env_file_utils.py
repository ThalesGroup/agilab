from __future__ import annotations

from pathlib import Path


def load_env_file_map(path: Path) -> dict[str, str]:
    """Return a key/value mapping from a .env-like file, including commented entries."""
    env_map: dict[str, str] = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            stripped = raw.strip()
            if not stripped or "=" not in stripped:
                continue
            target = stripped.lstrip("#").strip()
            if "=" not in target:
                continue
            key, val = target.split("=", 1)
            key = key.strip()
            if key:
                env_map[key] = val.strip()
    except FileNotFoundError:
        pass
    return env_map
