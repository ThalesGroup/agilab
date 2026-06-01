from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
from pathlib import Path


MODULE_PATH = Path("tools/agilab_widget_robot.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("agilab_widget_robot_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_public_builtin_apps_are_sorted_project_directories() -> None:
    module = _load_module()

    apps = module.public_builtin_apps()

    assert apps == sorted(apps)
    assert any(path.name == "flight_telemetry_project" for path in apps)
    assert all(path.name.endswith("_project") for path in apps)


def test_resolve_apps_accepts_all_names_and_paths(tmp_path) -> None:
    module = _load_module()
    custom = tmp_path / "custom_project"
    custom.mkdir()

    all_apps = module.resolve_apps("all")
    selected = module.resolve_apps(f"flight_telemetry_project,uav_relay_queue,{custom},unknown_project")

    assert len(all_apps) >= 2
    assert any(Path(app).name == "flight_telemetry_project" for app in selected)
    assert any(Path(app).name == "uav_relay_queue_project" for app in selected)
    assert custom.resolve() in selected
    assert "unknown_project" in selected


def test_resolve_pages_accepts_all_csv_and_home_alias() -> None:
    module = _load_module()

    assert module.resolve_pages("all") == list(module.DEFAULT_PAGES)
    assert module.resolve_pages("none") == []
    assert module.resolve_pages("PROJECT, ANALYSIS") == ["PROJECT", "ANALYSIS"]


def test_settings_page_has_stable_robot_expectations() -> None:
    module = _load_module()

    assert module.PAGE_EXPECTED_TEXT["SETTINGS"] == (
        "SETTINGS",
        "Settings",
        "Runtime diagnostics",
        "Environment variables",
    )
    assert module.PAGE_EXPECTED_TEXT[""] == ("Turn experiments", "First proof: built-in demo")
    assert module.PAGE_MIN_WIDGETS["SETTINGS"] == 5
    assert module.PAGE_MIN_WIDGETS[""] == 1


def test_append_route_query_preserves_active_app_and_adds_deep_link() -> None:
    module = _load_module()

    url = module.append_route_query(
        "http://127.0.0.1:8501/PROJECT?active_app=flight_telemetry_project",
        "start=notebook-import",
    )

    assert url == "http://127.0.0.1:8501/PROJECT?active_app=flight_telemetry_project&start=notebook-import"


def test_streamlit_health_failure_detail_includes_process_output() -> None:
    module = _load_module()

    class _Health:
        detail = "not ready"

    class _Process:
        @staticmethod
        def poll() -> int:
            return 2

    class _Server:
        process = _Process()

        @staticmethod
        def output_tail() -> str:
            return "Traceback: missing dependency"

    detail = module._streamlit_health_failure_detail(
        _Health(),
        _Server(),
        base_url="http://127.0.0.1:8501",
    )

    assert "not ready" in detail
    assert "process exited with 2" in detail
    assert "Traceback: missing dependency" in detail
    assert module.resolve_pages("HOME,PROJECT") == ["", "PROJECT"]
    assert module.page_label("") == "HOME"
    assert module.DEFAULT_WIDGET_TIMEOUT_SECONDS < module.DEFAULT_TIMEOUT_SECONDS


def test_widget_robot_parser_exposes_resumable_run_controls() -> None:
    module = _load_module()

    args = module.build_parser().parse_args([])

    assert args.page_timeout == module.DEFAULT_PAGE_TIMEOUT_SECONDS
    assert args.progress_log is None
    assert args.resume_from_progress is None
    assert args.json_output is None
    assert args.quiet_progress is False
    assert args.runtime_isolation == "isolated"
    assert args.missing_selected_action_policy == "fail"
    assert args.assert_orchestrate_artifacts is False
    assert args.assert_workflow_artifacts is False
    assert args.assert_analysis_artifacts is False
    assert args.viewport_width == module.DEFAULT_VIEWPORT_WIDTH
    assert args.viewport_height == module.DEFAULT_VIEWPORT_HEIGHT
    assert args.fresh_browser_context_per_page is False
    assert args.keyboard_focus_check is False
    assert args.layout_integrity_check is False
    assert args.accessibility_check is False
    assert args.browser_error_check is False
    assert args.above_fold_check is False
    assert args.required_text == ""
    assert args.forbidden_text == ""
    assert args.forbidden_sidebar_text == ""
    assert args.required_links == ""
    assert args.required_action_labels == ""
    assert args.visual_mask_dynamic_regions is False
    assert args.success_screenshot is False
    assert args.failure_bundle_dir is None
    assert args.trace_dir is None
    assert args.har_dir is None
    assert args.video_dir is None
    assert args.max_first_render_seconds == 0.0
    assert args.max_widgets_ready_seconds == 0.0
    assert args.max_action_settle_seconds == 0.0


def test_widget_robot_context_artifact_labels_are_filesystem_safe() -> None:
    module = _load_module()

    assert module._context_artifact_label("flight/project:ANALYSIS") == "flight-project-ANALYSIS"
    assert module._context_artifact_label("") == "context"


def test_any_visible_locator_tolerates_locator_exceptions() -> None:
    module = _load_module()

    class BrokenCountLocator:
        @staticmethod
        def count():
            raise RuntimeError("detached")

    class Candidate:
        def __init__(self, visible: bool, broken: bool = False):
            self.visible = visible
            self.broken = broken

        def is_visible(self, *, timeout):
            assert timeout == 25.0
            if self.broken:
                raise RuntimeError("stale element")
            return self.visible

    class Locator:
        def __init__(self, candidates):
            self.candidates = candidates

        def count(self):
            return len(self.candidates)

        def nth(self, index):
            return self.candidates[index]

    assert module._any_visible_locator(BrokenCountLocator()) is False
    assert module._any_visible_locator(
        Locator([Candidate(False, broken=True), Candidate(True), Candidate(False)]),
        timeout_ms=25.0,
    ) is True
    assert module._any_visible_locator(
        Locator([Candidate(False), Candidate(False), Candidate(True)]),
        timeout_ms=25.0,
        limit=2,
    ) is False


def test_robot_context_records_optional_playwright_artifacts(tmp_path) -> None:
    module = _load_module()
    captured: dict[str, object] = {}
    starts: list[dict[str, object]] = []
    stops: list[dict[str, object]] = []
    closed: list[bool] = []

    class _Tracing:
        def start(self, **kwargs):
            starts.append(kwargs)

        def stop(self, **kwargs):
            stops.append(kwargs)

    class _Context:
        tracing = _Tracing()

        @staticmethod
        def close() -> None:
            closed.append(True)

    class _Browser:
        @staticmethod
        def new_context(**kwargs):
            captured.update(kwargs)
            return _Context()

    trace_dir = tmp_path / "traces"
    har_dir = tmp_path / "hars"
    video_dir = tmp_path / "videos"
    context = module._new_robot_context(
        _Browser(),
        viewport_width=1280,
        viewport_height=720,
        artifact_label="flight/PROJECT",
        trace_dir=trace_dir,
        har_dir=har_dir,
        video_dir=video_dir,
    )

    assert context is not None
    assert captured["viewport"] == {"width": 1280, "height": 720}
    assert captured["record_har_path"] == str(har_dir / "flight-PROJECT.har")
    assert captured["record_video_dir"] == str(video_dir / "flight-PROJECT")
    assert starts == [{"screenshots": True, "snapshots": True, "sources": True}]
    assert trace_dir.is_dir()
    assert har_dir.is_dir()
    assert (video_dir / "flight-PROJECT").is_dir()

    module._close_robot_context(
        context,
        artifact_label="flight/PROJECT",
        trace_dir=trace_dir,
    )

    assert stops == [{"path": str(trace_dir / "flight-PROJECT.zip")}]
    assert closed == [True]
    assert module._context_artifact_label("") == "context"


def test_robot_context_trace_failures_do_not_hide_context_close(tmp_path) -> None:
    module = _load_module()
    closed: list[bool] = []

    class _Tracing:
        @staticmethod
        def start(**_kwargs):
            raise RuntimeError("trace start failed")

        @staticmethod
        def stop(**_kwargs):
            raise RuntimeError("trace stop failed")

    class _Context:
        tracing = _Tracing()

        @staticmethod
        def close() -> None:
            closed.append(True)

    class _Browser:
        @staticmethod
        def new_context(**_kwargs):
            return _Context()

    context = module._new_robot_context(
        _Browser(),
        viewport_width=800,
        viewport_height=600,
        trace_dir=tmp_path / "trace",
    )
    module._close_robot_context(context, trace_dir=tmp_path / "trace")

    assert closed == [True]


def test_widget_robot_main_rejects_invalid_action_button_mode() -> None:
    module = _load_module()

    try:
        module.main(["--interaction-mode", "actionability", "--action-button-policy", "click"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected parser rejection for invalid action-button mode")


def test_widget_robot_main_requires_labels_for_selected_action_buttons() -> None:
    module = _load_module()

    try:
        module.main(["--interaction-mode", "full", "--action-button-policy", "click-selected"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected parser rejection for selected action buttons without labels")


def test_widget_robot_main_rejects_remote_artifact_assertions() -> None:
    module = _load_module()

    for flag in ("--assert-orchestrate-artifacts", "--assert-workflow-artifacts", "--assert-analysis-artifacts"):
        try:
            module.main(["--url", "http://localhost:8501", flag])
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError(f"expected parser rejection for remote artifact assertions with {flag}")


def test_widget_robot_main_forwards_artifact_capture_dirs(
    tmp_path, monkeypatch, capsys
) -> None:
    module = _load_module()
    captured: dict[str, object] = {}

    monkeypatch.setattr(module, "resolve_apps", lambda _value: ["flight_telemetry_project"])
    monkeypatch.setattr(module, "resolve_pages", lambda _value: [""])
    monkeypatch.setattr(module, "resolve_apps_pages", lambda _value: [])

    def _fake_sweep_app(**kwargs):
        captured.update(kwargs)
        page = module.PageSweep(
            app="flight_telemetry_project",
            page="HOME",
            success=True,
            duration_seconds=0.1,
            widget_count=1,
            main_widget_count=1,
            sidebar_widget_count=0,
            interacted_count=0,
            probed_count=1,
            skipped_count=0,
            failed_count=0,
            url="http://local",
            failures=[],
            skips=[],
        )
        kwargs["on_page_result"](page)
        return [page]

    monkeypatch.setattr(module, "sweep_app", _fake_sweep_app)

    exit_code = module.main(
        [
            "--apps",
            "flight_telemetry_project",
            "--pages",
            "HOME",
            "--apps-pages",
            "none",
            "--trace-dir",
            str(tmp_path / "traces"),
            "--har-dir",
            str(tmp_path / "hars"),
            "--video-dir",
            str(tmp_path / "videos"),
            "--quiet-progress",
            "--json",
        ]
    )

    assert exit_code == 0
    assert captured["trace_dir"] == (tmp_path / "traces").resolve()
    assert captured["har_dir"] == (tmp_path / "hars").resolve()
    assert captured["video_dir"] == (tmp_path / "videos").resolve()
    assert '"success": true' in capsys.readouterr().out


def test_write_failure_bundle_sanitizes_names_and_records_manifest(tmp_path) -> None:
    module = _load_module()
    failure = module.WidgetProbe(
        "flight_telemetry_project",
        "ANALYSIS",
        "browser_error",
        "pageerror",
        "failed",
        "broken callback",
        "http://demo",
    )

    bundle = module._write_failure_bundle(
        root=tmp_path,
        page=None,
        web_robot=None,
        app_name="flight/telemetry project",
        display="ANALYSIS:widgets",
        status="failed",
        target_url="http://demo/analysis",
        failures=[failure],
        skips=[],
        browser_issues=[{"kind": "pageerror", "detail": "broken callback"}],
        command_argv=["agilab_widget_robot.py", "--json"],
    )

    assert bundle == tmp_path / "flight-telemetry-project" / "ANALYSIS-widgets"
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == module.FAILURE_BUNDLE_SCHEMA
    assert manifest["status"] == "failed"
    assert manifest["failures"][0]["detail"] == "broken callback"
    assert manifest["command"] == ["agilab_widget_robot.py", "--json"]


def test_write_failure_bundle_records_progress_tail_and_page_diagnostics(tmp_path, monkeypatch) -> None:
    module = _load_module()
    progress_log = tmp_path / "progress.ndjson"
    progress_log.write_text('{"event":"one"}\n{"event":"two"}\n', encoding="utf-8")

    class _Page:
        url = "http://demo/current"

    monkeypatch.setattr(module, "_capture_failure_bundle_screenshot", lambda *_args, **_kwargs: ("failure.png", None))
    monkeypatch.setattr(module, "_page_text_snapshot", lambda _page: ("visible page text", None))
    monkeypatch.setattr(module, "_visible_streamlit_issue_detail", lambda _page: "streamlit exploded")

    bundle = module._write_failure_bundle(
        root=tmp_path,
        page=_Page(),
        web_robot=None,
        app_name="flight_telemetry_project",
        display="PROJECT",
        status="failed",
        target_url="http://demo/project",
        failures=[],
        skips=[],
        progress_log=progress_log,
        command_argv=["robot"],
    )

    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["url"] == "http://demo/current"
    assert manifest["screenshot"] == "failure.png"
    assert manifest["page_text"] == "page.txt"
    assert manifest["progress_tail"] == "progress-tail.ndjson"
    assert manifest["visible_issue"] == "streamlit exploded"
    assert (bundle / "page.txt").read_text(encoding="utf-8") == "visible page text"


def test_write_failure_bundle_records_page_diagnostic_collection_errors(tmp_path, monkeypatch) -> None:
    module = _load_module()

    class _Page:
        url = "http://demo/current"

    monkeypatch.setattr(module, "_capture_failure_bundle_screenshot", lambda *_args, **_kwargs: (None, "screenshot failed"))
    monkeypatch.setattr(module, "_page_text_snapshot", lambda _page: ("", "text failed"))

    def _raise_visible_issue(_page):
        raise RuntimeError("collector failed")

    monkeypatch.setattr(module, "_visible_streamlit_issue_detail", _raise_visible_issue)

    bundle = module._write_failure_bundle(
        root=tmp_path,
        page=_Page(),
        web_robot=None,
        app_name="flight_telemetry_project",
        display="PROJECT",
        status="failed",
        target_url="http://demo/project",
        failures=[],
        skips=[],
        command_argv=["robot"],
    )

    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["screenshot_error"] == "screenshot failed"
    assert manifest["page_text_error"] == "text failed"
    assert "visible issue collection failed" in manifest["visible_issue"]


def test_evidence_text_and_upload_fixture_helpers(tmp_path, monkeypatch) -> None:
    module = _load_module()
    upload = tmp_path / "upload.txt"
    upload.write_text("raw", encoding="utf-8")

    notebook = module._robot_upload_fixture_for_widget(upload, {"label": "Notebook upload"})
    json_fixture = module._robot_upload_fixture_for_widget(upload, {"label": "JSON payload"})
    csv_fixture = module._robot_upload_fixture_for_widget(upload, {"label": "CSV file"})
    raw_fixture = module._robot_upload_fixture_for_widget(upload, {"label": "Document"})

    assert notebook.suffix == ".ipynb"
    assert json.loads(notebook.read_text(encoding="utf-8"))["nbformat"] == 4
    assert json_fixture.read_text(encoding="utf-8") == "{}\n"
    assert csv_fixture.read_text(encoding="utf-8").startswith("value")
    assert raw_fixture == upload
    assert module._robot_upload_fixture_for_widget(upload, {"label": "Notebook upload"}) == notebook
    assert module._robot_upload_fixture_for_widget(upload, {"label": "JSON payload"}) == json_fixture
    assert module._robot_upload_fixture_for_widget(upload, {"label": "CSV file"}) == csv_fixture

    assert module._limited_text("a\r\nb", limit=10) == "a\nb"
    assert module._limited_text("x" * 12, limit=4) == "xxxx\n...[truncated]\n"
    assert module._tail_text_file(None) == ""
    assert module._tail_text_file(tmp_path / "missing.ndjson") == ""
    log = tmp_path / "progress.ndjson"
    log.write_text("one\ntwo\nthree\n", encoding="utf-8")
    assert module._tail_text_file(log, lines=2) == "two\nthree\n"
    original_read_text = Path.read_text

    def _raise_read_text(self, *args, **kwargs):
        if self == log:
            raise OSError("read failed")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _raise_read_text)
    assert module._tail_text_file(log) == ""

    base = tmp_path / "bundle"
    assert module._unique_evidence_dir(base) == base
    base.mkdir()
    assert module._unique_evidence_dir(base) == tmp_path / "bundle-2"
    (tmp_path / "bundle-2").mkdir()
    assert module._unique_evidence_dir(base) == tmp_path / "bundle-3"


def test_keyboard_focus_result_probe_fails_on_focus_trap() -> None:
    module = _load_module()

    direct_failure = module._keyboard_focus_result_probe(
        app_name="flight_telemetry_project",
        display="PROJECT",
        url="http://demo/PROJECT",
        focusable_count=5,
        visited_labels=[],
        failure="keyboard probe crashed",
    )
    probe = module._keyboard_focus_result_probe(
        app_name="flight_telemetry_project",
        display="PROJECT",
        url="http://demo/PROJECT",
        focusable_count=5,
        visited_labels=["INSTALL", "INSTALL", "INSTALL"],
    )

    assert direct_failure.status == "failed"
    assert "keyboard probe crashed" in direct_failure.detail
    assert probe.status == "failed"
    assert probe.kind == "keyboard_focus"
    assert "expected at least" in probe.detail


def test_keyboard_focus_result_probe_accepts_unique_visible_targets() -> None:
    module = _load_module()

    probe = module._keyboard_focus_result_probe(
        app_name="flight_telemetry_project",
        display="PROJECT",
        url="http://demo/PROJECT",
        focusable_count=5,
        visited_labels=["PROJECT", "ORCHESTRATE", "ANALYSIS"],
    )

    assert probe.status == "interacted"
    assert "unique visible focus" in probe.detail


def test_layout_integrity_result_probe_reports_first_issue() -> None:
    module = _load_module()

    probe = module._layout_integrity_result_probe(
        app_name="flight_telemetry_project",
        display="ANALYSIS",
        url="http://demo/ANALYSIS",
        issues=[{"kind": "text_overflow", "label": "Run", "detail": "text width exceeds container"}],
    )

    assert probe.status == "failed"
    assert probe.kind == "layout_integrity"
    assert "text_overflow" in probe.detail


def test_layout_integrity_result_probe_accepts_clean_geometry() -> None:
    module = _load_module()

    probe = module._layout_integrity_result_probe(
        app_name="flight_telemetry_project",
        display="ANALYSIS",
        url="http://demo/ANALYSIS",
        issues=[],
    )

    assert probe.status == "interacted"
    assert "no obvious overflow" in probe.detail


def test_accessibility_result_probe_reports_first_issue() -> None:
    module = _load_module()

    probe = module._accessibility_result_probe(
        app_name="flight_telemetry_project",
        display="PROJECT",
        url="http://demo/PROJECT",
        issues=[{"kind": "missing_accessible_name", "label": "button", "detail": "visible control has no name"}],
    )

    assert probe.status == "failed"
    assert probe.kind == "accessibility"
    assert "missing_accessible_name" in probe.detail


def test_accessibility_result_probe_accepts_clean_semantics() -> None:
    module = _load_module()

    probe = module._accessibility_result_probe(
        app_name="flight_telemetry_project",
        display="PROJECT",
        url="http://demo/PROJECT",
        issues=[],
    )

    assert probe.status == "interacted"
    assert "ARIA references" in probe.detail


def test_browser_error_check_probe_records_clean_capture() -> None:
    module = _load_module()

    probe = module._browser_error_check_probe(
        app_name="flight_telemetry_project",
        display="PROJECT",
        url="http://demo/PROJECT",
        browser_issues=[
            {"kind": "console.warning", "detail": "favicon failed to load resource"},
            {"kind": "console.error", "detail": "ignored earlier traceback"},
        ],
        start_index=2,
    )

    assert probe is not None
    assert probe.status == "interacted"
    assert probe.kind == "browser_error"
    assert "no relevant console" in probe.detail


def test_browser_error_check_probe_skips_when_existing_failure_probe_handles_issue() -> None:
    module = _load_module()

    probe = module._browser_error_check_probe(
        app_name="flight_telemetry_project",
        display="PROJECT",
        url="http://demo/PROJECT",
        browser_issues=[{"kind": "pageerror", "detail": "TypeError: broken callback"}],
        start_index=0,
    )

    assert probe is None


def test_browser_error_check_probe_fails_when_capture_is_missing() -> None:
    module = _load_module()

    probe = module._browser_error_check_probe(
        app_name="flight_telemetry_project",
        display="PROJECT",
        url="http://demo/PROJECT",
        browser_issues=None,
        start_index=0,
    )

    assert probe is not None
    assert probe.status == "failed"
    assert "capture was not attached" in probe.detail


def test_accessibility_probe_wraps_collector_shape_errors() -> None:
    module = _load_module()

    class _Page:
        url = "http://demo/PROJECT"

        @staticmethod
        def evaluate(_script: str) -> dict[str, str]:
            return {"unexpected": "payload"}

    probe = module._accessibility_probe(_Page(), app_name="flight_telemetry_project", display="PROJECT")

    assert probe.status == "failed"
    assert probe.kind == "accessibility"
    assert "collector_error" in probe.detail


def test_above_fold_result_probe_reports_missing_primary_target() -> None:
    module = _load_module()

    probe = module._above_fold_result_probe(
        app_name="flight_telemetry_project",
        display="ORCHESTRATE",
        url="http://demo/ORCHESTRATE",
        expected_labels=("ORCHESTRATE", "INSTALL", "EXECUTE"),
        seen_labels=("ORCHESTRATE", "INSTALL"),
        fold=900,
    )

    assert probe.status == "failed"
    assert probe.kind == "above_fold"
    assert "EXECUTE" in probe.detail


def test_above_fold_result_probe_accepts_primary_targets() -> None:
    module = _load_module()

    probe = module._above_fold_result_probe(
        app_name="flight_telemetry_project",
        display="ORCHESTRATE",
        url="http://demo/ORCHESTRATE",
        expected_labels=("ORCHESTRATE", "INSTALL", "EXECUTE"),
        seen_labels=("ORCHESTRATE", "INSTALL action", "EXECUTE action"),
        fold=900,
    )

    assert probe.status == "interacted"
    assert "primary targets visible" in probe.detail


def test_above_fold_probe_reports_collector_exception() -> None:
    module = _load_module()

    class _Page:
        url = "http://demo/ORCHESTRATE"

        @staticmethod
        def evaluate(_script: str) -> None:
            raise RuntimeError("js disabled")

    probe = module._above_fold_probe(_Page(), app_name="flight_telemetry_project", display="ORCHESTRATE")

    assert probe.status == "failed"
    assert probe.kind == "above_fold"
    assert "collector failed" in probe.detail


def test_above_fold_probe_filters_targets_by_initial_fold() -> None:
    module = _load_module()

    class _Page:
        url = "http://demo/ORCHESTRATE"

        @staticmethod
        def evaluate(_script: str) -> dict[str, object]:
            return {
                "fold": 800,
                "targets": [
                    {"label": "ORCHESTRATE", "inFold": True},
                    {"label": "INSTALL", "inFold": True},
                    {"label": "EXECUTE", "inFold": False},
                ],
            }

    probe = module._above_fold_probe(_Page(), app_name="flight_telemetry_project", display="ORCHESTRATE")

    assert probe.status == "failed"
    assert "EXECUTE" in probe.detail


def test_required_text_probe_reads_child_frames() -> None:
    module = _load_module()

    class _Locator:
        def __init__(self, text: str):
            self._text = text

        def inner_text(self, **_kwargs) -> str:
            return self._text

    class _Frame:
        def __init__(self, text: str):
            self._text = text

        def locator(self, _selector: str) -> _Locator:
            return _Locator(self._text)

    class _Page(_Frame):
        url = "http://demo/ANALYSIS"

        def __init__(self) -> None:
            super().__init__("PyTorch Playground")
            self.main_frame = object()
            self.frames = [
                self.main_frame,
                _Frame("Run training\nSynced RUN snippet\nSettings"),
            ]

    probe = module._required_text_probe(
        _Page(),
        app_name="pytorch_playground_project",
        display="ANALYSIS",
        required_text=("Run training", "Synced RUN snippet"),
        timeout_ms=100,
    )

    assert probe.status == "interacted"
    assert probe.kind == "required_text"


def test_required_text_probe_reports_missing_text() -> None:
    module = _load_module()

    class _Locator:
        def inner_text(self, **_kwargs) -> str:
            return "PyTorch Playground"

    class _Page:
        url = "http://demo/ANALYSIS"
        frames: list[object] = []
        main_frame = None

        @staticmethod
        def locator(_selector: str) -> _Locator:
            return _Locator()

    probe = module._required_text_probe(
        _Page(),
        app_name="pytorch_playground_project",
        display="ANALYSIS",
        required_text=("Run training",),
        timeout_ms=100,
    )

    assert probe.status == "failed"
    assert "Run training" in probe.detail


def test_forbidden_text_probe_reads_child_frames_and_passes_when_absent() -> None:
    module = _load_module()

    class _Locator:
        def __init__(self, text: str):
            self._text = text

        def inner_text(self, **_kwargs) -> str:
            return self._text

    class _Frame:
        def __init__(self, text: str):
            self._text = text

        def locator(self, _selector: str) -> _Locator:
            return _Locator(self._text)

    class _Page(_Frame):
        url = "http://demo/ANALYSIS"

        def __init__(self) -> None:
            super().__init__("PyTorch Playground\nPage")
            self.main_frame = object()
            self.frames = [self.main_frame, _Frame("Refresh evidence")]

    probe = module._forbidden_text_probe(
        _Page(),
        app_name="pytorch_playground_project",
        display="ANALYSIS",
        forbidden_text=("Project:",),
        timeout_ms=100,
    )

    assert probe.status == "interacted"
    assert probe.kind == "forbidden_text"
    assert "forbidden text absent" in probe.detail


def test_forbidden_text_probe_reports_visible_forbidden_text() -> None:
    module = _load_module()

    class _Locator:
        def inner_text(self, **_kwargs) -> str:
            return "Project: PyTorch Playground\nPage"

    class _Page:
        url = "http://demo/ANALYSIS"
        frames: list[object] = []
        main_frame = None

        @staticmethod
        def locator(_selector: str) -> _Locator:
            return _Locator()

    probe = module._forbidden_text_probe(
        _Page(),
        app_name="pytorch_playground_project",
        display="ANALYSIS",
        forbidden_text=("Project:",),
        timeout_ms=100,
    )

    assert probe.status == "failed"
    assert probe.kind == "forbidden_text"
    assert "forbidden text present" in probe.detail


def test_forbidden_sidebar_text_probe_reports_visible_sidebar_text() -> None:
    module = _load_module()

    class _SidebarLocator:
        def count(self) -> int:
            return 1

        def nth(self, index: int):
            assert index == 0
            return self

        def inner_text(self, **_kwargs) -> str:
            return "Project: PyTorch Playground\nPage"

    class _Page:
        url = "http://demo/ANALYSIS"
        frames: list[object] = []
        main_frame = None

        @staticmethod
        def locator(selector: str) -> _SidebarLocator:
            assert selector == "[data-testid='stSidebar']"
            return _SidebarLocator()

    probe = module._forbidden_sidebar_text_probe(
        _Page(),
        app_name="pytorch_playground_project",
        display="ANALYSIS",
        forbidden_sidebar_text=("Project:",),
        timeout_ms=100,
    )

    assert probe.status == "failed"
    assert probe.kind == "forbidden_sidebar_text"
    assert "forbidden sidebar text present" in probe.detail


def test_required_link_probe_matches_label_and_href_fragments() -> None:
    module = _load_module()

    class _LinkLocator:
        def count(self) -> int:
            return 1

        def nth(self, index: int):
            assert index == 0
            return self

        def is_visible(self, **_kwargs) -> bool:
            return True

        def get_attribute(self, name: str, **_kwargs) -> str:
            assert name == "href"
            return "/ANALYSIS?current_page=view_app_ui&active_app=pytorch_playground_project"

    class _Page:
        url = "http://demo/ANALYSIS"
        frames: list[object] = []
        main_frame = None

        @staticmethod
        def get_by_role(role: str, name):
            assert role == "link"
            assert getattr(name, "pattern", "Page") == "Page"
            return _LinkLocator()

    probe = module._required_link_probe(
        _Page(),
        app_name="pytorch_playground_project",
        display="ANALYSIS",
        required_links=("Page=>current_page=view_app_ui;pytorch_playground_project",),
        timeout_ms=100,
    )

    assert probe.status == "interacted"
    assert probe.kind == "required_link"
    assert "required links visible" in probe.detail


def test_required_link_probe_reports_missing_href_fragment() -> None:
    module = _load_module()

    class _LinkLocator:
        def count(self) -> int:
            return 1

        def nth(self, index: int):
            assert index == 0
            return self

        def is_visible(self, **_kwargs) -> bool:
            return True

        def get_attribute(self, name: str, **_kwargs) -> str:
            assert name == "href"
            return "/ANALYSIS?current_page=view_maps"

    class _Page:
        url = "http://demo/ANALYSIS"
        frames: list[object] = []
        main_frame = None

        @staticmethod
        def get_by_role(role: str, name):
            assert role == "link"
            return _LinkLocator()

    probe = module._required_link_probe(
        _Page(),
        app_name="pytorch_playground_project",
        display="ANALYSIS",
        required_links=("Page=>current_page=view_app_ui",),
        timeout_ms=100,
    )

    assert probe.status == "failed"
    assert probe.kind == "required_link"
    assert "required links missing" in probe.detail


def test_required_action_probe_trial_clicks_child_frame_button() -> None:
    module = _load_module()

    class _ButtonLocator:
        clicked_with_trial = False

        def count(self) -> int:
            return 1

        def nth(self, _index):
            return self

        def is_visible(self, **_kwargs) -> bool:
            return True

        def is_enabled(self, **_kwargs) -> bool:
            return True

        def click(self, **kwargs) -> None:
            self.clicked_with_trial = bool(kwargs.get("trial"))

    class _EmptyLocator:
        @staticmethod
        def count() -> int:
            return 0

    class _Frame:
        def __init__(self, locator):
            self._locator = locator

        def get_by_role(self, _role: str, **_kwargs):
            return self._locator

    button_locator = _ButtonLocator()

    class _Page(_Frame):
        url = "http://demo/ANALYSIS"

        def __init__(self) -> None:
            super().__init__(_EmptyLocator())
            self.main_frame = object()
            self.frames = [
                self.main_frame,
                _Frame(button_locator),
            ]

    probe = module._required_action_probe(
        _Page(),
        app_name="pytorch_playground_project",
        display="ANALYSIS",
        required_action_labels=("Run training",),
        timeout_ms=100,
    )

    assert probe.status == "probed"
    assert probe.kind == "required_action"
    assert button_locator.clicked_with_trial is True


def test_required_action_probe_reports_missing_button() -> None:
    module = _load_module()

    class _EmptyLocator:
        @staticmethod
        def count() -> int:
            return 0

    class _Page:
        url = "http://demo/ANALYSIS"
        frames: list[object] = []
        main_frame = None

        @staticmethod
        def get_by_role(_role: str, **_kwargs):
            return _EmptyLocator()

    probe = module._required_action_probe(
        _Page(),
        app_name="pytorch_playground_project",
        display="ANALYSIS",
        required_action_labels=("Run training",),
        timeout_ms=100,
    )

    assert probe.status == "failed"
    assert "Run training" in probe.detail


def test_widget_robot_main_rejects_non_positive_timeout() -> None:
    module = _load_module()

    try:
        module.main(["--timeout", "0"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected parser rejection for non-positive timeout")


def test_public_apps_pages_discovers_view_entrypoints() -> None:
    module = _load_module()

    routes = module.public_apps_pages()

    assert routes == sorted(routes, key=lambda route: route.name)
    assert any(route.name == "view_maps" for route in routes)
    assert all(route.path.name.startswith("view_") for route in routes)


def test_resolve_apps_pages_accepts_none_all_names_and_paths(tmp_path) -> None:
    module = _load_module()
    custom = tmp_path / "custom_view.py"
    custom.write_text("def main(): pass\n", encoding="utf-8")

    all_routes = module.resolve_apps_pages("all")
    selected = module.resolve_apps_pages(f"view_maps,{custom}")

    assert module.resolve_apps_pages("none") == []
    assert len(all_routes) >= 1
    assert any(route.name == "view_maps" for route in selected)
    assert any(route.path == custom.resolve() for route in selected)


def test_configured_apps_pages_for_app_reads_app_settings() -> None:
    module = _load_module()
    app = Path("src/agilab/apps/builtin/uav_relay_queue_project").resolve()

    routes = module.configured_apps_pages_for_app(app)

    assert [route.name for route in routes] == [
        "view_scenario_cockpit",
        "view_relay_resilience",
        "view_maps_network",
    ]


def test_apps_page_entrypoint_and_configured_pages_handle_missing_settings(tmp_path) -> None:
    module = _load_module()
    app = tmp_path / "demo_project"
    app.mkdir()

    assert module._apps_page_entrypoint(app) is None
    assert module.configured_apps_pages_for_app(app) == []


def test_active_app_route_matching_accepts_project_suffix_alias() -> None:
    module = _load_module()

    assert module.active_app_aliases("/tmp/flight_telemetry_project") == {
        "flight_telemetry_project",
        "flight_telemetry",
    }
    assert module.active_app_aliases("uav_relay_queue") == {"uav_relay_queue", "uav_relay_queue_project"}
    assert module.active_app_route_matches("http://x/WORKFLOW?active_app=flight_telemetry", "/tmp/flight_telemetry_project")
    assert module.active_app_route_matches("http://x/WORKFLOW?active_app=uav_relay_queue_project", "uav_relay_queue")
    assert module.app_target_name("uav_relay_queue_project") == "uav_relay_queue"
    assert module.app_target_name("flight_telemetry_worker") == "flight_telemetry"
    assert module.app_target_name("plain_app") == "plain_app"


def test_normalized_label_treats_ascii_and_unicode_arrows_as_equal() -> None:
    module = _load_module()

    assert module._normalized_label("Run -> Load -> Export") == module._normalized_label("Run \u2192 Load \u2192 Export")


def test_normalize_remote_url_maps_huggingface_space_page_to_runtime() -> None:
    module = _load_module()

    assert (
        module.normalize_remote_url("https://huggingface.co/spaces/jpmorard/agilab?active_app=flight_telemetry_project")
        == "https://jpmorard-agilab.hf.space/?active_app=flight_telemetry_project"
    )
    assert module.normalize_remote_url("jpmorard-agilab.hf.space") == "https://jpmorard-agilab.hf.space/"


def test_remote_apps_page_path_uses_remote_checkout_root() -> None:
    module = _load_module()
    route = next(route for route in module.public_apps_pages() if route.name == "view_maps")

    assert module.remote_apps_page_path(route, remote_app_root="/app").startswith("/app/src/agilab/apps-pages/view_maps/")


def test_project_root_for_finds_nearest_pyproject(tmp_path) -> None:
    module = _load_module()
    project_root = tmp_path / "project"
    nested_file = project_root / "src" / "pkg" / "module.py"
    nested_file.parent.mkdir(parents=True)
    nested_file.write_text("VALUE = 1\n", encoding="utf-8")
    (project_root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    assert module._project_root_for(nested_file) == project_root
    assert module._project_root_for(tmp_path / "loose.py") == tmp_path


def test_seed_public_demo_artifacts_creates_queue_analysis_bundle(tmp_path) -> None:
    module = _load_module()
    export_root = tmp_path / "export"
    share_root = tmp_path / "share"

    module.seed_public_demo_artifacts(
        "uav_relay_queue_project",
        export_root=export_root,
        share_root=share_root,
    )

    analysis_root = export_root / "uav_relay_queue" / "queue_analysis"
    summary_files = sorted(analysis_root.glob("**/*_summary_metrics.json"))
    assert len(summary_files) == 2
    first_run = summary_files[0].parent
    stem = summary_files[0].name.removesuffix("_summary_metrics.json")
    assert (first_run / f"{stem}_queue_timeseries.csv").is_file()
    assert (first_run / f"{stem}_packet_events.csv").is_file()
    assert (first_run / f"{stem}_node_positions.csv").is_file()
    assert (first_run / f"{stem}_routing_summary.csv").is_file()
    assert (first_run / "pipeline" / "topology.gml").is_file()
    assert (export_root / "00_robot_tracks.csv").is_file()


def test_seed_public_demo_artifacts_creates_forecast_evidence(tmp_path) -> None:
    module = _load_module()
    export_root = tmp_path / "export"
    share_root = tmp_path / "share"

    module.seed_public_demo_artifacts(
        "weather_forecast_project",
        export_root=export_root,
        share_root=share_root,
    )

    forecast_root = export_root / "weather_forecast" / "forecast_analysis"
    assert sorted(path.name for path in forecast_root.iterdir()) == ["baseline", "candidate"]
    assert (forecast_root / "baseline" / "forecast_metrics.json").is_file()
    assert (forecast_root / "candidate" / "forecast_predictions.csv").is_file()


def test_seed_public_demo_artifacts_skips_unknown_targets(tmp_path) -> None:
    module = _load_module()
    export_root = tmp_path / "export"
    share_root = tmp_path / "share"

    module.seed_public_demo_artifacts(
        "minimal_app_project",
        export_root=export_root,
        share_root=share_root,
    )

    assert not export_root.exists()
    assert not share_root.exists()


def test_seed_public_demo_artifacts_tolerates_placeholder_public_target(tmp_path, monkeypatch) -> None:
    module = _load_module()
    export_root = tmp_path / "export"
    share_root = tmp_path / "share"
    monkeypatch.setattr(
        module,
        "PUBLIC_APP_TARGETS_WITH_SEEDED_ARTIFACTS",
        {*module.PUBLIC_APP_TARGETS_WITH_SEEDED_ARTIFACTS, "placeholder"},
    )

    module.seed_public_demo_artifacts(
        "placeholder_project",
        export_root=export_root,
        share_root=share_root,
    )

    assert export_root.is_dir()
    assert share_root.is_dir()
    assert list(export_root.iterdir()) == []


def test_build_seeded_server_env_isolates_home_and_share_paths(tmp_path) -> None:
    module = _load_module()

    class _WebRobot:
        @staticmethod
        def build_server_env():
            return {"PATH": "robot-path", "HOME": "/real-home"}

    seeded = module.build_seeded_server_env(
        _WebRobot(),
        app_name="flight_telemetry_project",
        runtime_root=tmp_path,
        seed_demo_artifacts=True,
    )

    assert seeded.env["HOME"] == str(tmp_path / "home")
    assert seeded.env["AGI_EXPORT_DIR"] == str(tmp_path / "export")
    assert seeded.env["AGI_LOCAL_SHARE"] == str(tmp_path / "localshare")
    assert seeded.env["AGI_CLUSTER_ENABLED"] == "0"
    assert (tmp_path / "localshare" / "flight_telemetry" / "dataframe" / "00_robot_flight.csv").is_file()


def test_build_seeded_server_env_can_use_current_home_runtime(tmp_path, monkeypatch) -> None:
    module = _load_module()
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    class _WebRobot:
        @staticmethod
        def build_server_env():
            return {"PATH": "robot-path", "HOME": "/real-home"}

    seeded = module.build_seeded_server_env(
        _WebRobot(),
        app_name="flight_telemetry_project",
        runtime_root=tmp_path / "runtime",
        seed_demo_artifacts=False,
        runtime_isolation="current-home",
    )

    assert seeded.env["HOME"] == str(fake_home)
    assert "AGI_LOCAL_SHARE" not in seeded.env
    assert seeded.share_root == fake_home / "localshare"
    assert seeded.env["AGI_CLUSTER_ENABLED"] == "0"


def test_build_orchestrate_artifact_context_uses_agilab_env_file(tmp_path) -> None:
    module = _load_module()
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    env_file = fake_home / ".agilab" / ".env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text(
        "AGI_EXPORT_DIR=exports\nAGI_LOCAL_SHARE=local\nAGI_CLUSTER_SHARE=cluster\n",
        encoding="utf-8",
    )

    context = module.build_orchestrate_artifact_context(
        app_name="flight_telemetry_project",
        active_app_query="flight_telemetry_project",
        home_root=fake_home,
        server_env={},
    )

    assert context.export_root == fake_home / "exports"
    assert context.share_root == fake_home / "local"
    assert context.cluster_share_root == fake_home / "cluster"


def test_artifact_context_args_loader_ignores_bad_or_non_mapping_settings(tmp_path) -> None:
    module = _load_module()
    fake_home = tmp_path / "home"
    app_settings = fake_home / ".agilab" / "apps" / "flight_telemetry_project" / "app_settings.toml"
    app_settings.parent.mkdir(parents=True)
    app_settings.write_text("[args\n", encoding="utf-8")
    source_app = tmp_path / "source_app"
    source_settings = source_app / "src" / "app_settings.toml"
    source_settings.parent.mkdir(parents=True)
    source_settings.write_text("args = ['not', 'a', 'table']\n", encoding="utf-8")
    context = module.OrchestrateArtifactContext(
        app_name="flight_telemetry_project",
        active_app_query=source_app,
        home_root=fake_home,
        export_root=tmp_path / "export",
        share_root=tmp_path / "localshare",
        cluster_share_root=tmp_path / "clustershare",
    )

    assert module._load_app_settings_args_for_artifact_context(context) == {}


def test_build_workflow_artifact_context_uses_agilab_env_file(tmp_path) -> None:
    module = _load_module()
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    env_file = fake_home / ".agilab" / ".env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text("AGI_EXPORT_DIR=exports\n", encoding="utf-8")

    context = module.build_workflow_artifact_context(
        app_name="flight_telemetry_project",
        active_app_query="flight_telemetry_project",
        home_root=fake_home,
        server_env={},
    )

    assert context.export_root == fake_home / "exports"


def test_build_workflow_artifact_context_prefers_robot_server_env(tmp_path) -> None:
    module = _load_module()
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    env_file = fake_home / ".agilab" / ".env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text("AGI_EXPORT_DIR=stale-home-export\n", encoding="utf-8")

    context = module.build_workflow_artifact_context(
        app_name="flight_telemetry_project",
        active_app_query="flight_telemetry_project",
        home_root=fake_home,
        server_env={"AGI_EXPORT_DIR": str(tmp_path / "robot-export")},
    )

    assert context.export_root == tmp_path / "robot-export"


def test_workflow_page_artifact_validation_skips_apps_without_source_stages(tmp_path) -> None:
    module = _load_module()
    app_root = tmp_path / "empty_project"
    app_root.mkdir()
    context = module.WorkflowArtifactContext(
        app_name="empty_project",
        active_app_query=str(app_root),
        home_root=tmp_path,
        export_root=tmp_path / "export",
    )

    probes = module.validate_workflow_page_artifacts(
        context=context,
        display="WORKFLOW",
        url="http://demo",
    )

    assert probes == []


def test_workflow_page_artifact_validation_fails_when_export_contract_missing(tmp_path) -> None:
    module = _load_module()
    app_root = tmp_path / "flight_telemetry_project"
    app_root.mkdir()
    (app_root / "lab_stages.toml").write_text("[__meta__]\nschema = 'agilab.lab_stages.v1'\nversion = 1\n", encoding="utf-8")
    context = module.WorkflowArtifactContext(
        app_name="flight_telemetry_project",
        active_app_query=str(app_root),
        home_root=tmp_path,
        export_root=tmp_path / "export",
    )

    probes = module.validate_workflow_page_artifacts(
        context=context,
        display="WORKFLOW",
        url="http://demo",
    )

    assert len(probes) == 1
    assert probes[0].status == "failed"
    assert "was not restored" in probes[0].detail


def test_workflow_page_artifact_validation_requires_versioned_export_contract(tmp_path) -> None:
    module = _load_module()
    app_root = tmp_path / "flight_telemetry_project"
    app_root.mkdir()
    (app_root / "lab_stages.toml").write_text("[__meta__]\nschema = 'agilab.lab_stages.v1'\nversion = 1\n", encoding="utf-8")
    export_contract = tmp_path / "export" / "flight_telemetry" / "lab_stages.toml"
    export_contract.parent.mkdir(parents=True)
    export_contract.write_text("[flight]\n", encoding="utf-8")
    context = module.WorkflowArtifactContext(
        app_name="flight_telemetry_project",
        active_app_query=str(app_root),
        home_root=tmp_path,
        export_root=tmp_path / "export",
    )

    probes = module.validate_workflow_page_artifacts(
        context=context,
        display="WORKFLOW",
        url="http://demo",
    )

    assert len(probes) == 1
    assert probes[0].status == "failed"
    assert "missing __meta__" in probes[0].detail


def test_workflow_page_artifact_validation_accepts_restored_contract(tmp_path) -> None:
    module = _load_module()
    app_root = tmp_path / "flight_telemetry_project"
    app_root.mkdir()
    (app_root / "lab_stages.toml").write_text("[__meta__]\nschema = 'agilab.lab_stages.v1'\nversion = 1\n", encoding="utf-8")
    export_contract = tmp_path / "export" / "flight_telemetry" / "lab_stages.toml"
    export_contract.parent.mkdir(parents=True)
    export_contract.write_text("[__meta__]\nschema = 'agilab.lab_stages.v1'\nversion = 1\n", encoding="utf-8")
    context = module.WorkflowArtifactContext(
        app_name="flight_telemetry_project",
        active_app_query=str(app_root),
        home_root=tmp_path,
        export_root=tmp_path / "export",
    )

    probes = module.validate_workflow_page_artifacts(
        context=context,
        display="WORKFLOW",
        url="http://demo",
    )

    assert len(probes) == 1
    assert probes[0].status == "interacted"


def test_workflow_artifact_helpers_cover_query_paths_and_bad_contracts(tmp_path) -> None:
    module = _load_module()
    context = module.WorkflowArtifactContext(
        app_name="flight_telemetry_project",
        active_app_query="flight_telemetry_project",
        home_root=tmp_path,
        export_root=tmp_path / "export",
    )

    absolute_index = tmp_path / "absolute" / "lab_stages.toml"
    queried_absolute = module._workflow_export_stage_contract_paths(
        context,
        url=f"http://demo/WORKFLOW?index_page={absolute_index}",
    )
    assert queried_absolute[0] == absolute_index

    queried = module._workflow_export_stage_contract_paths(
        context,
        url="http://demo/WORKFLOW?index_page=custom/lab_stages.toml",
    )
    assert queried[0] == tmp_path / "export" / "custom" / "lab_stages.toml"
    assert module._workflow_export_stage_contract_paths(context, url=object())[:2] == [
        tmp_path / "export" / "flight_telemetry" / "lab_stages.toml",
        tmp_path / "export" / "flight_telemetry_project" / "lab_stages.toml",
    ]

    run_log = tmp_path / "log" / "execute" / "flight_telemetry" / "run.log"
    run_log.parent.mkdir(parents=True)
    run_log.write_text("run", encoding="utf-8")
    assert run_log in module._snapshot_workflow_run_logs(context).files

    file_root_context = module.WorkflowArtifactContext(
        app_name="weather_forecast_legacy_project",
        active_app_query="weather_forecast_legacy_project",
        home_root=tmp_path,
        export_root=tmp_path / "export",
    )
    file_root = tmp_path / "log" / "execute" / "weather_forecast_legacy"
    file_root.parent.mkdir(parents=True, exist_ok=True)
    file_root.write_text("single log root", encoding="utf-8")
    assert file_root in module._snapshot_workflow_run_logs(file_root_context).files

    unreadable = tmp_path / "bad-stage.toml"
    unreadable.write_text("[broken\n", encoding="utf-8")
    missing_meta = tmp_path / "missing-meta.toml"
    missing_meta.write_text("[step]\nname='x'\n", encoding="utf-8")
    wrong_schema = tmp_path / "wrong-schema.toml"
    wrong_schema.write_text("[__meta__]\nschema='wrong'\n", encoding="utf-8")
    assert module._workflow_stage_contract_is_versioned(unreadable)[0] is False
    assert module._workflow_stage_contract_is_versioned(missing_meta)[1] == "stage contract is missing __meta__ table"
    assert "expected" in module._workflow_stage_contract_is_versioned(wrong_schema)[1]


def test_analysis_artifact_validation_requires_first_proof_outputs(tmp_path) -> None:
    module = _load_module()
    context = module.OrchestrateArtifactContext(
        app_name="flight_telemetry_project",
        active_app_query="flight_telemetry_project",
        home_root=tmp_path,
        export_root=tmp_path / "export",
        share_root=tmp_path / "localshare",
        cluster_share_root=tmp_path / "clustershare",
    )

    probes = module.validate_analysis_artifacts(
        context=context,
        display="ANALYSIS",
        url="http://demo/ANALYSIS",
    )

    assert len(probes) == 1
    assert probes[0].status == "failed"
    assert "no first-proof output/export artifacts" in probes[0].detail


def test_analysis_artifact_validation_accepts_existing_first_proof_outputs(tmp_path) -> None:
    module = _load_module()
    output_file = tmp_path / "localshare" / "flight_telemetry" / "dataframe" / "proof.csv"
    output_file.parent.mkdir(parents=True)
    output_file.write_text("value\n1\n", encoding="utf-8")
    export_file = tmp_path / "export" / "flight_telemetry" / "proof.json"
    export_file.parent.mkdir(parents=True)
    export_file.write_text('{"ok": true}\n', encoding="utf-8")
    context = module.OrchestrateArtifactContext(
        app_name="flight_telemetry_project",
        active_app_query="flight_telemetry_project",
        home_root=tmp_path,
        export_root=tmp_path / "export",
        share_root=tmp_path / "localshare",
        cluster_share_root=tmp_path / "clustershare",
    )

    probes = module.validate_analysis_artifacts(
        context=context,
        display="ANALYSIS",
        url="http://demo/ANALYSIS",
    )

    assert len(probes) == 1
    assert probes[0].status == "interacted"
    assert "first-proof artifacts available" in probes[0].detail


def test_workflow_action_artifact_validation_detects_missing_run_log(tmp_path) -> None:
    module = _load_module()
    context = module.WorkflowArtifactContext(
        app_name="flight_telemetry_project",
        active_app_query="flight_telemetry_project",
        home_root=tmp_path,
        export_root=tmp_path / "export",
    )

    probes = module.validate_workflow_action_artifacts(
        context=context,
        display="WORKFLOW",
        selected_label="Run workflow",
        before_logs=module.ArtifactFileSnapshot(files={}),
        url="http://demo",
    )

    assert len(probes) == 1
    assert probes[0].status == "failed"
    assert "without creating or modifying a run log" in probes[0].detail
    assert module.validate_workflow_action_artifacts(
        context=context,
        display="WORKFLOW",
        selected_label="Preview workflow",
        before_logs=module.ArtifactFileSnapshot(files={}),
        url="http://demo",
    ) == []


def test_workflow_action_artifact_validation_verifies_run_log_change(tmp_path) -> None:
    module = _load_module()
    context = module.WorkflowArtifactContext(
        app_name="flight_telemetry_project",
        active_app_query="flight_telemetry_project",
        home_root=tmp_path,
        export_root=tmp_path / "export",
    )
    before_logs = module._snapshot_workflow_run_logs(context)
    log_file = tmp_path / "log" / "execute" / "flight_telemetry" / "pipeline_20260508.log"
    log_file.parent.mkdir(parents=True)
    log_file.write_text("Run workflow started\n", encoding="utf-8")

    probes = module.validate_workflow_action_artifacts(
        context=context,
        display="WORKFLOW",
        selected_label="Run workflow",
        before_logs=before_logs,
        url="http://demo",
    )

    assert len(probes) == 1
    assert probes[0].status == "interacted"
    assert "run log side effect verified" in probes[0].detail


def test_orchestrate_artifact_validation_fails_when_load_output_has_no_file(tmp_path) -> None:
    module = _load_module()
    context = module.OrchestrateArtifactContext(
        app_name="flight_telemetry_project",
        active_app_query="flight_telemetry_project",
        home_root=tmp_path,
        export_root=tmp_path / "export",
        share_root=tmp_path / "localshare",
        cluster_share_root=tmp_path / "clustershare",
    )

    probes = module.validate_orchestrate_action_artifacts(
        context=context,
        display="ORCHESTRATE",
        selected_label="Load output",
        before_output=module.ArtifactFileSnapshot(files={}),
        before_export=module.ArtifactFileSnapshot(files={}),
        before_trash=module.ArtifactFileSnapshot(files={}),
        url="http://demo",
    )

    assert len(probes) == 1
    assert probes[0].status == "failed"
    assert "no loadable output artifact" in probes[0].detail


def test_orchestrate_artifact_validation_verifies_output_side_effect(tmp_path) -> None:
    module = _load_module()
    share_root = tmp_path / "localshare"
    context = module.OrchestrateArtifactContext(
        app_name="flight_telemetry_project",
        active_app_query="flight_telemetry_project",
        home_root=tmp_path,
        export_root=tmp_path / "export",
        share_root=share_root,
        cluster_share_root=tmp_path / "clustershare",
    )
    output_file = share_root / "flight_telemetry" / "dataframe" / "part-0.csv"
    output_file.parent.mkdir(parents=True)
    output_file.write_text("value\n1\n", encoding="utf-8")

    probes = module.validate_orchestrate_action_artifacts(
        context=context,
        display="ORCHESTRATE",
        selected_label="Load output",
        before_output=module.ArtifactFileSnapshot(files={}),
        before_export=module.ArtifactFileSnapshot(files={}),
        before_trash=module.ArtifactFileSnapshot(files={}),
        url="http://demo",
    )

    assert len(probes) == 1
    assert probes[0].status == "interacted"
    assert "output artifact side effect verified" in probes[0].detail


def test_orchestrate_artifact_validation_fails_when_export_has_no_file(tmp_path) -> None:
    module = _load_module()
    context = module.OrchestrateArtifactContext(
        app_name="flight_telemetry_project",
        active_app_query="flight_telemetry_project",
        home_root=tmp_path,
        export_root=tmp_path / "export",
        share_root=tmp_path / "localshare",
        cluster_share_root=tmp_path / "clustershare",
    )

    probes = module.validate_orchestrate_action_artifacts(
        context=context,
        display="ORCHESTRATE",
        selected_label="EXPORT dataframe",
        before_output=module.ArtifactFileSnapshot(files={}),
        before_export=module.ArtifactFileSnapshot(files={}),
        before_trash=module.ArtifactFileSnapshot(files={}),
        url="http://demo",
    )

    assert len(probes) == 1
    assert probes[0].status == "failed"
    assert "export artifact was not found" in probes[0].detail


def test_artifact_snapshot_helpers_skip_invalid_empty_and_trash_paths(tmp_path, monkeypatch) -> None:
    module = _load_module()
    root = tmp_path / "artifacts"
    root.mkdir()
    empty = root / "empty.csv"
    empty.write_text("", encoding="utf-8")
    metadata = root / "run_manifest.json"
    metadata.write_text("{}", encoding="utf-8")
    trash = root / ".agilab-trash" / "old.csv"
    trash.parent.mkdir()
    trash.write_text("old", encoding="utf-8")
    visible = root / "visible.csv"
    visible.write_text("value\n1\n", encoding="utf-8")

    snapshot = module._snapshot_artifact_files([root])
    with_trash = module._snapshot_artifact_files([root], include_trash=True)
    specific = module._snapshot_specific_files([root, empty, visible], require_non_empty=True)
    root_file_snapshot = module._snapshot_artifact_files([visible])

    assert set(snapshot.files) == {visible}
    assert set(with_trash.files) == {visible, trash}
    assert set(specific.files) == {visible}
    assert set(root_file_snapshot.files) == {visible}
    assert module._snapshot_artifact_files([tmp_path / "missing"]).files == {}

    original_stat = Path.stat

    def _raising_stat(self, *args, **kwargs):
        if self == visible:
            raise OSError("stat failed")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _raising_stat)
    assert module._snapshot_artifact_files([root]).files == {}

    monkeypatch.undo()
    original_is_file = Path.is_file

    def _raising_is_file(self):
        if self == root:
            raise OSError("is_file failed")
        return original_is_file(self)

    monkeypatch.setattr(Path, "is_file", _raising_is_file)
    assert module._snapshot_artifact_files([root]).files == {}


def test_specific_artifact_snapshot_handles_bad_and_resolved_paths(tmp_path, monkeypatch) -> None:
    module = _load_module()
    real_file = tmp_path / "real.csv"
    real_file.write_text("value\n1\n", encoding="utf-8")
    link = tmp_path / "link.csv"
    link.symlink_to(real_file)

    class _BadPath:
        def expanduser(self):
            raise ValueError("bad path")

    snapshot = module._snapshot_specific_files([_BadPath(), link], require_non_empty=True)

    assert real_file in snapshot.files
    assert link in snapshot.files

    original_resolve = Path.resolve

    def _raising_resolve(self, *args, **kwargs):
        if self == real_file:
            raise OSError("resolve failed")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", _raising_resolve)
    assert set(module._snapshot_specific_files([real_file]).files) == {real_file}


def test_orchestrate_artifact_validation_verifies_export_change(tmp_path) -> None:
    module = _load_module()
    export_root = tmp_path / "export"
    context = module.OrchestrateArtifactContext(
        app_name="flight_telemetry_project",
        active_app_query="flight_telemetry_project",
        home_root=tmp_path,
        export_root=export_root,
        share_root=tmp_path / "localshare",
        cluster_share_root=tmp_path / "clustershare",
    )
    before_export = module._snapshot_artifact_files(module._orchestrate_export_roots(context))
    export_file = export_root / "flight_telemetry" / "export.csv"
    export_file.parent.mkdir(parents=True)
    export_file.write_text("value\n1\n", encoding="utf-8")

    probes = module.validate_orchestrate_action_artifacts(
        context=context,
        display="ORCHESTRATE",
        selected_label="EXPORT dataframe",
        before_output=module.ArtifactFileSnapshot(files={}),
        before_export=before_export,
        before_trash=module.ArtifactFileSnapshot(files={}),
        url="http://demo",
    )

    assert len(probes) == 1
    assert probes[0].status == "interacted"
    assert "export artifact side effect verified" in probes[0].detail


def test_orchestrate_artifact_validation_accepts_existing_manual_export(tmp_path) -> None:
    module = _load_module()
    export_root = tmp_path / "export"
    export_file = export_root / "flight_telemetry" / "export.csv"
    export_file.parent.mkdir(parents=True)
    export_file.write_text("value\n1\n", encoding="utf-8")
    context = module.OrchestrateArtifactContext(
        app_name="flight_telemetry_project",
        active_app_query="flight_telemetry_project",
        home_root=tmp_path,
        export_root=export_root,
        share_root=tmp_path / "localshare",
        cluster_share_root=tmp_path / "clustershare",
    )
    before_export = module._snapshot_artifact_files(module._orchestrate_export_roots(context))

    probes = module.validate_orchestrate_action_artifacts(
        context=context,
        display="ORCHESTRATE",
        selected_label="EXPORT dataframe",
        before_output=module.ArtifactFileSnapshot(files={}),
        before_export=before_export,
        before_trash=module.ArtifactFileSnapshot(files={}),
        url="http://demo",
    )

    assert len(probes) == 1
    assert probes[0].status == "interacted"
    assert "export artifact availability verified" in probes[0].detail


def test_orchestrate_artifact_validation_verifies_delete_backup(tmp_path) -> None:
    module = _load_module()
    share_root = tmp_path / "localshare"
    context = module.OrchestrateArtifactContext(
        app_name="flight_telemetry_project",
        active_app_query="flight_telemetry_project",
        home_root=tmp_path,
        export_root=tmp_path / "export",
        share_root=share_root,
        cluster_share_root=tmp_path / "clustershare",
    )
    output_file = share_root / "flight_telemetry" / "dataframe" / "part-0.csv"
    output_file.parent.mkdir(parents=True)
    output_file.write_text("value\n1\n", encoding="utf-8")
    output_roots = module._orchestrate_output_roots(context)
    before_output = module._snapshot_artifact_files(output_roots)
    before_trash = module._snapshot_artifact_files(output_roots, include_trash=True)
    trash_file = output_file.parent / ".agilab-trash" / "part-0.csv.bak"
    trash_file.parent.mkdir()
    output_file.replace(trash_file)

    probes = module.validate_orchestrate_action_artifacts(
        context=context,
        display="ORCHESTRATE",
        selected_label="Confirm delete",
        before_output=before_output,
        before_export=module.ArtifactFileSnapshot(files={}),
        before_trash=before_trash,
        url="http://demo",
    )

    assert len(probes) == 1
    assert probes[0].status == "interacted"
    assert "delete side effect verified" in probes[0].detail


def test_orchestrate_artifact_validation_covers_skip_and_unchanged_failures(tmp_path) -> None:
    module = _load_module()
    share_root = tmp_path / "localshare"
    export_root = tmp_path / "export"
    context = module.OrchestrateArtifactContext(
        app_name="flight_telemetry_project",
        active_app_query="flight_telemetry_project",
        home_root=tmp_path,
        export_root=export_root,
        share_root=share_root,
        cluster_share_root=tmp_path / "clustershare",
    )
    no_output_context = module.OrchestrateArtifactContext(
        app_name="minimal_app_project",
        active_app_query="minimal_app_project",
        home_root=tmp_path,
        export_root=export_root,
        share_root=share_root,
        cluster_share_root=tmp_path / "clustershare",
    )
    output_file = share_root / "flight_telemetry" / "dataframe" / "part-0.csv"
    export_file = export_root / "flight_telemetry" / "export.csv"
    output_file.parent.mkdir(parents=True)
    export_file.parent.mkdir(parents=True)
    output_file.write_text("value\n1\n", encoding="utf-8")
    export_file.write_text("value\n1\n", encoding="utf-8")
    before_output = module._snapshot_artifact_files(module._orchestrate_output_roots(context))
    before_export = module._snapshot_artifact_files(module._orchestrate_export_roots(context))

    assert module.validate_orchestrate_action_artifacts(
        context=no_output_context,
        display="ORCHESTRATE",
        selected_label="Load output",
        before_output=module.ArtifactFileSnapshot(files={}),
        before_export=module.ArtifactFileSnapshot(files={}),
        before_trash=module.ArtifactFileSnapshot(files={}),
        url="http://demo",
    ) == []

    unchanged = module.validate_orchestrate_action_artifacts(
        context=context,
        display="ORCHESTRATE",
        selected_label="Run -> Load -> Export",
        before_output=before_output,
        before_export=before_export,
        before_trash=module.ArtifactFileSnapshot(files={}),
        url="http://demo",
    )
    assert len(unchanged) == 2
    assert all(probe.status == "failed" for probe in unchanged)

    missing_delete = module.validate_orchestrate_action_artifacts(
        context=context,
        display="ORCHESTRATE",
        selected_label="Confirm delete",
        before_output=before_output,
        before_export=module.ArtifactFileSnapshot(files={}),
        before_trash=module._snapshot_artifact_files(module._orchestrate_output_roots(context), include_trash=True),
        url="http://demo",
    )
    assert len(missing_delete) == 1
    assert missing_delete[0].status == "failed"


def test_current_home_action_preflight_blocks_enabled_cluster_with_missing_share(tmp_path) -> None:
    module = _load_module()
    fake_home = tmp_path / "home"
    app_settings = fake_home / ".agilab" / "apps" / "flight_telemetry_project" / "app_settings.toml"
    app_settings.parent.mkdir(parents=True)
    app_settings.write_text("[cluster]\ncluster_enabled = true\n", encoding="utf-8")
    env_file = fake_home / ".agilab" / ".env"
    env_file.write_text(
        "AGI_CLUSTER_SHARE=missing-clustershare\nAGI_LOCAL_SHARE=localshare\n",
        encoding="utf-8",
    )

    detail = module.current_home_action_preflight_blocker(
        app_name="flight_telemetry_project",
        active_app_query="flight_telemetry_project",
        page_name="ORCHESTRATE",
        action_button_policy="click-selected",
        click_action_labels=["Run -> Load -> Export"],
        runtime_isolation="current-home",
        server_env={"AGI_CLUSTER_ENABLED": "0"},
        home_root=fake_home,
    )

    assert detail is not None
    assert "environment_blocked" in detail
    assert "AGI_CLUSTER_SHARE" in detail
    assert "missing-clustershare" in detail
    assert str(app_settings) in detail


def test_current_home_action_preflight_allows_disabled_cluster_with_missing_share(tmp_path) -> None:
    module = _load_module()
    fake_home = tmp_path / "home"
    app_settings = fake_home / ".agilab" / "apps" / "flight_telemetry_project" / "app_settings.toml"
    app_settings.parent.mkdir(parents=True)
    app_settings.write_text("[cluster]\ncluster_enabled = false\n", encoding="utf-8")
    env_file = fake_home / ".agilab" / ".env"
    env_file.write_text("AGI_CLUSTER_SHARE=missing-clustershare\n", encoding="utf-8")

    detail = module.current_home_action_preflight_blocker(
        app_name="flight_telemetry_project",
        active_app_query="flight_telemetry_project",
        page_name="ORCHESTRATE",
        action_button_policy="click-selected",
        click_action_labels=["INSTALL"],
        runtime_isolation="current-home",
        server_env={"AGI_CLUSTER_ENABLED": "0"},
        home_root=fake_home,
    )

    assert detail is None


def test_current_home_action_preflight_blocks_missing_worker_dependency(tmp_path, monkeypatch) -> None:
    module = _load_module()
    fake_home = tmp_path / "home"
    worker_root = fake_home / "wenv" / "weather_forecast_worker"
    worker_root.mkdir(parents=True)
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)

    def fake_run(argv, cwd, capture_output, text, check, timeout):
        calls.append(
            {
                "argv": argv,
                "cwd": cwd,
                "capture_output": capture_output,
                "text": text,
                "check": check,
                "timeout": timeout,
            }
        )
        return module.subprocess.CompletedProcess(
            argv,
            1,
            stdout="",
            stderr="ModuleNotFoundError: No module named 'skforecast'\n",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    detail = module.current_home_action_preflight_blocker(
        app_name="weather_forecast_project",
        active_app_query="weather_forecast_project",
        page_name="ORCHESTRATE",
        action_button_policy="click-selected",
        click_action_labels=["Run -> Load -> Export"],
        runtime_isolation="current-home",
        server_env={"AGI_CLUSTER_ENABLED": "0"},
        home_root=fake_home,
    )

    assert detail is not None
    assert "environment_blocked" in detail
    assert "weather_forecast_project" in detail
    assert "weather_forecast_worker" in detail
    assert "skforecast" in detail
    assert "Run INSTALL" in detail
    assert calls
    argv = calls[0]["argv"]
    assert argv[:6] == ["/usr/bin/uv", "--quiet", "run", "--no-sync", "--project", str(worker_root)]
    assert argv[-1] == "weather_forecast_worker"
    assert calls[0]["cwd"] == worker_root


def test_current_home_action_preflight_does_not_block_install_when_worker_missing(tmp_path) -> None:
    module = _load_module()
    fake_home = tmp_path / "home"

    detail = module.current_home_action_preflight_blocker(
        app_name="weather_forecast_project",
        active_app_query="weather_forecast_project",
        page_name="ORCHESTRATE",
        action_button_policy="click-selected",
        click_action_labels=["INSTALL"],
        runtime_isolation="current-home",
        server_env={"AGI_CLUSTER_ENABLED": "0"},
        home_root=fake_home,
    )

    assert detail is None


def test_current_home_action_preflight_allows_direct_run_with_missing_worker(tmp_path) -> None:
    module = _load_module()
    fake_home = tmp_path / "home"

    detail = module.current_home_action_preflight_blocker(
        app_name="pytorch_playground_project",
        active_app_query="pytorch_playground_project",
        page_name="ORCHESTRATE",
        action_button_policy="click-selected",
        click_action_labels=["RUN"],
        runtime_isolation="current-home",
        server_env={"AGI_CLUSTER_ENABLED": "0"},
        home_root=fake_home,
    )

    assert detail is None


def test_current_home_action_preflight_blocks_same_cluster_and_local_share(tmp_path) -> None:
    module = _load_module()
    fake_home = tmp_path / "home"
    share = fake_home / "share"
    share.mkdir(parents=True)
    app_settings = fake_home / ".agilab" / "apps" / "flight_telemetry_project" / "app_settings.toml"
    app_settings.parent.mkdir(parents=True)
    app_settings.write_text("[cluster]\ncluster_enabled = true\n", encoding="utf-8")
    env_file = fake_home / ".agilab" / ".env"
    env_file.write_text(f"AGI_CLUSTER_SHARE={share}\nAGI_LOCAL_SHARE={share}\n", encoding="utf-8")

    detail = module.current_home_action_preflight_blocker(
        app_name="flight_telemetry_project",
        active_app_query="flight_telemetry_project",
        page_name="ORCHESTRATE",
        action_button_policy="click-selected",
        click_action_labels=["CHECK distribute"],
        runtime_isolation="current-home",
        server_env={"AGI_CLUSTER_ENABLED": "0"},
        home_root=fake_home,
    )

    assert detail is not None
    assert "both resolve" in detail
    assert str(share) in detail


def test_current_home_action_preflight_allows_ready_cluster_and_worker(tmp_path, monkeypatch) -> None:
    module = _load_module()
    fake_home = tmp_path / "home"
    cluster_share = fake_home / "clustershare"
    local_share = fake_home / "localshare"
    cluster_share.mkdir(parents=True)
    local_share.mkdir(parents=True)
    app_settings = fake_home / ".agilab" / "apps" / "flight_telemetry_project" / "app_settings.toml"
    app_settings.parent.mkdir(parents=True)
    app_settings.write_text("[cluster]\ncluster_enabled = true\n", encoding="utf-8")
    env_file = fake_home / ".agilab" / ".env"
    env_file.write_text(
        f"AGI_CLUSTER_SHARE={cluster_share}\nAGI_LOCAL_SHARE={local_share}\n",
        encoding="utf-8",
    )
    worker_root = fake_home / "wenv" / "flight_telemetry_worker"
    worker_root.mkdir(parents=True)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda argv, **_kwargs: module.subprocess.CompletedProcess(argv, 0, stdout="import-ok", stderr=""),
    )

    detail = module.current_home_action_preflight_blocker(
        app_name="flight_telemetry_project",
        active_app_query="flight_telemetry_project",
        page_name="ORCHESTRATE",
        action_button_policy="click-selected",
        click_action_labels=["Run -> Load -> Export"],
        runtime_isolation="current-home",
        server_env={},
        home_root=fake_home,
    )

    assert detail is None


def test_current_home_preflight_short_circuits_and_worker_probe_errors(tmp_path, monkeypatch) -> None:
    module = _load_module()
    fake_home = tmp_path / "home"
    worker_root = fake_home / "wenv" / "flight_telemetry_worker"
    worker_root.mkdir(parents=True)

    missing_home = tmp_path / "missing-home"
    assert "installed worker project is missing" in module._current_home_worker_import_issue(
        app_name="flight_telemetry_project",
        home_root=missing_home,
    )

    assert (
        module.current_home_action_preflight_blocker(
            app_name="flight_telemetry_project",
            active_app_query="flight_telemetry_project",
            page_name="PROJECT",
            action_button_policy="click-selected",
            click_action_labels=["Run -> Load -> Export"],
            runtime_isolation="current-home",
            server_env={},
            home_root=fake_home,
        )
        is None
    )
    assert (
        module.current_home_action_preflight_blocker(
            app_name="flight_telemetry_project",
            active_app_query="flight_telemetry_project",
            page_name="ORCHESTRATE",
            action_button_policy="trial",
            click_action_labels=["Run -> Load -> Export"],
            runtime_isolation="current-home",
            server_env={},
            home_root=fake_home,
        )
        is None
    )
    assert (
        module.current_home_action_preflight_blocker(
            app_name="flight_telemetry_project",
            active_app_query="flight_telemetry_project",
            page_name="ORCHESTRATE",
            action_button_policy="click-selected",
            click_action_labels=["Run -> Load -> Export"],
            runtime_isolation="isolated",
            server_env={},
            home_root=fake_home,
        )
        is None
    )

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("uv")),
    )
    assert "uv` was not found" in module._current_home_worker_import_issue(
        app_name="flight_telemetry_project",
        home_root=fake_home,
    )

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(module.subprocess.TimeoutExpired(["uv"], 3)),
    )
    assert "timed out" in module._current_home_worker_import_issue(
        app_name="flight_telemetry_project",
        home_root=fake_home,
    )

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda argv, **_kwargs: module.subprocess.CompletedProcess(argv, 9, stdout="", stderr=""),
    )
    assert "exit code 9" in module._current_home_worker_import_issue(
        app_name="flight_telemetry_project",
        home_root=fake_home,
    )

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda argv, **_kwargs: module.subprocess.CompletedProcess(argv, 0, stdout="import-ok", stderr=""),
    )
    assert module._current_home_worker_import_issue(
        app_name="flight_telemetry_project",
        home_root=fake_home,
    ) is None


