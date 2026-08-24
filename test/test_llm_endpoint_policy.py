from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest

from agilab.security.llm_endpoint_policy import (
    LLM_TRUSTED_ORIGINS_ENV,
    LlmEndpointPolicyError,
    SameOriginLlmRedirectHandler,
    _PinnedEndpointPolicy,
    _PinnedHTTPConnection,
    build_no_redirect_http_client,
    clear_credentials_on_origin_change,
    same_endpoint_origin,
    validate_llm_endpoint,
)


def _resolver(*addresses: str):
    def resolve(_host, port, **_kwargs):
        results = []
        for address in addresses:
            family = socket.AF_INET6 if ":" in address else socket.AF_INET
            sockaddr = (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
            results.append((family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr))
        return results

    return resolve


@pytest.mark.parametrize("endpoint", ["file:///tmp/model", "ftp://example.test/model", "https://user:pass@example.test/v1"])
def test_llm_endpoint_policy_rejects_unsafe_urls(endpoint: str) -> None:
    with pytest.raises(LlmEndpointPolicyError):
        validate_llm_endpoint(endpoint, resolver=_resolver("203.0.113.8"))


@pytest.mark.parametrize("address", ["169.254.169.254", "169.254.170.2", "fd00:ec2::254"])
def test_llm_endpoint_policy_always_rejects_metadata(address: str) -> None:
    endpoint = "https://metadata-alias.example/v1"
    with pytest.raises(LlmEndpointPolicyError, match="metadata"):
        validate_llm_endpoint(
            endpoint,
            envars={LLM_TRUSTED_ORIGINS_ENV: "https://metadata-alias.example"},
            resolver=_resolver(address),
        )


def test_llm_endpoint_policy_rejects_dns_private_and_mixed_answers() -> None:
    endpoint = "https://gateway.example/v1"
    with pytest.raises(LlmEndpointPolicyError, match="private"):
        validate_llm_endpoint(endpoint, resolver=_resolver("10.20.30.40"))
    with pytest.raises(LlmEndpointPolicyError, match="private"):
        validate_llm_endpoint(endpoint, resolver=_resolver("203.0.113.8", "192.168.1.20"))


def test_llm_endpoint_policy_preserves_loopback_and_explicit_private_gateway() -> None:
    assert validate_llm_endpoint("http://127.0.0.1:11434/api", resolver=_resolver())
    endpoint = "http://gpu-box.internal:8000/v1"
    with pytest.raises(LlmEndpointPolicyError):
        validate_llm_endpoint(endpoint, resolver=_resolver("10.10.0.12"))
    assert validate_llm_endpoint(
        endpoint,
        envars={LLM_TRUSTED_ORIGINS_ENV: "http://gpu-box.internal:8000"},
        resolver=_resolver("10.10.0.12"),
    ) == endpoint


def test_llm_endpoint_policy_requires_https_for_untrusted_public_origin() -> None:
    resolver = _resolver("93.184.216.34")
    assert validate_llm_endpoint("https://gateway.example/v1", resolver=resolver)
    with pytest.raises(LlmEndpointPolicyError, match="HTTP"):
        validate_llm_endpoint("http://gateway.example/v1", resolver=resolver)


def test_llm_endpoint_policy_fails_closed_for_every_resolution_error() -> None:
    def unresolved(*_args, **_kwargs):
        raise socket.gaierror("offline")

    with pytest.raises(LlmEndpointPolicyError, match="resolved safely"):
        validate_llm_endpoint("https://unknown.example/v1", resolver=unresolved)
    with pytest.raises(LlmEndpointPolicyError, match="resolved safely"):
        validate_llm_endpoint(
            "https://trusted-gateway.example/v1",
            envars={LLM_TRUSTED_ORIGINS_ENV: "https://trusted-gateway.example"},
            resolver=unresolved,
        )


def test_llm_redirect_handler_rejects_cross_origin_before_forwarding() -> None:
    handler = SameOriginLlmRedirectHandler(resolver=_resolver("93.184.216.34"))
    request = SimpleNamespace(full_url="https://gateway.example/v1/responses")
    with pytest.raises(LlmEndpointPolicyError, match="credentials were not forwarded"):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://attacker.example/collect",
        )
    assert same_endpoint_origin("https://gateway.example/v1", "https://gateway.example/other")
    assert not same_endpoint_origin("https://gateway.example/v1", "https://attacker.example/v1")


def test_urllib_transport_reuses_validated_address_without_dns_rebinding() -> None:
    resolver_calls = 0

    def rebinding_resolver(host, port, **kwargs):
        nonlocal resolver_calls
        resolver_calls += 1
        address = "93.184.216.34" if resolver_calls == 1 else "10.0.0.8"
        return _resolver(address)(host, port, **kwargs)

    policy = _PinnedEndpointPolicy(envars=None, resolver=rebinding_resolver)
    first_addresses = policy.addresses_for("https://gateway.example/v1")
    assert policy.addresses_for("https://gateway.example/models") == first_addresses
    assert resolver_calls == 1

    connected: list[tuple[str, int]] = []
    connection = _PinnedHTTPConnection(
        "gateway.example",
        pinned_addresses=first_addresses,
    )
    connection._create_connection = (  # type: ignore[method-assign]
        lambda address, _timeout, _source: connected.append(address)
        or SimpleNamespace()
    )
    connection.connect()

    assert connected == [("93.184.216.34", 80)]
    assert all(address[0] != "10.0.0.8" for address in connected)


def test_httpx_backend_pins_address_and_preserves_tls_hostname() -> None:
    resolver_calls = 0
    connected: list[tuple[str, int]] = []
    tls_hostnames: list[str | None] = []

    def rebinding_resolver(host, port, **kwargs):
        nonlocal resolver_calls
        resolver_calls += 1
        address = "93.184.216.34" if resolver_calls == 1 else "10.0.0.8"
        return _resolver(address)(host, port, **kwargs)

    class FakeStream:
        def __init__(self) -> None:
            self._chunks = [b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"]

        def read(self, _max_bytes, timeout=None):
            return self._chunks.pop(0) if self._chunks else b""

        def write(self, _buffer, timeout=None):
            return None

        def close(self):
            return None

        def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            tls_hostnames.append(server_hostname)
            return self

        def get_extra_info(self, _info):
            return None

    class FakeBackend:
        def connect_tcp(
            self,
            host,
            port,
            timeout=None,
            local_address=None,
            socket_options=None,
        ):
            connected.append((host, port))
            return FakeStream()

        def sleep(self, _seconds):
            return None

    with build_no_redirect_http_client(
        "https://gateway.example/v1",
        resolver=rebinding_resolver,
        _network_backend=FakeBackend(),
    ) as client:
        response = client.get("https://gateway.example/v1/models")

    assert response.text == "ok"
    assert resolver_calls == 1
    assert connected == [("93.184.216.34", 443)]
    assert tls_hostnames == ["gateway.example"]


def test_origin_change_clears_cached_secrets_without_persisting_them() -> None:
    state = {
        "provider_origin": "https://old.example",
        "provider_api_key": "session-secret",
    }
    envars = {"PROVIDER_API_KEY": "environment-secret"}

    assert clear_credentials_on_origin_change(
        "https://new.example/v1",
        session_state=state,
        envars=envars,
        origin_state_key="provider_origin",
        session_secret_keys=("provider_api_key",),
        env_secret_keys=("PROVIDER_API_KEY",),
    )
    assert state == {"provider_origin": "https://new.example"}
    assert "PROVIDER_API_KEY" not in envars
