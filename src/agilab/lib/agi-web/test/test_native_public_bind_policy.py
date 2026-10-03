"""Standalone native hosts preserve the canonical fail-closed bind policy."""

from __future__ import annotations

import pytest

from agi_web.public_bind_guard import PUBLIC_BIND_CONTROL_ENVS, PUBLIC_BIND_OK_ENV, PublicBindPolicyError
from agi_web.react_python_host import ReactPythonServer


@pytest.fixture(autouse=True)
def clear_public_bind_environment(monkeypatch):
    for name in (*PUBLIC_BIND_CONTROL_ENVS, PUBLIC_BIND_OK_ENV):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("controls", [{}, {"AGILAB_PUBLIC_BIND_OK": "1"}, {"AGILAB_TLS_TERMINATED": "1"}])
def test_native_public_host_requires_consent_and_protection(monkeypatch, controls):
    for name, value in controls.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(PublicBindPolicyError, match="0.0.0.0"):
        ReactPythonServer(("0.0.0.0", 0), lambda: None)


@pytest.mark.parametrize("control", PUBLIC_BIND_CONTROL_ENVS)
def test_native_public_host_accepts_consent_with_declared_protection(monkeypatch, control):
    monkeypatch.setenv(PUBLIC_BIND_OK_ENV, "1")
    monkeypatch.setenv(control, "1")
    server = ReactPythonServer(("0.0.0.0", 0), lambda: None)
    try:
        assert server.server_address[0] == "0.0.0.0"
    finally:
        server.server_close()


def test_actual_native_bind_overrides_loopback_environment(monkeypatch):
    monkeypatch.setenv("AGILAB_UI_HOST", "127.0.0.1")
    monkeypatch.setenv("AGILAB_UI_ADDRESS", "127.0.0.1")
    with pytest.raises(PublicBindPolicyError, match="0.0.0.0"):
        ReactPythonServer(("0.0.0.0", 0), lambda: None)
