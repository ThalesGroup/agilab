from __future__ import annotations

import builtins
import importlib
from pathlib import Path
import stat
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
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600


def test_persist_env_var_creates_env_file_when_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    pipeline_openai.persist_env_var("OPENAI_API_KEY", "created-key")

    env_dir = tmp_path / ".agilab"
    env_file = env_dir / ".env"
    assert env_file.read_text(encoding="utf-8") == 'OPENAI_API_KEY="created-key"\n'
    assert stat.S_IMODE(env_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600


def test_persist_env_var_quotes_values_and_rejects_bad_names(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    pipeline_openai.persist_env_var("OPENAI_API_KEY", 'quoted "value"\nnext')

    assert (
        (tmp_path / ".agilab" / ".env").read_text(encoding="utf-8")
        == 'OPENAI_API_KEY="quoted \\"value\\"\\nnext"\n'
    )
    with pytest.raises(ValueError, match="Invalid environment variable name"):
        pipeline_openai.persist_env_var("OPENAI API KEY", "bad")


def test_persist_env_var_refuses_env_symlink(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    env_dir = tmp_path / ".agilab"
    env_dir.mkdir()
    target = tmp_path / "target.env"
    target.write_text("", encoding="utf-8")
    (env_dir / ".env").symlink_to(target)

    with pytest.raises(OSError, match="Refusing to write API credentials through symlink"):
        pipeline_openai.persist_env_var("OPENAI_API_KEY", "created-key")


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


def test_make_openai_client_and_model_uses_standard_openai_client_without_base_url(monkeypatch):
    captured = {}

    class _OpenAIClient:
        def __init__(self, **kwargs):
            captured["openai"] = kwargs

    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = _OpenAIClient
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_TYPE", raising=False)

    client, model_name, is_azure = pipeline_openai.make_openai_client_and_model({}, "openai-secret")

    assert isinstance(client, _OpenAIClient)
    assert model_name
    assert is_azure is False
    assert captured["openai"] == {"api_key": "openai-secret"}


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


def test_prompt_for_openai_api_key_handles_empty_input(monkeypatch):
    events: list[tuple[str, str]] = []

    class FakeForm:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_st = types.SimpleNamespace(
        session_state={"openai_api_key": "cached"},
        warning=lambda message: events.append(("warning", str(message))),
        form=lambda _key: FakeForm(),
        text_input=lambda *args, **kwargs: "",
        checkbox=lambda *args, **kwargs: True,
        form_submit_button=lambda *args, **kwargs: True,
        error=lambda message: events.append(("error", str(message))),
        success=lambda message: events.append(("success", str(message))),
        rerun=lambda: events.append(("rerun", "")),
        stop=lambda: (_ for _ in ()).throw(RuntimeError("stopped")),
    )
    monkeypatch.setattr(pipeline_openai, "st", fake_st)

    with pytest.raises(RuntimeError, match="stopped"):
        pipeline_openai.prompt_for_openai_api_key("Missing key")

    assert ("warning", "Missing key") in events
    assert ("error", "API key cannot be empty.") in events
    assert not any(kind == "success" for kind, _ in events)


def test_prompt_for_openai_api_key_updates_session_and_persists(monkeypatch):
    events: list[tuple[str, str]] = []

    class FakeForm:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeAgiEnv:
        def __init__(self):
            self.envars = {}

        @staticmethod
        def set_env_var(name, value):
            events.append(("set_env_var", f"{name}={value}"))

    env_obj = FakeAgiEnv()
    fake_st = types.SimpleNamespace(
        session_state={"openai_api_key": "cached", "env": env_obj},
        warning=lambda message: events.append(("warning", str(message))),
        form=lambda _key: FakeForm(),
        text_input=lambda *args, **kwargs: "sk-updated-value-123456",
        checkbox=lambda *args, **kwargs: True,
        form_submit_button=lambda *args, **kwargs: True,
        error=lambda message: events.append(("error", str(message))),
        success=lambda message: events.append(("success", str(message))),
        rerun=lambda: events.append(("rerun", "")),
        stop=lambda: (_ for _ in ()).throw(RuntimeError("stopped")),
    )
    monkeypatch.setattr(pipeline_openai, "st", fake_st)
    monkeypatch.setitem(sys.modules, "agi_env", types.SimpleNamespace(AgiEnv=FakeAgiEnv))
    monkeypatch.setattr(
        pipeline_openai,
        "persist_env_var",
        lambda name, value: events.append(("persist", f"{name}={value}")),
    )

    with pytest.raises(RuntimeError, match="stopped"):
        pipeline_openai.prompt_for_openai_api_key("Missing key")

    assert fake_st.session_state["openai_api_key"] == "sk-updated-value-123456"
    assert env_obj.envars["OPENAI_API_KEY"] == "sk-updated-value-123456"
    assert ("persist", "OPENAI_API_KEY=sk-updated-value-123456") in events
    assert any(kind == "success" and "saved to ~/.agilab/.env" in message for kind, message in events)


def test_prompt_for_openai_api_key_handles_session_update_when_set_env_fails(monkeypatch):
    events: list[tuple[str, str]] = []

    class FakeForm:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeAgiEnv:
        def __init__(self):
            self.envars = {}

        @staticmethod
        def set_env_var(_name, _value):
            raise RuntimeError("boom")

    env_obj = FakeAgiEnv()
    fake_st = types.SimpleNamespace(
        session_state={"openai_api_key": "cached", "env": env_obj},
        warning=lambda message: events.append(("warning", str(message))),
        form=lambda _key: FakeForm(),
        text_input=lambda *args, **kwargs: "sk-updated-value-654321",
        checkbox=lambda *args, **kwargs: False,
        form_submit_button=lambda *args, **kwargs: True,
        error=lambda message: events.append(("error", str(message))),
        success=lambda message: events.append(("success", str(message))),
        rerun=lambda: events.append(("rerun", "")),
        stop=lambda: (_ for _ in ()).throw(RuntimeError("stopped")),
    )
    monkeypatch.setattr(pipeline_openai, "st", fake_st)
    monkeypatch.setitem(sys.modules, "agi_env", types.SimpleNamespace(AgiEnv=FakeAgiEnv))

    with pytest.raises(RuntimeError, match="stopped"):
        pipeline_openai.prompt_for_openai_api_key("Missing key")

    assert fake_st.session_state["openai_api_key"] == "sk-updated-value-654321"
    assert env_obj.envars == {}
    assert ("success", "API key updated for this session.") in events


def test_prompt_for_openai_api_key_warns_when_persist_fails(monkeypatch):
    events: list[tuple[str, str]] = []

    class FakeForm:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeAgiEnv:
        def __init__(self):
            self.envars = {}

        @staticmethod
        def set_env_var(_name, _value):
            return None

    env_obj = FakeAgiEnv()
    fake_st = types.SimpleNamespace(
        session_state={"openai_api_key": "cached", "env": env_obj},
        warning=lambda message: events.append(("warning", str(message))),
        form=lambda _key: FakeForm(),
        text_input=lambda *args, **kwargs: "sk-updated-value-999999",
        checkbox=lambda *args, **kwargs: True,
        form_submit_button=lambda *args, **kwargs: True,
        error=lambda message: events.append(("error", str(message))),
        success=lambda message: events.append(("success", str(message))),
        rerun=lambda: events.append(("rerun", "")),
        stop=lambda: (_ for _ in ()).throw(RuntimeError("stopped")),
    )
    monkeypatch.setattr(pipeline_openai, "st", fake_st)
    monkeypatch.setitem(sys.modules, "agi_env", types.SimpleNamespace(AgiEnv=FakeAgiEnv))
    monkeypatch.setattr(
        pipeline_openai,
        "persist_env_var",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(RuntimeError, match="stopped"):
        pipeline_openai.prompt_for_openai_api_key("Missing key")

    assert env_obj.envars["OPENAI_API_KEY"] == "sk-updated-value-999999"
    assert ("warning", "Could not persist API key: disk full") in events


def test_prompt_for_openai_api_key_stops_when_form_not_submitted(monkeypatch):
    events: list[tuple[str, str]] = []
    checkbox_kwargs: dict[str, object] = {}

    class FakeForm:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_st = types.SimpleNamespace(
        session_state={"openai_api_key": "cached"},
        warning=lambda message: events.append(("warning", str(message))),
        form=lambda _key: FakeForm(),
        text_input=lambda *args, **kwargs: "sk-unused-value-123456",
        checkbox=lambda *args, **kwargs: checkbox_kwargs.update(kwargs) or False,
        form_submit_button=lambda *args, **kwargs: False,
        error=lambda message: events.append(("error", str(message))),
        success=lambda message: events.append(("success", str(message))),
        rerun=lambda: events.append(("rerun", "")),
        stop=lambda: (_ for _ in ()).throw(RuntimeError("stopped")),
    )
    monkeypatch.setattr(pipeline_openai, "st", fake_st)

    with pytest.raises(RuntimeError, match="stopped"):
        pipeline_openai.prompt_for_openai_api_key("Missing key")

    assert ("warning", "Missing key") in events
    assert checkbox_kwargs["value"] is False
    assert not any(kind in {"error", "success", "rerun"} for kind, _ in events)


def test_make_openai_client_and_model_azure_falls_back_to_openai_client(monkeypatch):
    captured = {}

    class _OpenAIClient:
        def __init__(self, **kwargs):
            captured["openai"] = kwargs

    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = _OpenAIClient
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-secret")

    client, model_name, is_azure = pipeline_openai.make_openai_client_and_model(
        {"OPENAI_BASE_URL": "https://proxy.example/v1", "OPENAI_MODEL": "azure-deploy"},
        "azure-secret",
    )

    assert isinstance(client, _OpenAIClient)
    assert model_name == "azure-deploy"
    assert is_azure is True
    assert captured["openai"] == {
        "api_key": "azure-secret",
        "base_url": "https://proxy.example/v1",
    }


def test_make_openai_client_and_model_module_fallback_without_base_url(monkeypatch):
    fake_openai = types.ModuleType("openai")
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_TYPE", raising=False)

    client, model_name, is_azure = pipeline_openai.make_openai_client_and_model({}, "module-secret")

    assert client is fake_openai
    assert model_name
    assert is_azure is False
    assert fake_openai.api_key == "module-secret"
    assert not hasattr(fake_openai, "api_base")


def test_make_openai_client_and_model_reports_missing_optional_ai_extra(monkeypatch):
    real_import = builtins.__import__

    def import_without_openai(name, *args, **kwargs):
        if name == "openai":
            raise ImportError("missing openai")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_openai)

    with pytest.raises(ImportError, match=r"agilab\[ai\]"):
        pipeline_openai.make_openai_client_and_model({}, "openai-secret")
