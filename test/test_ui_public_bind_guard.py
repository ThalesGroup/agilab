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

DEFAULT_UI_HOST = guard.DEFAULT_UI_HOST
PublicBindPolicyError = guard.PublicBindPolicyError
configured_ui_host = guard.configured_ui_host
enforce_public_bind_policy = guard.enforce_public_bind_policy
enforce_public_bind_policy_or_stop = guard.enforce_public_bind_policy_or_stop
public_bind_has_controls = guard.public_bind_has_controls
ui_config_getter_from_module = guard.ui_config_getter_from_module


def test_configured_ui_host_defaults_to_loopback():
    assert configured_ui_host({}) == DEFAULT_UI_HOST


def test_configured_ui_host_reads_direct_react_config_when_env_is_empty():
    assert (
        configured_ui_host({}, ui_config_getter=lambda key: "0.0.0.0")
        == "0.0.0.0"
    )


def test_configured_ui_host_uses_react_address_env_for_launch():
    assert (
        configured_ui_host({"AGILAB_UI_HOST": " 0.0.0.0 "})
        == "0.0.0.0"
    )


@pytest.mark.parametrize("env_key", ["AGILAB_UI_HOST"])
def test_effective_react_config_takes_precedence_over_env_host(env_key):
    assert (
        configured_ui_host(
            {env_key: "127.0.0.1"},
            ui_config_getter=lambda key: "0.0.0.0",
        )
        == "0.0.0.0"
    )
    with pytest.raises(PublicBindPolicyError, match="0.0.0.0"):
        enforce_public_bind_policy(
            {env_key: "127.0.0.1"}, ui_config_getter=lambda key: "0.0.0.0"
        )


@pytest.mark.parametrize("host", [None, "", "  "])
def test_unset_effective_react_address_requires_public_controls(host):
    with pytest.raises(PublicBindPolicyError, match="0.0.0.0"):
        enforce_public_bind_policy({}, ui_config_getter=lambda key: host)
    assert (
        enforce_public_bind_policy(
            {"AGILAB_PUBLIC_BIND_OK": "1", "AGILAB_TLS_TERMINATED": "1"},
            ui_config_getter=lambda key: host,
        )
        == "0.0.0.0"
    )


def test_effective_react_loopback_overrides_public_launch_preference():
    assert (
        enforce_public_bind_policy(
            {"AGILAB_UI_HOST": "0.0.0.0"},
            ui_config_getter=lambda key: "127.0.0.1",
        )
        == "127.0.0.1"
    )


def test_runtime_config_unavailable_fails_closed():
    def broken_config(_key: str):
        raise RuntimeError("private configuration detail")

    with pytest.raises(PublicBindPolicyError, match="address") as caught:
        enforce_public_bind_policy(
            {"AGILAB_UI_HOST": "127.0.0.1"}, ui_config_getter=broken_config
        )
    assert "private configuration detail" not in str(caught.value)


def test_explicit_empty_environment_ignores_inherited_bind_and_controls(monkeypatch):
    monkeypatch.setenv("AGILAB_UI_HOST", "0.0.0.0")
    monkeypatch.setenv("AGILAB_PUBLIC_BIND_OK", "1")
    monkeypatch.setenv("AGILAB_TLS_TERMINATED", "1")
    assert configured_ui_host({}) == DEFAULT_UI_HOST
    assert not public_bind_has_controls({})
    with pytest.raises(PublicBindPolicyError):
        enforce_public_bind_policy({}, ui_config_getter=lambda key: "0.0.0.0")


def test_public_bind_requires_explicit_ok_and_auth_or_tls_indicator():
    assert not public_bind_has_controls({"AGILAB_TLS_TERMINATED": "1"})
    assert not public_bind_has_controls({"AGILAB_PUBLIC_BIND_OK": "1"})
    assert public_bind_has_controls(
        {"AGILAB_PUBLIC_BIND_OK": "1", "AGILAB_TLS_TERMINATED": "1"}
    )


def test_direct_react_public_bind_is_refused_without_controls():
    with pytest.raises(PublicBindPolicyError, match="0.0.0.0"):
        enforce_public_bind_policy({}, ui_config_getter=lambda key: "0.0.0.0")


@pytest.mark.parametrize(
    "host", ["192.168.1.20", "10.0.0.5", "[2001:db8::1]", "lab-host.example.com"]
)
def test_non_loopback_interface_binds_are_refused_without_controls(host):
    # Regression: binding a specific LAN/WAN interface IP or hostname is just
    # as exposed as a 0.0.0.0 wildcard bind and must require the same controls.
    with pytest.raises(PublicBindPolicyError):
        enforce_public_bind_policy({"AGILAB_UI_HOST": host})


