from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types

import pytest


def _import_agilab_module(module_name: str):
    src_root = Path(__file__).resolve().parents[1] / "src"
    package_root = src_root / "agilab"
    src_root_str = str(src_root)
    package_root_str = str(package_root)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)
    pkg = sys.modules.get("agilab")
    if pkg is None or not hasattr(pkg, "__path__"):
        pkg = types.ModuleType("agilab")
        pkg.__path__ = [package_root_str]
        sys.modules["agilab"] = pkg
    else:
        package_path = list(pkg.__path__)
        if package_root_str not in package_path:
            pkg.__path__ = [package_root_str, *package_path]
    importlib.invalidate_caches()
    return importlib.import_module(module_name)


pipeline_openai_compatible = _import_agilab_module("agilab.pipeline_openai_compatible")


def test_normalize_openai_compatible_base_url_accepts_vllm_shapes():
    normalize = pipeline_openai_compatible.normalize_openai_compatible_base_url

    assert normalize("") == "http://127.0.0.1:8000/v1"
    assert normalize("http://127.0.0.1:8000") == "http://127.0.0.1:8000/v1"
    assert normalize("http://127.0.0.1:8000/v1") == "http://127.0.0.1:8000/v1"
    assert normalize("http://127.0.0.1:8000/v1/chat/completions") == "http://127.0.0.1:8000/v1"


def test_resolve_openai_compatible_settings_uses_env_style_keys(monkeypatch):
    monkeypatch.delenv("AGILAB_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("AGILAB_LLM_MODEL", raising=False)

    settings = pipeline_openai_compatible.resolve_openai_compatible_settings(
        {
            "AGILAB_LLM_BASE_URL": "http://gpu-box:8000",
            "AGILAB_LLM_API_KEY": "gateway-secret",
            "AGILAB_LLM_MODEL": "mistralai/Mistral-7B-Instruct-v0.3",
            "AGILAB_LLM_TEMPERATURE": "0.2",
            "AGILAB_LLM_MAX_TOKENS": "512",
            "AGILAB_LLM_TIMEOUT": "30",
        }
    )

    assert settings.base_url == "http://gpu-box:8000/v1"
    assert settings.api_key == "gateway-secret"
    assert settings.model == "mistralai/Mistral-7B-Instruct-v0.3"
    assert settings.temperature == 0.2
    assert settings.max_tokens == 512
    assert settings.timeout_s == 30.0


def test_openai_compatible_completion_payload_rejects_invalid_numbers():
    with pytest.raises(ValueError, match="AGILAB_LLM_TEMPERATURE must be numeric"):
        pipeline_openai_compatible.resolve_openai_compatible_settings(
            {"AGILAB_LLM_TEMPERATURE": "hot"}
        )

    with pytest.raises(ValueError, match="AGILAB_LLM_MAX_TOKENS must be positive"):
        pipeline_openai_compatible.resolve_openai_compatible_settings(
            {"AGILAB_LLM_MAX_TOKENS": "0"}
        )


def test_build_openai_compatible_completion_kwargs_includes_optional_max_tokens():
    payload, settings = pipeline_openai_compatible.build_openai_compatible_completion_kwargs(
        [{"role": "user", "content": "make code"}],
        {"AGILAB_LLM_MODEL": "served-model", "AGILAB_LLM_MAX_TOKENS": "128"},
    )

    assert settings.model == "served-model"
    assert payload == {
        "model": "served-model",
        "messages": [{"role": "user", "content": "make code"}],
        "temperature": 0.1,
        "max_tokens": 128,
    }