def test_config_and_artifact_path_helpers_cover_edge_cases(tmp_path, monkeypatch) -> None:
    module = _load_module()

    assert module._parse_config_bool(1) is True
    assert module._parse_config_bool(0) is False
    assert module._parse_config_bool("yes") is True
    assert module._parse_config_bool("maybe") is None
    assert module._strip_config_value('"quoted"') == "quoted"
    assert module._strip_config_value("plain") == "plain"

    dotenv = tmp_path / ".env"
    dotenv.write_text("# A='1'\nBROKEN\nB=\"two\"\n=ignored\n", encoding="utf-8")
    assert module._load_dotenv_map(dotenv) == {"A": "1", "B": "two"}
    assert module._load_dotenv_map(tmp_path / "missing.env") == {}

    empty_settings = tmp_path / "empty.toml"
    empty_settings.write_text("", encoding="utf-8")
    assert module._read_cluster_enabled_setting(empty_settings) is None
    no_cluster_key = tmp_path / "no-cluster-key.toml"
    no_cluster_key.write_text("[cluster]\nname='local'\n", encoding="utf-8")
    assert module._read_cluster_enabled_setting(no_cluster_key) is None
    bad_settings = tmp_path / "bad.toml"
    bad_settings.write_text("[cluster\n", encoding="utf-8")
    assert module._read_cluster_enabled_setting(bad_settings) is None

    missing_source = tmp_path / "missing_project"
    assert module._source_app_settings_path(missing_source) is None
    existing_source_without_settings = tmp_path / "existing_project"
    existing_source_without_settings.mkdir()
    assert module._source_app_settings_path(existing_source_without_settings) is None
    source_dir = tmp_path / "project" / "src"
    source_dir.mkdir(parents=True)
    source_settings = source_dir / "app_settings.toml"
    source_settings.write_text("[args]\ndata_out='out'\n", encoding="utf-8")
    assert module._source_app_settings_path(source_dir) == source_settings
    project_root = tmp_path / "project_root"
    project_settings = project_root / "src" / "app_settings.toml"
    project_settings.parent.mkdir(parents=True)
    project_settings.write_text("[args]\ndata_out='from-root'\n", encoding="utf-8")
    assert module._source_app_settings_path(project_root) == project_settings

    class _BadString:
        def __str__(self):
            raise TypeError("bad path")

    assert module._source_app_settings_path(_BadString()) is None

    current_home = tmp_path / "current-home"
    assert module._current_home_cluster_enabled(
        app_name="flight_telemetry_project",
        active_app_query=existing_source_without_settings,
        home_root=current_home,
        server_env={"AGI_CLUSTER_ENABLED": "on"},
        env_values={},
    ) is True
    assert module._current_home_cluster_enabled(
        app_name="flight_telemetry_project",
        active_app_query=existing_source_without_settings,
        home_root=current_home,
        server_env={"AGI_CLUSTER_ENABLED": "off"},
        env_values={"AGI_CLUSTER_ENABLED": "yes"},
    ) is True

    assert module._artifact_path_from_configured_value("", roots=[tmp_path]) == []
    assert module._artifact_path_from_configured_value("/tmp/data", roots=[tmp_path]) == [Path("/tmp/data")]
    assert module._artifact_path_from_configured_value("data", roots=[tmp_path / "a", tmp_path / "b"]) == [
        tmp_path / "a" / "data",
        tmp_path / "b" / "data",
    ]
    assert module._unique_paths([tmp_path / "a", tmp_path / "a"]) == [tmp_path / "a"]
    assert module._is_orchestrate_preview_file(tmp_path / "data.csv") is True
    assert module._is_orchestrate_preview_file(tmp_path / "run_manifest.json") is False
    assert module._is_orchestrate_preview_file(tmp_path / "._metadata.csv") is False
    assert module._rgb_brightness("not-rgb") is None

    writable = tmp_path / "writable"
    writable.mkdir()
    assert module._is_writable_directory(writable) is True
    assert module._is_writable_directory(tmp_path / "missing") is False
    monkeypatch.setattr(module.os, "listdir", lambda _path: (_ for _ in ()).throw(OSError("denied")))
    assert module._is_writable_directory(writable) is False