@pytest.mark.parametrize(
    "host", ["127.0.0.1", "127.0.1.1", "::1", "[::1]", "localhost"]
)
def test_loopback_binds_never_require_controls(host):
    assert enforce_public_bind_policy({"AGILAB_UI_HOST": host}) == host


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


def test_direct_react_public_bind_is_allowed_with_controls():
    host = enforce_public_bind_policy(
        {"AGILAB_PUBLIC_BIND_OK": "1", "AGILAB_TLS_TERMINATED": "1"},
        ui_config_getter=lambda key: "0.0.0.0",
    )

    assert host == "0.0.0.0"


def test_public_bind_guard_or_stop_reports_error_before_stopping():
    class FakePythonUI:
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
            FakePythonUI,
            {},
            ui_config_getter=lambda key: "0.0.0.0",
        )

    assert FakePythonUI.errors
    assert "AGILAB refuses to bind" in FakePythonUI.errors[0]
    assert "AGILAB_PUBLIC_BIND_EVIDENCE" in FakePythonUI.errors[0]
    assert FakePythonUI.stopped is True


@pytest.mark.parametrize("actual_host", [None, "0.0.0.0"])
def test_public_bind_guard_or_stop_uses_react_get_option_when_available(
    actual_host,
):
    class FakePythonUI:
        stopped = False

        @staticmethod
        def get_option(key: str) -> str | None:
            assert key == "address"
            return actual_host

        @classmethod
        def stop(cls) -> None:
            cls.stopped = True

    with pytest.raises(PublicBindPolicyError, match="0.0.0.0"):
        enforce_public_bind_policy_or_stop(
            FakePythonUI, {"AGILAB_UI_HOST": "127.0.0.1"}
        )

    assert FakePythonUI.stopped is True


def test_direct_entrypoint_without_config_getter_fails_closed():
    with pytest.raises(PublicBindPolicyError, match="address"):
        enforce_public_bind_policy_or_stop(object(), {"AGILAB_UI_HOST": "127.0.0.1"})


def test_ui_config_getter_prefers_get_option_over_legacy_config_get():
    class FakeConfig:
        @staticmethod
        def get(_key: str) -> str:
            return "0.0.0.0"

    class FakePythonUI:
        config = FakeConfig()

        @staticmethod
        def get_option(_key: str) -> str:
            return "modern"

    getter = ui_config_getter_from_module(FakePythonUI)

    assert getter is not None
    assert getter("address") == "modern"


def test_ui_config_getter_uses_legacy_config_get_and_stop_is_optional():
    class FakeConfig:
        @staticmethod
        def get(_key: str) -> str:
            return "0.0.0.0"

    class FakePythonUI:
        config = FakeConfig()
        errors: list[str] = []

        @classmethod
        def error(cls, message: str) -> None:
            cls.errors.append(message)

    getter = ui_config_getter_from_module(FakePythonUI)

    assert getter is not None
    assert getter("address") == "0.0.0.0"
    with pytest.raises(PublicBindPolicyError, match="0.0.0.0"):
        enforce_public_bind_policy_or_stop(FakePythonUI, {})
    assert FakePythonUI.errors
    assert ui_config_getter_from_module(object()) is None


def test_main_page_entrypoint_enforces_public_bind_guard():
    text = (ROOT / "src" / "agilab" / "main_page.py").read_text(encoding="utf-8")

    assert "enforce_public_bind_policy" in text
    assert "PublicBindPolicyError" in text


def test_native_guard_bundle_matches_canonical_source():
    """A standalone host must enforce the same policy without optional root packages."""
    import tomllib

    package = ROOT / "src/agilab/lib/agi-web"
    metadata = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))
    source = metadata["tool"]["agilab"]["generated-sources"]["public-bind-guard"]
    canonical = (package / source["canonical"]).resolve()
    assert canonical == (ROOT / "src/agilab/security/ui_public_bind_guard.py").resolve()
    assert (package / source["generator"]).is_file()
    assert (package / source["destination"]).read_bytes() == canonical.read_bytes()


def test_direct_react_pages_enforce_public_bind_guard():
    for page_name in (
        "PROJECT.py",
        "PROJECT_EDITOR.py",
        "2_ORCHESTRATE.py",
        "3_WORKFLOW.py",
        "4_ANALYSIS.py",
    ):
        text = (ROOT / "src" / "agilab" / "pages" / page_name).read_text(
            encoding="utf-8"
        )

        guard_module = (
            "agilab.security.ui_public_bind_guard"
            if page_name == "PROJECT.py"
            else "agilab.ui_public_bind_guard"
        )
        assert guard_module in text
        assert "enforce_public_bind_policy_or_stop(" in text
        assert "st.config.get" not in text
