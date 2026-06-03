"""State persistence helpers extracted from ui_support."""

from __future__ import annotations

import tomllib
from pathlib import Path


def load_global_state(
    global_state_file: Path,
    legacy_last_app_file: Path,
    *,
    toml_module=tomllib,
) -> dict[str, str]:
    """Load persisted UI state, falling back to the legacy plaintext file."""
    try:
        if global_state_file.exists():
            with global_state_file.open("rb") as handle:
                data = toml_module.load(handle)
            return data if isinstance(data, dict) else {}
    except (OSError, toml_module.TOMLDecodeError, TypeError, ValueError):
        pass

    try:
        if legacy_last_app_file.exists():
            raw = legacy_last_app_file.read_text(encoding="utf-8").strip()
            if raw:
                return {"last_active_app": raw}
    except (OSError, UnicodeDecodeError):
        pass
    return {}


def persist_global_state(
    global_state_file: Path,
    data: dict[str, str],
    *,
    dump_payload_fn,
) -> None:
    """Persist the UI state, swallowing serialization and filesystem failures."""
    try:
        global_state_file.parent.mkdir(parents=True, exist_ok=True)
        with global_state_file.open("wb") as handle:
            dump_payload_fn(data, handle)
    except (OSError, RuntimeError, TypeError, ValueError):
        pass


def normalize_existing_path(raw, *, path_cls=Path) -> Path | None:
    """Return a normalized path only when it resolves to an existing location."""
    if not raw:
        return None
    try:
        candidate = path_cls(raw).expanduser()
    except (TypeError, ValueError, OSError):
        return None
    try:
        return candidate if candidate.exists() else None
    except OSError:
        return None


def normalize_path_string(path, *, path_cls=Path) -> str | None:
    """Return a normalized string form for a user path or ``None`` when invalid."""
    try:
        return str(path_cls(path).expanduser())
    except (TypeError, ValueError, OSError):
        return None
