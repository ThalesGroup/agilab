# BSD 3-Clause License
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Python pipeline editor controls rendered by AGILAB's React host."""

from __future__ import annotations

import hashlib
from typing import Any

from agi_web import python_ui as ui
from agi_web.python_view_session import current_session


def code_editor(body: str, **kwargs: Any) -> dict[str, Any]:
    """Edit and submit code atomically using the existing save/run response contract."""
    label = str(kwargs.get("label") or "Code")
    key = str(kwargs.get("key") or "agilab:code-editor:" + hashlib.sha256(body.encode()).hexdigest()[:16])
    height = kwargs.get("height") or 240
    if isinstance(height, (int, float)) and height < 60: height = max(120, height * 20)
    specifications = kwargs.get("buttons") or [{"name": "Save", "commands": [["response", "save"]]}]
    if isinstance(specifications, dict): specifications = specifications.get("buttons", [])
    actions = []
    for specification in specifications:
        if not isinstance(specification, dict): continue
        response = next((command[1] for command in specification.get("commands", [])
                         if isinstance(command, (list, tuple)) and len(command) == 2 and command[0] == "response"), None)
        if isinstance(response, str): actions.append((str(specification.get("name") or response.title()), response))
    if not actions: actions = [("Save", "save")]
    action = ""
    with ui.form(key + ":form", border=False):
        text = ui.text_area(label, body or "", height=height, key=key + ":text", disabled=bool(kwargs.get("disabled", False)))
        for name, response in actions:
            if ui.form_submit_button(name, key=key + ":" + response, disabled=bool(kwargs.get("disabled", False))): action = response
    return {"text": text, "type": action, "id": f"{current_session().revision}:{action}" if action else "", "language": kwargs.get("language", "python")}