def test_wait_for_page_ready_returns_after_initialization_clears() -> None:
    module = _load_module()
    texts = iter(["Initializing environment...", "Ready"])
    waits: list[int] = []

    class _Body:
        def inner_text(self, timeout):
            return next(texts)

    class _Spinner:
        def count(self):
            return 0

    class _Page:
        def locator(self, selector):
            return _Body() if selector == "body" else _Spinner()

        def wait_for_timeout(self, ms):
            waits.append(ms)

    module.wait_for_page_ready(_Page(), timeout_ms=1000)

    assert waits


def test_wait_for_page_ready_ignores_hidden_initialization_text() -> None:
    module = _load_module()
    waits: list[int] = []

    class _HiddenText:
        def count(self):
            return 1

        def nth(self, _index):
            return self

        def is_visible(self, timeout):
            return False

    class _Spinner:
        def count(self):
            return 0

    class _Page:
        def get_by_text(self, _pattern):
            return _HiddenText()

        def locator(self, _selector):
            return _Spinner()

        def wait_for_timeout(self, ms):
            waits.append(ms)

    module.wait_for_page_ready(_Page(), timeout_ms=1000)

    assert waits == [module.PAGE_READY_STABILIZE_MS]


def test_summarize_counts_interactions_and_failures() -> None:
    module = _load_module()
    failure = module.WidgetProbe("flight_telemetry_project", "PROJECT", "button", "Run", "failed", "blocked", "http://demo", "sidebar")
    pages = [
        module.PageSweep(
            app="flight_telemetry_project",
            page="PROJECT",
            success=False,
            duration_seconds=1.0,
            widget_count=3,
            main_widget_count=2,
            sidebar_widget_count=1,
            interacted_count=1,
            probed_count=1,
            skipped_count=0,
            failed_count=1,
            url="http://demo",
            failures=[failure],
            skips=[],
            combination_space_count=4,
            combination_count=4,
            combination_failed_count=1,
            combination_skipped_count=0,
        )
    ]

    summary = module.summarize(pages, app_count=1, target_seconds=10.0)

    assert summary.success is False
    assert summary.widget_count == 3
    assert summary.main_widget_count == 2
    assert summary.sidebar_widget_count == 1
    assert summary.interacted_count == 1
    assert summary.probed_count == 1
    assert summary.failed_count == 1
    assert summary.combination_space_count == 4
    assert summary.combination_count == 4
    assert summary.combination_failed_count == 1
    assert summary.within_target is False


