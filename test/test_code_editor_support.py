from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import sys

import pytest


def _load_module(module_name: str, relative_path: str):
    module_path = Path(relative_path)
    importlib.invalidate_caches()
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


code_editor_support = _load_module("agilab.code_editor_support", "src/agilab/code_editor_support.py")
normalize_custom_buttons = code_editor_support.normalize_custom_buttons


def test_normalize_custom_buttons_accepts_legacy_list_payload():
    buttons = [{"name": "Run"}]

    assert normalize_custom_buttons(buttons) == buttons


def test_normalize_custom_buttons_unwraps_object_payload():
    payload = {"buttons": [{"name": "Save"}]}

    assert normalize_custom_buttons(payload) == payload["buttons"]


def test_normalize_custom_buttons_rejects_invalid_payload():
    with pytest.raises(TypeError, match="custom_buttons payload"):
        normalize_custom_buttons({"buttons": "invalid"})


def test_native_editor_saves_only_after_form_submission(tmp_path):
    from agi_web.testing import AppTest
    from agilab.components.code_editor_component import code_editor
    destination = tmp_path / "pipeline.py"
    def view():
        response = code_editor("x = 1", key="pipeline")
        if response["type"] == "save": destination.write_text(response["text"])
    app = AppTest.from_function(view).run()
    app.text_area[0].set_value("x = 2").run()
    assert not destination.exists()
    app.button[0].click().run()
    assert not app.exception
    assert destination.read_text() == "x = 2"
    destination.write_text("external change")
    app.run()
    assert destination.read_text() == "external change"


def test_native_editor_preserves_run_response_contract():
    from agi_web.testing import AppTest
    from agilab.components.code_editor_component import code_editor
    responses = []
    def view():
        responses.append(code_editor("print(1)", key="snippet", buttons=[{"name": "Run", "commands": [["response", "run"]]}]))
    app = AppTest.from_function(view).run()
    app.text_area[0].set_value("print(2)")
    app.button[0].click().run()
    assert responses[-1]["type"] == "run"
    assert responses[-1]["text"] == "print(2)" and responses[-1]["id"]
    app.run()
    assert responses[-1]["type"] == ""
