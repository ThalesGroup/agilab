"""Fail-closed network policy for configurable LLM service endpoints."""

from __future__ import annotations

import http.client
import ipaddress
import os
import socket
import ssl
import threading
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from functools import partial
from typing import Any
from urllib import request
from urllib.parse import SplitResult, urlsplit


LLM_TRUSTED_ORIGINS_ENV = "AGILAB_LLM_TRUSTED_ORIGINS"

_METADATA_ADDRESSES = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("169.254.170.2"),
        ipaddress.ip_address("100.100.100.200"),
        ipaddress.ip_address("fd00:ec2::254"),
    }
)

Resolver = Callable[..., list[tuple[Any, ...]]]
Origin = tuple[str, str, int]


class LlmEndpointPolicyError(ValueError):
    """Raised when an LLM endpoint violates the outbound network policy."""


def _parsed_endpoint(endpoint: str) -> SplitResult:
    value = str(endpoint or "").strip()
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise LlmEndpointPolicyError("LLM endpoints must use http or https.")
    if not parsed.hostname:
        raise LlmEndpointPolicyError("LLM endpoints must include a hostname.")
    if parsed.username is not None or parsed.password is not None:
        raise LlmEndpointPolicyError("LLM endpoint URLs must not contain credentials.")
    if parsed.fragment:
        raise LlmEndpointPolicyError("LLM endpoint URLs must not contain fragments.")
    try:
        parsed.port
    except ValueError as exc:
        raise LlmEndpointPolicyError("LLM endpoint URLs must contain a valid port.") from exc
    return parsed


def endpoint_origin(endpoint: str) -> Origin:
    """Return a normalized scheme/host/port tuple for exact-origin comparisons."""
    parsed = _parsed_endpoint(endpoint)
    scheme = parsed.scheme.lower()
    return scheme, (parsed.hostname or "").lower().rstrip("."), parsed.port or (443 if scheme == "https" else 80)


def format_endpoint_origin(origin: Origin) -> str:
    scheme, host, port = origin
    rendered_host = f"[{host}]" if ":" in host else host
    default_port = 443 if scheme == "https" else 80
    suffix = "" if port == default_port else f":{port}"
    return f"{scheme}://{rendered_host}{suffix}"


def _trusted_origins(envars: Mapping[str, str] | None) -> set[Origin]:
    configured = ""
    if envars is not None:
        configured = str(envars.get(LLM_TRUSTED_ORIGINS_ENV) or "").strip()
    if not configured:
        configured = os.getenv(LLM_TRUSTED_ORIGINS_ENV, "").strip()

    origins: set[Origin] = set()
    for raw_origin in configured.split(","):
        candidate = raw_origin.strip()
        if not candidate:
            continue
        parsed = _parsed_endpoint(candidate)
        if parsed.path not in {"", "/"} or parsed.query:
            raise LlmEndpointPolicyError(
                f"{LLM_TRUSTED_ORIGINS_ENV} entries must be origins without paths or queries."
            )
        origins.add(endpoint_origin(candidate))
    return origins


def _resolved_addresses(host: str, port: int, resolver: Resolver) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        return [literal]

    if host == "localhost" or host.endswith(".localhost"):
        return [ipaddress.ip_address("127.0.0.1"), ipaddress.ip_address("::1")]

    try:
        infos = resolver(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError) as exc:
        raise LlmEndpointPolicyError(f"LLM endpoint hostname {host!r} could not be resolved safely.") from exc

    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        try:
            sockaddr = info[4]
            address = ipaddress.ip_address(sockaddr[0])
        except (IndexError, TypeError, ValueError):
            continue
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise LlmEndpointPolicyError(f"LLM endpoint hostname {host!r} did not resolve to an IP address.")
    return addresses