def test_summarize_reports_skipped_widgets_without_failing_sweep() -> None:
    module = _load_module()
    skip = module.WidgetProbe(
        "flight_telemetry_project",
        "WORKFLOW",
        "segmented_control",
        "Safe actions",
        "skipped",
        "not enabled",
        "http://demo",
    )
    pages = [
        module.PageSweep(
            app="flight_telemetry_project",
            page="WORKFLOW",
            success=True,
            duration_seconds=1.0,
            widget_count=3,
            main_widget_count=3,
            sidebar_widget_count=0,
            interacted_count=1,
            probed_count=1,
            skipped_count=1,
            failed_count=0,
            url="http://demo",
            failures=[],
            skips=[skip],
            status="passed",
        )
    ]

    summary = module.summarize(pages, app_count=1, target_seconds=10.0)

    assert summary.success is True
    assert summary.within_target is True
    assert summary.skipped_count == 1
    assert summary.failed_count == 0
    assert summary.pages[0].skips == [skip]


def test_progress_log_round_trips_passed_pages_only(tmp_path) -> None:
    module = _load_module()
    passed = module.PageSweep(
        app="flight_telemetry_project",
        page="PROJECT",
        success=True,
        duration_seconds=1.0,
        widget_count=1,
        interacted_count=1,
        probed_count=0,
        skipped_count=0,
        failed_count=0,
        url="http://demo",
        failures=[],
        skips=[],
        status="passed",
    )
    failed = module.PageSweep(
        app="flight_telemetry_project",
        page="WORKFLOW",
        success=False,
        duration_seconds=1.0,
        widget_count=1,
        interacted_count=0,
        probed_count=0,
        skipped_count=0,
        failed_count=1,
        url="http://demo",
        failures=[module.WidgetProbe("flight_telemetry_project", "WORKFLOW", "page", "", "failed", "boom", "http://demo")],
        skips=[],
        status="failed",
    )
    reported = []
    progress_log = tmp_path / "progress.ndjson"
    progress = module.ProgressReporter(progress_log, stderr=False)

    module._emit_page_result(passed, progress=progress, on_page_result=reported.append)
    module._emit_page_result(failed, progress=progress, on_page_result=reported.append)

    resumed = module.load_completed_page_results(progress_log)
    assert reported == [passed, failed]
    assert resumed[module.page_result_key("flight_telemetry_project", "PROJECT")] == passed
    assert module.page_result_key("flight_telemetry_project", "WORKFLOW") not in resumed


def test_progress_reporter_recreates_parent_directory_on_emit(tmp_path) -> None:
    module = _load_module()
    progress_log = tmp_path / "progress" / "robot.ndjson"
    progress = module.ProgressReporter(progress_log, stderr=False)
    progress_log.parent.rmdir()

    progress.emit("page_start", app="flight_telemetry_project", page="ORCHESTRATE")

    assert progress_log.is_file()


def test_progress_reporter_stderr_and_resume_edge_cases(tmp_path, capsys) -> None:
    module = _load_module()
    progress = module.ProgressReporter(None, stderr=True)
    progress.emit("page_start", app="flight", page="PROJECT")
    progress.emit("page_done", app="flight", page="PROJECT", status="passed", duration_seconds=1.25)
    progress.emit("page_resume", app="flight", page="PROJECT", status="passed")
    progress.emit("run_start", app_count=2, page_count=3)
    progress.emit("run_done", status="passed", duration_seconds=4.5)
    progress.emit("heartbeat")
    stderr = capsys.readouterr().err

    assert "start flight/PROJECT" in stderr
    assert "done flight/PROJECT status=passed duration=1.25s" in stderr
    assert "resume flight/PROJECT status=passed" in stderr
    assert "run start apps=2 pages=3" in stderr
    assert "run done status=passed duration=4.50s" in stderr

    missing_log = tmp_path / "missing.ndjson"
    assert module.load_completed_page_results(missing_log) == {}

    progress_log = tmp_path / "progress.ndjson"
    progress_log.write_text(
        "\n".join(
            [
                "",
                "{not-json",
                json.dumps({"event": "heartbeat"}),
                json.dumps({"event": "page_done", "result": "not-a-dict"}),
            ]
        ),
        encoding="utf-8",
    )
    assert module.load_completed_page_results(progress_log) == {}

    assert module._resume_page_if_available(
        app_name="flight",
        page_name="PROJECT",
        resume_page_results=None,
        progress=None,
        on_page_result=None,
    ) is None
    assert module._resume_page_if_available(
        app_name="flight",
        page_name="PROJECT",
        resume_page_results={},
        progress=None,
        on_page_result=None,
    ) is None
    assert module._resume_page_if_available(
        app_name="flight",
        page_name="PROJECT",
        resume_page_results={"other::PROJECT": module.PageSweep("other", "PROJECT", True, 0, 0, 0, 0, 0, 0, "", [], [])},
        progress=None,
        on_page_result=None,
    ) is None

    passed = module.PageSweep("flight", "PROJECT", True, 0, 0, 0, 0, 0, 0, "", [], [])
    assert module._resume_page_if_available(
        app_name="flight",
        page_name="PROJECT",
        resume_page_results={module.page_result_key("flight", "PROJECT"): passed},
        progress=None,
        on_page_result=None,
    ) == passed

    emitted: list[dict[str, object]] = []

    class _Progress:
        def emit(self, event, **payload):
            emitted.append({"event": event, **payload})

    assert module._resume_page_if_available(
        app_name="flight",
        page_name="PROJECT",
        resume_page_results={module.page_result_key("flight", "PROJECT"): passed},
        progress=_Progress(),
        on_page_result=None,
    ) == passed
    assert emitted == [{"event": "page_resume", "app": "flight", "page": "PROJECT", "status": "passed"}]


def test_streamlit_health_failure_detail_handles_running_process() -> None:
    module = _load_module()

    class _Process:
        def poll(self):
            return None

    class _Server:
        process = _Process()

        @staticmethod
        def output_tail():
            return "tail"

    detail = module._streamlit_health_failure_detail(
        type("Health", (), {"detail": ""})(),
        _Server(),
        base_url="http://localhost:8501",
    )

    assert "process still running" in detail
    assert "output tail: tail" in detail


def test_write_summary_json_includes_page_status(tmp_path) -> None:
    module = _load_module()
    page = module.PageSweep(
        app="flight_telemetry_project",
        page="PROJECT",
        success=True,
        duration_seconds=1.0,
        widget_count=1,
        interacted_count=1,
        probed_count=0,
        skipped_count=0,
        failed_count=0,
        url="http://demo",
        failures=[],
        skips=[],
        status="passed",
    )
    output = tmp_path / "summary.json"

    module.write_summary_json(output, [page], app_count=1, target_seconds=10.0)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["success"] is True
    assert payload["pages"][0]["status"] == "passed"


def test_page_watchdog_helper_raises_when_deadline_expired() -> None:
    module = _load_module()

    module._enforce_page_deadline(None, "disabled")
    try:
        module._enforce_page_deadline(0.0, "expired")
    except module.PageWatchdogTimeout as exc:
        assert "expired" in str(exc)
    else:
        raise AssertionError("expected PageWatchdogTimeout")


def test_static_widget_combination_controls_cover_binary_and_radio_groups() -> None:
    module = _load_module()
    widgets = [
        {
            "id": "show-advanced",
            "kind": "checkbox",
            "label": "Show advanced",
            "checked": False,
            "testid": "stCheckbox",
            "path": "input:nth-of-type(1)",
            "scope": "main",
        },
        {
            "id": "cluster",
            "kind": "toggle",
            "label": "Cluster mode",
            "checked": True,
            "testid": "stToggle",
            "path": "input:nth-of-type(2)",
            "scope": "sidebar",
        },
        {
            "id": "disabled",
            "kind": "checkbox",
            "label": "Disabled",
            "checked": False,
            "disabled": True,
            "scope": "main",
        },
        {
            "id": "local-radio",
            "kind": "radio",
            "label": "Execution backend",
            "name": "backend",
            "value": "local",
            "checked": True,
            "testid": "stRadio",
            "path": "input:nth-of-type(3)",
            "scope": "main",
        },
        {
            "id": "cluster-radio",
            "kind": "radio",
            "label": "Execution backend",
            "name": "backend",
            "value": "cluster",
            "checked": False,
            "testid": "stRadio",
            "path": "input:nth-of-type(4)",
            "scope": "main",
        },
    ]

    controls = module.collect_static_widget_combination_controls(widgets)

    assert [control.kind for control in controls] == ["checkbox", "toggle", "radio"]
    assert [choice.checked for choice in controls[0].choices] == [False, True]
    assert [choice.default for choice in controls[1].choices] == [False, True]
    assert [choice.value for choice in controls[2].choices] == ["local", "cluster"]
    assert [choice.default for choice in controls[2].choices] == [True, False]


def test_widget_choice_labels_descriptions_and_static_control_edges() -> None:
    module = _load_module()

    assert module._choice_label({"label": "Mode", "value": "Fast"}, 0) == "Mode: Fast"
    assert module._choice_label({"label": "Mode", "value": "Mode"}, 0) == "Mode"
    assert module._choice_label({"value": "Fast"}, 0) == "Fast"
    assert module._choice_label({}, 2) == "option 3"
    assert module._choice_description(
        module.WidgetChoice("flag", "checkbox", "Use cache", "on", {}, checked=True)
    ) == "Use cache=on"
    assert module._choice_description(
        module.WidgetChoice("mode", "selectbox", "Mode", "fast", {}, checked=True)
    ) == "Mode=fast"
    assert module._choice_description(
        module.WidgetChoice("action", "radio", "Backend", "", {}, checked=True)
    ) == "Backend=radio"
    assert module._combination_description(
        [module.WidgetChoice("flag", "checkbox", "Use cache", "off", {}, checked=False)]
    ) == "Use cache=off"
    assert module._binary_widget_control({"kind": "button", "label": "Run"}) is None
    assert module._binary_widget_control({"kind": "toggle", "label": "Disabled", "disabled": True}) is None
    assert module._radio_group_key({"kind": "radio", "label": "Backend", "scope": "sidebar"}) == (
        "sidebar",
        "label",
        "backend",
    )
    controls = module.collect_static_widget_combination_controls(
        [
            {"kind": "radio", "label": "Solo", "value": "only"},
            {"kind": "radio", "label": "Group", "value": "a"},
            {"kind": "radio", "label": "Group", "value": "b"},
        ]
    )
    assert len(controls) == 1
    assert [choice.default for choice in controls[0].choices] == [True, False]


