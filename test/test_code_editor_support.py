from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

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


def test_code_editor_component_version_and_text_area_fallback(monkeypatch):
    module = _load_module(
        "agilab.code_editor_component_fallback_test",
        "src/agilab/code_editor_component.py",
    )

    def missing_version(_name):
        raise module.metadata.PackageNotFoundError("streamlit")

    monkeypatch.setattr(module.metadata, "version", missing_version)
    assert module._streamlit_minor_version() is None
    monkeypatch.setattr(module.metadata, "version", lambda _name: "1")
    assert module._streamlit_minor_version() is None
    monkeypatch.setattr(module.metadata, "version", lambda _name: "bad.version")
    assert module._streamlit_minor_version() is None

    monkeypatch.setattr(module.metadata, "version", lambda _name: "1.57.0")
    calls = []

    def text_area(label, *, value, height, key):
        calls.append((label, value, height, key))
        return value + "\n# edited"

    monkeypatch.setitem(sys.modules, "streamlit", SimpleNamespace(text_area=text_area))

    result = module.code_editor("print('x')", key="snippet", height=120)

    assert result["type"] == "fallback"
    assert result["text"].endswith("# edited")
    assert "Streamlit >=1.57" in result["component_error"]
    assert calls == [("snippet (fallback editor)", "print('x')", 120, "snippet")]


def test_code_editor_component_delegates_to_optional_component(monkeypatch):
    module = _load_module(
        "agilab.code_editor_component_delegate_test",
        "src/agilab/code_editor_component.py",
    )
    delegated = []

    def fake_code_editor(body, **kwargs):
        delegated.append((body, kwargs))
        return {"text": body, "type": "component"}

    monkeypatch.setattr(module, "_streamlit_requires_fallback", lambda: False)
    monkeypatch.setitem(sys.modules, "code_editor", SimpleNamespace(code_editor=fake_code_editor))

    assert module.code_editor("x = 1", language="python") == {"text": "x = 1", "type": "component"}
    assert module._load_component_code_editor() is fake_code_editor
    assert delegated == [("x = 1", {"language": "python"})]
