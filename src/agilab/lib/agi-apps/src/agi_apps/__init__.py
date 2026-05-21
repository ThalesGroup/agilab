"""Catalog for public AGILAB app project packages."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any


def app_packages() -> tuple[dict[str, str], ...]:
    with resources.files(__package__).joinpath("catalog.json").open("r", encoding="utf-8") as handle:
        data: Any = json.load(handle)
    return tuple(dict(item) for item in data)


__all__ = ["app_packages"]
