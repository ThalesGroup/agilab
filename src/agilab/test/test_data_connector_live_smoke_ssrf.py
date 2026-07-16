"""Regression tests for DNS-based SSRF screening in the live endpoint smoke.

Covers audit finding #11 (security-app bucket): ``_host_is_blocked`` previously
only screened IP-literal hosts and returned "allowed" for any DNS name (the
``ipaddress.ip_address`` ``ValueError`` path). A hostname that resolves to a
metadata / loopback / private target therefore received the connection and the
Bearer token. The fix resolves the hostname via ``socket.getaddrinfo`` and
applies the block policy to every resolved address before the token is attached.

Tests are hermetic: ``getaddrinfo`` is monkeypatched, no real DNS or network.
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
