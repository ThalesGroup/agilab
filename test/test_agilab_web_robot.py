from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
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
        "--extra",
    ]
    assert command[5:7] == [
        "ui",
        "streamlit",
    ]
    assert "src/agilab/main_page.py" in joined
    assert "--server.port 8899" in joined
    assert "--active-app" in command
    assert str(module.DEFAULT_ACTIVE_APP) in command
    assert "--apps-path" in command
    assert str(module.DEFAULT_APPS_PATH) in command


def test_build_server_env_scrubs_parent_uv_temp_environment(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setenv("UV_RUN_RECURSION_DEPTH", "1")
    monkeypatch.setenv("VIRTUAL_ENV", "/tmp/uv-build-env")
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))

    env = module.build_server_env()

    assert "UV_RUN_RECURSION_DEPTH" not in env
    assert "VIRTUAL_ENV" not in env
    assert env["AGILAB_DISABLE_BACKGROUND_SERVICES"] == "1"


def test_streamlit_server_output_tail_is_available_while_process_runs() -> None:
    module = _load_module()

    command = [
        sys.executable,
        "-c",
        "import time; print('server boot failed detail', flush=True); time.sleep(5)",
    ]
    with module.StreamlitServer(command, env={}, url="http://127.0.0.1:9999") as server:
        time.sleep(0.2)
        assert "server boot failed detail" in server.output_tail()


def test_build_url_preserves_existing_query_and_encodes_current_page() -> None:
    module = _load_module()

    url = module.build_url(
        "http://127.0.0.1:8501/?foo=bar",
        active_app="flight_telemetry_project",
        current_page="/app/src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py",
    )

    assert url.startswith("http://127.0.0.1:8501/?")
    assert "foo=bar" in url
    assert "active_app=flight_telemetry_project" in url
    assert "current_page=%2Fapp%2Fsrc%2Fagilab%2Fapps-pages%2Fview_maps%2Fsrc%2Fview_maps%2Fview_maps.py" in url


def test_build_page_url_targets_streamlit_page_route() -> None:
    module = _load_module()

    url = module.build_page_url("http://127.0.0.1:8501/", "ANALYSIS", active_app="flight_telemetry_project")

    assert url == "http://127.0.0.1:8501/ANALYSIS?active_app=flight_telemetry_project"


def test_resolve_local_active_app_accepts_builtin_project_name() -> None:
    module = _load_module()

    resolved = module.resolve_local_active_app("flight_telemetry_project", str(module.DEFAULT_APPS_PATH))

    assert resolved == module.DEFAULT_ACTIVE_APP


def test_resolve_local_active_app_accepts_builtin_project_shorthand() -> None:
    module = _load_module()

    resolved = module.resolve_local_active_app("uav_relay_queue", str(module.DEFAULT_APPS_PATH))

    assert Path(resolved).name == "uav_relay_queue_project"


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


def test_screenshot_capture_writes_versioned_manifest(tmp_path: Path) -> None:
    module = _load_module()

    class _Page:
        def screenshot(self, *, path: str, full_page: bool) -> None:
            assert full_page is True
            Path(path).write_bytes(
                b"\x89PNG\r\n\x1a\n"
                + (13).to_bytes(4, "big")
                + b"IHDR"
                + (12).to_bytes(4, "big")
                + (8).to_bytes(4, "big")
                + b"\x08\x02\x00\x00\x00"
                + b"\x00\x00\x00\x00"
            )

    screenshot_path = module._screenshot(_Page(), tmp_path, "WORKFLOW failure")
    manifest_path = tmp_path / "screenshot_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert screenshot_path == str(tmp_path / "WORKFLOW-failure.png")
    assert manifest["schema"] == "agilab.screenshot_manifest.v1"
    assert manifest["schema_version"] == 1
    assert manifest["screenshots"][0]["image_path"] == "WORKFLOW-failure.png"
    assert manifest["screenshots"][0]["width_px"] == 12
    assert manifest["screenshots"][0]["height_px"] == 8


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
    assert payload["route"] == [
        "landing Upload chooser",
        "PROJECT notebook handoff",
        "ORCHESTRATE",
        "ANALYSIS",
    ]
    assert payload["analysis_view"] == "view_maps"
    assert payload["analysis_view_path"] == str(module.ANALYSIS_VIEW_PATHS["view_maps"].resolve())
    assert payload["launch_command"][0] == "uv"


