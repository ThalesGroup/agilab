from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ABOUT_MENU_BRAND = ":blue[AGILAB&trade;]"
ABOUT_MENU_TAGLINE = "Reproducible AI engineering, from project to proof."
ABOUT_MENU_ORGANIZATION = "Thales SIX GTS France SAS"
ABOUT_MENU_SUPPORT = "Support: open a GitHub issue"


def load_json_resource(resources_root: Path, filename: str) -> dict[str, Any]:
    with open(resources_root / filename, encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise TypeError(f"{filename} must contain a JSON object")
    return payload


def about_content_text() -> str:
    return "\n\n".join(
        [
            ABOUT_MENU_BRAND,
            ABOUT_MENU_TAGLINE,
            ABOUT_MENU_ORGANIZATION,
            ABOUT_MENU_SUPPORT,
        ]
    )


def about_content_payload() -> dict[str, str]:
    return {"About": about_content_text()}
