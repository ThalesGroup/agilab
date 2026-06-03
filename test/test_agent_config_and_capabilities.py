from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAPABILITY_MODULE_PATH = ROOT / "src" / "agilab" / "agent_provider_capabilities.py"
CONFIG_MODULE_PATH = ROOT / "src" / "agilab" / "agent_config.py"


def _load_capability_module():
    previous_package = sys.modules.get("agilab")
    sys.modules.pop("agilab.agent_provider_capabilities", None)
    package = types.ModuleType("agilab")
    package.__path__ = [str(ROOT / "src" / "agilab")]  # type: ignore[attr-defined]
    package.__file__ = str(ROOT / "src" / "agilab" / "__init__.py")
    package.__package__ = "agilab"
    sys.modules["agilab"] = package
    spec = importlib.util.spec_from_file_location("agilab.agent_provider_capabilities", CAPABILITY_MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous_package is None:
            sys.modules.pop("agilab", None)
        else:
            sys.modules["agilab"] = previous_package
    return module


def _load_config_module():
    previous_package = sys.modules.get("agilab")
    previous_capability = sys.modules.get("agilab.agent_provider_capabilities")
    sys.modules.pop("agilab.agent_config", None)
    package = types.ModuleType("agilab")
    package.__path__ = [str(ROOT / "src" / "agilab")]  # type: ignore[attr-defined]
    package.__file__ = str(ROOT / "src" / "agilab" / "__init__.py")
    package.__package__ = "agilab"
    sys.modules["agilab"] = package
    _load_capability_module()
    spec = importlib.util.spec_from_file_location("agilab.agent_config", CONFIG_MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous_capability is None:
            sys.modules.pop("agilab.agent_provider_capabilities", None)
        else:
            sys.modules["agilab.agent_provider_capabilities"] = previous_capability
        if previous_package is None:
            sys.modules.pop("agilab", None)
        else:
            sys.modules["agilab"] = previous_package
    return module


def test_provider_capability_infers_and_overrides_model_features() -> None:
    module = _load_capability_module()

    openai = module.resolve_provider_capability(model="gpt-5")
    local = module.resolve_provider_capability(model="qwen2.5-coder:latest")
    overridden = module.resolve_provider_capability(
        "openai-compatible",
        "private-model",
        overrides={
            "context_window": "65536",
            "max_output_tokens": 4096,
            "supports_reasoning": "true",
            "supports_image_input": "false",
        },
    )

    assert openai.provider == "openai"
    assert module.default_model_for_provider("openai") == "gpt-5.4-mini"
    assert openai.supports_reasoning is True
    assert openai.supports_image_input is True
    assert local.provider == "ollama"
    assert local.supports_pdf_input is False
    assert overridden.provider == "openai-compatible"
    assert overridden.context_window == 65536
    assert overridden.max_output_tokens == 4096
    assert overridden.supports_reasoning is True
    assert overridden.supports_image_input is False
    assert overridden.source == "override"


def test_provider_capability_aliases_defaults_and_invalid_overrides() -> None:
    module = _load_capability_module()

    assert module.normalize_provider("azure_openai") == "openai"
    assert module.normalize_provider("mistralai") == "mistral"
    assert module.normalize_provider("vllm") == "openai-compatible"
    assert module.normalize_provider("gptoss") == "gpt-oss"
    assert module.normalize_provider("uoaic") == "ollama"
    assert module.normalize_provider("local_llm") == "local"
    assert module.normalize_provider("custom_provider") == "custom-provider"
    assert module.normalize_provider(None, "gpt-oss-20b") == "gpt-oss"
    assert module.normalize_provider(None, "text-embedding-3-large") == "openai"
    assert module.normalize_provider(None, "ministral-8b") == "mistral"
    assert module.normalize_provider(None, "deepseek-r1") == "ollama"
    assert module.normalize_provider(None, "") == "local"
    assert module.default_model_for_provider("custom_provider") == "custom-provider"

    openai_legacy = module.resolve_provider_capability("openai", "gpt-4.1")
    mistral_alias = module.resolve_provider_capability("mistralai", "mistral-large-latest")
    unknown = module.resolve_provider_capability(
        "private_provider",
        "",
        overrides={
            "context_window": True,
            "max_output_tokens": "0",
            "supports_reasoning": True,
            "supports_image_input": "off",
            "supports_pdf_input": "maybe",
        },
    )

    assert openai_legacy.source == "model-default"
    assert openai_legacy.supports_reasoning is False
    assert openai_legacy.supports_pdf_input is True
    assert mistral_alias.provider == "mistral"
    assert mistral_alias.source == "provider-default"
    assert mistral_alias.supports_reasoning is False
    assert unknown.as_dict() == {
        "schema": module.CAPABILITY_SCHEMA,
        "provider": "private-provider",
        "model": "private-provider",
        "context_window": None,
        "max_output_tokens": None,
        "supports_reasoning": True,
        "supports_image_input": False,
        "supports_pdf_input": None,
        "source": "override",
    }


def test_agent_config_layers_global_and_project_files(tmp_path: Path) -> None:
    module = _load_config_module()
    home = tmp_path / "home"
    project = tmp_path / "repo"
    child = project / "sub"
    (project / ".git").mkdir(parents=True)
    (project / ".agilab").mkdir()
    (home).mkdir()
    child.mkdir(parents=True)
    (home / module.CONFIG_FILENAME).write_text(
        json.dumps(
            {
                "default": {"provider": "openai-main", "model": "gpt-5"},
                "permission": {"level": "readonly"},
                "providers": {
                    "openai-main": {
                        "type": "openai",
                        "model": "gpt-5",
                        "api_key_env": "OPENAI_API_KEY",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (project / ".agilab" / module.CONFIG_FILENAME).write_text(
        json.dumps(
            {
                "default": {"provider": "local-code"},
                "permission": {"level": "standard"},
                "trace": {"enabled": False},
                "providers": {
                    "local-code": {
                        "type": "ollama",
                        "model": "qwen2.5-coder:latest",
                        "capability": {"context_window": 32768},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    config = module.load_agent_config(child, environ={module.AGENT_HOME_ENV: str(home)})
    provider = module.resolve_agent_provider(config)

    assert [path.name for path in config.config_paths] == [module.CONFIG_FILENAME, module.CONFIG_FILENAME]
    assert config.default_provider == "local-code"
    assert config.default_model == "gpt-5"
    assert config.permission_level == "standard"
    assert config.trace_enabled is False
    assert config.providers["openai-main"].api_key_env_var == "OPENAI_API_KEY"
    assert provider.name == "local-code"
    assert provider.provider == "ollama"
    assert provider.model == "qwen2.5-coder:latest"
    assert provider.capability.context_window == 32768


def test_agent_config_handles_missing_or_invalid_files(tmp_path: Path) -> None:
    module = _load_config_module()

    config = module.load_agent_config(tmp_path, environ={module.AGENT_HOME_ENV: str(tmp_path / "missing")})
    provider = module.resolve_agent_provider(config, provider="gpt-oss", model="gpt-oss-120b")

    assert config.schema == module.CONFIG_SCHEMA
    assert config.config_paths == ()
    assert config.permission_level == "safe"
    assert provider.provider == "gpt-oss"
    assert provider.capability.supports_reasoning is True


def test_agent_config_covers_string_forms_and_fallbacks(tmp_path: Path) -> None:
    module = _load_config_module()
    home = tmp_path / "home"
    project = tmp_path / "project"
    leaf = project / "nested"
    home.mkdir()
    (project / ".git").mkdir(parents=True)
    (project / ".agilab").mkdir()
    leaf.mkdir(parents=True)
    (home / module.CONFIG_FILENAME).write_text("{not json", encoding="utf-8")
    (project / ".agilab" / module.CONFIG_FILENAME).write_text(
        json.dumps(
            {
                "default_provider": "remote",
                "default_model": "gpt-4.1",
                "permission_level": "yolo",
                "trace_enabled": "off",
                "providers": {
                    "remote": {
                        "provider": "azure-openai",
                        "model": "gpt-4.1",
                        "base_url": "https://example.invalid",
                        "api_key": "${REMOTE_API_KEY}",
                    },
                    "ignored": "not a dict",
                },
            }
        ),
        encoding="utf-8",
    )

    config = module.load_agent_config(leaf, environ={module.AGENT_HOME_ENV: str(home)})
    provider = module.resolve_agent_provider(config)

    assert config.permission_level == "operator"
    assert config.trace_enabled is False
    assert sorted(config.providers) == ["remote"]
    assert provider.name == "remote"
    assert provider.provider == "openai"
    assert provider.model == "gpt-4.1"
    assert provider.base_url == "https://example.invalid"
    assert provider.api_key_env_var == "REMOTE_API_KEY"
    assert module.project_dirs(tmp_path, project=tmp_path / "outside" / "root")[0] == Path(tmp_path.anchor)
    assert module._as_bool("yes", False) is True
    assert module._as_bool("maybe", False) is False
