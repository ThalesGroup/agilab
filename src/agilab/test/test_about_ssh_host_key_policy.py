"""Regression tests for the remote hardware probe SSH host-key posture.

Covers audit finding #20 (security-app bucket): ``_remote_hardware_probe``
hardcoded ``StrictHostKeyChecking=accept-new`` (trust-on-first-use) regardless
of the strict-by-default cluster posture, and it lacked ``--`` before the ssh
target (option injection when a host starts with ``-``). The fix defaults to
``StrictHostKeyChecking=yes``, only relaxes to ``accept-new`` when the operator
opts in via the cluster host-key policy env, and inserts ``--`` before the
target.

Tests are hermetic: the module is loaded from its file path, ``_command_output``
is stubbed so no ssh runs, and the host-key policy env is controlled per test.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "about_page" / "layout.py"

_POLICY_ENV_NAMES = (
    "AGILAB_CLUSTER_SSH_HOST_KEY_POLICY",
    "AGILAB_CLUSTER_HOST_KEY_POLICY",
    "AGI_CLUSTER_SSH_HOST_KEY_POLICY",
    "AGI_CLUSTER_HOST_KEY_POLICY",
    "AGILAB_CLUSTER_SSH_STRICT_HOST_KEY_CHECKING",
)


def _load_layout():
    spec = importlib.util.spec_from_file_location(
        "agilab_about_layout_under_test", _MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


layout = _load_layout()


def _capture_probe(monkeypatch, host="node-a", user="op", key="/tmp/key"):
    captured: dict[str, tuple[str, ...]] = {}

    def _fake_command_output(cmd):
        captured["cmd"] = cmd
        return ""

    monkeypatch.setattr(layout, "_command_output", _fake_command_output)
    monkeypatch.setattr(layout, "_hardware_probes_disabled", lambda: False)
    layout._remote_hardware_probe.cache_clear()
    layout._remote_hardware_probe(host, user, key)
    layout._remote_hardware_probe.cache_clear()
    return captured["cmd"]


@pytest.fixture(autouse=True)
def _clear_policy_env(monkeypatch):
    for name in _POLICY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    yield


def test_default_probe_uses_strict_host_key_checking(monkeypatch):
    cmd = _capture_probe(monkeypatch)
    assert "StrictHostKeyChecking=yes" in cmd
    assert "StrictHostKeyChecking=accept-new" not in cmd


def test_probe_inserts_double_dash_before_target(monkeypatch):
    cmd = _capture_probe(monkeypatch, host="node-a", user="op")
    assert "--" in cmd
    dash_index = cmd.index("--")
    # The very next argv token is the ssh target, guarding option injection.
    assert cmd[dash_index + 1] == "op@node-a"


def test_probe_with_leading_dash_host_is_not_treated_as_option(monkeypatch):
    cmd = _capture_probe(monkeypatch, host="-oProxyCommand=evil", user="")
    dash_index = cmd.index("--")
    assert cmd[dash_index + 1] == "-oProxyCommand=evil"


@pytest.mark.parametrize("optin_value", ["accept-new", "tofu", "learn", "off"])
def test_operator_optin_relaxes_to_accept_new(monkeypatch, optin_value):
    monkeypatch.setenv("AGILAB_CLUSTER_SSH_HOST_KEY_POLICY", optin_value)
    cmd = _capture_probe(monkeypatch)
    assert "StrictHostKeyChecking=accept-new" in cmd


@pytest.mark.parametrize("strict_value", ["strict", "yes", "1", "on"])
def test_strict_policy_values_keep_yes(monkeypatch, strict_value):
    monkeypatch.setenv("AGILAB_CLUSTER_SSH_HOST_KEY_POLICY", strict_value)
    cmd = _capture_probe(monkeypatch)
    assert "StrictHostKeyChecking=yes" in cmd
