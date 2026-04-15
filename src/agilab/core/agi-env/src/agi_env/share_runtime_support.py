"""Pure shared-path and runtime flag helpers for AGILAB."""

from __future__ import annotations

import sys
import sysconfig
import re
from pathlib import Path

FREE_THREADING_PROBE_EXCEPTIONS = (AttributeError, OSError, RuntimeError)
FREE_THREADING_CONFIG_EXCEPTIONS = (AttributeError, OSError, TypeError, ValueError)


def share_target_name(target: str | None, app: str | None, *, default: str = "app") -> str:
    """Return the logical app name for share paths."""

    name = target or app or default
    for suffix in ("_project", "_worker"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def resolve_share_path(path: str | Path | None, share_root: Path) -> Path:
    """Resolve ``path`` relative to ``share_root``."""

    if path in (None, "", "."):
        return share_root

    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    return (share_root / candidate).resolve(strict=False)


def mode_to_str(mode: int, *, hw_rapids_capable: bool = False) -> str:
    """Encode a bitmask ``mode`` into readable ``pcdr`` flag form."""

    chars = ["p", "c", "d", "r"]
    reversed_chars = reversed(list(enumerate(chars)))
    normalized_mode = mode + 8 if hw_rapids_capable else mode
    return "".join(
        "_" if (normalized_mode & (1 << i)) == 0 else v for i, v in reversed_chars
    )


def mode_to_int(mode: str) -> int:
    """Convert iterable mode flags (``p``, ``c``, ``d``) into the bitmask int."""

    mode_int = 0
    set_rm = set(mode)
    for i, value in enumerate(["p", "c", "d"]):
        if value in set_rm:
            mode_int += 2 ** (len(["p", "c", "d"]) - 1 - i)
    return mode_int


def is_valid_ip(ip: str) -> bool:
    """Return ``True`` when ``ip`` is a syntactically valid IPv4 address."""

    pattern = re.compile(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$")
    if pattern.match(ip):
        parts = ip.split(".")
        return all(0 <= int(part) <= 255 for part in parts)
    return False


def python_supports_free_threading() -> bool:
    """Return ``True`` when the current interpreter can run with ``PYTHON_GIL=0``."""

    checker = getattr(sys, "_is_gil_enabled", None)
    if callable(checker):
        try:
            return not bool(checker())
        except FREE_THREADING_PROBE_EXCEPTIONS:
            pass

    try:
        return bool(sysconfig.get_config_var("Py_GIL_DISABLED"))
    except FREE_THREADING_CONFIG_EXCEPTIONS:
        return False