def test_project_switching_selectbox_is_excluded_from_combination_controls() -> None:
    module = _load_module()

    class _Page:
        url = "http://demo"

    widgets = [
        {
            "id": "project",
            "kind": "selectbox",
            "label": "Project flight_telemetry_project",
            "scope": "sidebar",
            "disabled": False,
        },
        {
            "id": "cluster",
            "kind": "checkbox",
            "label": "Enable cluster",
            "scope": "main",
            "checked": False,
            "disabled": False,
        },
    ]

    controls, probes = module.collect_widget_combination_controls(
        _Page(),
        widgets,
        app_name="flight_telemetry_project",
        page_name="ORCHESTRATE",
        timeout_ms=1000,
        max_options_per_widget=8,
    )

    assert [control.label for control in controls] == ["Enable cluster"]
    assert probes == []
    assert module.is_project_switching_widget(widgets[0]) is True


def test_dynamic_selectboxes_are_excluded_from_exhaustive_combinations() -> None:
    module = _load_module()

    class _Page:
        url = "http://demo"

        def locator(self, *_args: object, **_kwargs: object) -> object:
            raise AssertionError("selectbox options must not be queried for combination setup")

    widgets = [
        {
            "id": "workflow-view",
            "kind": "selectbox",
            "label": "Workflow view",
            "scope": "main",
            "disabled": False,
        },
        {
            "id": "cluster",
            "kind": "toggle",
            "label": "Enable cluster",
            "scope": "main",
            "checked": False,
            "disabled": False,
        },
    ]

    controls, probes = module.collect_widget_combination_controls(
        _Page(),
        widgets,
        app_name="flight_telemetry_project",
        page_name="WORKFLOW",
        timeout_ms=1000,
        max_options_per_widget=8,
    )

    assert [control.kind for control in controls] == ["toggle"]
    assert [control.label for control in controls] == ["Enable cluster"]
    assert probes == []


def test_build_widget_combination_plan_is_exhaustive_and_reports_truncation() -> None:
    module = _load_module()
    checkbox = module.WidgetControl(
        "advanced",
        "checkbox",
        "Show advanced",
        (
            module.WidgetChoice("advanced", "checkbox", "Show advanced", "off", {}, checked=False),
            module.WidgetChoice("advanced", "checkbox", "Show advanced", "on", {}, checked=True),
        ),
    )
    backend = module.WidgetControl(
        "backend",
        "radio",
        "Backend",
        (
            module.WidgetChoice("backend", "radio", "Backend", "local", {}, checked=True),
            module.WidgetChoice("backend", "radio", "Backend", "cluster", {}, checked=True),
            module.WidgetChoice("backend", "radio", "Backend", "remote", {}, checked=True),
        ),
    )

    plan = module.build_widget_combination_plan((checkbox, backend), max_combinations=10)
    truncated = module.build_widget_combination_plan((checkbox, backend), max_combinations=4)

    assert plan.total_count == 6
    assert len(plan.combinations) == 6
    assert plan.truncated is False
    assert [choice.value for choice in plan.combinations[0]] == ["off", "local"]
    assert truncated.total_count == 6
    assert len(truncated.combinations) == 4
    assert truncated.truncated is True

    try:
        module.build_widget_combination_plan((), max_combinations=0)
    except ValueError as exc:
        assert "max_combinations" in str(exc)
    else:
        raise AssertionError("max_combinations=0 should fail")
    assert module.build_widget_combination_plan((), max_combinations=1).total_count == 0


def test_widget_robot_parser_enables_exhaustive_combinations_by_default() -> None:
    module = _load_module()

    args = module.build_parser().parse_args([])

    assert args.combination_mode == "exhaustive"
    assert args.action_button_policy == "safe-click"
    assert args.max_combinations > 0
    assert args.max_options_per_widget > 0
    assert args.discovery_passes == 2
    assert args.max_action_clicks_per_page > 0


def test_action_click_budget_helper_handles_none_empty_and_decrement() -> None:
    module = _load_module()

    budget = [1]
    assert module._consume_action_click_budget(None) is True
    assert module._consume_action_click_budget([]) is False
    assert module._consume_action_click_budget([0]) is False
    assert module._consume_action_click_budget(budget) is True
    assert budget == [0]


def test_widget_scope_distinguishes_sidebar_from_main_widgets() -> None:
    module = _load_module()
    main_widget = {
        "id": "main",
        "kind": "button",
        "label": "Run",
        "testid": "stButton",
        "path": "button:nth-of-type(1)",
        "scope": "main",
    }
    sidebar_widget = {**main_widget, "id": "sidebar", "scope": "sidebar"}

    assert module.widget_scope(main_widget) == "main"
    assert module.widget_scope(sidebar_widget) == "sidebar"
    assert module._widget_fingerprint(main_widget) != module._widget_fingerprint(sidebar_widget)
    assert module._same_widget(main_widget, sidebar_widget) is False
    assert module._same_widget(main_widget, {**main_widget, "label": "Run now"}) is True
    assert module._same_widget({**main_widget, "label": ""}, {**main_widget, "label": ""}) is True
    assert "[data-testid='stSidebar']" in module.WIDGET_COLLECTOR_JS
    assert "scope: scopeFor(el)" in module.WIDGET_COLLECTOR_JS
    assert 'removeAttribute("data-agilab-widget-id")' in module.WIDGET_COLLECTOR_JS
    assert "window.__agilabWidgetRobotRunId" in module.WIDGET_COLLECTOR_JS
    assert 'details:not([open])' in module.WIDGET_COLLECTOR_JS
    assert "details.contains(target)" in module.CLOSE_EXPANDERS_EXCEPT_WIDGET_JS
    assert "details.open = true" in module.CLOSE_EXPANDERS_EXCEPT_WIDGET_JS
    assert "orchestration log" in module.ACTION_LOG_FEEDBACK_COLLECTOR_JS.lower()
    assert "stCodeBlock" in module.ACTION_LOG_FEEDBACK_COLLECTOR_JS
    assert "stStatus" in module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS
    assert "stToast" in module.VISIBLE_STREAMLIT_FEEDBACK_COLLECTOR_JS
    assert "fatalTextNeedles" in module.VISIBLE_STREAMLIT_FEEDBACK_COLLECTOR_JS
    assert "diagnostic" in module.ACTION_LOG_FEEDBACK_COLLECTOR_JS.lower()
    assert "install finished with errors" in module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS
    assert "install finished with errors" in module.VISIBLE_STREAMLIT_FEEDBACK_COLLECTOR_JS
    assert "install finished with errors" in module.ACTION_LOG_FEEDBACK_COLLECTOR_JS


def test_action_log_error_collectors_ignore_generic_failure_words() -> None:
    module = _load_module()
    broad_needles = {"error", "exception", "failed", "failure", "worker failed"}
    scripts = [
        module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS,
        module.VISIBLE_STREAMLIT_FEEDBACK_COLLECTOR_JS,
        module.ACTION_LOG_FEEDBACK_COLLECTOR_JS,
    ]

    for script in scripts:
        arrays = re.findall(r"const\s+(?:errorNeedles|fatalTextNeedles)\s*=\s*\[(.*?)\];", script, re.DOTALL)
        assert arrays
        for array_body in arrays:
            values = set(re.findall(r'"([^"]+)"', array_body))
            assert broad_needles.isdisjoint(values)
            assert "distribution build failed" in values
            assert "install finished with errors" in values


def test_action_log_feedback_collector_catches_install_finished_with_errors() -> None:
    module = _load_module()

    assert '"install finished with errors"' in module.ACTION_LOG_FEEDBACK_COLLECTOR_JS
    assert '"finished with errors"' in module.VISIBLE_STREAMLIT_FEEDBACK_COLLECTOR_JS
    assert '"installation failed"' in module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS


def test_visible_streamlit_issue_detail_detects_error_alert_payload() -> None:
    module = _load_module()

    class _Page:
        def evaluate(self, script):
            assert script == module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS
            return [{"kind": "error", "detail": "AGI execution failed."}]

    assert module._visible_streamlit_issue_detail(_Page()) == "error: AGI execution failed."


def test_selected_action_matching_can_require_enabled_button() -> None:
    module = _load_module()
    widgets = [
        {"kind": "button", "label": "EXPORT dataframe", "disabled": True},
        {"kind": "button", "label": "Load output", "disabled": False},
    ]

    assert module._selected_action_matches(widgets, "") == []
    assert len(module._selected_action_matches(widgets, "EXPORT dataframe")) == 1
    assert module._selected_action_matches(widgets, "EXPORT dataframe", require_enabled=True) == []


def test_callable_or_value_handles_success_and_exceptions() -> None:
    module = _load_module()

    class _Value:
        @staticmethod
        def ok():
            return "ready"

        @staticmethod
        def bad():
            raise RuntimeError("boom")

    assert module._callable_or_value(_Value(), "ok", "fallback") == "ready"
    assert module._callable_or_value(_Value(), "bad", "fallback") == "fallback"
    assert module._callable_or_value(_Value(), "missing", "fallback") == "fallback"


def test_browser_issue_capture_filters_noise_and_records_fatal_console() -> None:
    module = _load_module()
    issues: list[dict[str, str]] = []

    module._record_browser_issue(
        issues,
        kind="console.error",
        detail="Failed to load resource: the server responded with a status of 404 (favicon.ico)",
    )
    module._record_browser_issue(
        issues,
        kind="console.error",
        detail="Uncaught RuntimeError: AGI execution failed.",
    )
    module._record_browser_issue(
        issues,
        kind="console.error",
        detail="Uncaught RuntimeError: AGI execution failed.",
    )
    module._record_browser_issue(
        issues,
        kind="pageerror",
        detail="TypeError: broken widget callback",
    )
    module._record_browser_issue(
        issues,
        kind="requestfailed",
        detail="https://demo/agilab.js net::ERR_FAILED",
    )
    module._record_browser_issue(
        issues,
        kind="http.500",
        detail="HTTP 500 https://demo/api/run",
    )
    module._record_browser_issue(
        issues,
        kind="http.404",
        detail="HTTP 404 http://demo/ORCHESTRATE/_stcore/health",
    )
    module._record_browser_issue(
        issues,
        kind="http.404",
        detail="HTTP 404 http://demo/ORCHESTRATE/_stcore/host-config",
    )

    assert issues == [
        {"kind": "console.error", "detail": "Uncaught RuntimeError: AGI execution failed."},
        {"kind": "pageerror", "detail": "TypeError: broken widget callback"},
        {"kind": "requestfailed", "detail": "https://demo/agilab.js net::ERR_FAILED"},
        {"kind": "http.500", "detail": "HTTP 500 https://demo/api/run"},
    ]


def test_browser_issue_capture_hooks_network_events() -> None:
    module = _load_module()
    callbacks = {}

    class _Page:
        def on(self, event, callback):
            callbacks[event] = callback

    class _Request:
        url = "https://demo/api/data"

        def failure(self):
            return {"errorText": "net::ERR_FAILED"}

    class _Response:
        status = 503
        url = "https://demo/api/run"

    issues = module._attach_browser_issue_capture(_Page())
    callbacks["requestfailed"](_Request())
    callbacks["response"](_Response())

    assert {"kind": "requestfailed", "detail": "https://demo/api/data net::ERR_FAILED"} in issues
    assert {"kind": "http.503", "detail": "HTTP 503 https://demo/api/run"} in issues


def test_append_browser_issue_probes_uses_new_issue_checkpoint() -> None:
    module = _load_module()
    probes: list[module.WidgetProbe] = []
    issues = [
        {"kind": "pageerror", "detail": "TypeError: old page failure"},
        {"kind": "console.error", "detail": "Uncaught RuntimeError: AGI execution failed."},
    ]

    appended = module._append_browser_issue_probes(
        probes,
        app_name="flight_telemetry_project",
        display="ORCHESTRATE",
        url="http://demo",
        browser_issues=issues,
        start_index=1,
    )

    assert appended is True
    assert len(probes) == 1
    assert probes[0].kind == "browser_error"
    assert probes[0].label == "console.error"
    assert "AGI execution failed" in probes[0].detail

    ignored_only: list[module.WidgetProbe] = []
    assert module._append_browser_issue_probes(
        ignored_only,
        app_name="flight_telemetry_project",
        display="ORCHESTRATE",
        url="http://demo",
        browser_issues=[{"kind": "console.warning", "detail": "Just a UI note"}],
        start_index=0,
    ) is False
    assert ignored_only == []


def test_missing_selected_action_probe_fails_when_label_was_not_fired() -> None:
    module = _load_module()
    probes = [
        module.WidgetProbe(
            "flight_telemetry_project",
            "ORCHESTRATE",
            "button",
            "Run -> Load -> Export",
            "probed",
            "action button browser-clickable; callback not selected for firing",
            "http://demo",
        )
    ]

    module._append_missing_selected_action_probes(
        probes,
        app_name="flight_telemetry_project",
        display="ORCHESTRATE",
        url="http://demo",
        click_action_labels=["Run -> Load -> Export"],
    )

    assert probes[-1].kind == "selected_action"
    assert probes[-1].status == "failed"
    assert "not fired" in probes[-1].detail


def test_missing_selected_action_probe_can_ignore_absent_label() -> None:
    module = _load_module()
    probes: list[module.WidgetProbe] = []

    module._append_missing_selected_action_probes(
        probes,
        app_name="execution_pandas_project",
        display="ORCHESTRATE",
        url="http://demo",
        click_action_labels=["Run -> Load -> Export"],
        missing_selected_action_policy="ignore-absent",
    )

    assert probes == []


def test_missing_selected_action_probe_still_fails_found_unfired_label_when_absent_is_ignored() -> None:
    module = _load_module()
    probes = [
        module.WidgetProbe(
            "flight_telemetry_project",
            "ORCHESTRATE",
            "button",
            "Run -> Load -> Export",
            "skipped",
            "clicked action button but UI did not settle within 180.0s",
            "http://demo",
        )
    ]

    module._append_missing_selected_action_probes(
        probes,
        app_name="flight_telemetry_project",
        display="ORCHESTRATE",
        url="http://demo",
        click_action_labels=["Run -> Load -> Export"],
        missing_selected_action_policy="ignore-absent",
    )

    assert probes[-1].kind == "selected_action"
    assert probes[-1].status == "failed"
    assert "not fired" in probes[-1].detail


def test_probe_selected_actions_first_preselects_before_run_action(tmp_path) -> None:
    module = _load_module()
    events: list[str] = []
    evaluate_events: list[str] = []
    current_widgets = [
        {"id": "run-now", "kind": "segmented_control", "label": "Run now", "scope": "main"},
        {"id": "cluster", "kind": "checkbox", "label": "Cluster", "scope": "main"},
        {"id": "combo", "kind": "button", "label": "Run \u2192 Load \u2192 Export", "scope": "main"},
    ]

    class _Locator:
        def __init__(self, widget_id: str, count: int = 1):
            self.widget_id = widget_id
            self._count = count

        @property
        def first(self):
            return self

        def count(self):
            return self._count

        def scroll_into_view_if_needed(self, timeout):
            return None

        def is_visible(self, timeout):
            return True

        def is_enabled(self, timeout):
            return True

        def bounding_box(self, timeout):
            return {"width": 10, "height": 10}

        def click(self, **kwargs):
            events.append(self.widget_id)

    class _Page:
        url = "http://demo"

        def evaluate(self, script):
            if script == module.CLOSE_EXPANDERS_JS:
                evaluate_events.append("close")
                return 0
            if script == module.OPEN_EXPANDERS_JS:
                evaluate_events.append("open")
                return 0
            if script == module.WIDGET_COLLECTOR_JS:
                evaluate_events.append("collect")
                return [dict(widget) for widget in current_widgets]
            if script == module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS:
                return []
            raise AssertionError(script)

        def locator(self, selector):
            if selector == "[data-testid='stSpinner']":
                return _Locator("spinner", count=0)
            widget_id = selector.split("'")[1]
            return _Locator(widget_id)

        def wait_for_timeout(self, ms):
            return None

    original_wait_for_action_outcome = module._wait_for_action_outcome
    module._wait_for_action_outcome = lambda page, **_kwargs: (None, True)
    try:
        probes = module._probe_selected_actions_first(
            _Page(),
            app_name="flight_telemetry_project",
            display="ORCHESTRATE",
            widget_timeout_ms=100,
            click_action_labels=["Run -> Load -> Export"],
            preselect_labels=["Run now"],
            missing_selected_action_policy="fail",
            action_timeout_ms=100,
            upload_file=tmp_path / "fixture.txt",
        )
    finally:
        module._wait_for_action_outcome = original_wait_for_action_outcome

    assert events == ["run-now", "combo"]
    assert evaluate_events[:2] == ["close", "collect"]
    assert evaluate_events.count("close") >= 2
    assert [(probe.kind, probe.status) for probe in probes] == [
        ("segmented_control", "interacted"),
        ("button", "interacted"),
    ]


def test_probe_selected_actions_first_recollects_between_stateful_actions(tmp_path) -> None:
    module = _load_module()
    events: list[str] = []
    current_widgets = [
        {"id": "combo", "kind": "button", "label": "Run \u2192 Load \u2192 Export", "scope": "main"},
    ]

    class _Locator:
        def __init__(self, widget_id: str, count: int = 1):
            self.widget_id = widget_id
            self._count = count

        @property
        def first(self):
            return self

        def count(self):
            return self._count

        def inner_text(self, timeout):
            return ""

        def scroll_into_view_if_needed(self, timeout):
            return None

        def is_visible(self, timeout):
            return True

        def is_enabled(self, timeout):
            return True

        def bounding_box(self, timeout):
            return {"width": 10, "height": 10}

        def click(self, **_kwargs):
            events.append(self.widget_id)
            if self.widget_id == "combo":
                current_widgets[:] = [
                    {"id": "export", "kind": "button", "label": "EXPORT dataframe", "scope": "main"},
                ]

    class _Page:
        url = "http://demo"

        def evaluate(self, script):
            if script in {
                module.CLOSE_EXPANDERS_JS,
                module.OPEN_EXPANDERS_JS,
                module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS,
                module.VISIBLE_STREAMLIT_FEEDBACK_COLLECTOR_JS,
                module.ACTION_LOG_FEEDBACK_COLLECTOR_JS,
            }:
                return []
            if script == module.WIDGET_COLLECTOR_JS:
                return [dict(widget) for widget in current_widgets]
            raise AssertionError(script)

        def locator(self, selector):
            if selector in {"body", "[data-testid='stSpinner']"}:
                return _Locator(selector, count=0 if selector != "body" else 1)
            widget_id = selector.split("'")[1]
            return _Locator(widget_id)

        def wait_for_timeout(self, _ms):
            return None

    original_wait_for_action_outcome = module._wait_for_action_outcome
    module._wait_for_action_outcome = lambda page, **_kwargs: (None, True)
    try:
        probes = module._probe_selected_actions_first(
            _Page(),
            app_name="flight_telemetry_project",
            display="ORCHESTRATE",
            widget_timeout_ms=100,
            click_action_labels=["Run -> Load -> Export", "EXPORT dataframe"],
            preselect_labels=[],
            missing_selected_action_policy="fail",
            action_timeout_ms=100,
            upload_file=tmp_path / "fixture.txt",
        )
    finally:
        module._wait_for_action_outcome = original_wait_for_action_outcome

    assert events == ["combo", "export"]
    assert [(probe.label, probe.status) for probe in probes] == [
        ("Run \u2192 Load \u2192 Export", "interacted"),
        ("EXPORT dataframe", "interacted"),
    ]


def test_probe_selected_actions_first_allows_idle_settle_for_already_ready_load(tmp_path) -> None:
    module = _load_module()
    probe_kwargs: list[dict] = []
    current_widgets = [
        {"id": "load", "kind": "button", "label": "Load output", "scope": "main"},
        {"id": "export", "kind": "button", "label": "EXPORT dataframe", "scope": "main"},
    ]

    class _Page:
        url = "http://demo"

        def evaluate(self, script):
            if script in {module.CLOSE_EXPANDERS_JS, module.OPEN_EXPANDERS_JS}:
                return 0
            if script == module.WIDGET_COLLECTOR_JS:
                return [dict(widget) for widget in current_widgets]
            return []

        def wait_for_timeout(self, _ms):
            return None

    original_probe_widget = module._probe_widget
    original_wait_for_page_ready = module.wait_for_page_ready
    original_wait_for_widgets_ready = module.wait_for_widgets_ready

    def fake_probe_widget(page, widget, **kwargs):
        probe_kwargs.append({"label": widget["label"], **kwargs})
        return "interacted", "clicked action button"

    try:
        module._probe_widget = fake_probe_widget
        module.wait_for_page_ready = lambda page, timeout_ms: None
        module.wait_for_widgets_ready = lambda page, page_name, timeout_ms: len(current_widgets)
        probes = module._probe_selected_actions_first(
            _Page(),
            app_name="mission_decision_project",
            display="ORCHESTRATE",
            widget_timeout_ms=100,
            click_action_labels=["Load output", "EXPORT dataframe"],
            preselect_labels=[],
            missing_selected_action_policy="fail",
            action_timeout_ms=100,
            upload_file=tmp_path / "fixture.txt",
        )
    finally:
        module._probe_widget = original_probe_widget
        module.wait_for_page_ready = original_wait_for_page_ready
        module.wait_for_widgets_ready = original_wait_for_widgets_ready

    assert [probe.label for probe in probes] == ["Load output", "EXPORT dataframe"]
    assert probe_kwargs[0]["allow_idle_settle"] is True
    assert probe_kwargs[1]["allow_idle_settle"] is False