def _address_policy_reason(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    if address in _METADATA_ADDRESSES or address.is_link_local:
        return "link-local and metadata-service addresses are blocked"
    if address.is_unspecified or address.is_multicast or address.is_reserved:
        return "non-routable addresses are blocked"
    return ""


def _validate_and_resolve_llm_endpoint(
    endpoint: str,
    *,
    envars: Mapping[str, str] | None = None,
    resolver: Resolver | None = None,
) -> tuple[
    str,
    tuple[str, str, int],
    tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...],
]:
    """Validate an LLM endpoint and return the URL, origin, and safe addresses.

    Public HTTPS and loopback HTTP(S) are accepted by default. Exact custom
    origins, including private/LAN gateways and non-loopback HTTP, require an
    explicit ``AGILAB_LLM_TRUSTED_ORIGINS`` entry. Link-local, metadata,
    multicast, unspecified, and reserved targets remain blocked even when an
    origin is listed as trusted.
    """
    value = str(endpoint or "").strip()
    parsed = _parsed_endpoint(value)
    origin = endpoint_origin(value)
    trusted = origin in _trusted_origins(envars)

    addresses = _resolved_addresses(origin[1], origin[2], resolver or socket.getaddrinfo)

    for address in addresses:
        reason = _address_policy_reason(address)
        if reason:
            raise LlmEndpointPolicyError(f"LLM endpoint {format_endpoint_origin(origin)} is blocked: {reason}.")

    all_loopback = bool(addresses) and all(address.is_loopback for address in addresses)
    contains_non_public = any(address.is_private or address.is_loopback for address in addresses)
    if contains_non_public and not (trusted or all_loopback):
        raise LlmEndpointPolicyError(
            f"LLM endpoint {format_endpoint_origin(origin)} resolves to a private address; "
            f"add its exact origin to {LLM_TRUSTED_ORIGINS_ENV} only when that gateway is trusted."
        )
    if parsed.scheme.lower() == "http" and not (trusted or all_loopback):
        raise LlmEndpointPolicyError(
            f"Non-loopback HTTP LLM endpoint {format_endpoint_origin(origin)} requires an exact "
            f"{LLM_TRUSTED_ORIGINS_ENV} opt-in."
        )
    return value, origin, tuple(addresses)


def validate_llm_endpoint(
    endpoint: str,
    *,
    envars: Mapping[str, str] | None = None,
    resolver: Resolver | None = None,
) -> str:
    """Validate an LLM endpoint and return its stripped URL."""

    value, _, _ = _validate_and_resolve_llm_endpoint(
        endpoint,
        envars=envars,
        resolver=resolver,
    )
    return value


def same_endpoint_origin(first: str, second: str) -> bool:
    return endpoint_origin(first) == endpoint_origin(second)


def clear_credentials_on_origin_change(
    endpoint: str,
    *,
    session_state: MutableMapping[str, Any],
    envars: MutableMapping[str, str],
    origin_state_key: str,
    session_secret_keys: Sequence[str],
    env_secret_keys: Sequence[str],
) -> bool:
    """Clear cached credentials when a configured endpoint changes origin."""
    current_origin = format_endpoint_origin(endpoint_origin(endpoint))
    previous_origin = str(session_state.get(origin_state_key) or "").strip()
    session_state[origin_state_key] = current_origin
    if not previous_origin or previous_origin == current_origin:
        return False
    for key in session_secret_keys:
        session_state.pop(key, None)
    for key in env_secret_keys:
        envars.pop(key, None)
    return True


class _PinnedEndpointPolicy:
    def __init__(
        self,
        *,
        envars: Mapping[str, str] | None,
        resolver: Resolver | None,
    ) -> None:
        self._envars = envars
        self._resolver = resolver
        self._pins: dict[tuple[str, str, int], tuple[str, ...]] = {}
        self._lock = threading.Lock()

    def addresses_for(self, endpoint: str) -> tuple[str, ...]:
        origin = endpoint_origin(endpoint)
        with self._lock:
            existing = self._pins.get(origin)
            if existing is not None:
                return existing
            _, _, addresses = _validate_and_resolve_llm_endpoint(
                endpoint,
                envars=self._envars,
                resolver=self._resolver,
            )
            pinned = tuple(str(address) for address in addresses)
            self._pins[origin] = pinned
            return pinned


