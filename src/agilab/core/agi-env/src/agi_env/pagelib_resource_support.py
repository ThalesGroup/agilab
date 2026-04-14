from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json_resource(resources_root: Path, filename: str) -> dict[str, Any]:
    with open(resources_root / filename, encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise TypeError(f"{filename} must contain a JSON object")
    return payload


def about_content_payload() -> dict[str, str]:
    return {
        "About": (
            ":blue[AGILab&trade;]\n\n"
            "An IDE for Data Science in Engineering\n\n"
            "Thales SIX GTS France SAS \n\n"
            "support: open a GitHub issue"
        )
    }
