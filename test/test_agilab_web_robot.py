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
    for env_key in [
        "STREAMLIT_CONFIG_FILE",
        "STREAMLIT_THEME_BASE",
        "STREAMLIT_THEME_PRIMARY_COLOR",
        "STREAMLIT_THEME_BACKGROUND_COLOR",
        "STREAMLIT_THEME_SECONDARY_BACKGROUND_COLOR",
        "STREAMLIT_THEME_TEXT_COLOR",
    ]:
        monkeypatch.delenv(env_key, raising=False)

    env = module.build_server_env()

    assert "UV_RUN_RECURSION_DEPTH" not in env
    assert "VIRTUAL_ENV" not in env
    assert env["AGILAB_DISABLE_BACKGROUND_SERVICES"] == "1"
    assert env["STREAMLIT_CONFIG_FILE"] == str(module.REPO_ROOT / "src/agilab/resources/config.toml")
    assert env["STREAMLIT_THEME_BASE"] == "dark"
    assert env["STREAMLIT_THEME_PRIMARY_COLOR"] == "#4A90E2"
    assert env["STREAMLIT_THEME_BACKGROUND_COLOR"] == "#08111F"
    assert env["STREAMLIT_THEME_SECONDARY_BACKGROUND_COLOR"] == "#102334"
    assert env["STREAMLIT_THEME_TEXT_COLOR"] == "#F7F2E8"


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


def test_frontend_static_asset_check_accepts_streamlit_js_and_css_mime_types() -> None:
    module = _load_module()

    class _Response:
        status = 200

        def __init__(self, body: str, content_type: str) -> None:
            self.body = body.encode("utf-8")
            self.content_type = content_type

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def read(self):
            return self.body

        def getheader(self, name: str, default: str = "") -> str:
            return self.content_type if name.lower() == "content-type" else default

    responses = {
        "http://demo/?active_app=flight_telemetry": _Response(
            '<html><script type="module" src="./static/js/index.js"></script>'
            '<link rel="stylesheet" href="/static/css/index.css"></html>',
            "text/html; charset=utf-8",
        ),
        "http://demo/static/js/index.js": _Response("console.log('ok')", "application/javascript"),
        "http://demo/static/css/index.css": _Response("body{}", "text/css"),
    }

    step = module.assert_frontend_static_assets("http://demo/?active_app=flight_telemetry", opener=responses.__getitem__)

    assert step.success is True
    assert step.label == "frontend static assets"
    assert "2 Streamlit JS/CSS asset" in step.detail


def test_frontend_static_asset_check_rejects_html_served_for_js() -> None:
    module = _load_module()

    class _Response:
        def __init__(self, body: str, content_type: str) -> None:
            self.body = body.encode("utf-8")
            self.content_type = content_type

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def read(self):
            return self.body

        def getheader(self, name: str, default: str = "") -> str:
            return self.content_type if name.lower() == "content-type" else default

    responses = {
        "http://demo/": _Response('<script type="module" src="/static/js/index.js"></script>', "text/html"),
        "http://demo/static/js/index.js": _Response("<!doctype html>", "text/html"),
    }

    step = module.assert_frontend_static_assets("http://demo/", opener=responses.__getitem__)

    assert step.success is False
    assert step.label == "frontend static assets"
    assert "content-type text/html" in step.detail
    assert "application/javascript" in step.detail


def test_find_rejected_pattern_flags_browser_connection_errors() -> None:
    module = _load_module()

    assert module._find_rejected_pattern("iframe refused to connect to 127.0.0.1")
    assert module._find_rejected_pattern("❌ Install finished with errors. Check logs above.")
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
    assert args.frontend_smoke_only is False


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


