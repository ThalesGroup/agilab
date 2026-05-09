"""Public Streamlit bind guard shared by CLI and direct page launches."""

from __future__ import annotations

import os
from typing import Callable, Mapping


EXPOSED_UI_HOSTS = {"0.0.0.0", "::"}
DEFAULT_STREAMLIT_HOST = "127.0.0.1"
PUBLIC_BIND_OK_ENV = "AGILAB_PUBLIC_BIND_OK"
PUBLIC_BIND_CONTROL_ENVS = (
    "AGILAB_AUTH_REQUIRED",
    "AGILAB_PUBLIC_AUTH",
    "AGILAB_TLS_TERMINATED",
    "STREAMLIT_AUTH_REQUIRED",
)


class PublicBindPolicyError(RuntimeError):
    """Raised when AGILAB would expose its Streamlit UI without controls."""


def truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def configured_streamlit_host(
    environ: Mapping[str, str] | None = None,
    *,
    streamlit_config_getter: Callable[[str], object] | None = None,
) -> str:
    env = environ or os.environ
    env_host = str(env.get("AGILAB_UI_HOST") or env.get("STREAMLIT_SERVER_ADDRESS") or "").strip()
    if env_host:
        return env_host

    if streamlit_config_getter is not None:
        try:
            config_host = streamlit_config_getter("server.address")
        except Exception:
            config_host = None
        if config_host is not None and str(config_host).strip():
            return str(config_host).strip()

    return DEFAULT_STREAMLIT_HOST


def public_bind_has_controls(environ: Mapping[str, str] | None = None) -> bool:
    env = environ or os.environ
    return truthy(env.get(PUBLIC_BIND_OK_ENV)) and any(
        truthy(env.get(name)) for name in PUBLIC_BIND_CONTROL_ENVS
    )


def public_bind_error_message(host: str) -> str:
    return (
        f"AGILAB refuses to bind the Streamlit UI publicly on {host!r} without explicit protection. "
        "Use the default 127.0.0.1 bind, or set AGILAB_PUBLIC_BIND_OK=1 together with "
        "an auth/TLS indicator such as AGILAB_TLS_TERMINATED=1."
    )


def enforce_public_bind_policy(
    environ: Mapping[str, str] | None = None,
    *,
    streamlit_config_getter: Callable[[str], object] | None = None,
) -> str:
    """Return the Streamlit host to use or fail before exposing the UI."""
    host = configured_streamlit_host(environ, streamlit_config_getter=streamlit_config_getter)
    if host in EXPOSED_UI_HOSTS and not public_bind_has_controls(environ):
        raise PublicBindPolicyError(public_bind_error_message(host))
    return host