def test_probe_selected_actions_first_stops_after_selected_action_failure(tmp_path) -> None:
    module = _load_module()
    called: list[str] = []
    current_widgets = [
        {"id": "run", "kind": "button", "label": "Run \u2192 Load \u2192 Export", "scope": "main"},
        {"id": "load", "kind": "button", "label": "Load output", "scope": "main"},
    ]

    class _Page:
        url = "http://demo"

        def evaluate(self, script):
            if script in {module.CLOSE_EXPANDERS_JS, module.OPEN_EXPANDERS_JS}:
                return 0
            if script == module.WIDGET_COLLECTOR_JS:
                return [dict(widget) for widget in current_widgets]
            return []

        def wait_for_timeout(self, _ms):
            return None

    original_probe_widget = module._probe_widget
    original_wait_for_page_ready = module.wait_for_page_ready
    original_wait_for_widgets_ready = module.wait_for_widgets_ready

    def fake_probe_widget(page, widget, **_kwargs):
        called.append(widget["label"])
        return "failed", "button click rendered Streamlit error: error: AGI execution failed."

    try:
        module._probe_widget = fake_probe_widget
        module.wait_for_page_ready = lambda page, timeout_ms: None
        module.wait_for_widgets_ready = lambda page, page_name, timeout_ms: len(current_widgets)
        probes = module._probe_selected_actions_first(
            _Page(),
            app_name="flight_telemetry_project",
            display="ORCHESTRATE",
            widget_timeout_ms=100,
            click_action_labels=["Run -> Load -> Export", "Load output"],
            preselect_labels=[],
            missing_selected_action_policy="fail",
            action_timeout_ms=100,
            upload_file=tmp_path / "fixture.txt",
        )
    finally:
        module._probe_widget = original_probe_widget
        module.wait_for_page_ready = original_wait_for_page_ready
        module.wait_for_widgets_ready = original_wait_for_widgets_ready

    assert called == ["Run \u2192 Load \u2192 Export"]
    assert [probe.label for probe in probes] == ["Run \u2192 Load \u2192 Export"]
    assert probes[0].status == "failed"


def test_probe_selected_actions_first_allows_known_no_output_placeholder_app(tmp_path) -> None:
    module = _load_module()
    called: list[str] = []
    current_widgets = [
        {"id": "combo", "kind": "button", "label": "Run \u2192 Load \u2192 Export", "scope": "main"},
        {"id": "load", "kind": "button", "label": "Load output", "scope": "main"},
        {"id": "delete", "kind": "button", "label": "Delete output", "scope": "main"},
    ]

    class _Page:
        url = "http://demo"

        def evaluate(self, script):
            if script in {module.CLOSE_EXPANDERS_JS, module.OPEN_EXPANDERS_JS}:
                return 0
            if script == module.WIDGET_COLLECTOR_JS:
                return [dict(widget) for widget in current_widgets]
            return []

        def wait_for_timeout(self, _ms):
            return None

    original_probe_widget = module._probe_widget
    original_wait_for_page_ready = module.wait_for_page_ready
    original_wait_for_widgets_ready = module.wait_for_widgets_ready

    def fake_probe_widget(page, widget, **_kwargs):
        called.append(widget["label"])
        return "skipped", "clicked action button but UI did not settle within 60.0s"

    try:
        module._probe_widget = fake_probe_widget
        module.wait_for_page_ready = lambda page, timeout_ms: None
        module.wait_for_widgets_ready = lambda page, page_name, timeout_ms: len(current_widgets)
        probes = module._probe_selected_actions_first(
            _Page(),
            app_name="minimal_app_project",
            display="ORCHESTRATE",
            widget_timeout_ms=100,
            click_action_labels=["Run -> Load -> Export", "Load output", "Delete output"],
            preselect_labels=[],
            missing_selected_action_policy="fail",
            action_timeout_ms=100,
            upload_file=tmp_path / "fixture.txt",
        )
    finally:
        module._probe_widget = original_probe_widget
        module.wait_for_page_ready = original_wait_for_page_ready
        module.wait_for_widgets_ready = original_wait_for_widgets_ready

    assert called == ["Run \u2192 Load \u2192 Export"]
    assert len(probes) == 1
    assert probes[0].status == "probed"
    assert "no concrete output is expected" in probes[0].detail


def test_probe_selected_actions_first_allows_idle_settle_for_confirm_delete(tmp_path) -> None:
    module = _load_module()
    allow_idle_values: list[bool] = []
    current_widgets = [{"id": "confirm", "kind": "button", "label": "Confirm delete", "scope": "main"}]

    class _Page:
        url = "http://demo"

        def evaluate(self, script):
            if script in {module.CLOSE_EXPANDERS_JS, module.OPEN_EXPANDERS_JS}:
                return 0
            if script == module.WIDGET_COLLECTOR_JS:
                return [dict(widget) for widget in current_widgets]
            return []

        def wait_for_timeout(self, _ms):
            return None

    original_probe_widget = module._probe_widget
    original_wait_for_page_ready = module.wait_for_page_ready
    original_wait_for_widgets_ready = module.wait_for_widgets_ready

    def fake_probe_widget(page, widget, **kwargs):
        allow_idle_values.append(kwargs["allow_idle_settle"])
        return "interacted", "clicked action button"

    try:
        module._probe_widget = fake_probe_widget
        module.wait_for_page_ready = lambda page, timeout_ms: None
        module.wait_for_widgets_ready = lambda page, page_name, timeout_ms: len(current_widgets)
        probes = module._probe_selected_actions_first(
            _Page(),
            app_name="flight_telemetry_project",
            display="ORCHESTRATE",
            widget_timeout_ms=100,
            click_action_labels=["Confirm delete"],
            preselect_labels=[],
            missing_selected_action_policy="fail",
            action_timeout_ms=100,
            upload_file=tmp_path / "fixture.txt",
        )
    finally:
        module._probe_widget = original_probe_widget
        module.wait_for_page_ready = original_wait_for_page_ready
        module.wait_for_widgets_ready = original_wait_for_widgets_ready

    assert allow_idle_values == [True]
    assert len(probes) == 1
    assert probes[0].status == "interacted"


def test_probe_selected_actions_first_fails_disabled_selected_action(tmp_path) -> None:
    module = _load_module()

    class _Locator:
        def __init__(self, count_value: int = 1):
            self.count_value = count_value

        @property
        def first(self):
            return self

        def count(self):
            return self.count_value

        def inner_text(self, timeout):
            return ""

        def scroll_into_view_if_needed(self, timeout):
            return None

        def is_visible(self, timeout):
            return True

        def is_enabled(self, timeout):
            return False

    class _Page:
        url = "http://demo"

        def evaluate(self, script):
            if script in {module.CLOSE_EXPANDERS_JS, module.OPEN_EXPANDERS_JS}:
                return 0
            if script == module.WIDGET_COLLECTOR_JS:
                return [{"id": "delete", "kind": "button", "label": "Delete output", "scope": "main"}]
            if script == module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS:
                return []
            return []

        def locator(self, selector):
            if selector == "[data-testid='stSpinner']":
                return _Locator()
            return _Locator()

        def wait_for_timeout(self, _ms):
            return None

    probes = module._probe_selected_actions_first(
        _Page(),
        app_name="flight_telemetry_project",
        display="ORCHESTRATE",
        widget_timeout_ms=100,
        click_action_labels=["Delete output"],
        preselect_labels=[],
        missing_selected_action_policy="fail",
        action_timeout_ms=100,
        upload_file=tmp_path / "fixture.txt",
    )

    assert len(probes) == 1
    assert probes[0].status == "failed"
    assert "not fired" in probes[0].detail


def test_collect_and_probe_current_view_fails_on_visible_error_after_interaction(tmp_path) -> None:
    module = _load_module()

    class _Locator:
        @property
        def first(self):
            return self

        def count(self):
            return 1

        def scroll_into_view_if_needed(self, timeout):
            return None

        def is_visible(self, timeout):
            return True

        def is_enabled(self, timeout):
            return True

        def bounding_box(self, timeout):
            return {"width": 10, "height": 10}

        def is_checked(self, timeout):
            return False

        def click(self, **_kwargs):
            return None

    class _Page:
        url = "http://127.0.0.1:8501/ORCHESTRATE?active_app=flight_telemetry_project"

        def evaluate(self, script):
            if script == module.OPEN_EXPANDERS_JS:
                return 0
            if script == module.WIDGET_COLLECTOR_JS:
                return [
                    {
                        "id": "w1",
                        "kind": "checkbox",
                        "label": "Cluster",
                        "testid": "stCheckbox",
                        "path": "input:nth-of-type(1)",
                        "scope": "main",
                    }
                ]
            if script == module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS:
                return [{"kind": "error", "detail": "AGI execution failed."}]
            return []

        def locator(self, _selector):
            return _Locator()

        def wait_for_timeout(self, _ms):
            return None

    probes = module._collect_and_probe_current_view(
        _Page(),
        app_name="flight_telemetry_project",
        page_name="ORCHESTRATE",
        widget_timeout_ms=100,
        interaction_mode="full",
        action_button_policy="trial",
        upload_file=tmp_path / "upload.txt",
        restore_view=None,
        known=set(),
    )

    assert len(probes) == 1
    assert probes[0].status == "failed"
    assert probes[0].kind == "checkbox"
    assert "AGI execution failed" in probes[0].detail


def test_sweep_page_marks_active_app_mismatch_as_failed() -> None:
    module = _load_module()

    class _Locator:
        def __init__(self, count_value: int = 0):
            self._count_value = count_value

        def nth(self, _index):
            return self

        @property
        def first(self):
            return self

        def count(self) -> int:
            return self._count_value

    class _Page:
        def __init__(self) -> None:
            self.url = "http://127.0.0.1:8501/PROJECT?active_app=other_project"

        def goto(self, *_args, **_kwargs):
            return None

        def wait_for_timeout(self, _ms) -> None:
            return None

        def locator(self, selector):
            if selector == "[role='tab']":
                return _Locator(0)
            return _Locator(0)

        def evaluate(self, _script):
            return []

    web_robot = module._load_web_robot()
    original_web_robot_assert = web_robot.assert_page_healthy
    original_wait_for_page_ready = module.wait_for_page_ready
    original_wait_for_widgets_ready = module.wait_for_widgets_ready
    web_robot.assert_page_healthy = lambda *args, **_kwargs: web_robot.RobotStep(
        "health",
        True,
        0.0,
        "ok",
        "http://127.0.0.1:8501",
    )

    def fake_wait_for_page_ready(page, timeout_ms: float) -> None:
        return None

    def fake_wait_for_widgets_ready(page: object, page_name: str, timeout_ms: float) -> int:
        return 1

    try:
        module.wait_for_page_ready = fake_wait_for_page_ready
        module.wait_for_widgets_ready = fake_wait_for_widgets_ready
        result = module.sweep_page(
            _Page(),
            web_robot=web_robot,
            base_url="http://127.0.0.1:8501",
            active_app_query="flight_telemetry_project",
            app_name="flight_telemetry_project",
            page_name="PROJECT",
            timeout=module.DEFAULT_TIMEOUT_SECONDS,
            widget_timeout=module.DEFAULT_WIDGET_TIMEOUT_SECONDS,
            interaction_mode="full",
            action_button_policy="trial",
            upload_file=Path("does-not-exist.txt"),
            screenshot_dir=None,
            page_timeout=module.DEFAULT_PAGE_TIMEOUT_SECONDS,
        )
    finally:
        web_robot.assert_page_healthy = original_web_robot_assert
        module.wait_for_page_ready = original_wait_for_page_ready
        module.wait_for_widgets_ready = original_wait_for_widgets_ready

    assert result.success is False
    assert result.status == "failed"
    assert result.failed_count == 1
    assert any(probe.kind == "active_app" for probe in result.failures)


def test_sweep_page_blocks_current_home_selected_actions_before_clicking(tmp_path) -> None:
    module = _load_module()
    fake_home = tmp_path / "home"
    app_settings = fake_home / ".agilab" / "apps" / "flight_telemetry_project" / "app_settings.toml"
    app_settings.parent.mkdir(parents=True)
    app_settings.write_text("[cluster]\ncluster_enabled = true\n", encoding="utf-8")
    env_file = fake_home / ".agilab" / ".env"
    env_file.write_text("AGI_CLUSTER_SHARE=missing-clustershare\n", encoding="utf-8")

    class _Locator:
        def __init__(self, count_value: int = 0):
            self._count_value = count_value

        def nth(self, _index):
            return self

        @property
        def first(self):
            return self

        def count(self) -> int:
            return self._count_value

    class _Page:
        def __init__(self) -> None:
            self.url = "http://127.0.0.1:8501/ORCHESTRATE?active_app=flight_telemetry_project"

        def goto(self, *_args, **_kwargs):
            return None

        def wait_for_timeout(self, _ms) -> None:
            return None

        def locator(self, selector):
            if selector == "[role='tab']":
                return _Locator(0)
            return _Locator(0)

        def evaluate(self, script):
            if script in {module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS, module.WIDGET_COLLECTOR_JS}:
                return []
            if script == module.OPEN_EXPANDERS_JS:
                return 0
            return []

    web_robot = module._load_web_robot()
    original_web_robot_assert = web_robot.assert_page_healthy
    original_wait_for_page_ready = module.wait_for_page_ready
    original_wait_for_widgets_ready = module.wait_for_widgets_ready
    original_probe_selected_actions_first = module._probe_selected_actions_first
    web_robot.assert_page_healthy = lambda *args, **_kwargs: web_robot.RobotStep(
        "health",
        True,
        0.0,
        "ok",
        "http://127.0.0.1:8501",
    )

    def fail_if_clicked(*_args, **_kwargs):
        raise AssertionError("selected actions should be blocked before click")

    try:
        module.wait_for_page_ready = lambda page, timeout_ms: None
        module.wait_for_widgets_ready = lambda page, page_name, timeout_ms: 0
        module._probe_selected_actions_first = fail_if_clicked
        result = module.sweep_page(
            _Page(),
            web_robot=web_robot,
            base_url="http://127.0.0.1:8501",
            active_app_query="flight_telemetry_project",
            app_name="flight_telemetry_project",
            page_name="ORCHESTRATE",
            timeout=module.DEFAULT_TIMEOUT_SECONDS,
            widget_timeout=module.DEFAULT_WIDGET_TIMEOUT_SECONDS,
            interaction_mode="full",
            action_button_policy="click-selected",
            click_action_labels=["Run -> Load -> Export"],
            upload_file=Path("does-not-exist.txt"),
            screenshot_dir=None,
            page_timeout=module.DEFAULT_PAGE_TIMEOUT_SECONDS,
            runtime_isolation="current-home",
            server_env={"AGI_CLUSTER_ENABLED": "0"},
            home_root=fake_home,
        )
    finally:
        web_robot.assert_page_healthy = original_web_robot_assert
        module.wait_for_page_ready = original_wait_for_page_ready
        module.wait_for_widgets_ready = original_wait_for_widgets_ready
        module._probe_selected_actions_first = original_probe_selected_actions_first

    assert result.success is False
    assert result.status == "environment_blocked"
    assert result.failed_count == 1
    assert result.failures[0].kind == "environment_preflight"
    assert "environment_blocked" in result.failures[0].detail
    assert "missing-clustershare" in result.failures[0].detail


def test_sweep_page_marks_visible_error_message_as_failed() -> None:
    module = _load_module()

    class _Locator:
        def __init__(self, count_value: int = 0):
            self._count_value = count_value

        def nth(self, _index):
            return self

        @property
        def first(self):
            return self

        def count(self) -> int:
            return self._count_value

    class _Page:
        def __init__(self) -> None:
            self.url = "http://127.0.0.1:8501/ORCHESTRATE?active_app=flight_telemetry_project"

        def goto(self, *_args, **_kwargs):
            return None

        def wait_for_timeout(self, _ms) -> None:
            return None

        def locator(self, selector):
            if selector == "[role='tab']":
                return _Locator(0)
            return _Locator(0)

        def evaluate(self, script):
            if script == module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS:
                return [{"kind": "error", "detail": "AGI execution failed."}]
            if script == module.OPEN_EXPANDERS_JS:
                return 0
            if script == module.WIDGET_COLLECTOR_JS:
                return []
            return []

    web_robot = module._load_web_robot()
    original_web_robot_assert = web_robot.assert_page_healthy
    original_wait_for_page_ready = module.wait_for_page_ready
    original_wait_for_widgets_ready = module.wait_for_widgets_ready
    web_robot.assert_page_healthy = lambda *args, **_kwargs: web_robot.RobotStep(
        "health",
        True,
        0.0,
        "ok",
        "http://127.0.0.1:8501",
    )

    try:
        module.wait_for_page_ready = lambda page, timeout_ms: None
        module.wait_for_widgets_ready = lambda page, page_name, timeout_ms: 0
        result = module.sweep_page(
            _Page(),
            web_robot=web_robot,
            base_url="http://127.0.0.1:8501",
            active_app_query="flight_telemetry_project",
            app_name="flight_telemetry_project",
            page_name="ORCHESTRATE",
            timeout=module.DEFAULT_TIMEOUT_SECONDS,
            widget_timeout=module.DEFAULT_WIDGET_TIMEOUT_SECONDS,
            interaction_mode="full",
            action_button_policy="trial",
            upload_file=Path("does-not-exist.txt"),
            screenshot_dir=None,
            page_timeout=module.DEFAULT_PAGE_TIMEOUT_SECONDS,
        )
    finally:
        web_robot.assert_page_healthy = original_web_robot_assert
        module.wait_for_page_ready = original_wait_for_page_ready
        module.wait_for_widgets_ready = original_wait_for_widgets_ready

    assert result.success is False
    assert result.status == "failed"
    assert result.failed_count == 1
    assert result.failures[0].kind == "visible_error"
    assert "AGI execution failed" in result.failures[0].detail


def test_sweep_page_marks_browser_page_error_as_failed() -> None:
    module = _load_module()
    browser_issues: list[dict[str, str]] = []

    class _Locator:
        def __init__(self, count_value: int = 0):
            self._count_value = count_value

        def nth(self, _index):
            return self

        @property
        def first(self):
            return self

        def count(self) -> int:
            return self._count_value

    class _Page:
        def __init__(self) -> None:
            self.url = "http://127.0.0.1:8501/ORCHESTRATE?active_app=flight_telemetry_project"

        def goto(self, *_args, **_kwargs):
            browser_issues.append({"kind": "pageerror", "detail": "TypeError: broken widget callback"})
            return None

        def wait_for_timeout(self, _ms) -> None:
            return None

        def locator(self, selector):
            if selector == "[role='tab']":
                return _Locator(0)
            return _Locator(0)

        def evaluate(self, script):
            if script == module.OPEN_EXPANDERS_JS:
                return 0
            if script == module.WIDGET_COLLECTOR_JS:
                return []
            if script == module.SCROLL_METRICS_JS:
                return {"y": 0, "height": 1000, "scrollHeight": 1000}
            return []

    web_robot = module._load_web_robot()
    original_web_robot_assert = web_robot.assert_page_healthy
    original_wait_for_page_ready = module.wait_for_page_ready
    original_wait_for_widgets_ready = module.wait_for_widgets_ready
    web_robot.assert_page_healthy = lambda *args, **_kwargs: web_robot.RobotStep(
        "health",
        True,
        0.0,
        "ok",
        "http://127.0.0.1:8501",
    )

    try:
        module.wait_for_page_ready = lambda page, timeout_ms: None
        module.wait_for_widgets_ready = lambda page, page_name, timeout_ms: 0
        result = module.sweep_page(
            _Page(),
            web_robot=web_robot,
            base_url="http://127.0.0.1:8501",
            active_app_query="flight_telemetry_project",
            app_name="flight_telemetry_project",
            page_name="ORCHESTRATE",
            timeout=module.DEFAULT_TIMEOUT_SECONDS,
            widget_timeout=module.DEFAULT_WIDGET_TIMEOUT_SECONDS,
            interaction_mode="full",
            action_button_policy="trial",
            upload_file=Path("does-not-exist.txt"),
            screenshot_dir=None,
            page_timeout=module.DEFAULT_PAGE_TIMEOUT_SECONDS,
            browser_issues=browser_issues,
        )
    finally:
        web_robot.assert_page_healthy = original_web_robot_assert
        module.wait_for_page_ready = original_wait_for_page_ready
        module.wait_for_widgets_ready = original_wait_for_widgets_ready

    assert result.success is False
    assert result.status == "failed"
    assert result.failed_count == 1
    assert result.failures[0].kind == "browser_error"
    assert result.failures[0].label == "pageerror"
    assert "broken widget callback" in result.failures[0].detail


def test_performance_budget_probe_fails_when_budget_is_exceeded() -> None:
    module = _load_module()

    unbudgeted = module._performance_budget_probe(
        app_name="flight_telemetry_project",
        display="PROJECT",
        label="first_render",
        seconds=0.5,
        budget_seconds=0.0,
        url="http://demo",
    )
    within_budget = module._performance_budget_probe(
        app_name="flight_telemetry_project",
        display="PROJECT",
        label="widgets_ready",
        seconds=0.5,
        budget_seconds=1.0,
        url="http://demo",
    )
    probe = module._performance_budget_probe(
        app_name="flight_telemetry_project",
        display="PROJECT",
        label="widgets_ready",
        seconds=2.5,
        budget_seconds=1.0,
        url="http://demo",
    )

    assert unbudgeted.status == "probed"
    assert "budget<=" not in unbudgeted.detail
    assert within_budget.status == "probed"
    assert "budget<=1.00s" in within_budget.detail
    assert probe.kind == "performance"
    assert probe.status == "failed"
    assert "exceeded" in probe.detail


def test_success_screenshot_probe_records_evidence(tmp_path) -> None:
    module = _load_module()

    class _Page:
        url = "http://demo"

    class _WebRobot:
        @staticmethod
        def _screenshot(page, screenshot_dir, label):
            path = screenshot_dir / f"{label}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"png")
            return str(path)

    probe = module._capture_success_screenshot_probe(
        _Page(),
        web_robot=_WebRobot(),
        app_name="flight_telemetry_project",
        display="PROJECT",
        screenshot_dir=tmp_path,
    )

    assert probe is not None
    assert probe.kind == "screenshot"
    assert probe.status == "probed"
    assert "success screenshot=" in probe.detail


