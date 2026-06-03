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
enforce_public_bind_policy_or_stop = guard.enforce_public_bind_policy_or_stop
public_bind_has_controls = guard.public_bind_has_controls
streamlit_config_getter_from_module = guard.streamlit_config_getter_from_module


def test_configured_streamlit_host_defaults_to_loopback():
    assert configured_streamlit_host({}) == DEFAULT_STREAMLIT_HOST


def test_configured_streamlit_host_reads_direct_streamlit_config_when_env_is_empty():
    assert (
        configured_streamlit_host({}, streamlit_config_getter=lambda key: "0.0.0.0")
        == "0.0.0.0"
    )


def test_configured_streamlit_host_uses_streamlit_address_env_and_ignores_broken_config():
    assert (
        configured_streamlit_host({"STREAMLIT_SERVER_ADDRESS": " 0.0.0.0 "})
        == "0.0.0.0"
    )

    def _broken_config(_key: str):
        raise RuntimeError("streamlit config unavailable")

    assert (
        configured_streamlit_host({}, streamlit_config_getter=_broken_config)
        == DEFAULT_STREAMLIT_HOST
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
    assert public_bind_has_controls(
        {"AGILAB_PUBLIC_BIND_OK": "1", "AGILAB_TLS_TERMINATED": "1"}
    )


def test_direct_streamlit_public_bind_is_refused_without_controls():
    with pytest.raises(PublicBindPolicyError, match="0.0.0.0"):
        enforce_public_bind_policy({}, streamlit_config_getter=lambda key: "0.0.0.0")


@pytest.mark.parametrize(
    "environment",
    [
        {"AGILAB_UI_HOST": "0.0.0.0", "AGILAB_PUBLIC_BIND_OK": "1"},
        {"AGILAB_UI_HOST": "0.0.0.0", "AGILAB_TLS_TERMINATED": "1"},
    ],
)
def test_public_bind_requires_both_controls_for_env_host(environment):
    with pytest.raises(PublicBindPolicyError, match="0.0.0.0"):
        enforce_public_bind_policy(environment)


def test_direct_streamlit_public_bind_is_allowed_with_controls():
    host = enforce_public_bind_policy(
        {"AGILAB_PUBLIC_BIND_OK": "1", "AGILAB_TLS_TERMINATED": "1"},
        streamlit_config_getter=lambda key: "0.0.0.0",
    )

    assert host == "0.0.0.0"


def test_public_bind_guard_or_stop_reports_error_before_stopping():
    class FakeStreamlit:
        errors: list[str] = []
        stopped = False

        @classmethod
        def error(cls, message: str) -> None:
            cls.errors.append(message)

        @classmethod
        def stop(cls) -> None:
            cls.stopped = True

    with pytest.raises(PublicBindPolicyError, match="0.0.0.0"):
        enforce_public_bind_policy_or_stop(
            FakeStreamlit,
            {},
            streamlit_config_getter=lambda key: "0.0.0.0",
        )

    assert FakeStreamlit.errors
    assert "AGILAB refuses to bind" in FakeStreamlit.errors[0]
    assert "AGILAB_PUBLIC_BIND_EVIDENCE" in FakeStreamlit.errors[0]
    assert FakeStreamlit.stopped is True


def test_public_bind_guard_or_stop_uses_streamlit_get_option_when_available():
    class FakeStreamlit:
        stopped = False

        @staticmethod
        def get_option(key: str) -> str:
            assert key == "server.address"
            return "0.0.0.0"

        @classmethod
        def stop(cls) -> None:
            cls.stopped = True

    with pytest.raises(PublicBindPolicyError, match="0.0.0.0"):
        enforce_public_bind_policy_or_stop(FakeStreamlit, {})

    assert FakeStreamlit.stopped is True


def test_streamlit_config_getter_prefers_get_option_over_legacy_config_get():
    class FakeConfig:
        @staticmethod
        def get(_key: str) -> str:
            return "0.0.0.0"

    class FakeStreamlit:
        config = FakeConfig()

        @staticmethod
        def get_option(_key: str) -> str:
            return "modern"

    getter = streamlit_config_getter_from_module(FakeStreamlit)

    assert getter is not None
    assert getter("server.address") == "modern"


def test_streamlit_config_getter_uses_legacy_config_get_and_stop_is_optional():
    class FakeConfig:
        @staticmethod
        def get(_key: str) -> str:
            return "0.0.0.0"

    class FakeStreamlit:
        config = FakeConfig()
        errors: list[str] = []

        @classmethod
        def error(cls, message: str) -> None:
            cls.errors.append(message)

    getter = streamlit_config_getter_from_module(FakeStreamlit)

    assert getter is not None
    assert getter("server.address") == "0.0.0.0"
    with pytest.raises(PublicBindPolicyError, match="0.0.0.0"):
        enforce_public_bind_policy_or_stop(FakeStreamlit, {})
    assert FakeStreamlit.errors
    assert streamlit_config_getter_from_module(object()) is None


def test_main_page_entrypoint_enforces_public_bind_guard():
    text = (ROOT / "src" / "agilab" / "main_page.py").read_text(encoding="utf-8")

    assert "enforce_public_bind_policy" in text
    assert "PublicBindPolicyError" in text


def test_direct_streamlit_pages_enforce_public_bind_guard():
    for page_name in (
        "1_PROJECT.py",
        "2_ORCHESTRATE.py",
        "3_WORKFLOW.py",
        "4_ANALYSIS.py",
    ):
        text = (ROOT / "src" / "agilab" / "pages" / page_name).read_text(
            encoding="utf-8"
        )

        assert "agilab.ui_public_bind_guard" in text
        assert "enforce_public_bind_policy_or_stop(" in text
        assert "st.config.get" not in text