def _connect_pinned_socket(
    connection: http.client.HTTPConnection,
    addresses: tuple[str, ...],
) -> socket.socket:
    last_error: OSError | None = None
    for address in addresses:
        try:
            return connection._create_connection(  # type: ignore[attr-defined]
                (address, connection.port),
                connection.timeout,
                connection.source_address,
            )
        except OSError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise LlmEndpointPolicyError("Validated LLM endpoint did not provide a connectable address.")


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, *, pinned_addresses: tuple[str, ...], **kwargs: Any) -> None:
        self._pinned_addresses = pinned_addresses
        super().__init__(host, **kwargs)

    def connect(self) -> None:
        if self._tunnel_host:
            raise LlmEndpointPolicyError("Proxy tunneling is disabled for credential-bearing LLM requests.")
        self.sock = _connect_pinned_socket(self, self._pinned_addresses)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, *, pinned_addresses: tuple[str, ...], **kwargs: Any) -> None:
        self._pinned_addresses = pinned_addresses
        super().__init__(host, **kwargs)

    def connect(self) -> None:
        if self._tunnel_host:
            raise LlmEndpointPolicyError("Proxy tunneling is disabled for credential-bearing LLM requests.")
        raw_socket = _connect_pinned_socket(self, self._pinned_addresses)
        self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)


class _PinnedLlmHTTPHandler(request.HTTPHandler):
    def __init__(self, policy: _PinnedEndpointPolicy) -> None:
        super().__init__()
        self._policy = policy

    def http_open(self, req):  # type: ignore[override]
        addresses = self._policy.addresses_for(req.full_url)
        connection = partial(_PinnedHTTPConnection, pinned_addresses=addresses)
        return self.do_open(connection, req)


class _PinnedLlmHTTPSHandler(request.HTTPSHandler):
    def __init__(self, policy: _PinnedEndpointPolicy) -> None:
        super().__init__()
        self._policy = policy

    def https_open(self, req):  # type: ignore[override]
        addresses = self._policy.addresses_for(req.full_url)
        connection = partial(_PinnedHTTPSConnection, pinned_addresses=addresses)
        return self.do_open(
            connection,
            req,
            context=self._context,
            check_hostname=self._check_hostname,
        )


def _build_pinned_httpcore_backend(
    httpcore_module: Any,
    *,
    expected_host: str,
    pinned_addresses: tuple[str, ...],
    delegate: Any | None = None,
) -> Any:
    network_backend_class = getattr(httpcore_module, "NetworkBackend", None)
    sync_backend_class = getattr(httpcore_module, "SyncBackend", None)
    if network_backend_class is None or (delegate is None and sync_backend_class is None):
        raise RuntimeError("Secure LLM requests require the supported httpcore network backend seam.")
    underlying = delegate if delegate is not None else sync_backend_class()

    class _PinnedNetworkBackend(network_backend_class):
        def connect_tcp(
            self,
            host: str,
            port: int,
            timeout: float | None = None,
            local_address: str | None = None,
            socket_options: Any | None = None,
        ) -> Any:
            if host.lower().rstrip(".") != expected_host.lower().rstrip("."):
                raise LlmEndpointPolicyError(
                    "Pinned LLM client refused a connection outside its validated origin."
                )
            last_error: Exception | None = None
            for address in pinned_addresses:
                try:
                    return underlying.connect_tcp(
                        address,
                        port,
                        timeout=timeout,
                        local_address=local_address,
                        socket_options=socket_options,
                    )
                except Exception as exc:  # pragma: no cover - fallback address path.
                    last_error = exc
            if last_error is not None:
                raise last_error
            raise LlmEndpointPolicyError(
                "Validated LLM endpoint did not provide a connectable address."
            )

        def connect_unix_socket(
            self,
            path: str,
            timeout: float | None = None,
            socket_options: Any | None = None,
        ) -> Any:
            raise LlmEndpointPolicyError("Unix sockets are not valid remote LLM endpoints.")

        def sleep(self, seconds: float) -> None:
            underlying.sleep(seconds)

    return _PinnedNetworkBackend()


