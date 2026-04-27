from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "agilab" / "About_agilab.py"
SPEC = importlib.util.spec_from_file_location("agilab_about_helpers", MODULE_PATH)
assert SPEC and SPEC.loader
about_agilab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(about_agilab)


class _BrokenTemplatePath:
    def read_text(self, encoding: str = "utf-8") -> str:  # pragma: no cover - called by test
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")


class _FakeExpander:
    def __init__(self, streamlit, label: str):
        self._streamlit = streamlit
        self._label = label

    def __enter__(self):
        self._streamlit.events.append(("enter_expander", self._label))
        return self

    def __exit__(self, exc_type, exc, tb):
        self._streamlit.events.append(("exit_expander", self._label))
        return False


class _FakeStreamlit:
    def __init__(self):
        self.events: list[tuple[str, str]] = []
        self.session_state: dict[str, object] = {}

    def expander(self, label: str, expanded: bool = False):
        self.events.append(("expander", f"{label}:{expanded}"))
        return _FakeExpander(self, label)

    def write(self, body: object):
        self.events.append(("write", str(body)))

    def caption(self, body: object):
        self.events.append(("caption", str(body)))

    def info(self, body: object, **_kwargs):
        self.events.append(("info", str(body)))

    def warning(self, body: object, **_kwargs):
        self.events.append(("warning", str(body)))

    def success(self, body: object, **_kwargs):
        self.events.append(("success", str(body)))

    def error(self, body: object, **_kwargs):
        self.events.append(("error", str(body)))

    def markdown(self, body: object, **_kwargs):
        self.events.append(("markdown", str(body)))

    def code(self, body: object, **_kwargs):
        self.events.append(("code", str(body)))

    def divider(self):
        self.events.append(("divider", ""))

    def button(self, label: str, **_kwargs):
        self.events.append(("button", label))
        return False

    def rerun(self):  # pragma: no cover - button is false in these tests
        raise AssertionError("rerun should not be called")


def _event_index(events: list[tuple[str, str]], kind: str, text: str) -> int:
    return next(
        index
        for index, (event_kind, body) in enumerate(events)
        if event_kind == kind and text in body
    )


def test_ensure_env_file_falls_back_to_touch_when_template_read_fails(tmp_path, monkeypatch):
    env_file = tmp_path / ".agilab" / ".env"
    monkeypatch.setattr(about_agilab, "TEMPLATE_ENV_PATH", _BrokenTemplatePath())

    result = about_agilab._ensure_env_file(env_file)

    assert result == env_file
    assert env_file.exists()
    assert env_file.read_text(encoding="utf-8") == ""


