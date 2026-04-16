from __future__ import annotations

import builtins

from agi_env.credential_store_support import (
    KEYRING_SENTINEL,
    read_cluster_credentials,
    store_cluster_credentials,
)
import agi_env.credential_store_support as credential_support


class _FakeKeyring:
    def __init__(self):
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password


class _FailingKeyring:
    def get_password(self, service: str, username: str) -> str | None:
        raise RuntimeError("backend read failed")

    def set_password(self, service: str, username: str, password: str) -> None:
        raise RuntimeError("backend write failed")


def test_read_cluster_credentials_prefers_plain_value():
    value = read_cluster_credentials("user:pass")
    assert value == "user:pass"


def test_read_cluster_credentials_uses_keyring_for_sentinel():
    keyring = _FakeKeyring()
    keyring.set_password("agilab", "alice:cluster_credentials", "alice:secret")

    value = read_cluster_credentials(
        KEYRING_SENTINEL,
        keyring_module=keyring,
        environ={},
        default_account="alice",
    )

    assert value == "alice:secret"


def test_read_cluster_credentials_returns_empty_without_keyring():
    value = read_cluster_credentials(KEYRING_SENTINEL, keyring_module=object(), environ={})
    assert value == ""


def test_read_cluster_credentials_keeps_env_fallback_when_keyring_missing():
    value = read_cluster_credentials(
        KEYRING_SENTINEL,
        keyring_module=object(),
        environ={"CLUSTER_CREDENTIALS": "fallback:user"},
    )
    assert value == "fallback:user"


def test_read_cluster_credentials_keeps_env_fallback_when_keyring_read_fails():
    value = read_cluster_credentials(
        KEYRING_SENTINEL,
        keyring_module=_FailingKeyring(),
        environ={"CLUSTER_CREDENTIALS": "fallback:user"},
    )
    assert value == "fallback:user"


def test_store_cluster_credentials_returns_false_without_keyring():
    assert store_cluster_credentials("user:pass", keyring_module=object(), environ={}) is False


def test_store_cluster_credentials_returns_false_when_backend_fails():
    assert store_cluster_credentials("user:pass", keyring_module=_FailingKeyring(), environ={}) is False


def test_store_cluster_credentials_persists_with_keyring_and_custom_config():
    keyring = _FakeKeyring()
    environ = {
        "AGILAB_KEYRING_SERVICE": "agilab-tests",
        "AGILAB_KEYRING_ACCOUNT": "bob",
    }

    stored = store_cluster_credentials(
        "bob:secret",
        keyring_module=keyring,
        environ=environ,
        default_account="ignored",
    )

    assert stored is True
    assert keyring.get_password("agilab-tests", "bob:cluster_credentials") == "bob:secret"


def test_store_cluster_credentials_ignores_empty_values():
    keyring = _FakeKeyring()
    assert store_cluster_credentials("", keyring_module=keyring, environ={}) is False


def test_credential_store_support_helper_branches(monkeypatch):
    original_import = builtins.__import__

    def _missing_keyring_import(name, *args, **kwargs):
        if name == "keyring":
            raise ImportError("missing keyring")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _missing_keyring_import)
    try:
        assert credential_support._load_keyring_module() is None
    finally:
        builtins.__import__ = original_import

    keyring_module = object()
    assert credential_support._load_keyring_module(keyring_module) is keyring_module
    assert credential_support._fallback_env_credentials({"CLUSTER_CREDENTIALS": KEYRING_SENTINEL}) == ""

    class _Errors:
        KeyringError = RuntimeError
        InitError = RuntimeError

    keyring = type("Keyring", (), {"errors": _Errors})()
    errors = credential_support._keyring_error_types(keyring)
    assert RuntimeError in errors
    assert errors.count(RuntimeError) == 1


def test_read_and_store_cluster_credentials_cover_keyring_none_paths(monkeypatch):
    monkeypatch.setattr(credential_support, "_load_keyring_module", lambda _module=None: None)

    assert read_cluster_credentials(
        KEYRING_SENTINEL,
        keyring_module=None,
        environ={"CLUSTER_CREDENTIALS": "fallback:user"},
    ) == "fallback:user"

    assert store_cluster_credentials(
        "user:pass",
        keyring_module=None,
        environ={},
    ) is False
