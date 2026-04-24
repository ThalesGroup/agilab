from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/agilab_web_robot.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("agilab_web_robot_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_streamlit_command_uses_source_ui_and_active_app() -> None:
    module = _load_module()

    command = module.build_streamlit_command(
        active_app=module.DEFAULT_ACTIVE_APP,
        apps_path=module.DEFAULT_APPS_PATH,
        port=8899,
    )

    joined = " ".join(command)
    assert command[:5] == [
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "streamlit",
    ]
    assert "src/agilab/About_agilab.py" in joined
    assert "--server.port 8899" in joined
    assert "--active-app" in command
    assert str(module.DEFAULT_ACTIVE_APP) in command
    assert "--apps-path" in command
    assert str(module.DEFAULT_APPS_PATH) in command


def test_build_url_preserves_existing_query_and_encodes_current_page() -> None:
    module = _load_module()

    url = module.build_url(
        "http://127.0.0.1:8501/?foo=bar",
        active_app="flight_project",
        current_page="/app/src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py",
    )

    assert url.startswith("http://127.0.0.1:8501/?")
    assert "foo=bar" in url
    assert "active_app=flight_project" in url
    assert "current_page=%2Fapp%2Fsrc%2Fagilab%2Fapps-pages%2Fview_maps%2Fsrc%2Fview_maps%2Fview_maps.py" in url


def test_build_page_url_targets_streamlit_page_route() -> None:
    module = _load_module()

    url = module.build_page_url("http://127.0.0.1:8501/", "ANALYSIS", active_app="flight_project")

    assert url == "http://127.0.0.1:8501/ANALYSIS?active_app=flight_project"


def test_resolve_local_active_app_accepts_builtin_project_name() -> None:
    module = _load_module()

    resolved = module.resolve_local_active_app("flight_project", str(module.DEFAULT_APPS_PATH))

    assert resolved == module.DEFAULT_ACTIVE_APP


def test_resolve_analysis_view_path_switches_between_local_and_remote() -> None:
    module = _load_module()

    local_path = module.resolve_analysis_view_path("view_maps", remote=False)
    remote_path = module.resolve_analysis_view_path("view_maps", remote=True, remote_app_root="/app")

    assert local_path == str(module.ANALYSIS_VIEW_PATHS["view_maps"].resolve())
    assert remote_path == "/app/src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py"


def test_wait_for_streamlit_health_succeeds_when_health_route_responds() -> None:
    module = _load_module()

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def getcode(self):
            return self.status

    result = module.wait_for_streamlit_health(
        "http://demo",
        timeout=1.0,
        opener=lambda _url: _Response(),
        clock=iter([0.0, 0.1, 0.2]).__next__,
        sleeper=lambda _seconds: None,
    )

    assert result.success is True
    assert result.label == "streamlit health"
    assert result.url == "http://demo/_stcore/health"


def test_find_rejected_pattern_flags_browser_connection_errors() -> None:
    module = _load_module()

    assert module._find_rejected_pattern("iframe refused to connect to 127.0.0.1")
    assert module._find_rejected_pattern("plain healthy page") is None


def test_summarize_steps_tracks_target_and_failure() -> None:
    module = _load_module()
    steps = [
        module.RobotStep("landing", True, 1.5, "ok", "http://demo"),
        module.RobotStep("analysis", False, 2.0, "traceback", "http://demo/analysis"),
    ]

    summary = module.summarize_steps(steps, target_seconds=10.0)

    assert summary.success is False
    assert summary.total_duration_seconds == 3.5
    assert summary.within_target is False


def test_main_print_only_json_has_no_playwright_requirement(capsys) -> None:
    module = _load_module()

    exit_code = module.main(["--print-only", "--json", "--port", "9999", "--analysis-view", "view_maps"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["base_url"] == "http://127.0.0.1:9999"
    assert payload["route"] == ["landing", "ORCHESTRATE", "ANALYSIS"]
    assert payload["analysis_view"] == "view_maps"
    assert payload["analysis_view_path"] == str(module.ANALYSIS_VIEW_PATHS["view_maps"].resolve())
    assert payload["launch_command"][0] == "uv"
