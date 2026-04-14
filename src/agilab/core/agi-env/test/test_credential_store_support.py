from __future__ import annotations

from agi_env.credential_store_support import (
    KEYRING_SENTINEL,
    read_cluster_credentials,
    store_cluster_credentials,
)


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
