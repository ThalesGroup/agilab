from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / "src" / "agilab" / "ui_public_bind_guard.py"
SPEC = importlib.util.spec_from_file_location("agilab.ui_public_bind_guard", GUARD_PATH)
assert SPEC and SPEC.loader
guard = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("agilab.ui_public_bind_guard", guard)
SPEC.loader.exec_module(guard)

DEFAULT_STREAMLIT_HOST = guard.DEFAULT_STREAMLIT_HOST
PublicBindPolicyError = guard.PublicBindPolicyError
configured_streamlit_host = guard.configured_streamlit_host
enforce_public_bind_policy = guard.enforce_public_bind_policy
public_bind_has_controls = guard.public_bind_has_controls


def test_configured_streamlit_host_defaults_to_loopback():
    assert configured_streamlit_host({}) == DEFAULT_STREAMLIT_HOST


def test_configured_streamlit_host_reads_direct_streamlit_config_when_env_is_empty():
    assert (
        configured_streamlit_host({}, streamlit_config_getter=lambda key: "0.0.0.0")
        == "0.0.0.0"
    )


def test_env_host_takes_precedence_over_streamlit_config():
    assert (
        configured_streamlit_host(
            {"AGILAB_UI_HOST": "127.0.0.1"},
            streamlit_config_getter=lambda key: "0.0.0.0",
        )
        == "127.0.0.1"
    )


def test_public_bind_requires_explicit_ok_and_auth_or_tls_indicator():
    assert not public_bind_has_controls({"AGILAB_TLS_TERMINATED": "1"})
    assert not public_bind_has_controls({"AGILAB_PUBLIC_BIND_OK": "1"})
    assert public_bind_has_controls({"AGILAB_PUBLIC_BIND_OK": "1", "AGILAB_TLS_TERMINATED": "1"})


def test_direct_streamlit_public_bind_is_refused_without_controls():
    with pytest.raises(PublicBindPolicyError, match="0.0.0.0"):
        enforce_public_bind_policy({}, streamlit_config_getter=lambda key: "0.0.0.0")


def test_direct_streamlit_public_bind_is_allowed_with_controls():
    host = enforce_public_bind_policy(
        {"AGILAB_PUBLIC_BIND_OK": "1", "AGILAB_TLS_TERMINATED": "1"},
        streamlit_config_getter=lambda key: "0.0.0.0",
    )

    assert host == "0.0.0.0"