def test_success_screenshot_probe_masks_dynamic_regions_when_requested(tmp_path) -> None:
    module = _load_module()

    class _Page:
        url = "http://demo"

        def __init__(self) -> None:
            self.evaluated_scripts = []

        def evaluate(self, script):
            self.evaluated_scripts.append(script)
            return 1

    class _WebRobot:
        @staticmethod
        def _screenshot(page, screenshot_dir, label):
            path = screenshot_dir / f"{label}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"png")
            return str(path)

    page = _Page()
    probe = module._capture_success_screenshot_probe(
        page,
        web_robot=_WebRobot(),
        app_name="flight_telemetry_project",
        display="PROJECT",
        screenshot_dir=tmp_path,
        visual_mask_dynamic_regions=True,
    )

    assert probe is not None
    assert probe.status == "probed"
    assert page.evaluated_scripts == [module.VISUAL_MASK_DYNAMIC_REGIONS_JS]


def test_browser_history_probe_checks_back_forward_and_active_app_route() -> None:
    module = _load_module()
    visited: list[str] = []

    class _Health:
        success = True
        detail = "ok"

    class _FakeWebRobot:
        @staticmethod
        def build_page_url(base_url, page_name, *, active_app=None, current_page=None):
            return f"{base_url.rstrip('/')}/{page_name}?active_app={active_app}"

        @staticmethod
        def assert_page_healthy(*_args, **_kwargs):
            return _Health()

    class _Page:
        url = "http://127.0.0.1:8501/PROJECT?active_app=flight_telemetry_project"

        def goto(self, url, **_kwargs):
            self.url = url
            visited.append(url)

        def go_back(self, **_kwargs):
            self.url = "http://127.0.0.1:8501/ORCHESTRATE?active_app=flight_telemetry_project"
            visited.append("BACK")

        def go_forward(self, **_kwargs):
            self.url = "http://127.0.0.1:8501/ANALYSIS?active_app=flight_telemetry_project"
            visited.append("FORWARD")

        def evaluate(self, script):
            if script == module.THEME_STATE_COLLECTOR_JS:
                return {
                    "app": {"backgroundColor": "rgb(8, 17, 31)"},
                    "body": {"backgroundColor": "rgb(8, 17, 31)"},
                    "rootBackground": "rgb(8, 17, 31)",
                }
            return {}

    original_wait_for_page_ready = module.wait_for_page_ready
    original_wait_for_widgets_ready = module.wait_for_widgets_ready
    try:
        module.wait_for_page_ready = lambda page, timeout_ms: None
        module.wait_for_widgets_ready = lambda page, page_name, timeout_ms: 0
        probe = module._browser_history_probe(
            _Page(),
            web_robot=_FakeWebRobot(),
            base_url="http://127.0.0.1:8501",
            active_app_query="flight_telemetry_project",
            app_name="flight_telemetry_project",
            display="PROJECT",
            timeout_ms=100,
            widget_timeout_ms=100,
            screenshot_dir=None,
            route_query="",
        )
    finally:
        module.wait_for_page_ready = original_wait_for_page_ready
        module.wait_for_widgets_ready = original_wait_for_widgets_ready

    assert probe.kind == "browser_history"
    assert probe.status == "interacted"
    assert "PROJECT -> ORCHESTRATE -> ANALYSIS" == probe.label
    assert "dark theme" in probe.detail
    assert visited[-2:] == ["BACK", "FORWARD"]


def test_dark_theme_status_fails_for_light_background() -> None:
    module = _load_module()

    class _Page:
        def evaluate(self, script):
            assert script == module.THEME_STATE_COLLECTOR_JS
            return {
                "app": {"backgroundColor": "rgb(255, 255, 255)"},
                "body": {"backgroundColor": "rgb(255, 255, 255)"},
                "rootBackground": "rgb(255, 255, 255)",
            }

    ok, detail = module._dark_theme_status(_Page())

    assert ok is False
    assert "dark theme was not preserved" in detail


def test_sweep_remote_app_returns_failed_result_on_health_timeout() -> None:
    module = _load_module()
    results: list[module.PageSweep] = []

    class _FakeHealthStep:
        success = False
        duration_seconds = 2.0
        detail = "not ready"
        url = "http://remote"

    class _FakeWebRobot:
        @staticmethod
        def wait_for_streamlit_health(base_url: str, timeout: float):
            return _FakeHealthStep()

        @staticmethod
        def _free_port() -> int:
            return 8501

    original_load_web_robot = module._load_web_robot
    original_normalize = module.normalize_remote_url

    module._load_web_robot = lambda: _FakeWebRobot()
    module.normalize_remote_url = lambda _value: _value
    try:
        pages = module.sweep_remote_app(
            app="flight_telemetry_project",
            base_url="http://remote",
            active_app_query="flight_telemetry_project",
            pages=[],
            apps_pages=[],
            remote_app_root="/app",
            timeout=30.0,
            widget_timeout=1.0,
            interaction_mode="full",
            action_button_policy="trial",
            browser_name="chromium",
            headless=True,
            screenshot_dir=None,
            page_timeout=module.DEFAULT_PAGE_TIMEOUT_SECONDS,
            progress=None,
            resume_page_results=None,
            on_page_result=results.append,
        )
    finally:
        module._load_web_robot = original_load_web_robot
        module.normalize_remote_url = original_normalize

    assert len(pages) == 1
    page = pages[0]
    assert page.status == "failed"
    assert page.success is False
    assert page.failed_count == 1
    assert page.page == "REMOTE_SERVER"
    assert len(results) == 1


def test_sweep_direct_apps_page_returns_failed_result_on_health_timeout() -> None:
    module = _load_module()
    progress_log: list[dict] = []

    class _HealthStep:
        success = False
        duration_seconds = 3.0
        detail = "not ready"
        url = "http://127.0.0.1:8551"

    class _FakeServer:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    class _FakeWebRobot:
        @staticmethod
        def _free_port() -> int:
            return 8551

        @staticmethod
        def wait_for_streamlit_health(base_url: str, timeout: float):
            return _HealthStep()

        StreamlitServer = _FakeServer

    class _Progress:
        def emit(self, event: str, **payload: object) -> None:
            progress_log.append({"event": event, **payload})

    route = module.AppsPageRoute("view_maps", Path("/tmp/view_maps.py"))
    original_load_web_robot = module._load_web_robot

    module._load_web_robot = lambda: _FakeWebRobot()
    try:
        result = module.sweep_direct_apps_page(
            web_robot=_FakeWebRobot(),
            app_name="flight_telemetry_project",
            active_app="flight_telemetry_project",
            route=route,
            timeout=10.0,
            widget_timeout=1.0,
            interaction_mode="full",
            action_button_policy="trial",
            browser_name="chromium",
            headless=True,
            screenshot_dir=None,
            server_env={},
            page_timeout=module.DEFAULT_PAGE_TIMEOUT_SECONDS,
            progress=_Progress(),
            resume_page_results=None,
            on_page_result=None,
        )
    finally:
        module._load_web_robot = original_load_web_robot

    assert result.success is False
    assert result.status == "failed"
    assert result.failed_count == 1
    assert result.page == "APPS_PAGE:view_maps"
    assert progress_log and progress_log[0]["event"] == "page_start"
def test_render_human_reports_sidebar_widget_counts() -> None:
    module = _load_module()
    failure = module.WidgetProbe("flight_telemetry_project", "PROJECT", "button", "Run", "failed", "boom", "http://demo")
    skip = module.WidgetProbe("flight_telemetry_project", "PROJECT", "file_uploader", "Upload", "skipped", "read-only", "http://demo")
    page = module.PageSweep(
        app="flight_telemetry_project",
        page="PROJECT",
        success=False,
        duration_seconds=1.0,
        widget_count=3,
        main_widget_count=2,
        sidebar_widget_count=1,
        interacted_count=3,
        probed_count=0,
        skipped_count=1,
        failed_count=1,
        url="http://demo",
        failures=[failure],
        skips=[skip],
        status="failed",
        combination_space_count=2,
        combination_count=2,
    )
    summary = module.summarize([page], app_count=1, target_seconds=10.0)

    report = module.render_human(summary)

    assert "widgets=3 main=2 sidebar=1" in report
    assert "combinations: space=2 executed=2" in report
    assert "flight_telemetry_project/PROJECT: FAIL status=failed widgets=3 main=2 sidebar=1" in report
    assert "combinations=2/2" in report
    assert "failure: button 'Run' - boom" in report
    assert "skipped: file_uploader 'Upload' - read-only" in report


def test_action_buttons_are_probed_by_default(tmp_path) -> None:
    module = _load_module()
    clicks: list[dict] = []

    class _Locator:
        @property
        def first(self):
            return self

        def count(self):
            return 1

        def scroll_into_view_if_needed(self, timeout):
            pass

        def is_visible(self, timeout):
            return True

        def is_enabled(self, timeout):
            return True

        def bounding_box(self, timeout):
            return {"width": 10, "height": 10}

        def click(self, **kwargs):
            clicks.append(kwargs)

    class _Page:
        def locator(self, selector):
            return _Locator()

    status, detail = module._probe_widget(
        _Page(),
        {"id": "w1", "kind": "button", "label": "EXECUTE"},
        timeout_ms=100,
        interaction_mode="full",
        action_button_policy="trial",
        upload_file=tmp_path / "fixture.txt",
        restore_view=None,
    )

    assert status == "probed"
    assert "callback not fired" in detail
    assert clicks == [{"timeout": 100, "trial": True}]


def test_safe_action_click_classifier_allows_navigation_and_denies_risky_actions() -> None:
    module = _load_module()

    assert module.safe_action_click_reason({"kind": "button", "label": "View maps"})
    assert module.safe_action_click_reason({"kind": "button", "label": "view_forecast_analysis"})
    assert module.safe_action_click_reason({"kind": "download_button", "label": "Download CSV"})
    assert module.safe_action_click_reason({"kind": "button", "label": "RUN pipeline"}) is None
    assert module.safe_action_click_reason({"kind": "form_submit_button", "label": "Create project"}) is None
    assert module.safe_action_click_reason({"kind": "button", "label": "Overwrite"}) is None
    assert module.safe_action_click_reason({"kind": "button", "label": "Rebuild Universal Offline knowledge base"}) is None
    assert module.safe_action_click_reason({"kind": "button", "label": "Telemetry"}) is None


def test_safe_click_policy_clicks_guarded_buttons_and_trials_risky_buttons(tmp_path) -> None:
    module = _load_module()
    clicks: list[dict] = []

    class _Locator:
        @property
        def first(self):
            return self

        def count(self):
            return 1

        def scroll_into_view_if_needed(self, timeout):
            pass

        def is_visible(self, timeout):
            return True

        def is_enabled(self, timeout):
            return True

        def bounding_box(self, timeout):
            return {"width": 10, "height": 10}

        def click(self, **kwargs):
            clicks.append(kwargs)

    class _Page:
        url = "http://demo"

        def locator(self, selector):
            if selector == "[data-testid='stSpinner']":
                return _Locator(0)
            return _Locator()

        def wait_for_timeout(self, ms):
            pass

    budget = [1]
    status, detail = module._probe_widget(
        _Page(),
        {"id": "safe", "kind": "button", "label": "View maps"},
        timeout_ms=100,
        interaction_mode="full",
        action_button_policy="safe-click",
        upload_file=tmp_path / "fixture.txt",
        restore_view=None,
        action_timeout_ms=100,
        action_click_budget=budget,
    )

    assert status == "interacted"
    assert "guarded safe action" in detail
    assert budget == [0]
    assert clicks == [{"timeout": 100}]

    status, detail = module._probe_widget(
        _Page(),
        {"id": "risky", "kind": "button", "label": "RUN pipeline"},
        timeout_ms=100,
        interaction_mode="full",
        action_button_policy="safe-click",
        upload_file=tmp_path / "fixture.txt",
        restore_view=None,
        action_timeout_ms=100,
        action_click_budget=[1],
    )

    assert status == "probed"
    assert "guarded safe-click policy" in detail
    assert clicks[-1] == {"timeout": 100, "trial": True}


def test_collect_current_view_repeats_discovery_after_safe_callback(tmp_path) -> None:
    module = _load_module()
    clicks: list[str] = []

    class _Locator:
        def __init__(self, widget_id: str):
            self.widget_id = widget_id

        @property
        def first(self):
            return self

        def count(self):
            return 0 if self.widget_id in {"exception", "spinner"} else 1

        def scroll_into_view_if_needed(self, timeout):
            pass

        def is_visible(self, timeout):
            return True

        def is_enabled(self, timeout):
            return True

        def bounding_box(self, timeout):
            return {"width": 10, "height": 10}

        def click(self, **kwargs):
            clicks.append(self.widget_id)

        def input_value(self, timeout):
            return ""

        def fill(self, value, timeout):
            pass

    class _Page:
        url = "http://demo"

        def __init__(self):
            self.evaluate_count = 0

        def evaluate(self, script):
            if script == module.OPEN_EXPANDERS_JS:
                return 0
            if script in {
                module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS,
                module.VISIBLE_STREAMLIT_FEEDBACK_COLLECTOR_JS,
                module.ACTION_LOG_FEEDBACK_COLLECTOR_JS,
            }:
                return []
            self.evaluate_count += 1
            widgets = [
                {
                    "id": "view",
                    "kind": "button",
                    "label": "View details",
                    "testid": "stButton",
                    "path": "button:nth-of-type(1)",
                    "scope": "main",
                },
            ]
            if clicks:
                widgets.append(
                    {
                        "id": "name",
                        "kind": "text_input",
                        "label": "Name",
                        "testid": "stTextInput",
                        "path": "input:nth-of-type(1)",
                        "scope": "main",
                    }
                )
            return widgets

        def locator(self, selector):
            if selector == "[data-testid='stException']":
                return _Locator("exception")
            if selector == "[data-testid='stSpinner']":
                return _Locator("spinner")
            if "name" in selector:
                return _Locator("name")
            return _Locator("view")

        def wait_for_timeout(self, ms):
            pass

    probes = module._collect_and_probe_current_view(
        _Page(),
        app_name="flight_telemetry_project",
        page_name="PROJECT",
        widget_timeout_ms=100,
        interaction_mode="full",
        action_button_policy="safe-click",
        upload_file=tmp_path / "fixture.txt",
        restore_view=None,
        known=set(),
        discovery_passes=2,
        action_click_budget=[2],
        action_timeout_ms=100,
    )

    assert [probe.kind for probe in probes] == ["button", "text_input"]
    assert probes[0].status == "interacted"
    assert probes[1].status == "interacted"


def test_hidden_data_editor_after_collection_is_not_a_matrix_failure(tmp_path) -> None:
    module = _load_module()

    class _Locator:
        @property
        def first(self):
            return self

        def count(self):
            return 1

        def scroll_into_view_if_needed(self, timeout):
            pass

        def is_visible(self, timeout):
            return False

    class _Page:
        def locator(self, selector):
            return _Locator()

    status, detail = module._probe_widget(
        _Page(),
        {"id": "w1", "kind": "data_editor", "label": "Stage table"},
        timeout_ms=100,
        interaction_mode="full",
        action_button_policy="trial",
        upload_file=tmp_path / "fixture.txt",
        restore_view=None,
    )

    assert status == "probed"
    assert "visible table content was still detected" in detail


def test_selected_action_button_clicks_and_detects_visible_error(tmp_path) -> None:
    module = _load_module()
    clicks: list[dict] = []

    class _Locator:
        @property
        def first(self):
            return self

        def count(self):
            return 1

        def scroll_into_view_if_needed(self, timeout):
            pass

        def is_visible(self, timeout):
            return True

        def is_enabled(self, timeout):
            return True

        def bounding_box(self, timeout):
            return {"width": 10, "height": 10}

        def click(self, **kwargs):
            clicks.append(kwargs)

    class _Page:
        def locator(self, selector):
            return _Locator()

        def evaluate(self, script):
            if script == module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS:
                return [{"kind": "error", "detail": "AGI execution failed."}]
            return []

    status, detail = module._probe_widget(
        _Page(),
        {"id": "w1", "kind": "button", "label": "Run \u2192 Load \u2192 Export"},
        timeout_ms=100,
        interaction_mode="full",
        action_button_policy="click-selected",
        click_action_labels=["Run -> Load -> Export"],
        action_timeout_ms=100,
        upload_file=tmp_path / "fixture.txt",
        restore_view=None,
    )

    assert status == "failed"
    assert "AGI execution failed" in detail
    assert clicks == [{"timeout": 100}]


def test_selected_action_button_reopens_expanders_to_detect_action_error(tmp_path) -> None:
    module = _load_module()
    clicks: list[dict] = []
    expanded = {"value": False}

    class _Locator:
        @property
        def first(self):
            return self

        def count(self):
            return 1

        def scroll_into_view_if_needed(self, timeout):
            pass

        def is_visible(self, timeout):
            return True

        def is_enabled(self, timeout):
            return True

        def bounding_box(self, timeout):
            return {"width": 10, "height": 10}

        def click(self, **kwargs):
            clicks.append(kwargs)

    class _Page:
        def locator(self, selector):
            return _Locator()

        def evaluate(self, script):
            if script == module.OPEN_EXPANDERS_JS:
                expanded["value"] = True
                return 1
            if script == module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS and expanded["value"]:
                return [{"kind": "error", "detail": "Distribution build failed."}]
            return []

    status, detail = module._probe_widget(
        _Page(),
        {"id": "w1", "kind": "button", "label": "CHECK distribute"},
        timeout_ms=100,
        interaction_mode="full",
        action_button_policy="click-selected",
        click_action_labels=["CHECK distribute"],
        action_timeout_ms=100,
        upload_file=tmp_path / "fixture.txt",
        restore_view=None,
    )

    assert status == "failed"
    assert "Distribution build failed" in detail
    assert clicks == [{"timeout": 100}]


def test_selected_action_button_waits_for_delayed_feedback_error(tmp_path) -> None:
    module = _load_module()
    clicks: list[dict] = []
    clicked = {"value": False}
    feedback_calls = {"value": 0}

    class _Locator:
        def __init__(self, count=1):
            self._count = count

        @property
        def first(self):
            return self

        def count(self):
            return self._count

        def scroll_into_view_if_needed(self, timeout):
            pass

        def is_visible(self, timeout):
            return True

        def is_enabled(self, timeout):
            return True

        def bounding_box(self, timeout):
            return {"width": 10, "height": 10}

        def click(self, **kwargs):
            clicked["value"] = True
            clicks.append(kwargs)

    class _Page:
        def locator(self, selector):
            if selector == "[data-testid='stSpinner']":
                return _Locator(count=0)
            return _Locator()

        def evaluate(self, script):
            if script == module.OPEN_EXPANDERS_JS:
                return 0
            if script == module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS:
                return []
            if script == module.VISIBLE_STREAMLIT_FEEDBACK_COLLECTOR_JS:
                if not clicked["value"]:
                    return []
                feedback_calls["value"] += 1
                if feedback_calls["value"] < 3:
                    return []
                return [{"kind": "error", "detail": "Distribution build failed."}]
            return []

        def wait_for_timeout(self, ms):
            pass

    status, detail = module._probe_widget(
        _Page(),
        {"id": "w1", "kind": "button", "label": "CHECK distribute"},
        timeout_ms=100,
        interaction_mode="full",
        action_button_policy="click-selected",
        click_action_labels=["CHECK distribute"],
        action_timeout_ms=1000,
        upload_file=tmp_path / "fixture.txt",
        restore_view=None,
    )

    assert status == "failed"
    assert "Distribution build failed" in detail
    assert feedback_calls["value"] >= 3
    assert clicks == [{"timeout": 1000}]


def test_action_outcome_does_not_settle_on_soft_feedback_before_late_error() -> None:
    module = _load_module()
    feedback_calls = {"value": 0}

    class _Locator:
        def count(self):
            return 0

    class _Page:
        def locator(self, selector):
            return _Locator()

        def evaluate(self, script):
            if script in {module.OPEN_EXPANDERS_JS, module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS}:
                return []
            if script == module.VISIBLE_STREAMLIT_FEEDBACK_COLLECTOR_JS:
                feedback_calls["value"] += 1
                if feedback_calls["value"] == 1:
                    return [{"kind": "info", "detail": "Logs saved"}]
                return [{"kind": "error", "detail": "AGI execution failed."}]
            return []

        def wait_for_timeout(self, _ms):
            return None

    error, settled = module._wait_for_action_outcome(
        _Page(),
        timeout_ms=1000,
        require_feedback=True,
        baseline_feedback=set(),
    )

    assert settled is True
    assert "AGI execution failed" in str(error)
    assert feedback_calls["value"] >= 2


def test_action_outcome_can_settle_when_next_selected_action_appears() -> None:
    module = _load_module()

    class _Locator:
        def count(self):
            return 0

    class _Page:
        def locator(self, selector):
            return _Locator()

        def evaluate(self, script):
            if script in {
                module.OPEN_EXPANDERS_JS,
                module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS,
                module.VISIBLE_STREAMLIT_FEEDBACK_COLLECTOR_JS,
                module.ACTION_LOG_FEEDBACK_COLLECTOR_JS,
            }:
                return []
            if script == module.WIDGET_COLLECTOR_JS:
                return [{"id": "confirm", "kind": "button", "label": "Confirm delete", "scope": "main"}]
            return []

        def wait_for_timeout(self, _ms):
            return None

    error, settled = module._wait_for_action_outcome(
        _Page(),
        timeout_ms=1000,
        require_feedback=True,
        baseline_feedback=set(),
        settle_action_labels=["Confirm delete"],
        allow_idle_settle=True,
    )

    assert error is None
    assert settled is True


def test_action_outcome_can_settle_on_soft_feedback_when_target_was_already_ready() -> None:
    module = _load_module()

    class _Locator:
        def count(self):
            return 0

    class _Page:
        def locator(self, selector):
            return _Locator()

        def evaluate(self, script):
            if script in {
                module.OPEN_EXPANDERS_JS,
                module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS,
                module.ACTION_LOG_FEEDBACK_COLLECTOR_JS,
            }:
                return []
            if script == module.VISIBLE_STREAMLIT_FEEDBACK_COLLECTOR_JS:
                return [{"kind": "info", "detail": "Run mode 0: python"}]
            if script == module.WIDGET_COLLECTOR_JS:
                return []
            return []

        def wait_for_timeout(self, _ms):
            return None

    error, settled = module._wait_for_action_outcome(
        _Page(),
        timeout_ms=50,
        require_feedback=True,
        baseline_feedback=set(),
        settle_action_labels=["Confirm delete"],
        allow_idle_settle=True,
    )

    assert error is None
    assert settled is True


