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


def test_ensure_cached_api_key_prefers_existing_session_value(monkeypatch):
    fake_st = types.SimpleNamespace(session_state={"openai_api_key": "sk-session-value-123456"}, secrets={})
    monkeypatch.setattr(pipeline_openai, "st", fake_st)

    resolved = pipeline_openai.ensure_cached_api_key({"OPENAI_API_KEY": "sk-env-value-123456"})

    assert resolved == "sk-session-value-123456"
    assert fake_st.session_state["openai_api_key"] == "sk-session-value-123456"


def test_ensure_cached_api_key_uses_process_env_and_clears_placeholder(monkeypatch):
    fake_st = types.SimpleNamespace(session_state={}, secrets={})
    monkeypatch.setattr(pipeline_openai, "st", fake_st)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-process-value-123456")

    resolved = pipeline_openai.ensure_cached_api_key({})

    assert resolved == "sk-process-value-123456"
    assert fake_st.session_state["openai_api_key"] == "sk-process-value-123456"

    fake_st.session_state.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-XXXX")
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)

    cleared = pipeline_openai.ensure_cached_api_key({})

    assert cleared == ""
    assert fake_st.session_state["openai_api_key"] == ""


def test_make_openai_client_and_model_uses_standard_openai_client(monkeypatch):
    captured = {}

    class _OpenAIClient:
        def __init__(self, **kwargs):
            captured["openai"] = kwargs

    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = _OpenAIClient
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_TYPE", raising=False)

    client, model_name, is_azure = pipeline_openai.make_openai_client_and_model(
        {"OPENAI_BASE_URL": "https://proxy.example/v1", "OPENAI_MODEL": "gpt-5.4"},
        "openai-secret",
    )

    assert isinstance(client, _OpenAIClient)
    assert model_name == "gpt-5.4"
    assert is_azure is False
    assert captured["openai"] == {
        "api_key": "openai-secret",
        "base_url": "https://proxy.example/v1",
    }


def test_make_openai_client_and_model_falls_back_to_module_level_openai_api(monkeypatch):
    fake_openai = types.ModuleType("openai")
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_TYPE", raising=False)

    client, model_name, is_azure = pipeline_openai.make_openai_client_and_model(
        {"OPENAI_BASE_URL": "https://proxy.example/v1", "OPENAI_MODEL": "gpt-5.4"},
        "module-secret",
    )

    assert client is fake_openai
    assert model_name == "gpt-5.4"
    assert is_azure is False
    assert fake_openai.api_key == "module-secret"
    assert fake_openai.api_base == "https://proxy.example/v1"


def test_is_placeholder_api_key_catches_short_and_template_values():
    assert pipeline_openai.is_placeholder_api_key("your-key") is True
    assert pipeline_openai.is_placeholder_api_key("sk-your-key") is True
    assert pipeline_openai.is_placeholder_api_key("short") is True


def test_is_placeholder_api_key_catches_none_blank_and_documentation_templates():
    assert pipeline_openai.is_placeholder_api_key(None) is True
    assert pipeline_openai.is_placeholder_api_key("   ") is True
    assert pipeline_openai.is_placeholder_api_key("YOUR_API_KEY") is True


def test_ensure_cached_api_key_recovers_from_secret_lookup_error(monkeypatch):
    class BrokenSecrets:
        def get(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    fake_st = types.SimpleNamespace(session_state={}, secrets=BrokenSecrets())
    monkeypatch.setattr(pipeline_openai, "st", fake_st)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-secret-value-123456")

    resolved = pipeline_openai.ensure_cached_api_key({})

    assert resolved == "azure-secret-value-123456"
    assert fake_st.session_state["openai_api_key"] == "azure-secret-value-123456"
