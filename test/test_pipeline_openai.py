from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types


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


pipeline_openai = _import_agilab_module("agilab.pipeline_openai")


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