def test_action_outcome_can_idle_settle_for_already_ready_idempotent_action() -> None:
    module = _load_module()

    class _Locator:
        def count(self):
            return 0

    class _Page:
        def locator(self, selector):
            return _Locator()

        def evaluate(self, script):
            if script in {
                module.OPEN_EXPANDERS_JS,
                module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS,
                module.VISIBLE_STREAMLIT_FEEDBACK_COLLECTOR_JS,
                module.ACTION_LOG_FEEDBACK_COLLECTOR_JS,
                module.WIDGET_COLLECTOR_JS,
            }:
                return []
            return []

        def wait_for_timeout(self, _ms):
            return None

    error, settled = module._wait_for_action_outcome(
        _Page(),
        timeout_ms=50,
        require_feedback=True,
        baseline_feedback=set(),
        settle_action_labels=["Confirm delete"],
        allow_idle_settle=True,
    )

    assert error is None
    assert settled is True


def test_visible_spinner_count_ignores_hidden_streamlit_spinners() -> None:
    module = _load_module()

    class _Spinner:
        def __init__(self, visible: bool):
            self.visible = visible

        def is_visible(self, timeout):
            return self.visible

    class _Locator:
        def __init__(self, visible_values):
            self.visible_values = visible_values

        def count(self):
            return len(self.visible_values)

        def nth(self, index):
            return _Spinner(self.visible_values[index])

    class _Page:
        def __init__(self, visible_values):
            self.visible_values = visible_values

        def locator(self, selector):
            assert selector == "[data-testid='stSpinner']"
            return _Locator(self.visible_values)

    assert module._visible_spinner_count(_Page([False, False])) == 0
    assert module._visible_spinner_count(_Page([False, True])) == 1


def test_selected_action_button_detects_failure_in_orchestration_log_expander(tmp_path) -> None:
    module = _load_module()
    clicks: list[dict] = []
    clicked = {"value": False}
    action_log_calls = {"value": 0}

    class _Locator:
        def __init__(self, count=1):
            self._count = count

        @property
        def first(self):
            return self

        def count(self):
            return self._count

        def scroll_into_view_if_needed(self, timeout):
            pass

        def is_visible(self, timeout):
            return True

        def is_enabled(self, timeout):
            return True

        def bounding_box(self, timeout):
            return {"width": 10, "height": 10}

        def click(self, **kwargs):
            clicked["value"] = True
            clicks.append(kwargs)

    class _Page:
        def locator(self, selector):
            if selector == "[data-testid='stSpinner']":
                return _Locator(count=0)
            return _Locator()

        def evaluate(self, script):
            if script == module.OPEN_EXPANDERS_JS:
                return 1
            if script in {module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS, module.VISIBLE_STREAMLIT_FEEDBACK_COLLECTOR_JS}:
                return []
            if script == module.ACTION_LOG_FEEDBACK_COLLECTOR_JS:
                if not clicked["value"]:
                    return []
                action_log_calls["value"] += 1
                return [{"kind": "error", "detail": "Distribution build failed. Traceback: worker build error"}]
            return []

        def wait_for_timeout(self, ms):
            pass

    status, detail = module._probe_widget(
        _Page(),
        {"id": "w1", "kind": "button", "label": "CHECK distribute"},
        timeout_ms=100,
        interaction_mode="full",
        action_button_policy="click-selected",
        click_action_labels=["CHECK distribute"],
        action_timeout_ms=1000,
        upload_file=tmp_path / "fixture.txt",
        restore_view=None,
    )

    assert status == "failed"
    assert "action='CHECK distribute' status=error" in detail
    assert "Distribution build failed" in detail
    assert "evidence_tail=" in detail
    assert action_log_calls["value"] >= 1
    assert clicks == [{"timeout": 1000}]


def test_install_selected_action_requires_enabled_followup_button(tmp_path) -> None:
    module = _load_module()
    clicks: list[dict] = []

    class _Locator:
        @property
        def first(self):
            return self

        def count(self):
            return 1

        def scroll_into_view_if_needed(self, timeout):
            pass

        def is_visible(self, timeout):
            return True

        def is_enabled(self, timeout):
            return True

        def bounding_box(self, timeout):
            return {"width": 10, "height": 10}

        def click(self, **kwargs):
            clicks.append(kwargs)

    class _Page:
        def locator(self, selector):
            return _Locator()

        def evaluate(self, script):
            if script == module.WIDGET_COLLECTOR_JS:
                return [{"id": "install", "kind": "button", "label": "INSTALL", "disabled": True}]
            if script in {
                module.OPEN_EXPANDERS_JS,
                module.CLOSE_EXPANDERS_EXCEPT_WIDGET_JS,
                module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS,
                module.VISIBLE_STREAMLIT_FEEDBACK_COLLECTOR_JS,
                module.ACTION_LOG_FEEDBACK_COLLECTOR_JS,
            }:
                return []
            return []

    original_wait_for_action_outcome = module._wait_for_action_outcome
    module._wait_for_action_outcome = lambda page, **_kwargs: (None, True)
    try:
        status, detail = module._probe_widget(
            _Page(),
            {"id": "install", "kind": "button", "label": "INSTALL"},
            timeout_ms=100,
            interaction_mode="full",
            action_button_policy="click-selected",
            click_action_labels=["INSTALL"],
            action_timeout_ms=100,
            upload_file=tmp_path / "fixture.txt",
            restore_view=None,
        )
    finally:
        module._wait_for_action_outcome = original_wait_for_action_outcome

    assert status == "failed"
    assert "action='INSTALL' status=error" in detail
    assert "no expected enabled follow-up action" in detail
    assert clicks == [{"timeout": 100}]


def test_install_selected_action_passes_when_followup_is_enabled(tmp_path) -> None:
    module = _load_module()

    class _Locator:
        @property
        def first(self):
            return self

        def count(self):
            return 1

        def scroll_into_view_if_needed(self, timeout):
            pass

        def is_visible(self, timeout):
            return True

        def is_enabled(self, timeout):
            return True

        def bounding_box(self, timeout):
            return {"width": 10, "height": 10}

        def click(self, **kwargs):
            pass

    class _Page:
        def locator(self, selector):
            return _Locator()

        def evaluate(self, script):
            if script == module.WIDGET_COLLECTOR_JS:
                return [{"id": "check", "kind": "button", "label": "CHECK distribute", "scope": "main"}]
            if script in {
                module.OPEN_EXPANDERS_JS,
                module.CLOSE_EXPANDERS_EXCEPT_WIDGET_JS,
                module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS,
                module.VISIBLE_STREAMLIT_FEEDBACK_COLLECTOR_JS,
                module.ACTION_LOG_FEEDBACK_COLLECTOR_JS,
            }:
                return []
            return []

    original_wait_for_action_outcome = module._wait_for_action_outcome
    module._wait_for_action_outcome = lambda page, **_kwargs: (None, True)
    try:
        status, detail = module._probe_widget(
            _Page(),
            {"id": "install", "kind": "button", "label": "INSTALL"},
            timeout_ms=100,
            interaction_mode="full",
            action_button_policy="click-selected",
            click_action_labels=["INSTALL"],
            action_timeout_ms=100,
            upload_file=tmp_path / "fixture.txt",
            restore_view=None,
        )
    finally:
        module._wait_for_action_outcome = original_wait_for_action_outcome

    assert status == "interacted"
    assert "action='INSTALL' status=success" in detail
    assert "enabled follow-up action 'CHECK distribute'" in detail


def test_selected_action_fails_when_settle_budget_is_exceeded(tmp_path) -> None:
    module = _load_module()

    class _Locator:
        @property
        def first(self):
            return self

        def count(self):
            return 1

        def scroll_into_view_if_needed(self, timeout):
            pass

        def is_visible(self, timeout):
            return True

        def is_enabled(self, timeout):
            return True

        def bounding_box(self, timeout):
            return {"width": 10, "height": 10}

        def click(self, **kwargs):
            pass

    class _Page:
        def locator(self, selector):
            return _Locator()

        def evaluate(self, script):
            if script in {
                module.OPEN_EXPANDERS_JS,
                module.CLOSE_EXPANDERS_EXCEPT_WIDGET_JS,
                module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS,
                module.VISIBLE_STREAMLIT_FEEDBACK_COLLECTOR_JS,
                module.ACTION_LOG_FEEDBACK_COLLECTOR_JS,
            }:
                return []
            return []

    original_wait_for_action_outcome = module._wait_for_action_outcome

    def slow_success(page, **_kwargs):
        time.sleep(0.002)
        return None, True

    module._wait_for_action_outcome = slow_success
    try:
        status, detail = module._probe_widget(
            _Page(),
            {"id": "run", "kind": "button", "label": "Run -> Load -> Export"},
            timeout_ms=100,
            interaction_mode="full",
            action_button_policy="click-selected",
            click_action_labels=["Run -> Load -> Export"],
            action_timeout_ms=100,
            upload_file=tmp_path / "fixture.txt",
            restore_view=None,
            max_action_settle_seconds=0.0001,
        )
    finally:
        module._wait_for_action_outcome = original_wait_for_action_outcome

    assert status == "failed"
    assert "status=slow" in detail
    assert "budget<=" in detail


def test_selected_action_baseline_includes_stale_action_log_feedback() -> None:
    module = _load_module()

    class _Page:
        def evaluate(self, script):
            if script == module.VISIBLE_STREAMLIT_FEEDBACK_COLLECTOR_JS:
                return [{"kind": "info", "detail": "Ready"}]
            if script == module.ACTION_LOG_FEEDBACK_COLLECTOR_JS:
                return [{"kind": "success", "detail": "Distribution built successfully."}]
            return []

    signatures = module._visible_streamlit_feedback_signatures(_Page())
    feedback = module._new_visible_streamlit_feedback(_Page(), signatures)

    assert signatures == {
        ("info", "Ready"),
        ("success", "Distribution built successfully."),
    }
    assert feedback is None


def test_new_visible_feedback_detects_action_log_failure_after_baseline() -> None:
    module = _load_module()
    clicked = {"value": False}

    class _Page:
        def evaluate(self, script):
            if script == module.VISIBLE_STREAMLIT_FEEDBACK_COLLECTOR_JS:
                return [{"kind": "info", "detail": "Ready"}]
            if script == module.ACTION_LOG_FEEDBACK_COLLECTOR_JS:
                if clicked["value"]:
                    return [{"kind": "error", "detail": "Distribution build failed."}]
                return []
            return []

    page = _Page()
    signatures = module._visible_streamlit_feedback_signatures(page)
    clicked["value"] = True
    feedback = module._new_visible_streamlit_feedback(page, signatures)

    assert signatures == {("info", "Ready")}
    assert feedback == {"kind": "error", "detail": "Distribution build failed."}


def test_new_visible_feedback_prioritizes_success_over_incidental_info() -> None:
    module = _load_module()

    class _Page:
        def evaluate(self, script):
            if script == module.VISIBLE_STREAMLIT_FEEDBACK_COLLECTOR_JS:
                return [
                    {"kind": "info", "detail": "Run mode 0: python"},
                    {"kind": "success", "detail": "Distribution built successfully."},
                ]
            if script == module.ACTION_LOG_FEEDBACK_COLLECTOR_JS:
                return []
            return []

    feedback = module._new_visible_streamlit_feedback(_Page(), set())

    assert feedback == {"kind": "success", "detail": "Distribution built successfully."}


def test_unselected_action_button_is_trial_clicked_only(tmp_path) -> None:
    module = _load_module()
    clicks: list[dict] = []

    class _Locator:
        @property
        def first(self):
            return self

        def count(self):
            return 1

        def scroll_into_view_if_needed(self, timeout):
            pass

        def is_visible(self, timeout):
            return True

        def is_enabled(self, timeout):
            return True

        def bounding_box(self, timeout):
            return {"width": 10, "height": 10}

        def click(self, **kwargs):
            clicks.append(kwargs)

    class _Page:
        def locator(self, selector):
            return _Locator()

    status, detail = module._probe_widget(
        _Page(),
        {"id": "w1", "kind": "button", "label": "INSTALL"},
        timeout_ms=100,
        interaction_mode="full",
        action_button_policy="click-selected",
        click_action_labels=["Run -> Load -> Export"],
        upload_file=tmp_path / "fixture.txt",
        restore_view=None,
    )

    assert status == "probed"
    assert "not selected" in detail
    assert clicks == [{"timeout": 100, "trial": True}]


def test_preselected_compact_choice_clicks_only_matching_label(tmp_path) -> None:
    module = _load_module()
    clicks: list[dict] = []
    waits: list[int] = []

    class _Locator:
        @property
        def first(self):
            return self

        def count(self):
            return 1

        def scroll_into_view_if_needed(self, timeout):
            pass

        def is_visible(self, timeout):
            return True

        def is_enabled(self, timeout):
            return True

        def bounding_box(self, timeout):
            return {"width": 10, "height": 10}

        def click(self, **kwargs):
            clicks.append(kwargs)

    class _Page:
        def locator(self, selector):
            return _Locator()

        def wait_for_timeout(self, ms):
            waits.append(ms)

    status, detail = module._probe_widget(
        _Page(),
        {"id": "w1", "kind": "segmented_control", "label": "Run now"},
        timeout_ms=100,
        interaction_mode="full",
        action_button_policy="click-selected",
        click_action_labels=["Run -> Load -> Export"],
        preselect_labels=["Run now"],
        upload_file=tmp_path / "fixture.txt",
        restore_view=None,
    )

    assert status == "interacted"
    assert "selected compact choice" in detail
    assert clicks == [{"timeout": 100}]
    assert waits == [500]


def test_expanders_hidden_after_collection_are_structural_probes(tmp_path) -> None:
    module = _load_module()

    class _Locator:
        @property
        def first(self):
            return self

        def count(self):
            return 1

        def scroll_into_view_if_needed(self, timeout):
            return None

        def is_visible(self, timeout):
            return False

    class _Page:
        def locator(self, _selector):
            return _Locator()

    status, detail = module._probe_widget(
        _Page(),
        {"id": "w1", "kind": "expander", "label": "Install logs"},
        timeout_ms=100,
        interaction_mode="full",
        action_button_policy="trial",
        upload_file=tmp_path / "fixture.txt",
        restore_view=None,
    )

    assert status == "probed"
    assert "expanded content" in detail


def test_text_inputs_are_filled_and_restored(tmp_path) -> None:
    module = _load_module()
    fills: list[str] = []

    class _Locator:
        @property
        def first(self):
            return self

        def count(self):
            return 1

        def scroll_into_view_if_needed(self, timeout):
            pass

        def is_visible(self, timeout):
            return True

        def is_enabled(self, timeout):
            return True

        def bounding_box(self, timeout):
            return {"width": 10, "height": 10}

        def input_value(self, timeout):
            return "original"

        def fill(self, value, timeout):
            fills.append(value)

    class _Page:
        def locator(self, selector):
            return _Locator()

    status, detail = module._probe_widget(
        _Page(),
        {"id": "w1", "kind": "text_input", "label": "Name"},
        timeout_ms=100,
        interaction_mode="full",
        action_button_policy="trial",
        upload_file=tmp_path / "fixture.txt",
        restore_view=None,
    )

    assert status == "interacted"
    assert "restored" in detail
    assert fills == ["original robot", "original"]


def test_file_uploader_uses_ipynb_fixture_for_notebook_upload(tmp_path) -> None:
    module = _load_module()
    uploads: list[dict[str, object]] = []

    class _FileInput:
        @property
        def first(self):
            return self

        def set_input_files(self, value, timeout):
            uploads.append({"value": value, "timeout": timeout})

    class _Locator:
        @property
        def first(self):
            return self

        def count(self):
            return 1

        def scroll_into_view_if_needed(self, timeout):
            pass

        def is_visible(self, timeout):
            return True

        def is_enabled(self, timeout):
            return True

        def bounding_box(self, timeout):
            return {"width": 10, "height": 10}

        def locator(self, selector):
            assert selector == "input[type='file']"
            return _FileInput()

    class _Page:
        def locator(self, selector):
            return _Locator()

        def wait_for_timeout(self, ms):
            pass

    status, detail = module._probe_widget(
        _Page(),
        {
            "id": "w1",
            "kind": "file_uploader",
            "label": "Import notebook upload Upload 200MB per file • IPYNB",
        },
        timeout_ms=100,
        interaction_mode="full",
        action_button_policy="trial",
        upload_file=tmp_path / "fixture.txt",
        restore_view=None,
    )

    assert status == "interacted"
    assert "(.ipynb)" in detail
    assert len(uploads) == 1
    uploaded = Path(str(uploads[0]["value"]))
    assert uploaded.suffix == ".ipynb"
    assert json.loads(uploaded.read_text(encoding="utf-8"))["nbformat"] == 4


def test_parse_csv_splits_and_strips_values() -> None:
    module = _load_module()

    assert module.parse_csv(" flight_telemetry_project, ,uav_queue_project,,flight_telemetry\n") == [
        "flight_telemetry_project",
        "uav_queue_project",
    ]


def test_resolve_apps_pages_rejects_configured_mode() -> None:
    module = _load_module()

    try:
        module.resolve_apps_pages("configured")
    except ValueError as exc:
        assert "configured" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_load_web_robot_reports_unloadable_spec_and_loader_file_errors(monkeypatch) -> None:
    import importlib.machinery

    module = _load_module()
    monkeypatch.setattr(module.importlib.util, "spec_from_file_location", lambda _name, _path: None)
    try:
        module._load_web_robot()
    except RuntimeError as exc:
        assert "Could not load" in str(exc)
    else:
        raise AssertionError("missing spec should fail")

    class _Loader:
        @staticmethod
        def create_module(_spec):
            return None

        @staticmethod
        def exec_module(_module):
            raise FileNotFoundError("missing")

    spec = importlib.machinery.ModuleSpec("fake_web_robot", _Loader())
    monkeypatch.setattr(module.importlib.util, "spec_from_file_location", lambda _name, _path: spec)
    try:
        module._load_web_robot()
    except RuntimeError as exc:
        assert "Could not load" in str(exc)
    else:
        raise AssertionError("loader FileNotFoundError should fail")


def test_resolve_apps_resolves_project_name_within_app_root(tmp_path) -> None:
    module = _load_module()
    app = tmp_path / "custom_project"
    app.mkdir()

    resolved = module.resolve_apps("custom_project", apps_root=tmp_path)

    assert resolved == [app.resolve()]


def test_active_app_slug_and_route_aliases() -> None:
    module = _load_module()

    assert module.active_app_slug("/tmp%2Fflight_telemetry_project") == "flight_telemetry_project"
    assert module.routed_active_app_slug("/foo?active_app=flight_telemetry_project&x=1") == "flight_telemetry_project"
    assert module.routed_active_app_slug("/foo?x=1") is None
    assert module.active_app_aliases("/tmp/flight_telemetry_project") == {
        "flight_telemetry_project",
        "flight_telemetry",
    }


def test_configured_apps_pages_for_app_with_invalid_settings_returns_empty(tmp_path) -> None:
    module = _load_module()
    app = tmp_path / "broken_project"
    settings = app / "src" / "app_settings.toml"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text("not = [ valid", encoding="utf-8")

    assert module.configured_apps_pages_for_app(app) == []


def test_load_web_robot_raises_for_missing_robot_script(tmp_path) -> None:
    module = _load_module()
    original = module.WEB_ROBOT_PATH
    module.WEB_ROBOT_PATH = tmp_path / "does-not-exist.py"
    try:
        module._load_web_robot()
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "Could not load" in str(exc)
    finally:
        module.WEB_ROBOT_PATH = original


def test_remote_apps_page_path_errors_for_external_route() -> None:
    module = _load_module()

    route = module.AppsPageRoute("external", Path("/tmp/not-in-repo.py"))

    try:
        module.remote_apps_page_path(route)
    except ValueError as exc:
        assert "Cannot map apps-page outside repository" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_write_csv_and_json_helpers(tmp_path) -> None:
    module = _load_module()

    csv_path = tmp_path / "values.csv"
    rows = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
    module._write_csv(csv_path, rows)

    contents = csv_path.read_text(encoding="utf-8").splitlines()
    assert contents[0] == "a,b"
    assert contents[1].startswith("1,x")

    module._write_csv(tmp_path / "empty.csv", [])
    assert (tmp_path / "empty.csv").read_text(encoding="utf-8") == ""

    json_path = tmp_path / "payload.json"
    payload = {"b": 2, "a": 1}
    module._write_json(json_path, payload)
    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded == payload


def test_resume_page_if_available_returns_and_reports_match() -> None:
    module = _load_module()
    passed = module.PageSweep(
        app="flight_telemetry_project",
        page="PROJECT",
        success=True,
        duration_seconds=1.0,
        widget_count=1,
        interacted_count=1,
        probed_count=0,
        skipped_count=0,
        failed_count=0,
        url="http://demo",
        failures=[],
        skips=[],
    )
    emitted: list[dict] = []

    class _Progress:
        def emit(self, event, **payload):
            emitted.append({"event": event, **payload})

    on_result: list[module.PageSweep] = []

    resumed = module._resume_page_if_available(
        app_name="flight_telemetry_project",
        page_name="PROJECT",
        resume_page_results={module.page_result_key("flight_telemetry_project", "PROJECT"): passed},
        progress=_Progress(),
        on_page_result=on_result.append,
    )

    assert resumed == passed
    assert on_result == [passed]
    assert any(record.get("event") == "page_resume" for record in emitted)


def test_probe_widget_reports_checkbox_toggle(tmp_path) -> None:
    module = _load_module()
    clicked: list[bool] = []

    class _Locator:
        def __init__(self) -> None:
            self._checked = False

        @property
        def first(self):
            return self

        def count(self) -> int:
            return 1

        def scroll_into_view_if_needed(self, timeout):
            pass

        def is_visible(self, timeout):
            return True

        def is_enabled(self, timeout):
            return True

        def is_checked(self, timeout):
            return self._checked

        def bounding_box(self, timeout):
            return {"width": 10, "height": 10}

        def click(self, **kwargs):
            clicked.append(True)

    class _Page:
        def locator(self, selector):
            return _Locator()

    status, detail = module._probe_widget(
        _Page(),
        {"id": "cb", "kind": "checkbox", "label": "Use advanced mode", "disabled": False},
        timeout_ms=100,
        interaction_mode="full",
        action_button_policy="trial",
        upload_file=tmp_path / "fixture.txt",
        restore_view=None,
    )

    assert status == "interacted"
    assert "clicked and restored" in detail
    assert clicked
