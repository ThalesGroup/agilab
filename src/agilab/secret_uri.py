# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Secret-reference helpers for AGILAB runtime configuration.

The helpers deliberately resolve only explicit secret URI schemes. Plain strings
are not treated as secrets, because silent fallbacks make credential handling hard
to audit.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any, Callable, Mapping
from urllib.parse import urlparse


SECRET_URI_SCHEMES = frozenset({"env", "secret", "vault"})
LEGACY_ENV_PREFIX = "env:"
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b((?=[A-Za-z_][A-Za-z0-9_]*=)(?=[A-Za-z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|KEY|CREDENTIAL|AUTH))[A-Za-z_][A-Za-z0-9_]*)=([^\s]+)",
    re.IGNORECASE,
)
_SECRET_URI_TEXT_RE = re.compile(r"\b(?:env|secret|vault)://[^\s,;]+")
_SECRET_KEY_RE = re.compile(r"(SECRET|TOKEN|PASSWORD|PASSWD|KEY|CREDENTIAL|AUTH)", re.IGNORECASE)


class SecretUriError(ValueError):
    """Raised when a secret reference cannot be parsed or resolved safely."""


@dataclass(frozen=True)
class SecretReference:
    """Parsed secret reference metadata without the resolved secret value."""

    raw: str
    scheme: str
    name: str
    display: str


KeyringGetter = Callable[[str, str], str | None]
VaultResolver = Callable[[str], str | None]


def is_secret_uri(value: object) -> bool:
    """Return whether *value* uses an AGILAB-supported secret URI scheme."""
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in SECRET_URI_SCHEMES and "://" in value


def is_env_ref(value: object) -> bool:
    """Return whether *value* is a legacy or URI environment reference."""
    if not isinstance(value, str):
        return False
    return bool(credential_env_name(value))


def credential_env_name(ref: str) -> str:
    """Extract the environment variable name from ``env:NAME`` or ``env://NAME``."""
    if ref.startswith("env://"):
        try:
            parsed = parse_secret_uri(ref)
        except SecretUriError:
            return ""
        if parsed.scheme != "env":
            return ""
        name = parsed.name
    elif ref.startswith(LEGACY_ENV_PREFIX):
        name = ref.removeprefix(LEGACY_ENV_PREFIX)
    else:
        return ""
    return name if _ENV_NAME_RE.fullmatch(name) else ""


def is_credential_ref(value: object) -> bool:
    """Return whether *value* is a credential reference, not a raw credential."""
    if is_env_ref(value):
        return True
    if not is_secret_uri(value):
        return False
    try:
        parse_secret_uri(str(value))
    except SecretUriError:
        return False
    return True


def parse_secret_uri(ref: str) -> SecretReference:
    """Parse a supported secret URI and return non-secret metadata."""
    if not isinstance(ref, str) or "://" not in ref:
        raise SecretUriError("secret reference must use env://, secret://, or vault://")
    parsed = urlparse(ref)
    if parsed.scheme not in SECRET_URI_SCHEMES:
        raise SecretUriError(f"unsupported secret URI scheme: {parsed.scheme or '(missing)'}")
    if parsed.scheme == "env":
        name = parsed.netloc or parsed.path.lstrip("/")
        if not _ENV_NAME_RE.fullmatch(name):
            raise SecretUriError(f"invalid environment secret reference: {redact_text(ref)}")
        return SecretReference(raw=ref, scheme="env", name=name, display=f"env://{name}")
    if parsed.scheme == "secret":
        service = parsed.netloc.strip()
        account = parsed.path.strip("/")
        if not service or not account:
            raise SecretUriError("secret:// references must use secret://service/account")
        return SecretReference(
            raw=ref,
            scheme="secret",
            name=f"{service}/{account}",
            display=f"secret://{service}/{account}",
        )
    vault_path = f"{parsed.netloc}{parsed.path}"
    if parsed.fragment:
        vault_path = f"{vault_path}#{parsed.fragment}"
    if not vault_path.strip("/"):
        raise SecretUriError("vault:// references must include a vault path")
    return SecretReference(
        raw=ref,
        scheme="vault",
        name=vault_path,
        display=f"vault://{vault_path}",
    )


def _default_keyring_getter(service: str, account: str) -> str | None:
    try:
        import keyring  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on optional package
        raise SecretUriError("secret:// requires the optional keyring package or a keyring_getter") from exc
    return keyring.get_password(service, account)


def resolve_secret_uri(
    ref: str,
    *,
    environ: Mapping[str, str] | None = None,
    keyring_getter: KeyringGetter | None = None,
    vault_resolver: VaultResolver | None = None,
) -> str:
    """Resolve an explicit secret URI to its value.

    Supported schemes:
    - ``env://NAME`` reads an environment variable.
    - ``secret://service/account`` reads a keyring entry.
    - ``vault://path#field`` delegates to the supplied ``vault_resolver``.
    """
    parsed = parse_secret_uri(ref)
    if parsed.scheme == "env":
        env = os.environ if environ is None else environ
        value = env.get(parsed.name)
        if value is None:
            raise SecretUriError(f"secret reference is not set: {parsed.display}")
        return value
    if parsed.scheme == "secret":
        service, account = parsed.name.split("/", 1)
        getter = keyring_getter or _default_keyring_getter
        value = getter(service, account)
        if value is None:
            raise SecretUriError(f"secret reference is not set: {parsed.display}")
        return value
    if vault_resolver is None:
        raise SecretUriError("vault:// requires an explicit vault_resolver")
    value = vault_resolver(parsed.name)
    if value is None:
        raise SecretUriError(f"secret reference is not set: {parsed.display}")
    return value


def redact_text(text: object) -> str:
    """Redact obvious secret assignments and supported secret URI occurrences."""
    value = str(text)
    value = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=<redacted>", value)
    return _SECRET_URI_TEXT_RE.sub("<secret-ref>", value)


def redact_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of a mapping with secret-like keys and refs redacted."""
    redacted: dict[str, Any] = {}
    for key, value in values.items():
        key_text = str(key)
        if _SECRET_KEY_RE.search(key_text):
            redacted[key_text] = "<redacted>"
        elif isinstance(value, Mapping):
            redacted[key_text] = redact_mapping(value)
        elif isinstance(value, list):
            redacted[key_text] = [
                redact_mapping(item) if isinstance(item, Mapping) else redact_text(item)
                for item in value
            ]
        else:
            redacted[key_text] = redact_text(value) if is_secret_uri(value) else value
    return redacted
