"""Generic queue resilience analysis page."""

from pathlib import Path


def bundle_root() -> Path:
    """Return the installed root for this AGILAB analysis page bundle."""

    return Path(__file__).resolve().parent
