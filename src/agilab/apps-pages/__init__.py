"""Public AGILAB analysis page bundle payload."""

from __future__ import annotations

from pathlib import Path


def bundles_root() -> Path:
    """Return the installed root containing AGILAB page bundles."""

    return Path(__file__).resolve().parent
