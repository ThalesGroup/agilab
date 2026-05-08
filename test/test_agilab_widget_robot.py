from __future__ import annotations

import importlib.util
import json
import sys
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
    assert any(path.name == "flight_project" for path in apps)
    assert all(path.name.endswith("_project") for path in apps)


def test_resolve_apps_accepts_all_names_and_paths(tmp_path) -> None:
    module = _load_module()
    custom = tmp_path / "custom_project"
    custom.mkdir()

    all_apps = module.resolve_apps("all")
    selected = module.resolve_apps(f"flight_project,{custom}")

    assert len(all_apps) >= 2
    assert any(Path(app).name == "flight_project" for app in selected)
    assert custom.resolve() in selected


def test_resolve_pages_accepts_all_csv_and_home_alias() -> None:
    module = _load_module()

    assert module.resolve_pages("all") == list(module.DEFAULT_PAGES)
    assert module.resolve_pages("none") == []
    assert module.resolve_pages("PROJECT, ANALYSIS") == ["PROJECT", "ANALYSIS"]
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
        "view_uav_relay_queue_analysis",
        "view_maps_network",
    ]


def test_active_app_route_matching_accepts_project_suffix_alias() -> None:
    module = _load_module()

    assert module.active_app_aliases("/tmp/flight_project") == {"flight_project", "flight"}
    assert module.active_app_route_matches("http://x/WORKFLOW?active_app=flight", "/tmp/flight_project")
    assert module.app_target_name("uav_relay_queue_project") == "uav_relay_queue"


def test_normalized_label_treats_ascii_and_unicode_arrows_as_equal() -> None:
    module = _load_module()

    assert module._normalized_label("Run -> Load -> Export") == module._normalized_label("Run \u2192 Load \u2192 Export")


def test_normalize_remote_url_maps_huggingface_space_page_to_runtime() -> None:
    module = _load_module()

    assert (
        module.normalize_remote_url("https://huggingface.co/spaces/jpmorard/agilab?active_app=flight_project")
        == "https://jpmorard-agilab.hf.space/?active_app=flight_project"
    )
    assert module.normalize_remote_url("jpmorard-agilab.hf.space") == "https://jpmorard-agilab.hf.space/"


def test_remote_apps_page_path_uses_remote_checkout_root() -> None:
    module = _load_module()
    route = next(route for route in module.public_apps_pages() if route.name == "view_maps")

    assert module.remote_apps_page_path(route, remote_app_root="/app").startswith("/app/src/agilab/apps-pages/view_maps/")


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
        "meteo_forecast_project",
        export_root=export_root,
        share_root=share_root,
    )

    forecast_root = export_root / "meteo_forecast" / "forecast_analysis"
    assert sorted(path.name for path in forecast_root.iterdir()) == ["baseline", "candidate"]
    assert (forecast_root / "baseline" / "forecast_metrics.json").is_file()
    assert (forecast_root / "candidate" / "forecast_predictions.csv").is_file()


def test_build_seeded_server_env_isolates_home_and_share_paths(tmp_path) -> None:
    module = _load_module()

    class _WebRobot:
        @staticmethod
        def build_server_env():
            return {"PATH": "robot-path", "HOME": "/real-home"}

    seeded = module.build_seeded_server_env(
        _WebRobot(),
        app_name="flight_project",
        runtime_root=tmp_path,
        seed_demo_artifacts=True,
    )

    assert seeded.env["HOME"] == str(tmp_path / "home")
    assert seeded.env["AGI_EXPORT_DIR"] == str(tmp_path / "export")
    assert seeded.env["AGI_LOCAL_SHARE"] == str(tmp_path / "localshare")
    assert seeded.env["AGI_CLUSTER_ENABLED"] == "0"
    assert (tmp_path / "localshare" / "flight" / "dataframe" / "00_robot_flight.csv").is_file()


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
        app_name="flight_project",
        runtime_root=tmp_path / "runtime",
        seed_demo_artifacts=False,
        runtime_isolation="current-home",
    )

    assert seeded.env["HOME"] == str(fake_home)
    assert "AGI_LOCAL_SHARE" not in seeded.env
    assert seeded.share_root == fake_home / "localshare"
    assert seeded.env["AGI_CLUSTER_ENABLED"] == "0"


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


