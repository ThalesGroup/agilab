"""Hermetic DNS, transport, redirect, and proxy boundary tests for live probes.

Both the initial safety check and the actual connection enforce the address
policy. The recording transport proves the numeric socket destination and
original Host/TLS identity without DNS traffic, network sockets, or real tokens.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "data_connectors"
    / "data_connector_live_endpoint_smoke.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "agilab_dc_live_smoke_under_test", _MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


smoke = _load_module()


def _patch_resolution(monkeypatch, ip):
    monkeypatch.setattr(
        smoke.socket,
        "getaddrinfo",
        lambda host, *args, **kwargs: [(2, 1, 6, "", (ip, 0))],
    )


@pytest.mark.parametrize(
    ("ip", "expected_fragment"),
    [
        ("127.0.0.1", "loopback"),
        ("::1", "loopback"),
        ("169.254.169.254", "metadata"),
        ("10.0.0.5", "non-public"),
        ("192.168.1.10", "non-public"),
    ],
)
def test_hostname_resolving_to_blocked_target_is_rejected(monkeypatch, ip, expected_fragment):
    _patch_resolution(monkeypatch, ip)
    reason = smoke._host_is_blocked("innocent-looking.example.com", allow_local_http=False)
    assert expected_fragment in reason


def test_hostname_resolving_to_public_ip_is_allowed(monkeypatch):
    _patch_resolution(monkeypatch, "8.8.8.8")
    assert smoke._host_is_blocked("api.example.com", allow_local_http=False) == ""


def test_unresolvable_hostname_is_blocked(monkeypatch):
    def _boom(host, *args, **kwargs):
        raise smoke.socket.gaierror("no such host")

    monkeypatch.setattr(smoke.socket, "getaddrinfo", _boom)
    reason = smoke._host_is_blocked("nx.example.invalid", allow_local_http=False)
    assert reason  # non-empty -> blocked (does not fall through to allowed)


def test_probe_opensearch_never_attaches_token_for_ssrf_hostname(monkeypatch):
    """A DNS name resolving to loopback must be refused before the Bearer token
    is attached and before any connection is opened."""
    _patch_resolution(monkeypatch, "127.0.0.1")

    # Guard: if anything tries to open a connection or build a token request,
    # fail loudly instead of silently sending the credential.
    def _forbidden_opener(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("network opener must not be built for a blocked host")

    monkeypatch.setattr(smoke, "_live_probe_opener", _forbidden_opener)
    monkeypatch.setattr(
        smoke,
        "_connector_target",
        lambda connector: "https://metadata-alias.example.com/",
    )

    connector = {"provider": "opensearch"}
    status, message, network_probe = smoke._probe_opensearch(connector, "super-secret-token")

    assert status == "skipped"
    assert network_probe is False
    assert "unsafe live endpoint target" in message
    assert "super-secret-token" not in message


class _ProbeSocket:
    def __init__(self, response):
        self.response = response
        self.sent = bytearray()
        self.closed = False

    def sendall(self, payload):
        self.sent.extend(payload)

    def makefile(self, _mode):
        import io

        return io.BytesIO(self.response)

    def close(self):
        self.closed = True


@pytest.fixture
def probe_transport(monkeypatch):
    """Exercise urllib/http.client without DNS, sockets, or real credentials."""
    import socket
    import ssl
    from types import SimpleNamespace

    transport = SimpleNamespace(
        destinations=[],
        sockets=[],
        tls_hostnames=[],
        responses=[],
        context=ssl.create_default_context(),
        connect_error=None,
    )
    monkeypatch.setattr(smoke.request, "getproxies", lambda: {})
    monkeypatch.setenv(smoke.LOCAL_HTTP_OPT_IN_ENV, "0")
    monkeypatch.setenv("OPENSEARCH_TOKEN", "synthetic-probe-token")

    def connect(destination, _timeout, _source):
        transport.destinations.append(destination)
        if transport.connect_error is not None:
            raise transport.connect_error
        response = (
            transport.responses.pop(0)
            if transport.responses
            else b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n"
        )
        sock = _ProbeSocket(response)
        transport.sockets.append(sock)
        return sock

    def wrap_socket(sock, *, server_hostname):
        assert transport.context.check_hostname is True
        assert transport.context.verify_mode == ssl.CERT_REQUIRED
        transport.tls_hostnames.append(server_hostname)
        return sock

    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(transport.context, "wrap_socket", wrap_socket)
    monkeypatch.setattr(ssl, "_create_default_https_context", lambda: transport.context)
    return transport


def _search_connector(url="https://search.example.invalid"):
    return {
        "kind": "opensearch",
        "provider": "opensearch",
        "url": url,
        "index": "runs",
        "id": "ops",
        "auth_ref": "env:OPENSEARCH_TOKEN",
    }


def test_probe_refuses_dns_rebinding_before_actual_connection(
    monkeypatch, probe_transport
):
    answers = iter(["93.184.216.34", "169.254.169.254"])
    monkeypatch.setattr(
        smoke,
        "_resolve_host_addresses",
        lambda _host: [smoke.ipaddress.ip_address(next(answers))],
    )

    status, message, executed = smoke._probe_opensearch(
        _search_connector(), "synthetic-probe-token"
    )
    assert (status, executed) == ("skipped", False)
    assert "connection target refused: metadata" in message

    assert probe_transport.destinations == []
    assert probe_transport.sockets == []


def test_https_probe_pins_destination_preserves_tls_host_and_authorization(
    monkeypatch, probe_transport
):
    resolved_hosts = []

    def resolve(host):
        resolved_hosts.append(host)
        # The transport must never perform a third hostname resolution.
        assert len(resolved_hosts) <= 2
        return [smoke.ipaddress.ip_address("93.184.216.34")]

    monkeypatch.setattr(smoke, "_resolve_host_addresses", resolve)
    status, message, executed = smoke._probe_opensearch(
        _search_connector(), "synthetic-probe-token"
    )

    assert (status, executed) == ("healthy", True)
    assert "204" in message
    assert resolved_hosts == ["search.example.invalid"] * 2
    assert probe_transport.destinations == [("93.184.216.34", 443)]
    assert probe_transport.tls_hostnames == ["search.example.invalid"]
    payload = bytes(probe_transport.sockets[0].sent)
    assert payload.startswith(b"HEAD /runs HTTP/1.1\r\n")
    assert b"Host: search.example.invalid\r\n" in payload
    assert b"Authorization: Bearer synthetic-probe-token\r\n" in payload


def test_opted_in_http_emulator_uses_pinned_loopback(monkeypatch, probe_transport):
    monkeypatch.setenv(smoke.LOCAL_HTTP_OPT_IN_ENV, "1")
    status, _message, executed = smoke._probe_opensearch(
        _search_connector("http://127.0.0.1:9200/runs"), "synthetic-probe-token"
    )

    assert (status, executed) == ("healthy", True)
    assert probe_transport.destinations == [("127.0.0.1", 9200)]
    assert probe_transport.tls_hostnames == []


def test_same_origin_redirect_remains_a_pinned_head_probe(monkeypatch, probe_transport):
    monkeypatch.setattr(
        smoke,
        "_resolve_host_addresses",
        lambda _host: [smoke.ipaddress.ip_address("93.184.216.34")],
    )
    probe_transport.responses.append(
        b"HTTP/1.1 302 Found\r\nLocation: /health\r\nContent-Length: 0\r\n\r\n"
    )

    status, _message, executed = smoke._probe_opensearch(
        _search_connector(), "synthetic-probe-token"
    )

    assert (status, executed) == ("healthy", True)
    assert probe_transport.destinations == [("93.184.216.34", 443)] * 2
    assert probe_transport.tls_hostnames == ["search.example.invalid"] * 2
    assert bytes(probe_transport.sockets[1].sent).startswith(
        b"HEAD /health HTTP/1.1\r\n"
    )
    for sock in probe_transport.sockets:
        assert b"Authorization: Bearer synthetic-probe-token\r\n" in bytes(sock.sent)


@pytest.mark.parametrize(
    "redirect",
    [
        "https://other.example.invalid/health",
        "http://search.example.invalid/health",
    ],
)
def test_cross_origin_redirect_never_forwards_credentials(
    monkeypatch, probe_transport, redirect
):
    monkeypatch.setattr(
        smoke,
        "_resolve_host_addresses",
        lambda _host: [smoke.ipaddress.ip_address("93.184.216.34")],
    )
    probe_transport.responses.append(
        f"HTTP/1.1 302 Found\r\nLocation: {redirect}\r\nContent-Length: 0\r\n\r\n".encode()
    )

    row = smoke._smoke_row(
        _search_connector(), execute=True, allowed_connector_ids={"ops"}
    )
    assert row["status"] == "unhealthy"
    assert row["execution_status"] == "executed"
    assert row["network_probe_executed"] is True
    assert "redirect changed origin" in row["message"]

    assert probe_transport.destinations == [("93.184.216.34", 443)]
    assert len(probe_transport.sockets) == 1


def test_redirect_rebinding_is_rejected_before_second_connection(
    monkeypatch, probe_transport
):
    answers = iter(["93.184.216.34"] * 3 + ["169.254.169.254"])
    monkeypatch.setattr(
        smoke,
        "_resolve_host_addresses",
        lambda _host: [smoke.ipaddress.ip_address(next(answers))],
    )
    probe_transport.responses.append(
        b"HTTP/1.1 302 Found\r\nLocation: /health\r\nContent-Length: 0\r\n\r\n"
    )

    status, message, executed = smoke._probe_opensearch(
        _search_connector(), "synthetic-probe-token"
    )
    assert (status, executed) == ("unhealthy", True)
    assert "connection target refused: metadata" in message

    assert probe_transport.destinations == [("93.184.216.34", 443)]


@pytest.mark.parametrize("bypass", [False, True])
def test_proxy_configuration_requires_explicit_standard_bypass(
    monkeypatch, probe_transport, bypass
):
    monkeypatch.setattr(
        smoke,
        "_resolve_host_addresses",
        lambda _host: [smoke.ipaddress.ip_address("93.184.216.34")],
    )
    monkeypatch.setattr(
        smoke.request,
        "getproxies",
        lambda: {"https": "http://proxy.example.invalid:3128"},
    )
    monkeypatch.setattr(smoke.request, "proxy_bypass", lambda _host: bypass)

    row = smoke._smoke_row(
        _search_connector(), execute=True, allowed_connector_ids={"ops"}
    )
    if bypass:
        assert row["status"] == "healthy"
        assert row["execution_status"] == "executed"
        assert row["network_probe_executed"] is True
        assert probe_transport.destinations == [("93.184.216.34", 443)]
    else:
        assert row["status"] == "skipped"
        assert row["execution_status"] == "skipped"
        assert row["network_probe_executed"] is False
        assert "configured proxies are unsupported" in row["message"]
        assert "synthetic-probe-token" not in row["message"]
        assert probe_transport.destinations == []


def _persisted_probe_report(monkeypatch, tmp_path, token, url="https://93.184.216.34"):
    import json

    monkeypatch.setenv("OPENSEARCH_TOKEN", token)
    catalog = smoke.load_connector_catalog(
        _MODULE_PATH.parents[3] / "docs/source/data/data_connectors_sample.toml"
    )
    connector = next(
        row for row in catalog["connectors"] if row["kind"] == "opensearch"
    )
    connector["url"] = url
    connector["auth_ref"] = "env:OPENSEARCH_TOKEN"
    state = smoke.build_data_connector_live_endpoint_smoke(
        catalog,
        source_path="synthetic.toml",
        execute=True,
        allowed_connector_ids=[connector["id"]],
    )
    assert state["source"]["facility_run_status"] == "validated"
    path = smoke.write_data_connector_live_endpoint_smoke(
        tmp_path / "evidence.json", state
    )
    serialized = path.read_text(encoding="utf-8")
    assert json.loads(serialized) == state
    assert "audit-only-secret" not in serialized
    assert state["provenance"]["credential_values_logged"] is False
    row = next(
        row
        for row in state["endpoint_smokes"]
        if row["connector_id"] == connector["id"]
    )
    return state, row


@pytest.mark.parametrize(
    "token",
    [
        "audit-only-secret'quoted\\value\r\n",
        "audit-only-secret\t",
        "audit-only-secret\x7f",
        "audit-only-secret\U0001f511",
    ],
)
def test_malformed_credentials_never_reach_transport_or_persist(
    monkeypatch, tmp_path, probe_transport, token
):
    state, row = _persisted_probe_report(monkeypatch, tmp_path, token)

    assert row["status"] == "skipped"
    assert row["execution_status"] == "skipped"
    assert row["network_probe_executed"] is False
    assert "invalid authorization credential" in row["message"]
    assert state["summary"]["network_probe_count"] == 0
    assert state["summary"]["executed_endpoint_count"] == 0
    assert probe_transport.destinations == []


@pytest.mark.parametrize("port", ["bad", "99999"])
def test_invalid_port_does_not_count_as_a_network_probe(
    monkeypatch, tmp_path, probe_transport, port
):
    state, row = _persisted_probe_report(
        monkeypatch, tmp_path, "audit-only-secret", f"https://93.184.216.34:{port}"
    )

    assert row["status"] == "skipped"
    assert row["network_probe_executed"] is False
    assert state["summary"]["network_probe_count"] == 0
    assert state["summary"]["executed_endpoint_count"] == 0
    assert "invalid live endpoint URL or port" in row["message"]
    assert probe_transport.destinations == []


def test_header_construction_failure_has_no_network_or_credential_evidence(
    monkeypatch, tmp_path, probe_transport
):
    import http.client

    original_putheader = http.client.HTTPConnection.putheader

    def rejected_header(connection, name, *values):
        if name.lower() == "authorization":
            # Model a library error that includes repr-escaped header contents.
            raise ValueError(f"Invalid header value {values!r}")
        return original_putheader(connection, name, *values)

    monkeypatch.setattr(http.client.HTTPConnection, "putheader", rejected_header)
    state, row = _persisted_probe_report(
        monkeypatch, tmp_path, "audit-only-secret'quoted\\value"
    )

    assert row["status"] == "skipped"
    assert row["message"] == "invalid live endpoint request configuration"
    assert row["network_probe_executed"] is False
    assert state["summary"]["network_probe_count"] == 0
    assert probe_transport.destinations == []


def test_failed_socket_attempt_counts_without_persisting_exception_credentials(
    monkeypatch, tmp_path, probe_transport
):
    token = "audit-only-secret'quoted\\value"
    probe_transport.connect_error = OSError(f"connection failed for {token!r}")
    state, row = _persisted_probe_report(monkeypatch, tmp_path, token)

    assert row["status"] == "unhealthy"
    assert row["execution_status"] == "executed"
    assert row["network_probe_executed"] is True
    assert row["message"] == "live endpoint connection failed (OSError)"
    assert state["summary"]["network_probe_count"] == 1
    assert probe_transport.destinations == [("93.184.216.34", 443)]


def test_http_error_reason_cannot_echo_credentials_into_evidence(
    monkeypatch, tmp_path, probe_transport
):
    token = "audit-only-secret'quoted\\value"
    probe_transport.responses.append(
        f"HTTP/1.1 401 {token}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode()
    )
    state, row = _persisted_probe_report(monkeypatch, tmp_path, token)

    assert row["status"] == "unhealthy"
    assert row["execution_status"] == "executed"
    assert row["network_probe_executed"] is True
    assert row["message"] == "live endpoint returned HTTP 401"
    assert state["summary"]["network_probe_count"] == 1
    assert probe_transport.destinations == [("93.184.216.34", 443)]
