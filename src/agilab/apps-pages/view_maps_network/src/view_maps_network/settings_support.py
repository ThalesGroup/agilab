from __future__ import annotations

import re
from typing import Any


def get_view_maps_page_settings(app_settings: dict[str, Any]) -> dict[str, Any]:
    pages = app_settings.get("pages")
    if not isinstance(pages, dict):
        return {}
    settings = pages.get("view_maps_network")
    return settings if isinstance(settings, dict) else {}


def coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = re.split(r"[,;\n]", value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = [str(item) for item in value]
    else:
        raw_items = [str(value)]
    items: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        cleaned = str(item).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        items.append(cleaned)
    return items


def first_nonempty_setting(sources: list[dict[str, Any]], *keys: str) -> str:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def setting_list(sources: list[dict[str, Any]], *keys: str) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            for item in coerce_str_list(source.get(key)):
                if item in seen:
                    continue
                seen.add(item)
                items.append(item)
    return items