def test_build_parser_has_expected_defaults() -> None:
    module = _load_module()

    parser = module._build_parser()
    args = parser.parse_args([])

    assert args.url is None
    assert args.active_app == str(module.DEFAULT_ACTIVE_APP)
    assert args.apps_path == str(module.DEFAULT_APPS_PATH)
    assert args.port is None
    assert args.browser == "chromium"
    assert args.headful is False
    assert args.timeout == module.DEFAULT_TIMEOUT_SECONDS
    assert args.target_seconds == module.DEFAULT_TARGET_SECONDS
    assert args.analysis_view is None
    assert args.screenshot_dir is None


def test_wait_for_streamlit_health_can_timeout_without_success() -> None:
    module = _load_module()

    timeline = iter([0.0, 0.1, 0.2, 0.3, 0.45, 0.6])

    def _clock() -> float:
        return next(timeline)

    calls: list[str] = []

    def _opener(url: str) -> None:
        calls.append(url)
        raise RuntimeError("cannot connect")

    step = module.wait_for_streamlit_health(
        "http://127.0.0.1:9999",
        timeout=0.4,
        opener=_opener,
        clock=_clock,
        sleeper=lambda _seconds: None,
    )

    assert step.success is False
    assert step.label == "streamlit health"
    assert step.url == "http://127.0.0.1:9999/_stcore/health"
    assert step.duration_seconds >= 0.4
    assert step.detail.startswith("not ready:")
    assert calls == ["http://127.0.0.1:9999/_stcore/health"] * 4


def test_assert_page_healthy_reports_streamlit_exception_block() -> None:
    module = _load_module()

    class _Locator:
        def count(self) -> int:
            return 2

    class _Page:
        url = "http://127.0.0.1:8501"

        def wait_for_selector(self, *_args, **_kwargs) -> None:
            return None

        def locator(self, selector: str) -> _Locator:
            return _Locator()

    page = _Page()

    step = module.assert_page_healthy(
        page,
        label="landing page",
        expect_any=("AGILAB",),
        timeout_ms=500,
        screenshot_dir=None,
    )

    assert step.success is False
    assert step.label == "landing page"
    assert step.detail.startswith("Streamlit exception block found")
    assert step.url == page.url


def test_main_print_only_with_remote_url_targets_remote_analysis_view(capsys) -> None:
    module = _load_module()

    code = module.main(
        [
            "--print-only",
            "--json",
            "--url",
            "https://huggingface.co/spaces/owner/flight_space",
            "--analysis-view",
            "view_maps",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["base_url"] == "https://huggingface.co/spaces/owner/flight_space"
    assert payload["launch_command"] is None
    assert payload["analysis_view"] == "view_maps"
    assert payload["analysis_view_path"] == "/app/src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py"


def test_main_rejects_zero_timeout() -> None:
    module = _load_module()

    try:
        module.main(["--timeout", "0", "--print-only"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected parser exit for non-positive timeout")


def test_main_rejects_non_positive_target_seconds() -> None:
    module = _load_module()

    try:
        module.main(["--target-seconds", "0", "--print-only"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected parser exit for non-positive target seconds")


def test_assert_page_healthy_can_succeed_without_expected_text() -> None:
    module = _load_module()

    class _Locator:
        def count(self) -> int:
            return 0

    class _Page:
        url = "http://127.0.0.1:8501"

        def wait_for_selector(self, *_args, **_kwargs) -> None:
            return None

        def locator(self, selector: str) -> _Locator:
            return _Locator()

    page = _Page()

    step = module.assert_page_healthy(
        page,
        label="orchestrate page",
        expect_any=(),
        timeout_ms=500,
        screenshot_dir=None,
    )

    assert step.success is True
    assert step.label == "orchestrate page"


def test_main_print_only_returns_analysis_view_path_for_remote_app_with_custom_root(capsys) -> None:
    module = _load_module()

    code = module.main(
        [
            "--print-only",
            "--json",
            "--url",
            "https://huggingface.co/spaces/owner/flight_space",
            "--analysis-view",
            "view_maps_network",
            "--remote-app-root",
            "/custom",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["analysis_view_path"] == "/custom/src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py"
