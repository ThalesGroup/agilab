"""Credential storage helpers with optional keyring support."""

from __future__ import annotations

import getpass
import os
from typing import Any, Mapping


CLUSTER_CREDENTIALS_KEY = "CLUSTER_CREDENTIALS"
KEYRING_SENTINEL = "__KEYRING__"
KEYRING_SERVICE_ENV = "AGILAB_KEYRING_SERVICE"
KEYRING_ACCOUNT_ENV = "AGILAB_KEYRING_ACCOUNT"
DEFAULT_KEYRING_SERVICE = "agilab"
_KEYRING_USERNAME_SUFFIX = "cluster_credentials"


def _normalize(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _keyring_username(account: str) -> str:
    return f"{account}:{_KEYRING_USERNAME_SUFFIX}"


def _resolve_keyring_config(
    *,
    environ: Mapping[str, str],
    default_account: str | None,
) -> tuple[str, str]:
    service = _normalize(environ.get(KEYRING_SERVICE_ENV)) or DEFAULT_KEYRING_SERVICE
    account = _normalize(environ.get(KEYRING_ACCOUNT_ENV)) or _normalize(default_account) or getpass.getuser()
    return service, account


def _load_keyring_module(keyring_module: Any = None) -> Any:
    if keyring_module is not None:
        return keyring_module
    try:
        import keyring  # type: ignore
    except ImportError:
        return None
    return keyring


def _fallback_env_credentials(environ: Mapping[str, str]) -> str:
    fallback = _normalize(environ.get(CLUSTER_CREDENTIALS_KEY))
    if fallback == KEYRING_SENTINEL:
        return ""
    return fallback


def _keyring_error_types(keyring: Any) -> tuple[type[BaseException], ...]:
    error_types: list[type[BaseException]] = [AttributeError, RuntimeError, TypeError, ValueError]
    errors_module = getattr(keyring, "errors", None)
    for attr_name in ("KeyringError", "InitError"):
        exc_type = getattr(errors_module, attr_name, None)
        if isinstance(exc_type, type) and issubclass(exc_type, BaseException):
            error_types.append(exc_type)

    unique_error_types: list[type[BaseException]] = []
    for exc_type in error_types:
        if exc_type not in unique_error_types:
            unique_error_types.append(exc_type)
    return tuple(unique_error_types)


def read_cluster_credentials(
    raw_value: object,
    *,
    environ: Mapping[str, str] = os.environ,
    default_account: str | None = None,
    keyring_module: Any = None,
    logger: Any = None,
) -> str:
    """Resolve cluster credentials from plain env value or keyring sentinel."""

    normalized = _normalize(raw_value)
    fallback_value = _fallback_env_credentials(environ)
    if normalized and normalized != KEYRING_SENTINEL:
        return normalized
    if normalized != KEYRING_SENTINEL:
        return fallback_value

    keyring = _load_keyring_module(keyring_module)
    if keyring is None:
        return fallback_value

    service, account = _resolve_keyring_config(environ=environ, default_account=default_account)
    username = _keyring_username(account)
    keyring_errors = _keyring_error_types(keyring)
    try:
        secret = keyring.get_password(service, username)
    except keyring_errors as exc:  # pragma: no cover - backend specific
        if logger:
            logger.warning("Unable to read cluster credentials from keyring: %s", exc)
        return fallback_value
    return _normalize(secret) or fallback_value


def store_cluster_credentials(
    secret: object,
    *,
    environ: Mapping[str, str] = os.environ,
    default_account: str | None = None,
    keyring_module: Any = None,
    logger: Any = None,
) -> bool:
    """Persist cluster credentials to keyring when available."""

    normalized = _normalize(secret)
    if not normalized:
        return False

    keyring = _load_keyring_module(keyring_module)
    if keyring is None:
        return False

    service, account = _resolve_keyring_config(environ=environ, default_account=default_account)
    username = _keyring_username(account)
    keyring_errors = _keyring_error_types(keyring)
    try:
        keyring.set_password(service, username, normalized)
    except keyring_errors as exc:  # pragma: no cover - backend specific
        if logger:
            logger.warning("Unable to store cluster credentials in keyring: %s", exc)
        return False
    return True
