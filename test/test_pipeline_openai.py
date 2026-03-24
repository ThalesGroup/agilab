from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path


def _load_module(module_name: str, relative_path: str):
    module_path = Path(relative_path)
    importlib.invalidate_caches()
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


pipeline_openai = _load_module("agilab.pipeline_openai", "src/agilab/pipeline_openai.py")


def test_ensure_cached_api_key_uses_secret(monkeypatch):
    fake_st = types.SimpleNamespace(session_state={}, secrets={"OPENAI_API_KEY": "sk-secret-value-12345"})
    monkeypatch.setattr(pipeline_openai, "st", fake_st)

    resolved = pipeline_openai.ensure_cached_api_key({})

    assert resolved == "sk-secret-value-12345"
    assert fake_st.session_state["openai_api_key"] == "sk-secret-value-12345"


def test_persist_env_var_replaces_existing_value(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    env_file = tmp_path / ".agilab" / ".env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text('OPENAI_API_KEY="old"\nOTHER="keep"\n', encoding="utf-8")

    pipeline_openai.persist_env_var("OPENAI_API_KEY", "new-key")

    assert env_file.read_text(encoding="utf-8") == 'OTHER="keep"\nOPENAI_API_KEY="new-key"\n'


def test_make_openai_client_and_model_prefers_azure(monkeypatch):
    captured = {}

    class _AzureClient:
        def __init__(self, **kwargs):
            captured["azure"] = kwargs

    class _OpenAIClient:
        def __init__(self, **kwargs):
            captured["openai"] = kwargs

    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = _OpenAIClient
    fake_openai.AzureOpenAI = _AzureClient
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5")
    monkeypatch.delenv("OPENAI_API_TYPE", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)

    client, model_name, is_azure = pipeline_openai.make_openai_client_and_model(
        {"AZURE_OPENAI_ENDPOINT": "https://azure.example", "AZURE_OPENAI_API_VERSION": "2024-10-01"},
        "azure-secret",
    )

    assert isinstance(client, _AzureClient)
    assert model_name == "gpt-5"
    assert is_azure is True
    assert captured["azure"] == {
        "api_key": "azure-secret",
        "azure_endpoint": "https://azure.example",
        "api_version": "2024-10-01",
    }


def test_is_placeholder_api_key_catches_redacted_forms():
    assert pipeline_openai.is_placeholder_api_key("***redacted***") is True
    assert pipeline_openai.is_placeholder_api_key("sk-realistic-key-123456") is False