def test_main_print_only_frontend_smoke_route_is_static_asset_focused(capsys) -> None:
    module = _load_module()

    code = module.main(["--print-only", "--json", "--frontend-smoke-only", "--port", "9999"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["base_url"] == "http://127.0.0.1:9999"
    assert payload["route"] == ["frontend static assets", "frontend landing hydration"]
    assert "--frontend-smoke-only" not in payload["launch_command"]


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


def test_frontend_asset_discovery_deduplicates_and_resolves_relative_urls() -> None:
    module = _load_module()

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def read(self) -> str:
            return (
                '<script type="module" src="./static/js/app.js"></script>'
                '<script src="./static/js/app.js"></script>'
                '<link rel="stylesheet" href="/static/css/app.css">'
            )

    assets = module.discover_frontend_assets(
        "http://demo/app/?active_app=flight",
        opener=lambda _url: _Response(),
    )

    assert [(asset.kind, asset.url) for asset in assets] == [
        ("script", "http://demo/app/static/js/app.js"),
        ("stylesheet", "http://demo/static/css/app.css"),
    ]


def test_frontend_static_asset_check_reports_missing_script_and_open_errors() -> None:
    module = _load_module()

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def read(self) -> bytes:
            return b'<link rel="stylesheet" href="/static/css/app.css">'

    missing_script = module.assert_frontend_static_assets("http://demo/", opener=lambda _url: _Response())

    assert missing_script.success is False
    assert "no JavaScript frontend assets discovered" in missing_script.detail

    failed_open = module.assert_frontend_static_assets(
        "http://demo/",
        opener=lambda _url: (_ for _ in ()).throw(RuntimeError("network down")),
    )

    assert failed_open.success is False
    assert "frontend asset check failed: network down" in failed_open.detail


def test_response_helpers_handle_header_variants_and_text_payloads() -> None:
    module = _load_module()

    class _HeadersContentType:
        @staticmethod
        def get_content_type() -> str:
            return "Application/JSON"

    class _HeadersGet:
        @staticmethod
        def get(_name: str, _default: str = "") -> str:
            return "text/css; charset=utf-8"

    class _GetHeaderResponse:
        @staticmethod
        def getheader(_name: str, _default: str = "") -> str:
            return "text/javascript; charset=utf-8"

    class _StringResponse:
        @staticmethod
        def read() -> str:
            return "already decoded"

    assert module._response_content_type(type("R", (), {"headers": _HeadersContentType()})()) == "application/json"
    assert module._response_content_type(type("R", (), {"headers": _HeadersGet()})()) == "text/css"
    assert module._response_content_type(_GetHeaderResponse()) == "text/javascript"
    assert module._response_content_type(object()) == ""
    assert module._read_response_text(_StringResponse()) == "already decoded"


def test_screenshot_manifest_failure_does_not_hide_screenshot(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()

    class _Page:
        @staticmethod
        def screenshot(*, path: str, full_page: bool) -> None:
            assert full_page is True
            Path(path).write_bytes(b"not a real png")

    monkeypatch.setattr(
        module,
        "build_page_shots_manifest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("manifest failed")),
    )

    screenshot = module._screenshot(_Page(), tmp_path, "bad page")

    assert screenshot == str(tmp_path / "bad-page.png")
    assert (tmp_path / "bad-page.png").read_bytes() == b"not a real png"
    assert not (tmp_path / "screenshot_manifest.json").exists()


def test_assert_page_healthy_reports_rejected_and_missing_text(tmp_path: Path) -> None:
    module = _load_module()

    class _Locator:
        def __init__(self, text: str = "", count: int = 0) -> None:
            self.text = text
            self._count = count

        def count(self) -> int:
            return self._count

        def inner_text(self, *, timeout: int) -> str:
            return self.text

    class _Page:
        url = "http://demo/"

        def __init__(self, body: str) -> None:
            self.body = body
            self.waits: list[int] = []

        def wait_for_selector(self, *_args, **_kwargs) -> None:
            return None

        def wait_for_timeout(self, ms: int) -> None:
            self.waits.append(ms)

        def screenshot(self, *, path: str, full_page: bool) -> None:
            assert full_page is True
            Path(path).write_bytes(b"png")

        def locator(self, selector: str) -> _Locator:
            if selector == "body":
                return _Locator(self.body)
            return _Locator(count=0)

    rejected = module.assert_page_healthy(
        _Page("Traceback: synthetic failure"),
        label="analysis rejected",
        expect_any=("ANALYSIS",),
        timeout_ms=0,
        screenshot_dir=tmp_path,
    )
    missing = module.assert_page_healthy(
        _Page("healthy but incomplete"),
        label="analysis missing",
        expect_any=("ANALYSIS", "Choose pages"),
        timeout_ms=0,
        screenshot_dir=tmp_path,
    )

    assert rejected.success is False
    assert "rejected pattern 'traceback'" in rejected.detail
    assert "screenshot=" in rejected.detail
    assert missing.success is False
    assert "missing expected text: ANALYSIS | Choose pages" in missing.detail


def test_main_remote_json_uses_patched_browser_robot(capsys, monkeypatch) -> None:
    module = _load_module()

    monkeypatch.setattr(
        module,
        "run_browser_robot",
        lambda **_kwargs: [module.RobotStep("remote browser", True, 1.25, "ok", "http://demo/")],
    )

    code = module.main(["--url", "http://demo", "--json", "--target-seconds", "2"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    assert payload["within_target"] is True
    assert payload["steps"][0]["label"] == "remote browser"


def test_main_remote_frontend_smoke_json_reports_setup_failure(capsys, monkeypatch) -> None:
    module = _load_module()

    def _raise_setup(**_kwargs):
        raise RuntimeError("Playwright missing")

    monkeypatch.setattr(module, "run_frontend_smoke", _raise_setup)

    code = module.main(["--url", "http://demo", "--frontend-smoke-only", "--json"])

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is False
    assert payload["steps"][0]["label"] == "browser setup"
    assert payload["steps"][0]["detail"] == "Playwright missing"


def _install_fake_playwright(monkeypatch, module, page):
    class FakePlaywrightError(Exception):
        pass

    class FakePlaywrightTimeoutError(Exception):
        pass

    class FakeContext:
        closed = False

        def new_page(self):
            return page

        def close(self) -> None:
            self.closed = True

    class FakeBrowser:
        closed = False

        def __init__(self) -> None:
            self.context = FakeContext()

        def new_context(self, *, viewport):
            assert viewport == {"width": 1440, "height": 1000}
            return self.context

        def close(self) -> None:
            self.closed = True

    class FakeBrowserType:
        def launch(self, *, headless):
            page.launch_headless = headless
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeBrowserType()
        firefox = FakeBrowserType()
        webkit = FakeBrowserType()

    class FakeSyncPlaywright:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, *_exc):
            return None

    monkeypatch.setattr(
        module,
        "_load_playwright",
        lambda: (FakePlaywrightError, FakePlaywrightTimeoutError, FakeSyncPlaywright),
    )
    return FakePlaywrightError, FakePlaywrightTimeoutError


class _FakeLocator:
    def __init__(self, page, *, selector: str, count: int = 0) -> None:
        self.page = page
        self.selector = selector
        self._count = count

    def count(self) -> int:
        return self._count

    def inner_text(self, *, timeout: int) -> str:
        assert self.selector == "body"
        return self.page.body_text

    def click(self, *, timeout: float) -> None:
        self.page.clicked_selectors.append((self.selector, timeout))


class _FakeFileChooser:
    def __init__(self, page) -> None:
        self.page = page

    def set_files(self, path: str) -> None:
        self.page.selected_files.append(Path(path).name)


class _FakeFileChooserContext:
    def __init__(self, page, error: Exception | None = None) -> None:
        self.value = _FakeFileChooser(page)
        self.error = error

    def __enter__(self):
        if self.error is not None:
            raise self.error
        return self

    def __exit__(self, *_exc):
        return None


class _FakeBrowserPage:
    def __init__(self, *, chooser_error: Exception | None = None, url_error: Exception | None = None) -> None:
        self.url = "about:blank"
        self.body_text = ""
        self.launch_headless: bool | None = None
        self.clicked_selectors: list[tuple[str, float]] = []
        self.selected_files: list[str] = []
        self.visited: list[str] = []
        self.chooser_error = chooser_error
        self.url_error = url_error

    def goto(self, url: str, *, wait_until: str, timeout: float) -> None:
        assert wait_until == "domcontentloaded"
        self.url = url
        self.visited.append(url)
        if "ORCHESTRATE" in url:
            self.body_text = "ORCHESTRATE INSTALL EXECUTE"
        elif "ANALYSIS" in url and "current_page=" in url:
            self.body_text = "View: selected analysis view"
        elif "ANALYSIS" in url:
            self.body_text = "ANALYSIS Choose pages View:"
        else:
            self.body_text = "First proof Upload"

    def wait_for_selector(self, selector: str, *, timeout: float) -> None:
        assert selector in {
            "[data-testid='stApp']",
            "[data-testid='stFileUploader'], [data-testid='stFileUploaderDropzone']",
        }

    def wait_for_url(self, _pattern, *, timeout: float) -> None:
        if self.url_error is not None:
            raise self.url_error
        self.url = "http://demo/PROJECT?active_app=flight"
        self.body_text = "PROJECT notebook uploader"

    def expect_file_chooser(self, *, timeout: float):
        return _FakeFileChooserContext(self, self.chooser_error)

    def locator(self, selector: str):
        if selector == "body":
            return _FakeLocator(self, selector=selector)
        if selector == "[data-testid='stException']":
            return _FakeLocator(self, selector=selector, count=0)
        return _FakeLocator(self, selector=selector)

    def screenshot(self, *, path: str, full_page: bool) -> None:
        assert full_page is True
        Path(path).write_bytes(b"png")


def test_run_browser_robot_covers_full_happy_path_with_analysis_view(monkeypatch) -> None:
    module = _load_module()
    page = _FakeBrowserPage()
    _install_fake_playwright(monkeypatch, module, page)

    steps = module.run_browser_robot(
        base_url="http://demo",
        active_app_query="flight",
        browser_name="chromium",
        headless=True,
        timeout=1.0,
        analysis_view="view_maps",
        analysis_view_path="/app/view_maps.py",
    )

    assert [step.label for step in steps] == [
        "landing navigation",
        "landing page",
        "about upload button",
        "notebook upload handoff",
        "project notebook uploader",
        "orchestrate navigation",
        "orchestrate page",
        "analysis navigation",
        "analysis page",
        "view_maps navigation",
        "view_maps analysis view",
    ]
    assert all(step.success for step in steps)
    assert page.launch_headless is True
    assert page.clicked_selectors == [("[data-testid='stFileUploaderDropzone'] button", 1000.0)]
    assert page.selected_files == ["agilab-web-robot-upload.ipynb"]
    assert page.visited[-1].endswith("active_app=flight&current_page=%2Fapp%2Fview_maps.py")


def test_run_browser_robot_reports_upload_handoff_failure(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    page = _FakeBrowserPage()
    PlaywrightError, _TimeoutError = _install_fake_playwright(monkeypatch, module, page)
    page.url_error = PlaywrightError("PROJECT did not load")

    steps = module.run_browser_robot(
        base_url="http://demo",
        active_app_query="flight",
        browser_name="chromium",
        headless=True,
        timeout=1.0,
        screenshot_dir=tmp_path,
    )

    assert steps[-1].label == "notebook upload handoff"
    assert steps[-1].success is False
    assert "PROJECT did not open after notebook upload" in steps[-1].detail
    assert "screenshot=" in steps[-1].detail


def test_run_frontend_smoke_covers_browser_hydration(monkeypatch) -> None:
    module = _load_module()
    page = _FakeBrowserPage()
    _install_fake_playwright(monkeypatch, module, page)
    monkeypatch.setattr(
        module,
        "assert_frontend_static_assets",
        lambda landing_url, *, opener: module.RobotStep(
            "frontend static assets",
            True,
            0.01,
            "ok",
            landing_url,
        ),
    )

    steps = module.run_frontend_smoke(
        base_url="http://demo",
        active_app_query="flight",
        browser_name="firefox",
        headless=False,
        timeout=1.0,
    )

    assert [step.label for step in steps] == [
        "frontend static assets",
        "frontend browser navigation",
        "frontend landing hydration",
    ]
    assert all(step.success for step in steps)
    assert page.launch_headless is False


def test_main_local_json_handles_health_success_and_process_exit(capsys, monkeypatch) -> None:
    module = _load_module()

    class _Process:
        returncode = 9

        @staticmethod
        def poll() -> int:
            return 9

    class _Server:
        process = _Process()

        def __init__(self, argv, *, env, url) -> None:
            self.argv = argv
            self.env = env
            self.url = url

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        @staticmethod
        def output_tail() -> str:
            return "server died"

    monkeypatch.setattr(module, "StreamlitServer", _Server)
    monkeypatch.setattr(module, "build_server_env", lambda: {"ENV": "1"})
    monkeypatch.setattr(
        module,
        "wait_for_streamlit_health",
        lambda *_args, **_kwargs: module.RobotStep("streamlit health", False, 0.2, "not ready", "http://demo"),
    )

    code = module.main(["--json", "--port", "8765", "--timeout", "1"])

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert [step["label"] for step in payload["steps"]] == ["streamlit health", "streamlit process"]
    assert "process exited with 9" in payload["steps"][1]["detail"]


def test_render_human_non_json_output_includes_route_and_step_details(capsys) -> None:
    module = _load_module()
    summary = module.RobotSummary(
        success=False,
        total_duration_seconds=2.5,
        target_seconds=2.0,
        within_target=False,
        steps=[module.RobotStep("analysis", False, 2.5, "missing View:", "http://demo/ANALYSIS")],
    )

    text = module.render_human(
        summary=summary,
        launch_command=["uv", "run", "streamlit"],
        base_url="http://demo",
    )

    assert "$ uv run streamlit" in text
    assert "verdict: FAIL" in text
    assert "within_target=no" in text
    assert "- analysis: FAIL in 2.50s - missing View:" in text

    assert module.main(["--print-only", "--port", "8765"]) == 0
    human = capsys.readouterr().out
    assert "mode: print-only" in human
    assert "route: landing Upload chooser -> PROJECT notebook handoff -> ORCHESTRATE -> ANALYSIS" in human