def test_refresh_env_from_file_updates_env_map_and_apps_path(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_MODEL=gpt-5.4",
                f"APPS_PATH={apps_dir}",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(about_agilab, "ENV_FILE_PATH", env_file)
    about_agilab.st.session_state.pop("env_file_mtime_ns", None)

    env = SimpleNamespace(
        envars={},
        apps_path="old/path",
    )

    about_agilab._refresh_env_from_file(env)

    assert env.envars["OPENAI_MODEL"] == "gpt-5.4"
    assert env.envars["APPS_PATH"] == str(apps_dir)
    assert env.apps_path == apps_dir.resolve()
    assert about_agilab.st.session_state["env_file_mtime_ns"] == env_file.stat().st_mtime_ns


def test_refresh_env_from_file_ignores_bad_envars_mapping(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_MODEL=gpt-5.4\n", encoding="utf-8")
    monkeypatch.setattr(about_agilab, "ENV_FILE_PATH", env_file)
    about_agilab.st.session_state.pop("env_file_mtime_ns", None)

    env = SimpleNamespace(
        envars=object(),
        apps_path="old/path",
    )

    about_agilab._refresh_env_from_file(env)

    assert about_agilab.st.session_state["env_file_mtime_ns"] == env_file.stat().st_mtime_ns


def test_refresh_env_from_file_keeps_runtime_cluster_credentials_when_sentinel(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("CLUSTER_CREDENTIALS=__KEYRING__\n", encoding="utf-8")
    monkeypatch.setattr(about_agilab, "ENV_FILE_PATH", env_file)
    monkeypatch.setenv("CLUSTER_CREDENTIALS", "runtime:user")
    about_agilab.st.session_state.pop("env_file_mtime_ns", None)

    env = SimpleNamespace(
        envars={},
        apps_path="old/path",
    )

    about_agilab._refresh_env_from_file(env)

    assert env.envars["CLUSTER_CREDENTIALS"] == "runtime:user"


def test_resolve_share_dir_path_accepts_relative_value(tmp_path):
    resolved = about_agilab._resolve_share_dir_path("shares/data", home_path=tmp_path)
    assert resolved == (tmp_path / "shares" / "data").resolve(strict=False)


def test_resolve_share_dir_path_rejects_invalid_value(tmp_path):
    with pytest.raises(ValueError, match="AGI_SHARE_DIR"):
        about_agilab._resolve_share_dir_path("\0bad-path", home_path=tmp_path)


def test_worker_python_override_key_detection():
    assert about_agilab._is_worker_python_override_key("127.0.0.1_PYTHON_VERSION") is True
    assert about_agilab._is_worker_python_override_key("worker-a_PYTHON_VERSION") is True
    assert about_agilab._is_worker_python_override_key("AGI_PYTHON_VERSION") is False
    assert about_agilab._is_worker_python_override_key("127.0.0.1_CMD_PREFIX") is False


def test_env_editor_field_label_for_python_keys():
    assert about_agilab._env_editor_field_label("AGI_PYTHON_VERSION") == "Default Python version"
    assert about_agilab._env_editor_field_label("AGI_PYTHON_FREE_THREADED") == "Use free-threaded Python"
    assert about_agilab._env_editor_field_label("127.0.0.1_PYTHON_VERSION") == "Worker Python version for 127.0.0.1"
    assert about_agilab._env_editor_field_label("OPENAI_API_KEY") == "OPENAI_API_KEY"


def test_visible_env_editor_keys_keeps_template_order_and_adds_worker_overrides():
    template_keys = ["AGI_PYTHON_VERSION", "AGI_PYTHON_FREE_THREADED", "OPENAI_API_KEY"]
    existing_entries = [
        {"type": "entry", "key": "OPENAI_API_KEY", "value": "dummy"},
        {"type": "entry", "key": "127.0.0.1_PYTHON_VERSION", "value": "3.12"},
        {"type": "entry", "key": "10.0.0.5_CMD_PREFIX", "value": "ssh"},
        {"type": "entry", "key": "worker-a_PYTHON_VERSION", "value": "3.11"},
    ]

    assert about_agilab._visible_env_editor_keys(template_keys, existing_entries) == [
        "AGI_PYTHON_VERSION",
        "AGI_PYTHON_FREE_THREADED",
        "OPENAI_API_KEY",
        "127.0.0.1_PYTHON_VERSION",
        "worker-a_PYTHON_VERSION",
    ]


def test_newcomer_first_proof_content_exposes_single_recommended_path():
    content = about_agilab._newcomer_first_proof_content()

    assert content["title"] == "Start here"
    assert "validated flight_project source-checkout proof" in content["intro"]
    assert content["recommended_path_id"] == "source-checkout-first-proof"
    assert content["actionable_route_ids"] == ["source-checkout-first-proof"]
    assert content["documented_route_ids"] == ["notebook-quickstart", "published-package-route"]
    assert [label for label, _ in content["steps"]] == [
        "PROJECT",
        "ORCHESTRATE",
        "ANALYSIS",
    ]
    assert any("flight_project" in detail for _, detail in content["steps"])
    assert any("Generated files" in item for item in content["success_criteria"])
    assert content["compatibility_status"] == "validated"
    assert content["compatibility_report_status"] == "pass"
    assert content["proof_command_labels"] == ["preinit smoke", "source ui smoke"]
    assert content["run_manifest_filename"] == "run_manifest.json"
    assert any("run_manifest.json" in item for item in content["success_criteria"])
    assert any("newcomer-guide" in url for _, url in content["links"])
    assert any("compatibility-matrix" in url for _, url in content["links"])


def test_landing_page_sections_use_clear_product_language():
    sections = about_agilab._landing_page_sections()

    assert sections["after_first_demo"] == [
        "try another built-in demo",
        "keep cluster mode for later",
    ]


def test_about_layout_helpers_cover_display_fallbacks(tmp_path, monkeypatch):
    import agi_gui.pagelib as pagelib

    fake_st = _FakeStreamlit()
    monkeypatch.setattr(about_agilab, "st", fake_st)
    monkeypatch.setattr(
        pagelib,
        "get_base64_of_image",
        lambda _path: (_ for _ in ()).throw(OSError("missing logo")),
    )

    about_agilab.quick_logo(tmp_path)
    about_agilab.display_landing_page(tmp_path)
    about_agilab._sync_layout_module()
    about_agilab._about_layout.render_package_versions()
    about_agilab._about_layout.render_system_information()
    about_agilab._about_layout.render_footer()

    assert about_agilab._clean_openai_key("sk-" + "a" * 16) == "sk-" + "a" * 16
    assert any("Welcome to AGILAB" in body for kind, body in fake_st.events if kind == "info")
    assert any("agilab:" in body for kind, body in fake_st.events if kind == "write")
    assert any("OS:" in body for kind, body in fake_st.events if kind == "write")
    assert any("2020-" in body for kind, body in fake_st.events if kind == "markdown")


def test_newcomer_first_proof_state_prefers_built_in_flight_project(tmp_path):
    apps_path = tmp_path / "apps"
    flight_project = apps_path / "builtin" / "flight_project"
    flight_project.mkdir(parents=True)

    env = SimpleNamespace(
        apps_path=apps_path,
        app="mycode_project",
        AGILAB_LOG_ABS=tmp_path / "log",
    )

    state = about_agilab._newcomer_first_proof_state(env)

    assert state["project_path"] == flight_project.resolve()
    assert state["project_available"] is True
    assert state["current_app_matches"] is False
    assert state["compatibility_slice"] == "Source checkout first proof"
    assert state["compatibility_status"] == "validated"
    assert state["recommended_path_id"] == "source-checkout-first-proof"
    assert state["actionable_route_ids"] == ["source-checkout-first-proof"]
    assert state["run_manifest_path"] == tmp_path / "log" / "execute" / "flight" / "run_manifest.json"
    assert state["run_manifest_loaded"] is False
    assert state["run_manifest_status"] == "missing"
    assert state["remediation_status"] == "missing"
    assert "tools/compatibility_report.py --manifest" in state["evidence_commands"][1]
    assert state["next_step"] == "Go to `PROJECT`. Choose `flight_project`."


def test_first_proof_progress_rows_prioritize_project_selection(tmp_path):
    apps_path = tmp_path / "apps"
    flight_project = apps_path / "builtin" / "flight_project"
    flight_project.mkdir(parents=True)

    env = SimpleNamespace(
        apps_path=apps_path,
        app="mycode_project",
        AGILAB_LOG_ABS=tmp_path / "log",
    )

    rows = about_agilab._first_proof_progress_rows(
        about_agilab._newcomer_first_proof_state(env)
    )
    by_step = {row["step"]: row for row in rows}

    assert by_step["Project selected"]["status"] == "Next"
    assert "mycode_project" in by_step["Project selected"]["detail"]
    assert by_step["Run executed"]["status"] == "Waiting"
    assert by_step["Evidence manifest"]["status"] == "Waiting"


def test_newcomer_first_proof_state_detects_generated_outputs(tmp_path):
    apps_path = tmp_path / "apps"
    flight_project = apps_path / "flight_project"
    flight_project.mkdir(parents=True)
    output_dir = tmp_path / "log" / "execute" / "flight"
    output_dir.mkdir(parents=True)
    (output_dir / "AGI_install_flight.py").write_text("# helper", encoding="utf-8")
    (output_dir / "AGI_run_flight.py").write_text("# helper", encoding="utf-8")
    (output_dir / "forecast_metrics.json").write_text("{}", encoding="utf-8")

    env = SimpleNamespace(
        apps_path=apps_path,
        app="flight_project",
        AGILAB_LOG_ABS=tmp_path / "log",
    )

    state = about_agilab._newcomer_first_proof_state(env)

    assert state["current_app_matches"] is True
    assert state["helper_scripts_present"] is True
    assert state["run_output_detected"] is True
    assert [path.name for path in state["visible_outputs"]] == ["forecast_metrics.json"]
    assert state["remediation_status"] == "missing_manifest_with_outputs"
    assert state["next_step"] == "Generate `run_manifest.json` with the first-proof JSON command."


def test_first_proof_progress_rows_show_incomplete_manifest_attention(tmp_path):
    apps_path = tmp_path / "apps"
    flight_project = apps_path / "flight_project"
    flight_project.mkdir(parents=True)
    output_dir = tmp_path / "log" / "execute" / "flight"
    output_dir.mkdir(parents=True)
    (output_dir / "forecast_metrics.json").write_text("{}", encoding="utf-8")

    env = SimpleNamespace(
        apps_path=apps_path,
        app="flight_project",
        AGILAB_LOG_ABS=tmp_path / "log",
    )

    rows = about_agilab._first_proof_progress_rows(
        about_agilab._newcomer_first_proof_state(env)
    )
    by_step = {row["step"]: row for row in rows}

    assert by_step["Project selected"]["status"] == "Done"
    assert by_step["Run executed"]["status"] == "Done"
    assert by_step["Evidence manifest"]["status"] == "Waiting"
    assert "run_manifest.json" in by_step["Evidence manifest"]["detail"]


def test_first_proof_progress_rows_cover_missing_and_passed_states():
    base_state = {
        "active_app_name": "flight_project",
        "output_dir": "/tmp/out",
        "project_available": True,
        "current_app_matches": True,
        "run_manifest_loaded": False,
        "run_output_detected": False,
        "run_manifest_passed": False,
        "run_manifest_status": "missing",
        "run_manifest_path": "/tmp/out/run_manifest.json",
    }

    missing_rows = about_agilab._first_proof_progress_rows(
        {**base_state, "project_available": False}
    )
    assert missing_rows[0]["status"] == "Blocked"

    passed_rows = about_agilab._first_proof_progress_rows(
        {
            **base_state,
            "run_manifest_loaded": True,
            "run_manifest_passed": True,
        }
    )
    by_step = {row["step"]: row for row in passed_rows}
    assert by_step["Run executed"]["status"] == "Done"
    assert by_step["Evidence manifest"]["status"] == "Done"


def test_first_proof_next_action_branches(monkeypatch):
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(about_agilab, "st", fake_st)
    base_state = {
        "next_step": "next",
        "project_available": True,
        "current_app_matches": True,
        "run_manifest_loaded": False,
        "run_output_detected": False,
        "run_manifest_passed": False,
    }

    about_agilab._render_first_proof_next_action(
        SimpleNamespace(),
        {**base_state, "project_available": False},
    )
    about_agilab._render_first_proof_next_action(
        SimpleNamespace(),
        {**base_state, "run_manifest_passed": True},
    )
    about_agilab._render_first_proof_next_action(
        SimpleNamespace(),
        {**base_state, "run_manifest_loaded": True},
    )
    about_agilab._render_first_proof_next_action(SimpleNamespace(), base_state)

    assert any(kind == "error" for kind, _ in fake_st.events)
    assert any(kind == "success" for kind, _ in fake_st.events)
    assert any(kind == "warning" for kind, _ in fake_st.events)
    assert any(kind == "info" for kind, _ in fake_st.events)


def test_env_editor_refresh_share_dir_success_and_ignored_empty(tmp_path, monkeypatch):
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(about_agilab, "st", fake_st)
    data_root = tmp_path / "share" / "flight"
    env = SimpleNamespace(
        home_abs=tmp_path,
        share_target_name="flight",
        ensure_data_root=lambda: data_root,
    )

    about_agilab._refresh_share_dir(env, "")
    about_agilab._refresh_share_dir(env, "share")

    assert env.agi_share_path == "share"
    assert env.data_root == data_root
    assert env.dataframe_path == tmp_path / "share" / "flight" / "dataframe"


def test_render_newcomer_first_proof_places_next_action_before_diagnostics(
    tmp_path,
    monkeypatch,
):
    apps_path = tmp_path / "apps"
    flight_project = apps_path / "builtin" / "flight_project"
    flight_project.mkdir(parents=True)
    fake_st = _FakeStreamlit()
    env = SimpleNamespace(
        apps_path=apps_path,
        app="mycode_project",
        AGILAB_LOG_ABS=tmp_path / "log",
        st_resources=tmp_path / "resources",
    )

    monkeypatch.setattr(about_agilab, "st", fake_st)
    monkeypatch.setattr(about_agilab, "display_landing_page", lambda _path: None)

    about_agilab.render_newcomer_first_proof(env)

    next_action = _event_index(fake_st.events, "warning", "Next action:")
    progress = _event_index(fake_st.events, "markdown", "**Progress**")
    troubleshooting = _event_index(
        fake_st.events,
        "markdown",
        "**Troubleshooting and evidence**",
    )
    validated_path = _event_index(fake_st.events, "caption", "Validated path:")

    assert next_action < progress < troubleshooting < validated_path


def test_render_newcomer_first_proof_uses_markdown(monkeypatch):
    captured: dict[str, object] = {}

    def fake_markdown(body: str, unsafe_allow_html: bool = False):
        captured["body"] = body
        captured["unsafe_allow_html"] = unsafe_allow_html

    monkeypatch.setattr(about_agilab.st, "markdown", fake_markdown)

    about_agilab.render_newcomer_first_proof()

    assert captured["unsafe_allow_html"] is True
    body = str(captured["body"])
    assert "Start here" in body
    assert "PROJECT" in body
    assert "ORCHESTRATE" in body
    assert "ANALYSIS" in body
    assert "flight_project" in body
    assert "run_manifest.json" in body
    assert "You are done when" in body
