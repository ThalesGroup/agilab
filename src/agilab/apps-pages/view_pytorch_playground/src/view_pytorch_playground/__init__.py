"""PyTorch playground Streamlit page."""

from __future__ import annotations

from pathlib import Path


def bundle_root() -> Path:
    """Return the installed root for this AGILAB analysis page bundle."""

    return Path(__file__).resolve().parent
