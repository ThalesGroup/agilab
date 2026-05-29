import os
from shlex import quote
from typing import Any


UV_INDEX_RESOLVER_ENV_VARS = ("UV_INDEX_URL", "UV_EXTRA_INDEX_URL")
UV_WHEELHOUSE_RESOLVER_ENV_VARS = ("UV_FIND_LINKS",)
UV_RESOLVER_PROPAGATED_ENV_VARS = (
    "UV_INDEX_URL",
    "UV_EXTRA_INDEX_URL",
    "UV_FIND_LINKS",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "UV_NATIVE_TLS",
)


def _shell_env_prefix(env_overrides: dict[str, str], *, os_name: str = os.name) -> str:
    if not env_overrides:
        return ""
    if os_name == "nt":
        return "".join(
            f'set "{key}={value}" && ' for key, value in env_overrides.items()
        )
    return "".join(f"{key}={quote(value)} " for key, value in env_overrides.items())


def _envar_value(envars: Any, key: str) -> Any:
    raw = os.environ.get(key)
    if raw is None:
        try:
            raw = envars.get(key)
        except (AttributeError, RuntimeError, TypeError):
            raw = None
    return raw


def _envar_nonempty(envars: Any, key: str) -> bool:
    raw = _envar_value(envars, key)
    if raw is None:
        return False
    normalized = str(raw).strip().strip("\"'").strip()
    return bool(normalized) and normalized.casefold() not in {"none", "null"}


def _uv_resolver_mode(envars: Any) -> str:
    if any(_envar_nonempty(envars, key) for key in UV_INDEX_RESOLVER_ENV_VARS):
        return "mirror"
    if any(_envar_nonempty(envars, key) for key in UV_WHEELHOUSE_RESOLVER_ENV_VARS):
        return "wheelhouse"
    raw = _envar_value(envars, "AGI_INTERNET_ON")
    if raw is None:
        return "online"
    if isinstance(raw, bool):
        return "online" if raw else "cache-only"
    if isinstance(raw, (int, float)):
        try:
            return "online" if int(raw) == 1 else "cache-only"
        except (TypeError, ValueError):
            return "cache-only"
    normalized = str(raw).strip().strip("\"'").strip().lower()
    return "online" if normalized in {"1", "true", "yes", "on"} else "cache-only"


def _uv_resolver_env_prefix(envars: Any, *, os_name: str = os.name) -> str:
    values: dict[str, str] = {}
    for key in UV_RESOLVER_PROPAGATED_ENV_VARS:
        if _envar_nonempty(envars, key):
            values[key] = str(_envar_value(envars, key)).strip().strip("\"'").strip()
    return _shell_env_prefix(values, os_name=os_name)


def _uv_offline_flag(envars: Any) -> str:
    mode = _uv_resolver_mode(envars)
    if mode in {"online", "mirror"}:
        return ""
    if mode == "wheelhouse":
        return "--offline "
    raw = _envar_value(envars, "AGI_INTERNET_ON")
    if isinstance(raw, bool):
        return "" if raw else "--offline "
    if isinstance(raw, (int, float)):
        try:
            return "" if int(raw) == 1 else "--offline "
        except (TypeError, ValueError):
            return "--offline "
    normalized = str(raw).strip().strip("\"'").strip().lower()
    return "" if normalized in {"1", "true", "yes", "on"} else "--offline "


def _local_worker_post_install_env_prefix(
    agi_cls: Any, *, os_name: str = os.name
) -> str:
    mode = int(getattr(agi_cls, "_mode", 0) or 0)
    dask_mode = int(getattr(agi_cls, "DASK_MODE", 0) or 0)
    if dask_mode and (mode & dask_mode):
        return ""
    return _shell_env_prefix({"AGI_CLUSTER_ENABLED": "0"}, os_name=os_name)

