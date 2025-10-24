"""Utility helpers shared across AGI node workers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


class MutableNamespace(SimpleNamespace):
    """SimpleNamespace that also supports dictionary-style access."""

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)


__all__ = ["MutableNamespace"]
