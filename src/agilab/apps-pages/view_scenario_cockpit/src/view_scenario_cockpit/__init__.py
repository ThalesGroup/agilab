from __future__ import annotations

from pathlib import Path


def bundle_root() -> Path:
    return Path(__file__).resolve().parent
