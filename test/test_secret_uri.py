from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "agilab" / "secret_uri.py"


def _load_module():
    previous_package = sys.modules.get("agilab")
    sys.modules.pop("agilab.secret_uri", None)
    package = types.ModuleType("agilab")
    package.__path__ = [str(ROOT / "src" / "agilab")]  # type: ignore[attr-defined]
    package.__file__ = str(ROOT / "src" / "agilab" / "__init__.py")
    package.__package__ = "agilab"
    sys.modules["agilab"] = package
    spec = importlib.util.spec_from_file_location("agilab.secret_uri", MODULE_PATH)
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


def test_env_secret_uri_resolves_without_logging_value() -> None:
    module = _load_module()
    value = module.resolve_secret_uri("env://OPENAI_API_KEY", environ={"OPENAI_API_KEY": "sk-secret"})
    parsed = module.parse_secret_uri("env://OPENAI_API_KEY")

    assert value == "sk-secret"
    assert parsed.display == "env://OPENAI_API_KEY"
    assert "sk-secret" not in repr(parsed)


def test_env_secret_uri_missing_fails_without_secret_value() -> None:
    module = _load_module()
    with pytest.raises(module.SecretUriError) as excinfo:
        module.resolve_secret_uri("env://OPENAI_API_KEY", environ={})

    message = str(excinfo.value)
    assert "env://OPENAI_API_KEY" in message
    assert "sk-" not in message


def test_secret_and_vault_uri_resolution_use_explicit_resolvers() -> None:
    module = _load_module()
    assert (
        module.resolve_secret_uri(
            "secret://agilab/openai",
            keyring_getter=lambda service, account: f"{service}:{account}:value",
        )
        == "agilab:openai:value"
    )
    assert (
        module.resolve_secret_uri(
            "vault://kv/agilab#OPENAI_API_KEY",
            vault_resolver=lambda name: f"{name}:value",
        )
        == "kv/agilab#OPENAI_API_KEY:value"
    )


def test_secret_uri_helpers_fail_closed_for_plain_or_unsupported_values() -> None:
    module = _load_module()
    assert module.is_secret_uri("env://TOKEN")
    assert not module.is_secret_uri(None)
    assert module.is_env_ref("env:TOKEN")
    assert not module.is_env_ref(None)
    assert module.credential_env_name("env://TOKEN") == "TOKEN"
    assert module.credential_env_name("env:TOKEN") == "TOKEN"
    assert module.credential_env_name("env://1INVALID") == ""
    assert module.credential_env_name("env:1INVALID") == ""
    assert module.is_credential_ref("secret://agilab/token")
    assert module.is_credential_ref("env:TOKEN")
    assert not module.is_credential_ref("env://1INVALID")
    assert not module.is_credential_ref("TOKEN=abc")

    with pytest.raises(module.SecretUriError, match="secret reference must use"):
        module.resolve_secret_uri("plain-secret")
    with pytest.raises(module.SecretUriError, match="unsupported secret URI scheme"):
        module.resolve_secret_uri("aws-sm://prod/key")
    with pytest.raises(module.SecretUriError, match="invalid environment secret reference"):
        module.parse_secret_uri("env://1INVALID")
    with pytest.raises(module.SecretUriError, match="secret:// references must use"):
        module.parse_secret_uri("secret://agilab")
    with pytest.raises(module.SecretUriError, match="vault:// references must include"):
        module.parse_secret_uri("vault://")
    with pytest.raises(module.SecretUriError, match="vault:// requires"):
        module.resolve_secret_uri("vault://kv/agilab#token")


def test_secret_uri_resolvers_fail_when_reference_is_unset() -> None:
    module = _load_module()

    with pytest.raises(module.SecretUriError) as secret_exc:
        module.resolve_secret_uri(
            "secret://agilab/openai",
            keyring_getter=lambda _service, _account: None,
        )
    with pytest.raises(module.SecretUriError) as vault_exc:
        module.resolve_secret_uri(
            "vault://kv/agilab#OPENAI_API_KEY",
            vault_resolver=lambda _name: None,
        )

    assert "secret://agilab/openai" in str(secret_exc.value)
    assert "vault://kv/agilab#OPENAI_API_KEY" in str(vault_exc.value)


def test_vault_uri_without_fragment_keeps_non_secret_display_metadata() -> None:
    module = _load_module()

    parsed = module.parse_secret_uri("vault://kv/agilab/openai")

    assert parsed.scheme == "vault"
    assert parsed.name == "kv/agilab/openai"
    assert parsed.display == "vault://kv/agilab/openai"
    assert "openai-secret-value" not in repr(parsed)


def test_redaction_helpers_remove_secret_values_and_secret_refs() -> None:
    module = _load_module()
    payload = {
        "OPENAI_API_KEY": "sk-real-secret",
        "safe": "value",
        "nested": {"token_ref": "env://OPENAI_API_KEY"},
        "items": ["TOKEN=abc123", {"password": "abc123"}],
    }

    redacted = module.redact_mapping(payload)
    text = module.redact_text("OPENAI_API_KEY=sk-real-secret via env://OPENAI_API_KEY")

    assert redacted["OPENAI_API_KEY"] == "<redacted>"
    assert redacted["safe"] == "value"
    assert redacted["nested"]["token_ref"] == "<redacted>"
    assert redacted["items"][0] == "TOKEN=<redacted>"
    assert redacted["items"][1]["password"] == "<redacted>"
    assert "sk-real-secret" not in text
    assert "env://OPENAI_API_KEY" not in text
