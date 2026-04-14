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