def build_no_redirect_http_client(
    endpoint: str,
    *,
    envars: Mapping[str, str] | None = None,
    resolver: Resolver | None = None,
    _network_backend: Any | None = None,
):
    """Return an httpx client pinned to the validated endpoint addresses."""

    try:
        import httpcore
        import httpx
        from httpx._transports.default import ResponseStream, map_httpcore_exceptions
    except (ImportError, AttributeError) as exc:  # pragma: no cover - dependency contract.
        raise RuntimeError(
            "Secure LLM requests require supported httpx/httpcore transport versions."
        ) from exc

    _, origin, addresses = _validate_and_resolve_llm_endpoint(
        endpoint,
        envars=envars,
        resolver=resolver,
    )
    pinned_addresses = tuple(str(address) for address in addresses)
    backend = _build_pinned_httpcore_backend(
        httpcore,
        expected_host=origin[1],
        pinned_addresses=pinned_addresses,
        delegate=_network_backend,
    )
    pool = httpcore.ConnectionPool(
        ssl_context=ssl.create_default_context(),
        network_backend=backend,
        retries=0,
    )

    class _PinnedHttpxTransport(httpx.BaseTransport):
        def handle_request(self, req):  # type: ignore[override]
            if endpoint_origin(str(req.url)) != origin:
                raise LlmEndpointPolicyError(
                    "Pinned LLM client refused a request outside its validated origin."
                )
            core_request = httpcore.Request(
                method=req.method,
                url=httpcore.URL(
                    scheme=req.url.raw_scheme,
                    host=req.url.raw_host,
                    port=req.url.port,
                    target=req.url.raw_path,
                ),
                headers=req.headers.raw,
                content=req.stream,
                extensions=req.extensions,
            )
            with map_httpcore_exceptions():
                response = pool.handle_request(core_request)
            return httpx.Response(
                status_code=response.status,
                headers=response.headers,
                stream=ResponseStream(response.stream),
                extensions=response.extensions,
            )

        def close(self) -> None:
            pool.close()

    return httpx.Client(
        transport=_PinnedHttpxTransport(),
        follow_redirects=False,
        trust_env=False,
    )


class SameOriginLlmRedirectHandler(request.HTTPRedirectHandler):
    """Permit only policy-valid redirects that remain on the original origin."""

    def __init__(
        self,
        *,
        envars: Mapping[str, str] | None = None,
        resolver: Resolver | None = None,
        policy: _PinnedEndpointPolicy | None = None,
    ) -> None:
        super().__init__()
        self._policy = policy or _PinnedEndpointPolicy(
            envars=envars,
            resolver=resolver,
        )

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        if not same_endpoint_origin(req.full_url, newurl):
            raise LlmEndpointPolicyError("LLM endpoint redirect changed origin; credentials were not forwarded.")
        self._policy.addresses_for(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def build_same_origin_llm_opener(
    *,
    envars: Mapping[str, str] | None = None,
    resolver: Resolver | None = None,
):
    policy = _PinnedEndpointPolicy(envars=envars, resolver=resolver)
    return request.build_opener(
        request.ProxyHandler({}),
        SameOriginLlmRedirectHandler(policy=policy),
        _PinnedLlmHTTPHandler(policy),
        _PinnedLlmHTTPSHandler(policy),
    )


__all__ = [
    "LLM_TRUSTED_ORIGINS_ENV",
    "LlmEndpointPolicyError",
    "SameOriginLlmRedirectHandler",
    "build_no_redirect_http_client",
    "build_same_origin_llm_opener",
    "clear_credentials_on_origin_change",
    "endpoint_origin",
    "format_endpoint_origin",
    "same_endpoint_origin",
    "validate_llm_endpoint",
]
