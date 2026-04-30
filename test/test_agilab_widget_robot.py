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
    assert module.active_app_route_matches("http://x/PIPELINE?active_app=flight", "/tmp/flight_project")
    assert module.app_target_name("uav_relay_queue_project") == "uav_relay_queue"


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
        page="PIPELINE",
        success=False,
        duration_seconds=1.0,
        widget_count=1,
        interacted_count=0,
        probed_count=0,
        skipped_count=0,
        failed_count=1,
        url="http://demo",
        failures=[module.WidgetProbe("flight_project", "PIPELINE", "page", "", "failed", "boom", "http://demo")],
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
    assert module.page_result_key("flight_project", "PIPELINE") not in resumed


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
