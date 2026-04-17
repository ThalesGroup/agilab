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


def test_newcomer_first_proof_content_exposes_single_recommended_path():
    content = about_agilab._newcomer_first_proof_content()

    assert content["title"] == "Start here"
    assert content["intro"] == "Goal: make one demo work on your computer. Start from PROJECT, not from this page."
    assert [label for label, _ in content["steps"]] == [
        "PROJECT",
        "ORCHESTRATE",
        "PIPELINE",
        "ANALYSIS",
    ]
    assert any("flight_project" in detail for _, detail in content["steps"])
    assert any("~/log/execute/flight/" in item for item in content["success_criteria"])
    assert any("newcomer-guide" in url for _, url in content["links"])
    assert any("compatibility-matrix" in url for _, url in content["links"])


def test_landing_page_sections_use_clear_product_language():
    sections = about_agilab._landing_page_sections()

    assert sections["headline"] == "Start with one local demo."
    assert sections["goal"] == "Goal: leave this page, run one demo, and open one result page."
    assert sections["do_this_now"] == [
        "Go to `PROJECT`.",
        "Choose `flight_project`.",
        "Open ORCHESTRATE.",
        "Click INSTALL.",
        "Click EXECUTE.",
        "Open PIPELINE, then ANALYSIS.",
    ]
    assert sections["done_when"] == [
        "you can see generated files",
        "you can open one result page",
    ]
    assert sections["then"] == [
        "try another demo",
        "keep cluster mode for later",
    ]


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
    assert state["compatibility_slice"] == "Web UI local first proof"
    assert state["next_step"] == "Go to `PROJECT`. Choose `flight_project`."


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
    assert state["next_step"] == "Go to `ANALYSIS`. Open one result page."


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
    assert "flight_project" in body
    assert "You are done when" in body
