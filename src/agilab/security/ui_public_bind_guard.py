"""Public Streamlit bind guard shared by CLI and direct page launches."""

from __future__ import annotations

import ipaddress
import os
from typing import Callable, Mapping


EXPOSED_UI_HOSTS = {"0.0.0.0", "::"}
LOOPBACK_HOSTNAMES = {"", "localhost", "localhost.localdomain"}
DEFAULT_STREAMLIT_HOST = "127.0.0.1"
PUBLIC_BIND_OK_ENV = "AGILAB_PUBLIC_BIND_OK"
PUBLIC_BIND_EVIDENCE_ENV = "AGILAB_PUBLIC_BIND_EVIDENCE"
PUBLIC_BIND_CONTROL_ENVS = (
    "AGILAB_AUTH_REQUIRED",
    "AGILAB_PUBLIC_AUTH",
    "AGILAB_TLS_TERMINATED",
    "STREAMLIT_AUTH_REQUIRED",
)
_UNAVAILABLE_CONFIG_MESSAGE = (
    "AGILAB cannot determine the active Streamlit server.address. "
    "Restart with a supported Streamlit runtime and an explicit --server.address."
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
    """Select a launch address, or inspect the effective address of a running UI."""
    if streamlit_config_getter is not None:
        try:
            config_host = streamlit_config_getter("server.address")
        except Exception:
            raise PublicBindPolicyError(_UNAVAILABLE_CONFIG_MESSAGE) from None
        # Streamlit binds all interfaces when server.address is unset. Its
        # effective configuration already includes CLI overrides of env values.
        runtime_host = "" if config_host is None else str(config_host).strip()
        return runtime_host or "0.0.0.0"

    # The launcher explicitly passes this selected address to Streamlit.
    env = os.environ if environ is None else environ
    env_host = str(
        env.get("AGILAB_UI_HOST") or env.get("STREAMLIT_SERVER_ADDRESS") or ""
    ).strip()
    if env_host:
        return env_host

    return DEFAULT_STREAMLIT_HOST


def host_is_exposed(host: str) -> bool:
    """Return True unless ``host`` is verifiably a loopback bind.

    Wildcard binds, LAN/WAN interface IPs, and unresolvable hostnames are all
    treated as exposed; only loopback addresses and well-known loopback
    hostnames are exempt from the public-bind controls.
    """
    candidate = str(host).strip().strip("[]")
    if candidate.lower() in LOOPBACK_HOSTNAMES:
        return False
    try:
        return not ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return True


def public_bind_has_controls(environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return truthy(env.get(PUBLIC_BIND_OK_ENV)) and any(
        truthy(env.get(name)) for name in PUBLIC_BIND_CONTROL_ENVS
    )


def public_bind_error_message(host: str) -> str:
    return (
        f"AGILAB refuses to bind the Streamlit UI on non-loopback host {host!r} without explicit protection. "
        "Launch with --server.address=127.0.0.1, or set AGILAB_PUBLIC_BIND_OK=1 together with "
        "an auth/TLS indicator such as AGILAB_TLS_TERMINATED=1. These flags are operator "
        "attestations, not proof: AGILAB does not verify that authentication or TLS is "
        "actually in place. For shared/public deployments, also archive "
        "AGILAB_PUBLIC_BIND_EVIDENCE for the security-check gate."
    )


def streamlit_config_getter_from_module(
    streamlit_module: object,
) -> Callable[[str], object] | None:
    """Return the compatible Streamlit config getter for the installed version."""
    get_option = getattr(streamlit_module, "get_option", None)
    if callable(get_option):
        return get_option

    config = getattr(streamlit_module, "config", None)
    config_get = getattr(config, "get", None)
    if callable(config_get):
        return config_get
    return None


def enforce_public_bind_policy(
    environ: Mapping[str, str] | None = None,
    *,
    streamlit_config_getter: Callable[[str], object] | None = None,
) -> str:
    """Return the Streamlit host to use or fail before exposing the UI."""
    host = configured_streamlit_host(
        environ, streamlit_config_getter=streamlit_config_getter
    )
    if host_is_exposed(host) and not public_bind_has_controls(environ):
        raise PublicBindPolicyError(public_bind_error_message(host))
    return host


def enforce_public_bind_policy_or_stop(
    streamlit_module: object,
    environ: Mapping[str, str] | None = None,
    *,
    streamlit_config_getter: Callable[[str], object] | None = None,
) -> str:
    """Apply the public-bind guard from direct Streamlit page entrypoints."""
    if streamlit_config_getter is None:
        streamlit_config_getter = streamlit_config_getter_from_module(streamlit_module)
    try:
        if streamlit_config_getter is None:
            raise PublicBindPolicyError(_UNAVAILABLE_CONFIG_MESSAGE)
        return enforce_public_bind_policy(
            environ,
            streamlit_config_getter=streamlit_config_getter,
        )
    except PublicBindPolicyError as exc:
        error_fn = getattr(streamlit_module, "error", None)
        stop_fn = getattr(streamlit_module, "stop", None)
        if callable(error_fn):
            error_fn(str(exc))
        if callable(stop_fn):
            stop_fn()
        raise