def test_summarize_counts_interactions_and_failures() -> None:
    module = _load_module()
    failure = module.WidgetProbe("flight_project", "PROJECT", "button", "Run", "failed", "blocked", "http://demo", "sidebar")
    pages = [
        module.PageSweep(
            app="flight_project",
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
    assert summary.within_target is False


def test_progress_log_round_trips_passed_pages_only(tmp_path) -> None:
    module = _load_module()
    passed = module.PageSweep(
        app="flight_project",
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
        app="flight_project",
        page="WORKFLOW",
        success=False,
        duration_seconds=1.0,
        widget_count=1,
        interacted_count=0,
        probed_count=0,
        skipped_count=0,
        failed_count=1,
        url="http://demo",
        failures=[module.WidgetProbe("flight_project", "WORKFLOW", "page", "", "failed", "boom", "http://demo")],
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
    assert resumed[module.page_result_key("flight_project", "PROJECT")] == passed
    assert module.page_result_key("flight_project", "WORKFLOW") not in resumed


def test_write_summary_json_includes_page_status(tmp_path) -> None:
    module = _load_module()
    page = module.PageSweep(
        app="flight_project",
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
    assert "[data-testid='stSidebar']" in module.WIDGET_COLLECTOR_JS
    assert "scope: scopeFor(el)" in module.WIDGET_COLLECTOR_JS


def test_visible_streamlit_issue_detail_detects_error_alert_payload() -> None:
    module = _load_module()

    class _Page:
        def evaluate(self, script):
            assert script == module.VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS
            return [{"kind": "error", "detail": "AGI execution failed."}]

    assert module._visible_streamlit_issue_detail(_Page()) == "error: AGI execution failed."


def test_missing_selected_action_probe_fails_when_label_was_not_fired() -> None:
    module = _load_module()
    probes = [
        module.WidgetProbe(
            "flight_project",
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
        app_name="flight_project",
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
            "flight_project",
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
        app_name="flight_project",
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
            if script == module.OPEN_EXPANDERS_JS:
                return 0
            if script == module.WIDGET_COLLECTOR_JS:
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
    module._wait_for_action_outcome = lambda page, timeout_ms: (None, True)
    try:
        probes = module._probe_selected_actions_first(
            _Page(),
            app_name="flight_project",
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
    assert [(probe.kind, probe.status) for probe in probes] == [
        ("segmented_control", "interacted"),
        ("button", "interacted"),
    ]


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
        url = "http://127.0.0.1:8501/ORCHESTRATE?active_app=flight_project"

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
        app_name="flight_project",
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
            active_app_query="flight_project",
            app_name="flight_project",
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
            self.url = "http://127.0.0.1:8501/ORCHESTRATE?active_app=flight_project"

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
            active_app_query="flight_project",
            app_name="flight_project",
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
            app="flight_project",
            base_url="http://remote",
            active_app_query="flight_project",
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
            app_name="flight_project",
            active_app="flight_project",
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
    page = module.PageSweep(
        app="flight_project",
        page="PROJECT",
        success=True,
        duration_seconds=1.0,
        widget_count=3,
        main_widget_count=2,
        sidebar_widget_count=1,
        interacted_count=3,
        probed_count=0,
        skipped_count=0,
        failed_count=0,
        url="http://demo",
        failures=[],
        skips=[],
    )
    summary = module.summarize([page], app_count=1, target_seconds=10.0)

    report = module.render_human(summary)

    assert "widgets=3 main=2 sidebar=1" in report
    assert "flight_project/PROJECT: OK status=passed widgets=3 main=2 sidebar=1" in report


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


def test_parse_csv_splits_and_strips_values() -> None:
    module = _load_module()

    assert module.parse_csv(" flight_project, ,uav_queue_project,,flight\n") == [
        "flight_project",
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


def test_resolve_apps_resolves_project_name_within_app_root(tmp_path) -> None:
    module = _load_module()
    app = tmp_path / "custom_project"
    app.mkdir()

    resolved = module.resolve_apps("custom_project", apps_root=tmp_path)

    assert resolved == [app.resolve()]


def test_active_app_slug_and_route_aliases() -> None:
    module = _load_module()

    assert module.active_app_slug("/tmp%2Fflight_project") == "flight_project"
    assert module.routed_active_app_slug("/foo?active_app=flight_project&x=1") == "flight_project"
    assert module.routed_active_app_slug("/foo?x=1") is None
    assert module.active_app_aliases("/tmp/flight_project") == {"flight_project", "flight"}


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
        app="flight_project",
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
        app_name="flight_project",
        page_name="PROJECT",
        resume_page_results={module.page_result_key("flight_project", "PROJECT"): passed},
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
