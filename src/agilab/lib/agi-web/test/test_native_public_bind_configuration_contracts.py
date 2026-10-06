"""Prove address selection and fail-closed direct-launch protection."""

from types import SimpleNamespace
import socketserver

import pytest

from agi_web import public_bind_guard as guard
from agi_web.react_python_host import ReactPythonServer


@pytest.mark.parametrize("value,expected", [(None, False), ("off", False), ("  yes ", True),
                                           ("TRUE", True), ("1", True), ("enabled", True)])
def test_operator_attestations_require_explicit_truthy_values(value, expected):
    assert guard.truthy(value) is expected


@pytest.mark.parametrize("host,exposed", [("localhost.localdomain", False), ("[::1]", False),
                                         ("127.0.0.2", False), ("0.0.0.0", True),
                                         ("[::]", True), ("192.0.2.3", True),
                                         ("unresolved.example.invalid", True)])
def test_only_verified_loopback_addresses_bypass_public_controls(host, exposed):
    assert guard.host_is_exposed(host) is exposed


def test_address_selection_prefers_live_configuration_then_launch_preferences(monkeypatch):
    monkeypatch.setenv("AGILAB_UI_HOST", " 127.0.0.2 ")
    assert guard.configured_ui_host() == "127.0.0.2"
    assert guard.configured_ui_host({"AGILAB_UI_HOST": " ", "AGILAB_UI_ADDRESS": " 127.0.0.3 "}) == "127.0.0.3"
    assert guard.configured_ui_host({}) == "127.0.0.1"
    assert guard.configured_ui_host({"AGILAB_UI_HOST": "127.0.0.1"}, ui_config_getter=lambda name: "192.0.2.1") == "192.0.2.1"
    assert guard.configured_ui_host({}, ui_config_getter=lambda name: None) == "0.0.0.0"
    assert guard.configured_ui_host({}, ui_config_getter=lambda name: " ") == "0.0.0.0"
    def broken(name): raise RuntimeError("configuration unavailable")
    with pytest.raises(guard.PublicBindPolicyError, match="cannot determine"):
        guard.configured_ui_host({}, ui_config_getter=broken)


@pytest.mark.parametrize("control", guard.PUBLIC_BIND_CONTROL_ENVS)
def test_public_bind_requires_both_operator_opt_in_and_a_control_indicator(control):
    values = {"AGILAB_UI_HOST": "0.0.0.0", guard.PUBLIC_BIND_OK_ENV: "1", control: "1"}
    assert guard.public_bind_has_controls(values)
    assert guard.enforce_public_bind_policy(values) == "0.0.0.0"
    del values[guard.PUBLIC_BIND_OK_ENV]
    assert not guard.public_bind_has_controls(values)
    with pytest.raises(guard.PublicBindPolicyError, match="operator attestations"):
        guard.enforce_public_bind_policy(values)
    assert guard.enforce_public_bind_policy({"AGILAB_UI_HOST": "127.0.0.1"}) == "127.0.0.1"


def test_default_environment_controls_and_config_getter_compatibility(monkeypatch):
    for name in guard.PUBLIC_BIND_CONTROL_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(guard.PUBLIC_BIND_OK_ENV, "1")
    assert not guard.public_bind_has_controls()
    monkeypatch.setenv("AGILAB_TLS_TERMINATED", "on")
    assert guard.public_bind_has_controls()
    def direct(name):
        return "127.0.0.1"

    assert guard.ui_config_getter_from_module(SimpleNamespace(get_option=direct)) is direct
    compatible = {"address": "127.0.0.2"}
    getter = guard.ui_config_getter_from_module(SimpleNamespace(get_option=None, config=compatible))
    assert getter("address") == "127.0.0.2"
    assert guard.ui_config_getter_from_module(object()) is None


def test_direct_launch_reports_and_stops_before_exposing_an_unprotected_host():
    calls = []
    ui = SimpleNamespace(get_option=lambda name: "0.0.0.0", error=lambda message: calls.append(("error", message)), stop=lambda: calls.append(("stop",)))
    with pytest.raises(guard.PublicBindPolicyError):
        guard.enforce_public_bind_policy_or_stop(ui, {})
    assert calls[0][0] == "error" and "non-loopback" in calls[0][1]
    assert calls[1] == ("stop",)
    with pytest.raises(guard.PublicBindPolicyError, match="cannot determine"):
        guard.enforce_public_bind_policy_or_stop(SimpleNamespace(error=None, stop=None), {})
    assert guard.enforce_public_bind_policy_or_stop(object(), {}, ui_config_getter=lambda name: "127.0.0.1") == "127.0.0.1"


@pytest.mark.parametrize("controls", [
    {},
    {guard.PUBLIC_BIND_OK_ENV: "0", "AGILAB_TLS_TERMINATED": "true"},
    {guard.PUBLIC_BIND_OK_ENV: "true", "AGILAB_TLS_TERMINATED": "false"},
    {guard.PUBLIC_BIND_OK_ENV: "1"},
])
def test_rejected_public_launch_does_not_initialize_a_socket(monkeypatch, controls):
    attempts = []

    def forbidden_socket(*args, **kwargs):
        attempts.append((args, kwargs))
        raise AssertionError("rejected public launch reached socket initialization")

    for name in (guard.PUBLIC_BIND_OK_ENV, *guard.PUBLIC_BIND_CONTROL_ENVS):
        monkeypatch.delenv(name, raising=False)
    for name, value in controls.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(socketserver.TCPServer, "__init__", forbidden_socket)
    with pytest.raises(guard.PublicBindPolicyError, match="operator attestations"):
        ReactPythonServer(("0.0.0.0", 0), lambda: None)
    assert attempts == []


@pytest.mark.parametrize("host", ["127.0.0.1:8000", "http://127.0.0.1:65536/", "[::1]:invalid"])
def test_host_port_or_uri_strings_cannot_establish_a_verified_loopback_bind(host):
    assert guard.host_is_exposed(host) is True
    with pytest.raises(guard.PublicBindPolicyError) as error:
        guard.enforce_public_bind_policy({"AGILAB_UI_HOST": host})
    assert host in str(error.value)


def test_configuration_exception_is_private_and_a_later_valid_address_recovers():
    marker = "SYNTHETIC_PRIVATE_CONFIGURATION_DETAIL"

    def broken(_option):
        raise ValueError(marker)

    with pytest.raises(guard.PublicBindPolicyError) as error:
        guard.enforce_public_bind_policy({}, ui_config_getter=broken)
    assert "explicit --address" in str(error.value)
    assert marker not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True
    assert guard.enforce_public_bind_policy({}, ui_config_getter=lambda _option: " [::1] ") == "[::1]"


def test_effective_native_getter_takes_precedence_when_both_interfaces_exist():
    called = []

    def native(option):
        called.append(option)
        return "127.0.0.1"

    module = SimpleNamespace(get_option=native, config={"address": "0.0.0.0"})
    assert guard.enforce_public_bind_policy_or_stop(module, {}) == "127.0.0.1"
    assert called == ["address"]


def test_direct_page_stop_exception_is_preserved_after_the_policy_message():
    class StopPage(Exception):
        pass

    events = []

    def stop():
        events.append("stop")
        raise StopPage("page stopped")

    module = SimpleNamespace(
        get_option=lambda _option: "0.0.0.0",
        error=lambda message: events.append(message),
        stop=stop,
    )
    with pytest.raises(StopPage, match="page stopped"):
        guard.enforce_public_bind_policy_or_stop(module, {})
    assert "operator attestations, not proof" in events[0]
    assert events[1] == "stop"
