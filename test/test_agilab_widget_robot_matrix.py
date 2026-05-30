from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


MODULE_PATH = Path("tools/agilab_widget_robot_matrix.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("agilab_widget_robot_matrix_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_default_scenarios_cover_isolated_pages_and_current_home_actions() -> None:
    module = _load_module()

    scenarios = module.resolve_scenarios(None)

    assert [scenario.name for scenario in scenarios] == [
        "isolated-core-pages",
        "isolated-entry-and-app-pages",
        "isolated-project-page",
        "isolated-project-notebook-import",
        "isolated-project-import-sidebar",
        "isolated-project-rename-sidebar",
        "isolated-settings-page",
        "current-home-actions",
        "current-home-orchestrate-journey",
    ]
    isolated, entry, project, project_notebook, project_import, project_rename, settings, current_home, journey = scenarios
    assert isolated.pages == "ORCHESTRATE,WORKFLOW,ANALYSIS"
    assert isolated.runtime_isolation == "isolated"
    assert isolated.action_button_policy == "trial"
    assert isolated.assert_workflow_artifacts is True
    assert entry.pages == "none"
    assert entry.apps_pages == "configured"
    assert entry.runtime_isolation == "isolated"
    assert entry.action_button_policy == "trial"
    assert entry.action_timeout_seconds == 30.0
    assert entry.max_action_clicks_per_page == 0
    assert project.pages == "PROJECT"
    assert project.apps_pages == "none"
    assert project.runtime_isolation == "isolated"
    assert project.action_button_policy == "safe-click"
    assert project.action_timeout_seconds == 30.0
    assert project_notebook.pages == "PROJECT"
    assert project_notebook.route_query == "start=notebook-import"
    assert project_notebook.apps_pages == "none"
    assert project_notebook.runtime_isolation == "isolated"
    assert project_notebook.action_button_policy == "safe-click"
    assert project_import.pages == "PROJECT"
    assert project_import.preselect_labels == "Import"
    assert project_import.apps_pages == "none"
    assert project_import.runtime_isolation == "isolated"
    assert project_import.action_button_policy == "safe-click"
    assert project_rename.pages == "PROJECT"
    assert project_rename.preselect_labels == "Rename"
    assert project_rename.apps_pages == "none"
    assert project_rename.runtime_isolation == "isolated"
    assert project_rename.action_button_policy == "safe-click"
    assert settings.pages == "SETTINGS"
    assert settings.apps_pages == "none"
    assert settings.runtime_isolation == "isolated"
    assert settings.action_button_policy == "safe-click"
    assert settings.action_timeout_seconds == 30.0
    assert current_home.pages == "ORCHESTRATE"
    assert current_home.runtime_isolation == "current-home"
    assert current_home.action_button_policy == "click-selected"
    assert current_home.click_action_labels == "CHECK distribute,Run -> Load -> Export"
    assert current_home.preselect_labels == "Run now"
    assert current_home.missing_selected_action_policy == "ignore-absent"
    assert journey.runtime_isolation == "current-home"
    assert journey.pages == "ORCHESTRATE"
    assert journey.action_button_policy == "click-selected"
    assert "Load output" in journey.click_action_labels
    assert "EXPORT dataframe" in journey.click_action_labels
    assert "Confirm delete" in journey.click_action_labels
    assert journey.assert_orchestrate_artifacts is True
    assert "isolated-browser-history" not in [scenario.name for scenario in scenarios]
    assert "isolated-mobile-core-pages" not in [scenario.name for scenario in scenarios]
    assert "isolated-release-evidence" not in [scenario.name for scenario in scenarios]
    assert "isolated-fresh-session-core-pages" not in [scenario.name for scenario in scenarios]
    assert "isolated-keyboard-focus-core-pages" not in [scenario.name for scenario in scenarios]
    assert "isolated-layout-integrity-desktop" not in [scenario.name for scenario in scenarios]
    assert "isolated-layout-integrity-mobile" not in [scenario.name for scenario in scenarios]
    assert "isolated-accessibility-core-pages" not in [scenario.name for scenario in scenarios]
    assert "isolated-browser-error-core-pages" not in [scenario.name for scenario in scenarios]
    assert "isolated-all-builtins-orchestrate-smoke" not in [scenario.name for scenario in scenarios]
    assert "isolated-pytorch-playground-analysis" not in [scenario.name for scenario in scenarios]
    assert "isolated-above-fold-core-pages" not in [scenario.name for scenario in scenarios]
    assert "isolated-visual-baseline-core-pages" not in [scenario.name for scenario in scenarios]
    assert "isolated-cross-browser-core-pages" not in [scenario.name for scenario in scenarios]
    assert "hf-first-proof-install" not in [scenario.name for scenario in scenarios]
    assert "hf-first-proof-visual-smoke" not in [scenario.name for scenario in scenarios]
    assert "hf-first-proof-app-pages-visual-smoke" not in [scenario.name for scenario in scenarios]


def test_opt_in_browser_history_scenario_is_not_part_of_default_all() -> None:
    module = _load_module()

    default_scenarios = module.resolve_scenarios(["all"])
    duplicate_selection = module.resolve_scenarios(["isolated-core-pages", "isolated-core-pages"])
    history = module.resolve_scenarios(["isolated-browser-history"])[0]

    assert "isolated-browser-history" not in [scenario.name for scenario in default_scenarios]
    assert [scenario.name for scenario in duplicate_selection] == ["isolated-core-pages"]
    assert history.name == "isolated-browser-history"
    assert history.pages == "PROJECT"
    assert history.apps_pages == "none"
    assert history.runtime_isolation == "isolated"
    assert history.action_button_policy == "safe-click"
    assert history.browser_history_check is True


def test_opt_in_hf_install_scenario_is_not_part_of_default_all() -> None:
    module = _load_module()

    default_scenarios = module.resolve_scenarios(["all"])
    hf_scenario = module.resolve_scenarios(["hf-first-proof-install"])[0]

    assert "hf-first-proof-install" not in [scenario.name for scenario in default_scenarios]
    assert hf_scenario.name == "hf-first-proof-install"
    assert hf_scenario.pages == "ORCHESTRATE"
    assert hf_scenario.apps_pages == "none"
    assert hf_scenario.action_button_policy == "click-selected"
    assert hf_scenario.click_action_labels == "INSTALL"
    assert hf_scenario.missing_selected_action_policy == "fail"
    assert hf_scenario.action_timeout_seconds == 600.0


def test_opt_in_mobile_and_release_evidence_scenarios_are_not_part_of_default_all() -> None:
    module = _load_module()

    default_names = [scenario.name for scenario in module.resolve_scenarios(["all"])]
    mobile = module.resolve_scenarios(["isolated-mobile-core-pages"])[0]
    evidence = module.resolve_scenarios(["isolated-release-evidence"])[0]
    fresh = module.resolve_scenarios(["isolated-fresh-session-core-pages"])[0]
    first_proof = module.resolve_scenarios(["current-home-first-proof-golden-path"])[0]
    keyboard = module.resolve_scenarios(["isolated-keyboard-focus-core-pages"])[0]
    layout_desktop = module.resolve_scenarios(["isolated-layout-integrity-desktop"])[0]
    layout_mobile = module.resolve_scenarios(["isolated-layout-integrity-mobile"])[0]
    accessibility = module.resolve_scenarios(["isolated-accessibility-core-pages"])[0]
    browser_error = module.resolve_scenarios(["isolated-browser-error-core-pages"])[0]
    all_builtin_orchestrate = module.resolve_scenarios(["isolated-all-builtins-orchestrate-smoke"])[0]
    pytorch_analysis = module.resolve_scenarios(["isolated-pytorch-playground-analysis"])[0]
    above_fold = module.resolve_scenarios(["isolated-above-fold-core-pages"])[0]
    visual_baseline = module.resolve_scenarios(["isolated-visual-baseline-core-pages"])[0]
    hf_visual_smoke = module.resolve_scenarios(["hf-first-proof-visual-smoke"])[0]
    hf_apps_pages_smoke = module.resolve_scenarios(["hf-first-proof-app-pages-visual-smoke"])[0]
    cross_browser = module.resolve_scenarios(["isolated-cross-browser-core-pages"])[0]

    assert mobile.name not in default_names
    assert evidence.name not in default_names
    assert fresh.name not in default_names
    assert first_proof.name not in default_names
    assert keyboard.name not in default_names
    assert layout_desktop.name not in default_names
    assert layout_mobile.name not in default_names
    assert accessibility.name not in default_names
    assert browser_error.name not in default_names
    assert all_builtin_orchestrate.name not in default_names
    assert pytorch_analysis.name not in default_names
    assert above_fold.name not in default_names
    assert visual_baseline.name not in default_names
    assert hf_visual_smoke.name not in default_names
    assert hf_apps_pages_smoke.name not in default_names
    assert cross_browser.name not in default_names
    assert mobile.viewport_width == 390
    assert mobile.viewport_height == 844
    assert evidence.success_screenshot is True
    assert evidence.max_first_render_seconds == 90.0
    assert evidence.max_widgets_ready_seconds == 30.0
    assert evidence.max_action_settle_seconds == 30.0
    assert fresh.fresh_browser_context_per_page is True
    assert first_proof.assert_orchestrate_artifacts is True
    assert first_proof.assert_analysis_artifacts is True
    assert keyboard.keyboard_focus_check is True
    assert layout_desktop.layout_integrity_check is True
    assert layout_desktop.viewport_width is None
    assert layout_mobile.layout_integrity_check is True
    assert layout_mobile.viewport_width == 390
    assert layout_mobile.viewport_height == 844
    assert accessibility.accessibility_check is True
    assert browser_error.browser_error_check is True
    assert all_builtin_orchestrate.pages == "ORCHESTRATE"
    assert all_builtin_orchestrate.apps_pages == "none"
    assert all_builtin_orchestrate.runtime_isolation == "isolated"
    assert all_builtin_orchestrate.action_button_policy == "trial"
    assert all_builtin_orchestrate.max_action_clicks_per_page == 0
    assert all_builtin_orchestrate.browser_error_check is True
    assert all_builtin_orchestrate.page_timeout_seconds == 120.0
    assert pytorch_analysis.apps == "pytorch_playground_project"
    assert pytorch_analysis.pages == "ANALYSIS"
    assert pytorch_analysis.required_text == "PyTorch Playground,Refresh evidence,Synced RUN snippet,Settings"
    assert pytorch_analysis.required_action_labels == "Refresh evidence"
    assert pytorch_analysis.browser_error_check is True
    assert above_fold.above_fold_check is True
    assert visual_baseline.success_screenshot is True
    assert visual_baseline.visual_mask_dynamic_regions is True
    assert visual_baseline.above_fold_check is True
    assert visual_baseline.browser_error_check is True
    assert hf_visual_smoke.success_screenshot is True
    assert hf_visual_smoke.visual_mask_dynamic_regions is True
    assert hf_visual_smoke.above_fold_check is True
    assert hf_visual_smoke.browser_error_check is True
    assert cross_browser.browser_error_check is True


def test_build_robot_command_contains_scenario_controls(tmp_path) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["current-home-actions"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        failure_bundle_dir=tmp_path / "failure-bundles",
        trace_dir=tmp_path / "traces",
        har_dir=tmp_path / "hars",
        video_dir=tmp_path / "videos",
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=True,
        browser="webkit",
        headful=True,
    )

    argv, summary_path, progress_path = module.build_robot_command(scenario, options=options)

    assert Path(argv[1]).name == "agilab_widget_robot.py"
    assert argv[argv.index("--apps") + 1] == "flight_telemetry_project"
    assert argv[argv.index("--pages") + 1] == "ORCHESTRATE"
    assert argv[argv.index("--apps-pages") + 1] == "none"
    assert argv[argv.index("--runtime-isolation") + 1] == "current-home"
    assert argv[argv.index("--action-button-policy") + 1] == "click-selected"
    assert argv[argv.index("--click-action-labels") + 1] == "CHECK distribute,Run -> Load -> Export"
    assert argv[argv.index("--preselect-labels") + 1] == "Run now"
    assert argv[argv.index("--browser") + 1] == "webkit"
    assert argv[argv.index("--screenshot-dir") + 1] == str(tmp_path / "screenshots" / "current-home-actions")
    assert argv[argv.index("--failure-bundle-dir") + 1] == str(
        tmp_path / "failure-bundles" / "current-home-actions"
    )
    assert argv[argv.index("--trace-dir") + 1] == str(tmp_path / "traces" / "current-home-actions")
    assert argv[argv.index("--har-dir") + 1] == str(tmp_path / "hars" / "current-home-actions")
    assert argv[argv.index("--video-dir") + 1] == str(tmp_path / "videos" / "current-home-actions")
    assert "--headful" in argv
    assert "--quiet-progress" in argv
    assert "--no-seed-demo-artifacts" in argv
    assert "--assert-orchestrate-artifacts" not in argv
    assert "--assert-workflow-artifacts" not in argv
    assert summary_path == tmp_path / "current-home-actions.json"
    assert progress_path == tmp_path / "current-home-actions.ndjson"


def test_build_robot_command_passes_optional_browser_artifact_dirs(tmp_path) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["isolated-project-page"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=None,
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
        trace_dir=tmp_path / "traces",
        har_dir=tmp_path / "har",
        video_dir=tmp_path / "video",
    )

    argv, _, _ = module.build_robot_command(scenario, options=options)

    assert argv[argv.index("--trace-dir") + 1] == str(tmp_path / "traces" / "isolated-project-page")
    assert argv[argv.index("--har-dir") + 1] == str(tmp_path / "har" / "isolated-project-page")
    assert argv[argv.index("--video-dir") + 1] == str(tmp_path / "video" / "isolated-project-page")


def test_options_from_args_controls_result_cache(tmp_path) -> None:
    module = _load_module()
    parser = module._build_parser()
    cache_path = tmp_path / "matrix-cache.json"

    enabled = module.options_from_args(parser.parse_args(["--result-cache-path", str(cache_path)]))
    disabled = module.options_from_args(parser.parse_args(["--no-result-cache"]))

    assert enabled.result_cache_path == cache_path
    assert disabled.result_cache_path is None


def test_build_robot_command_covers_hosted_hf_install_action(tmp_path) -> None:
    module = _load_module()
    scenario = module.ALL_SCENARIOS["hf-first-proof-install"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project,weather_forecast_project",
        output_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        timeout_seconds=90.0,
        widget_timeout_seconds=3.0,
        quiet_progress=True,
        no_seed_demo_artifacts=True,
        url="https://huggingface.co/spaces/jpmorard/agilab",
    )

    argv, summary_path, progress_path = module.build_robot_command(scenario, options=options)

    assert argv[argv.index("--apps") + 1] == "flight_telemetry_project,weather_forecast_project"
    assert argv[argv.index("--pages") + 1] == "ORCHESTRATE"
    assert argv[argv.index("--apps-pages") + 1] == "none"
    assert argv[argv.index("--action-button-policy") + 1] == "click-selected"
    assert argv[argv.index("--click-action-labels") + 1] == "INSTALL"
    assert argv[argv.index("--missing-selected-action-policy") + 1] == "fail"
    assert argv[argv.index("--action-timeout") + 1] == "600.0"
    assert argv[argv.index("--url") + 1] == "https://huggingface.co/spaces/jpmorard/agilab"
    assert "--active-app" not in argv
    assert argv[argv.index("--screenshot-dir") + 1] == str(tmp_path / "screenshots" / "hf-first-proof-install")
    assert summary_path == tmp_path / "hf-first-proof-install.json"
    assert progress_path == tmp_path / "hf-first-proof-install.ndjson"


def test_build_robot_command_passes_url_active_app_and_remote_root(tmp_path) -> None:
    module = _load_module()
    scenario = module.ALL_SCENARIOS["hf-first-proof-install"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=None,
        timeout_seconds=90.0,
        widget_timeout_seconds=3.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
        url="https://example.invalid/agilab",
        active_app="flight_telemetry_project",
        remote_app_root="/opt/agilab/apps",
    )

    argv, _, _ = module.build_robot_command(scenario, options=options)

    assert argv[argv.index("--url") + 1] == "https://example.invalid/agilab"
    assert argv[argv.index("--active-app") + 1] == "flight_telemetry_project"
    assert argv[argv.index("--remote-app-root") + 1] == "/opt/agilab/apps"


def test_build_robot_command_enables_browser_history_check(tmp_path) -> None:
    module = _load_module()
    scenario = module.ALL_SCENARIOS["isolated-browser-history"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )

    argv, summary_path, progress_path = module.build_robot_command(scenario, options=options)

    assert argv[argv.index("--pages") + 1] == "PROJECT"
    assert argv[argv.index("--action-button-policy") + 1] == "safe-click"
    assert "--browser-history-check" in argv
    assert argv[argv.index("--screenshot-dir") + 1] == str(tmp_path / "screenshots" / "isolated-browser-history")
    assert summary_path == tmp_path / "isolated-browser-history.json"
    assert progress_path == tmp_path / "isolated-browser-history.ndjson"


def test_build_robot_command_enables_mobile_viewport(tmp_path) -> None:
    module = _load_module()
    scenario = module.ALL_SCENARIOS["isolated-mobile-core-pages"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )

    argv, summary_path, progress_path = module.build_robot_command(scenario, options=options)

    assert argv[argv.index("--pages") + 1] == "PROJECT,ORCHESTRATE,ANALYSIS"
    assert argv[argv.index("--viewport-width") + 1] == "390"
    assert argv[argv.index("--viewport-height") + 1] == "844"
    assert summary_path == tmp_path / "isolated-mobile-core-pages.json"
    assert progress_path == tmp_path / "isolated-mobile-core-pages.ndjson"


def test_build_robot_command_enables_release_evidence_controls(tmp_path) -> None:
    module = _load_module()
    scenario = module.ALL_SCENARIOS["isolated-release-evidence"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )

    argv, _, _ = module.build_robot_command(scenario, options=options)

    assert "--success-screenshot" in argv
    assert argv[argv.index("--max-first-render-seconds") + 1] == "90.0"
    assert argv[argv.index("--max-widgets-ready-seconds") + 1] == "30.0"
    assert argv[argv.index("--max-action-settle-seconds") + 1] == "30.0"


def test_build_robot_command_enables_fresh_browser_context(tmp_path) -> None:
    module = _load_module()
    scenario = module.ALL_SCENARIOS["isolated-fresh-session-core-pages"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=None,
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )

    argv, _, _ = module.build_robot_command(scenario, options=options)

    assert "--fresh-browser-context-per-page" in argv


def test_build_robot_command_enables_keyboard_focus_check(tmp_path) -> None:
    module = _load_module()
    scenario = module.ALL_SCENARIOS["isolated-keyboard-focus-core-pages"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=None,
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )

    argv, _, _ = module.build_robot_command(scenario, options=options)

    assert argv[argv.index("--pages") + 1] == "HOME,PROJECT,ORCHESTRATE,WORKFLOW,ANALYSIS,SETTINGS"
    assert "--keyboard-focus-check" in argv


def test_build_robot_command_enables_layout_integrity_mobile_viewport(tmp_path) -> None:
    module = _load_module()
    scenario = module.ALL_SCENARIOS["isolated-layout-integrity-mobile"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=None,
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )

    argv, _, _ = module.build_robot_command(scenario, options=options)

    assert "--layout-integrity-check" in argv
    assert argv[argv.index("--viewport-width") + 1] == "390"
    assert argv[argv.index("--viewport-height") + 1] == "844"


def test_build_robot_command_enables_accessibility_check(tmp_path) -> None:
    module = _load_module()
    scenario = module.ALL_SCENARIOS["isolated-accessibility-core-pages"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=None,
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )

    argv, _, _ = module.build_robot_command(scenario, options=options)

    assert argv[argv.index("--pages") + 1] == "HOME,PROJECT,ORCHESTRATE,WORKFLOW,ANALYSIS,SETTINGS"
    assert "--accessibility-check" in argv


def test_build_robot_command_enables_browser_error_check(tmp_path) -> None:
    module = _load_module()
    scenario = module.ALL_SCENARIOS["isolated-browser-error-core-pages"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=None,
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )

    argv, _, _ = module.build_robot_command(scenario, options=options)

    assert argv[argv.index("--pages") + 1] == "HOME,PROJECT,ORCHESTRATE,WORKFLOW,ANALYSIS,SETTINGS"
    assert "--browser-error-check" in argv


def test_build_robot_command_covers_pytorch_playground_analysis_text(tmp_path) -> None:
    module = _load_module()
    scenario = module.ALL_SCENARIOS["isolated-pytorch-playground-analysis"]
    options = module.MatrixOptions(
        apps="all",
        output_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )

    argv, summary_path, progress_path = module.build_robot_command(scenario, options=options)

    assert argv[argv.index("--apps") + 1] == "pytorch_playground_project"
    assert argv[argv.index("--pages") + 1] == "ANALYSIS"
    assert argv[argv.index("--apps-pages") + 1] == "none"
    assert argv[argv.index("--required-text") + 1] == "PyTorch Playground,Refresh evidence,Synced RUN snippet,Settings"
    assert argv[argv.index("--required-action-labels") + 1] == "Refresh evidence"
    assert "--browser-error-check" in argv
    assert summary_path == tmp_path / "isolated-pytorch-playground-analysis.json"
    assert progress_path == tmp_path / "isolated-pytorch-playground-analysis.ndjson"


def test_build_robot_command_enables_above_fold_check(tmp_path) -> None:
    module = _load_module()
    scenario = module.ALL_SCENARIOS["isolated-above-fold-core-pages"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=None,
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )

    argv, _, _ = module.build_robot_command(scenario, options=options)

    assert argv[argv.index("--pages") + 1] == "HOME,PROJECT,ORCHESTRATE,WORKFLOW,ANALYSIS,SETTINGS"
    assert "--above-fold-check" in argv


def test_build_robot_command_enables_visual_baseline_controls(tmp_path) -> None:
    module = _load_module()
    scenario = module.ALL_SCENARIOS["isolated-visual-baseline-core-pages"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )

    argv, summary_path, progress_path = module.build_robot_command(scenario, options=options)

    assert argv[argv.index("--pages") + 1] == "HOME,PROJECT,ORCHESTRATE,WORKFLOW,ANALYSIS,SETTINGS"
    assert "--success-screenshot" in argv
    assert "--visual-mask-dynamic-regions" in argv
    assert "--above-fold-check" in argv
    assert "--browser-error-check" in argv
    assert argv[argv.index("--screenshot-dir") + 1] == str(
        tmp_path / "screenshots" / "isolated-visual-baseline-core-pages"
    )
    assert summary_path == tmp_path / "isolated-visual-baseline-core-pages.json"
    assert progress_path == tmp_path / "isolated-visual-baseline-core-pages.ndjson"


def test_build_robot_command_enables_hf_visual_smoke_controls(tmp_path) -> None:
    module = _load_module()
    scenario = module.ALL_SCENARIOS["hf-first-proof-visual-smoke"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project,weather_forecast_project",
        output_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
        url="https://huggingface.co/spaces/jpmorard/agilab",
    )

    argv, summary_path, progress_path = module.build_robot_command(scenario, options=options)

    assert argv[argv.index("--apps") + 1] == "flight_telemetry_project,weather_forecast_project"
    assert argv[argv.index("--pages") + 1] == "HOME,PROJECT,ORCHESTRATE,WORKFLOW,ANALYSIS"
    assert argv[argv.index("--url") + 1] == "https://huggingface.co/spaces/jpmorard/agilab"
    assert "--active-app" not in argv
    assert "--success-screenshot" in argv
    assert "--visual-mask-dynamic-regions" in argv
    assert "--above-fold-check" in argv
    assert "--browser-error-check" in argv
    assert summary_path == tmp_path / "hf-first-proof-visual-smoke.json"
    assert progress_path == tmp_path / "hf-first-proof-visual-smoke.ndjson"


def test_build_robot_command_enables_hf_app_pages_visual_smoke_controls(tmp_path) -> None:
    module = _load_module()
    scenario = module.ALL_SCENARIOS["hf-first-proof-app-pages-visual-smoke"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project,weather_forecast_project",
        output_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
        url="https://huggingface.co/spaces/jpmorard/agilab",
    )

    argv, summary_path, progress_path = module.build_robot_command(scenario, options=options)

    assert argv[argv.index("--apps") + 1] == "flight_telemetry_project,weather_forecast_project"
    assert argv[argv.index("--pages") + 1] == "none"
    assert argv[argv.index("--apps-pages") + 1] == "view_maps,view_forecast_analysis,view_release_decision"
    assert argv[argv.index("--url") + 1] == "https://huggingface.co/spaces/jpmorard/agilab"
    assert "--active-app" not in argv
    assert "--success-screenshot" in argv
    assert "--visual-mask-dynamic-regions" in argv
    assert "--above-fold-check" in argv
    assert "--browser-error-check" in argv
    assert summary_path == tmp_path / "hf-first-proof-app-pages-visual-smoke.json"
    assert progress_path == tmp_path / "hf-first-proof-app-pages-visual-smoke.ndjson"


def test_build_robot_command_enables_artifact_assertions_for_stateful_journey(tmp_path) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["current-home-orchestrate-journey"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=None,
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )

    argv, _, _ = module.build_robot_command(scenario, options=options)

    assert "--assert-orchestrate-artifacts" in argv


def test_build_robot_command_enables_workflow_artifact_assertions_for_core_sweep(tmp_path) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["isolated-core-pages"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=None,
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )

    argv, _, _ = module.build_robot_command(scenario, options=options)

    assert "--assert-workflow-artifacts" in argv


def test_build_robot_command_enables_first_proof_failure_evidence(tmp_path) -> None:
    module = _load_module()
    scenario = module.ALL_SCENARIOS["current-home-first-proof-golden-path"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        failure_bundle_dir=tmp_path / "failure-bundles",
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )

    argv, _, _ = module.build_robot_command(scenario, options=options)

    assert argv[argv.index("--pages") + 1] == "ORCHESTRATE,ANALYSIS"
    assert argv[argv.index("--route-query") + 1] == "first_proof_action=install"
    first_proof_actions = argv[argv.index("--click-action-labels") + 1].split(",")
    assert "INSTALL" in first_proof_actions
    assert "Run -> Load -> Export" in first_proof_actions
    assert "Load output" not in first_proof_actions
    assert "EXPORT dataframe" not in first_proof_actions
    assert "--assert-orchestrate-artifacts" in argv
    assert "--assert-analysis-artifacts" in argv
    assert "--success-screenshot" in argv
    assert argv[argv.index("--failure-bundle-dir") + 1] == str(
        tmp_path / "failure-bundles" / "current-home-first-proof-golden-path"
    )


def test_write_matrix_failure_bundle_records_scenario_evidence(tmp_path) -> None:
    module = _load_module()
    progress_path = tmp_path / "progress.ndjson"
    progress_path.write_text('{"event": "page_start"}\n{"event": "page_done"}\n', encoding="utf-8")
    scenario = module.RobotScenario(
        name="demo",
        description="demo",
        pages="HOME",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="trial",
    )
    result = module.ScenarioResult(
        scenario=scenario,
        argv=["robot", "--json"],
        returncode=1,
        duration_seconds=3.0,
        summary_path=tmp_path / "summary.json",
        progress_path=progress_path,
        summary={"success": False, "failed_count": 1},
        output="robot failed\n",
    )
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=None,
        failure_bundle_dir=tmp_path / "failure-bundles",
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )

    bundle = module._write_matrix_failure_bundle(result, options=options)

    assert bundle == tmp_path / "failure-bundles" / "demo" / "_scenario"
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == module.FAILURE_BUNDLE_SCHEMA
    assert manifest["scenario"] == "demo"
    assert manifest["returncode"] == 1
    assert manifest["command"] == ["robot", "--json"]
    assert (bundle / "summary.json").is_file()
    assert (bundle / "progress-tail.ndjson").read_text(encoding="utf-8").endswith('{"event": "page_done"}\n')


def test_write_matrix_failure_bundle_skips_when_unconfigured_or_successful(tmp_path) -> None:
    module = _load_module()
    scenario = module.RobotScenario(
        name="demo",
        description="demo",
        pages="HOME",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="trial",
    )
    result = module.ScenarioResult(
        scenario=scenario,
        argv=["robot", "--json"],
        returncode=0,
        duration_seconds=1.0,
        summary_path=tmp_path / "summary.json",
        progress_path=tmp_path / "progress.ndjson",
        summary={"success": True, "failed_count": 0},
        output="",
    )
    without_bundle_dir = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=None,
        failure_bundle_dir=None,
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )
    with_bundle_dir = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=None,
        failure_bundle_dir=tmp_path / "failure-bundles",
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )

    assert module._write_matrix_failure_bundle(result, options=without_bundle_dir) is None
    assert module._write_matrix_failure_bundle(result, options=with_bundle_dir) is None


def test_write_matrix_failure_bundle_records_artifact_retry_evidence(tmp_path) -> None:
    module = _load_module()
    progress_path = tmp_path / "progress.ndjson"
    retry_progress_path = tmp_path / "retry-progress.ndjson"
    progress_path.write_text('{"event": "page_done", "success": false}\n', encoding="utf-8")
    retry_progress_path.write_text('{"event": "page_done", "success": false}\n', encoding="utf-8")
    scenario = module.RobotScenario(
        name="demo",
        description="demo",
        pages="HOME",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="trial",
    )
    retry = module.FailureArtifactRetry(
        argv=["robot", "--trace-dir", "traces/demo"],
        returncode=1,
        duration_seconds=2.0,
        summary_path=tmp_path / "failure-retry" / "demo.json",
        progress_path=retry_progress_path,
        summary={"success": False, "failed_count": 1},
        output="retry failed\n",
        trace_dir=tmp_path / "failure-artifacts" / "traces" / "demo",
        har_dir=tmp_path / "failure-artifacts" / "har" / "demo",
        video_dir=tmp_path / "failure-artifacts" / "video" / "demo",
    )
    result = module.ScenarioResult(
        scenario=scenario,
        argv=["robot", "--json"],
        returncode=1,
        duration_seconds=3.0,
        summary_path=tmp_path / "summary.json",
        progress_path=progress_path,
        summary={"success": False, "failed_count": 1},
        output="robot failed\n",
        artifact_retry=retry,
    )
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=None,
        failure_bundle_dir=tmp_path / "failure-bundles",
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )

    bundle = module._write_matrix_failure_bundle(result, options=options)

    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    retry_payload = manifest["failure_artifact_retry"]
    assert retry_payload["returncode"] == 1
    assert retry_payload["success"] is False
    assert retry_payload["trace_dir"].endswith("failure-artifacts/traces/demo")
    assert retry_payload["har_dir"].endswith("failure-artifacts/har/demo")
    assert retry_payload["video_dir"].endswith("failure-artifacts/video/demo")
    assert retry_payload["command"] == ["robot", "--trace-dir", "traces/demo"]
    assert (bundle / "retry-summary.json").is_file()
    assert (bundle / "retry-progress-tail.ndjson").is_file()


def test_write_matrix_failure_bundle_handles_missing_optional_tails(tmp_path) -> None:
    module = _load_module()
    scenario = module.RobotScenario(
        name="demo",
        description="demo",
        pages="HOME",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="trial",
    )
    retry = module.FailureArtifactRetry(
        argv=["robot", "--trace-dir", "traces/demo"],
        returncode=1,
        duration_seconds=2.0,
        summary_path=tmp_path / "retry-summary.json",
        progress_path=tmp_path / "missing-retry-progress.ndjson",
        summary={"success": False, "failed_count": 1},
        output="",
        trace_dir=None,
        har_dir=None,
        video_dir=None,
    )
    result = module.ScenarioResult(
        scenario=scenario,
        argv=["robot", "--json"],
        returncode=1,
        duration_seconds=3.0,
        summary_path=tmp_path / "summary.json",
        progress_path=tmp_path / "missing-progress.ndjson",
        summary={"success": False, "failed_count": 1},
        output="",
        artifact_retry=retry,
    )
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        failure_bundle_dir=tmp_path / "failure-bundles",
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )
    screenshot = tmp_path / "screenshots" / "demo" / "page.png"
    screenshot.parent.mkdir(parents=True)
    screenshot.write_bytes(b"png")

    bundle = module._write_matrix_failure_bundle(result, options=options)

    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["screenshots"] == [str(screenshot)]
    assert not (bundle / "progress-tail.ndjson").exists()
    assert not (bundle / "retry-output-tail.txt").exists()
    assert not (bundle / "retry-progress-tail.ndjson").exists()


def test_build_robot_command_covers_entry_shell_and_configured_app_pages(tmp_path) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["isolated-entry-and-app-pages"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )

    argv, summary_path, progress_path = module.build_robot_command(scenario, options=options)

    assert argv[argv.index("--pages") + 1] == "none"
    assert argv[argv.index("--apps-pages") + 1] == "configured"
    assert argv[argv.index("--runtime-isolation") + 1] == "isolated"
    assert argv[argv.index("--action-button-policy") + 1] == "trial"
    assert argv[argv.index("--action-timeout") + 1] == "30.0"
    assert argv[argv.index("--max-action-clicks-per-page") + 1] == "0"
    assert argv[argv.index("--screenshot-dir") + 1] == str(
        tmp_path / "screenshots" / "isolated-entry-and-app-pages"
    )
    assert summary_path == tmp_path / "isolated-entry-and-app-pages.json"
    assert progress_path == tmp_path / "isolated-entry-and-app-pages.ndjson"


def test_build_robot_command_covers_project_page(tmp_path) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["isolated-project-page"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )

    argv, summary_path, progress_path = module.build_robot_command(scenario, options=options)

    assert argv[argv.index("--pages") + 1] == "PROJECT"
    assert argv[argv.index("--apps-pages") + 1] == "none"
    assert argv[argv.index("--runtime-isolation") + 1] == "isolated"
    assert argv[argv.index("--action-button-policy") + 1] == "safe-click"
    assert argv[argv.index("--action-timeout") + 1] == "30.0"
    assert argv[argv.index("--screenshot-dir") + 1] == str(
        tmp_path / "screenshots" / "isolated-project-page"
    )
    assert summary_path == tmp_path / "isolated-project-page.json"
    assert progress_path == tmp_path / "isolated-project-page.ndjson"


def test_build_robot_command_covers_project_notebook_import_deep_link(tmp_path) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["isolated-project-notebook-import"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )

    argv, summary_path, progress_path = module.build_robot_command(scenario, options=options)

    assert argv[argv.index("--pages") + 1] == "PROJECT"
    assert argv[argv.index("--apps-pages") + 1] == "none"
    assert argv[argv.index("--runtime-isolation") + 1] == "isolated"
    assert argv[argv.index("--action-button-policy") + 1] == "safe-click"
    assert argv[argv.index("--route-query") + 1] == "start=notebook-import"
    assert argv[argv.index("--screenshot-dir") + 1] == str(
        tmp_path / "screenshots" / "isolated-project-notebook-import"
    )
    assert summary_path == tmp_path / "isolated-project-notebook-import.json"
    assert progress_path == tmp_path / "isolated-project-notebook-import.ndjson"


def test_build_robot_command_covers_project_import_sidebar(tmp_path) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["isolated-project-import-sidebar"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )

    argv, summary_path, progress_path = module.build_robot_command(scenario, options=options)

    assert argv[argv.index("--pages") + 1] == "PROJECT"
    assert argv[argv.index("--apps-pages") + 1] == "none"
    assert argv[argv.index("--runtime-isolation") + 1] == "isolated"
    assert argv[argv.index("--action-button-policy") + 1] == "safe-click"
    assert argv[argv.index("--preselect-labels") + 1] == "Import"
    assert argv[argv.index("--screenshot-dir") + 1] == str(
        tmp_path / "screenshots" / "isolated-project-import-sidebar"
    )
    assert summary_path == tmp_path / "isolated-project-import-sidebar.json"
    assert progress_path == tmp_path / "isolated-project-import-sidebar.ndjson"


def test_build_robot_command_covers_project_rename_sidebar(tmp_path) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["isolated-project-rename-sidebar"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )

    argv, summary_path, progress_path = module.build_robot_command(scenario, options=options)

    assert argv[argv.index("--pages") + 1] == "PROJECT"
    assert argv[argv.index("--apps-pages") + 1] == "none"
    assert argv[argv.index("--runtime-isolation") + 1] == "isolated"
    assert argv[argv.index("--action-button-policy") + 1] == "safe-click"
    assert argv[argv.index("--preselect-labels") + 1] == "Rename"
    assert argv[argv.index("--screenshot-dir") + 1] == str(
        tmp_path / "screenshots" / "isolated-project-rename-sidebar"
    )
    assert summary_path == tmp_path / "isolated-project-rename-sidebar.json"
    assert progress_path == tmp_path / "isolated-project-rename-sidebar.ndjson"


def test_build_robot_command_covers_settings_page(tmp_path) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["isolated-settings-page"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )

    argv, summary_path, progress_path = module.build_robot_command(scenario, options=options)

    assert argv[argv.index("--pages") + 1] == "SETTINGS"
    assert argv[argv.index("--apps-pages") + 1] == "none"
    assert argv[argv.index("--runtime-isolation") + 1] == "isolated"
    assert argv[argv.index("--action-button-policy") + 1] == "safe-click"
    assert argv[argv.index("--action-timeout") + 1] == "30.0"
    assert argv[argv.index("--screenshot-dir") + 1] == str(
        tmp_path / "screenshots" / "isolated-settings-page"
    )
    assert summary_path == tmp_path / "isolated-settings-page.json"
    assert progress_path == tmp_path / "isolated-settings-page.ndjson"


def test_streaming_runner_keeps_child_output_on_stderr(capsys) -> None:
    module = _load_module()

    result = module._run_robot_command_streaming(
        [sys.executable, "-c", "print('child-progress'); print('{\"ok\": true}')"]
    )
    captured = capsys.readouterr()

    assert result.returncode == 0
    assert "child-progress" in result.stdout
    assert '"ok": true' in result.stdout
    assert "child-progress" not in captured.out
    assert "child-progress" in captured.err
    assert "[ui-robot-matrix] start:" in captured.err
    assert "[ui-robot-matrix] exit=0:" in captured.err


def test_load_summary_falls_back_to_stdout_json_and_default_failure(tmp_path) -> None:
    module = _load_module()

    parsed = module._load_summary(tmp_path / "missing.json", '{"success": true, "page_count": 1}')
    failed = module._load_summary(tmp_path / "missing.json", "not-json")

    assert parsed["success"] is True
    assert parsed["page_count"] == 1
    assert failed == {
        "success": False,
        "failed_count": 1,
        "skipped_count": 0,
        "page_count": 0,
        "widget_count": 0,
        "interacted_count": 0,
        "probed_count": 0,
        "error": "robot did not emit a JSON summary",
    }


def test_failure_bundle_text_helpers_cover_missing_oversize_and_read_errors(tmp_path, monkeypatch) -> None:
    module = _load_module()
    log = tmp_path / "progress.ndjson"
    log.write_text("one\ntwo\nthree\n", encoding="utf-8")

    assert module._tail_text_file(None) == ""
    assert module._tail_text_file(tmp_path / "missing.ndjson") == ""
    assert module._tail_text_file(log, lines=2) == "two\nthree\n"
    assert module._limited_text("x" * (module.FAILURE_BUNDLE_TEXT_LIMIT + 2)).endswith("...[tail truncated]\n")

    original_read_text = Path.read_text

    def _raising_read_text(self, *args, **kwargs):
        if self == log:
            raise OSError("boom")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _raising_read_text)

    assert module._tail_text_file(log) == ""


def test_path_signature_and_git_helpers_cover_error_branches(tmp_path, monkeypatch) -> None:
    module = _load_module()
    file_path = tmp_path / "payload.txt"
    file_path.write_text("payload", encoding="utf-8")
    missing_path = tmp_path / "missing.txt"

    assert module._repo_relative_or_absolute(tmp_path).startswith(str(tmp_path))
    assert module._file_signature(tmp_path)["state"] == "directory"
    assert module._file_signature(missing_path)["state"] == "missing"
    monkeypatch.setattr(module, "_file_sha256", lambda _path: (_ for _ in ()).throw(OSError("hash failed")))
    signature = module._file_signature(file_path)
    assert signature["state"] == "file"
    assert signature["sha256_error"] == "OSError"

    def _failing_git(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 2, stdout="", stderr="fatal")

    monkeypatch.setattr(module.subprocess, "run", _failing_git)

    assert module._git_head() == ""
    assert module._git_text(["git", "status"]).startswith("git-error:2:fatal")
    assert module._git_output_sha256(["git", "diff"]) == "git-error:2"


def test_status_paths_handles_short_renamed_and_duplicate_entries() -> None:
    module = _load_module()

    paths = module._status_paths('?? "new file.py"\nR  old.py -> renamed.py\n M renamed.py\nX\n')

    assert paths == ["new file.py", "renamed.py"]


def test_result_cache_load_write_prune_and_support_guards(tmp_path, monkeypatch) -> None:
    module = _load_module()
    cache_path = tmp_path / "cache.json"
    scenario = module.DEFAULT_SCENARIOS["isolated-core-pages"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path / "out",
        screenshot_dir=None,
        timeout_seconds=10.0,
        widget_timeout_seconds=1.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
        result_cache_path=cache_path,
    )

    assert module._load_result_cache(cache_path) == module._empty_result_cache()
    cache_path.write_text("{not-json", encoding="utf-8")
    assert module._load_result_cache(cache_path) == module._empty_result_cache()
    cache_path.write_text(json.dumps({"schema": "wrong", "entries": {}}), encoding="utf-8")
    assert module._load_result_cache(cache_path) == module._empty_result_cache()
    cache_path.write_text(json.dumps({"schema": module.RESULT_CACHE_SCHEMA, "entries": []}), encoding="utf-8")
    assert module._load_result_cache(cache_path) == module._empty_result_cache()

    invalid_state = {"schema": module.RESULT_CACHE_SCHEMA, "entries": []}
    module._write_result_cache(cache_path, invalid_state)
    assert json.loads(cache_path.read_text(encoding="utf-8"))["entries"] == []

    monkeypatch.setattr(module, "RESULT_CACHE_MAX_ENTRIES", 2)
    entries = {
        "old": {"stored_at": 1.0},
        "new": {"stored_at": 3.0},
        "middle": {"stored_at": 2.0},
        "bad": "not-a-dict",
    }
    module._prune_result_cache(entries)
    assert set(entries) == {"new", "middle"}

    assert module._scenario_cache_supported(scenario, options) is True
    assert module._scenario_cache_supported(scenario, module.replace(options, result_cache_path=None)) is False
    assert module._scenario_cache_supported(scenario, module.replace(options, url="https://example.invalid")) is False
    assert module._scenario_cache_supported(scenario, module.replace(options, headful=True)) is False
    assert module._scenario_cache_supported(scenario, module.replace(options, trace_dir=tmp_path / "traces")) is False
    assert module._scenario_cache_supported(
        module.replace(scenario, success_screenshot=True),
        options,
    ) is False


def test_scenario_result_cache_rejects_bad_payloads_and_writes_synthetic_progress(tmp_path) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["isolated-core-pages"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path / "out",
        screenshot_dir=None,
        timeout_seconds=10.0,
        widget_timeout_seconds=1.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
        result_cache_path=tmp_path / "cache.json",
    )

    assert module._scenario_result_from_cache("not-a-dict", scenario, options=options) is None
    assert module._scenario_result_from_cache({"scenario": "other", "returncode": 0}, scenario, options=options) is None
    assert module._scenario_result_from_cache({"scenario": scenario.name, "returncode": 1}, scenario, options=options) is None
    assert (
        module._scenario_result_from_cache(
            {"scenario": scenario.name, "returncode": 0, "summary": {"success": False}},
            scenario,
            options=options,
        )
        is None
    )

    cached = module._scenario_result_from_cache(
        {
            "scenario": scenario.name,
            "returncode": 0,
            "summary": {"success": True, "page_count": 1},
            "stored_at": 1.5,
            "progress_log": " ",
        },
        scenario,
        options=options,
    )

    assert cached is not None
    assert cached.cached is True
    assert json.loads(cached.progress_path.read_text(encoding="utf-8"))["event"] == "cached_result"


def test_cacheable_progress_log_and_store_cache_cover_rejections(tmp_path, monkeypatch) -> None:
    module = _load_module()
    missing = tmp_path / "missing.ndjson"
    empty = tmp_path / "empty.ndjson"
    filled = tmp_path / "filled.ndjson"
    empty.write_text(" \n", encoding="utf-8")
    filled.write_text('{"event":"page_done"}\n', encoding="utf-8")
    monkeypatch.setattr(module, "RESULT_CACHE_PROGRESS_LOG_LIMIT_BYTES", 1)

    assert module._cacheable_progress_log(missing) is None
    assert module._cacheable_progress_log(filled) is None

    monkeypatch.setattr(module, "RESULT_CACHE_PROGRESS_LOG_LIMIT_BYTES", 100)
    assert module._cacheable_progress_log(empty) is None

    original_read_text = Path.read_text

    def _raising_read_text(self, *args, **kwargs):
        if self == filled:
            raise OSError("boom")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _raising_read_text)
    assert module._cacheable_progress_log(filled) is None
    monkeypatch.setattr(Path, "read_text", original_read_text)

    scenario = module.DEFAULT_SCENARIOS["isolated-core-pages"]
    result = module.ScenarioResult(
        scenario=scenario,
        argv=["robot"],
        returncode=0,
        duration_seconds=0.1,
        summary_path=tmp_path / "summary.json",
        progress_path=filled,
        summary={"success": True},
        output="",
    )
    cache_state = {"schema": module.RESULT_CACHE_SCHEMA, "entries": []}

    assert module._store_scenario_result_cache(cache_state, "key", result) is True
    assert isinstance(cache_state["entries"], dict)
    assert cache_state["entries"]["key"]["progress_log"] == '{"event":"page_done"}\n'


def test_streaming_default_paths_for_scenario_and_failure_retry(tmp_path, monkeypatch) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["isolated-project-page"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path / "results",
        screenshot_dir=None,
        failure_bundle_dir=None,
        timeout_seconds=10.0,
        widget_timeout_seconds=1.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )
    calls: list[list[str]] = []

    def _fake_streaming(argv):
        calls.append(list(argv))
        summary_path = Path(argv[argv.index("--json-output") + 1])
        progress_path = Path(argv[argv.index("--progress-log") + 1])
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(
                {
                    "success": True,
                    "page_count": 1,
                    "widget_count": 1,
                    "interacted_count": 1,
                    "probed_count": 0,
                    "skipped_count": 0,
                    "failed_count": 0,
                }
            ),
            encoding="utf-8",
        )
        progress_path.write_text('{"event":"page_done"}\n', encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="")

    monkeypatch.setattr(module, "_run_robot_command_streaming", _fake_streaming)

    result = module.run_scenario(scenario, options=options)
    retry = module.run_failure_artifact_retry(scenario, options=options)
    retry_options = module._failure_artifact_retry_options(options)

    assert result.returncode == 0
    assert retry.returncode == 0
    assert len(calls) == 2
    assert retry_options.screenshot_dir == options.output_dir / "failure-artifacts" / "screenshots"
    assert retry_options.trace_dir == options.output_dir / "failure-artifacts" / "traces"
    assert retry_options.har_dir == options.output_dir / "failure-artifacts" / "har"
    assert retry_options.video_dir == options.output_dir / "failure-artifacts" / "video"


def test_run_matrix_ignores_malformed_cache_entries_and_failure_sample_limits(tmp_path, monkeypatch) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["isolated-core-pages"]
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps({"schema": module.RESULT_CACHE_SCHEMA, "entries": []}), encoding="utf-8")
    monkeypatch.setattr(module, "_result_cache_run_fingerprint", lambda: {"fingerprint": "stable"})
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path / "out",
        screenshot_dir=None,
        timeout_seconds=10.0,
        widget_timeout_seconds=1.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
        result_cache_path=cache_path,
    )

    def _runner(argv, **_kwargs):
        summary_path = Path(argv[argv.index("--json-output") + 1])
        progress_path = Path(argv[argv.index("--progress-log") + 1])
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps({"success": True, "page_count": 1}), encoding="utf-8")
        progress_path.write_text('{"event":"page_done"}\n', encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="")

    result = module.run_matrix([scenario], options=options, runner=_runner, keep_going=True)[0]

    assert result.cached is False

    pages = ["not-a-dict", {"failures": ["not-a-dict"]}]
    pages.extend(
        {
            "app": f"app-{index}",
            "page": "ORCHESTRATE",
            "failures": [{"kind": "error", "label": str(index), "detail": "broken"}],
        }
        for index in range(25)
    )
    result_with_failures = module.replace(result, returncode=1, summary={"success": False, "pages": pages})
    samples = module._failure_samples([result_with_failures], limit=3)

    assert [sample["label"] for sample in samples] == ["0", "1", "2"]


def test_run_matrix_ignores_non_mapping_cache_entries_state(tmp_path, monkeypatch) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["isolated-core-pages"]
    monkeypatch.setattr(module, "_load_result_cache", lambda _path: {"schema": module.RESULT_CACHE_SCHEMA, "entries": []})
    monkeypatch.setattr(module, "_result_cache_run_fingerprint", lambda: {"fingerprint": "stable"})
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path / "out",
        screenshot_dir=None,
        timeout_seconds=10.0,
        widget_timeout_seconds=1.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
        result_cache_path=tmp_path / "cache.json",
    )

    def _runner(argv, **_kwargs):
        summary_path = Path(argv[argv.index("--json-output") + 1])
        progress_path = Path(argv[argv.index("--progress-log") + 1])
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps({"success": True, "page_count": 1}), encoding="utf-8")
        progress_path.write_text('{"event":"page_done"}\n', encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="")

    results = module.run_matrix([scenario], options=options, runner=_runner, keep_going=True)

    assert results[0].cached is False


def test_run_matrix_aggregates_json_summaries(tmp_path) -> None:
    module = _load_module()
    scenarios = module.resolve_scenarios(["all"])
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=None,
        timeout_seconds=10.0,
        widget_timeout_seconds=1.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )
    seen: list[str] = []

    def _fake_runner(argv, **_kwargs):
        scenario_name = Path(argv[argv.index("--json-output") + 1]).stem
        seen.append(scenario_name)
        summary_path = Path(argv[argv.index("--json-output") + 1])
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(
                {
                    "success": True,
                    "app_count": 1,
                    "page_count": 2,
                    "widget_count": 5,
                    "interacted_count": 3,
                    "probed_count": 2,
                    "skipped_count": 0,
                    "failed_count": 0,
                }
            ),
            encoding="utf-8",
        )
        progress_path = Path(argv[argv.index("--progress-log") + 1])
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text(
            json.dumps({"event": "scenario_complete", "scenario": scenario_name}) + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(argv, 0, stdout="")

    results = module.run_matrix(scenarios, options=options, runner=_fake_runner, keep_going=True)
    summary = module.summarize_matrix(results)

    assert seen == [
        "isolated-core-pages",
        "isolated-entry-and-app-pages",
        "isolated-project-page",
        "isolated-project-notebook-import",
        "isolated-project-import-sidebar",
        "isolated-project-rename-sidebar",
        "isolated-settings-page",
        "current-home-actions",
        "current-home-orchestrate-journey",
    ]
    assert summary["success"] is True
    assert summary["scenario_count"] == 9
    assert summary["page_count"] == 18
    assert summary["widget_count"] == 45
    assert summary["interacted_count"] == 27
    assert summary["probed_count"] == 18
    assert summary["failed_scenarios"] == []
    assert summary["failure_samples"] == []


def test_run_matrix_reuses_cached_successful_scenario(tmp_path, monkeypatch) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["isolated-project-page"]
    monkeypatch.setattr(module, "_result_cache_run_fingerprint", lambda: {"fingerprint": "stable"})
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path / "first",
        screenshot_dir=None,
        timeout_seconds=10.0,
        widget_timeout_seconds=1.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
        result_cache_path=tmp_path / "matrix-cache.json",
    )
    seen: list[str] = []

    def _fake_runner(argv, **_kwargs):
        scenario_name = Path(argv[argv.index("--json-output") + 1]).stem
        seen.append(scenario_name)
        summary_path = Path(argv[argv.index("--json-output") + 1])
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(
                {
                    "success": True,
                    "page_count": 1,
                    "widget_count": 2,
                    "interacted_count": 1,
                    "probed_count": 1,
                    "skipped_count": 0,
                    "failed_count": 0,
                }
            ),
            encoding="utf-8",
        )
        progress_path = Path(argv[argv.index("--progress-log") + 1])
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text(
            json.dumps({"event": "scenario_complete", "scenario": scenario_name}) + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(argv, 0, stdout="")

    first_results = module.run_matrix([scenario], options=options, runner=_fake_runner, keep_going=True)
    cached_options = module.MatrixOptions(
        apps=options.apps,
        output_dir=tmp_path / "second",
        screenshot_dir=None,
        timeout_seconds=options.timeout_seconds,
        widget_timeout_seconds=options.widget_timeout_seconds,
        quiet_progress=options.quiet_progress,
        no_seed_demo_artifacts=options.no_seed_demo_artifacts,
        result_cache_path=options.result_cache_path,
    )

    def _unexpected_runner(argv, **_kwargs):
        raise AssertionError(f"cached scenario should not invoke runner: {argv}")

    cached_results = module.run_matrix([scenario], options=cached_options, runner=_unexpected_runner, keep_going=True)
    cached_summary = module.summarize_matrix(cached_results)

    assert seen == ["isolated-project-page"]
    assert first_results[0].cached is False
    assert cached_results[0].cached is True
    assert cached_results[0].duration_seconds == 0.0
    assert cached_summary["success"] is True
    assert cached_summary["cached_count"] == 1
    assert json.loads(cached_results[0].summary_path.read_text(encoding="utf-8"))["success"] is True
    progress_event = json.loads(cached_results[0].progress_path.read_text(encoding="utf-8"))
    assert progress_event["event"] == "scenario_complete"
    assert progress_event["scenario"] == "isolated-project-page"


def test_run_matrix_does_not_cache_failed_scenario(tmp_path) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["isolated-project-page"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=None,
        timeout_seconds=10.0,
        widget_timeout_seconds=1.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
        result_cache_path=tmp_path / "matrix-cache.json",
    )
    calls = 0

    def _failing_runner(argv, **_kwargs):
        nonlocal calls
        calls += 1
        summary_path = Path(argv[argv.index("--json-output") + 1])
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(
                {
                    "success": False,
                    "page_count": 1,
                    "widget_count": 1,
                    "interacted_count": 0,
                    "probed_count": 0,
                    "skipped_count": 0,
                    "failed_count": 1,
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(argv, 1, stdout="")

    first_results = module.run_matrix([scenario], options=options, runner=_failing_runner, keep_going=True)
    second_results = module.run_matrix([scenario], options=options, runner=_failing_runner, keep_going=True)

    assert calls == 2
    assert first_results[0].cached is False
    assert second_results[0].cached is False
    assert not options.result_cache_path.exists()


def test_run_scenario_retries_failed_scenario_with_artifacts(tmp_path) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["isolated-project-page"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path / "results",
        screenshot_dir=tmp_path / "screenshots",
        failure_bundle_dir=tmp_path / "results" / "failure-bundles",
        timeout_seconds=10.0,
        widget_timeout_seconds=1.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
        retry_failed_with_artifacts=True,
        retry_trace_dir=tmp_path / "retry" / "traces",
        retry_har_dir=tmp_path / "retry" / "har",
        retry_video_dir=tmp_path / "retry" / "video",
    )
    calls: list[list[str]] = []

    def _runner(argv, **_kwargs):
        calls.append(list(argv))
        summary_path = Path(argv[argv.index("--json-output") + 1])
        progress_path = Path(argv[argv.index("--progress-log") + 1])
        is_retry = "failure-retry" in summary_path.parts
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(
                {
                    "success": is_retry,
                    "page_count": 1,
                    "widget_count": 1,
                    "interacted_count": 0,
                    "probed_count": 1,
                    "skipped_count": 0,
                    "failed_count": 0 if is_retry else 1,
                }
            ),
            encoding="utf-8",
        )
        progress_path.write_text(
            json.dumps(
                {
                    "event": "page_done",
                    "scenario": scenario.name,
                    "success": is_retry,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(argv, 0 if is_retry else 1, stdout="")

    result = module.run_scenario(scenario, options=options, runner=_runner)
    summary = module.summarize_matrix([result])

    assert len(calls) == 2
    retry_argv = calls[1]
    assert retry_argv[retry_argv.index("--json-output") + 1].endswith(
        "failure-retry/isolated-project-page.json"
    )
    assert retry_argv[retry_argv.index("--trace-dir") + 1] == str(
        tmp_path / "retry" / "traces" / "isolated-project-page"
    )
    assert retry_argv[retry_argv.index("--har-dir") + 1] == str(
        tmp_path / "retry" / "har" / "isolated-project-page"
    )
    assert retry_argv[retry_argv.index("--video-dir") + 1] == str(
        tmp_path / "retry" / "video" / "isolated-project-page"
    )
    assert result.returncode == 1
    assert result.artifact_retry is not None
    assert result.artifact_retry.returncode == 0
    assert summary["success"] is False
    assert summary["failure_artifact_retry_count"] == 1
    assert summary["failure_artifact_retry_passed_count"] == 1
    assert summary["scenarios"][0]["failure_artifact_retry"]["success"] is True
    manifest = json.loads(
        (
            tmp_path
            / "results"
            / "failure-bundles"
            / "isolated-project-page"
            / "_scenario"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["failure_artifact_retry"]["success"] is True


def test_run_matrix_fail_fast_stops_on_first_failed_scenario(tmp_path) -> None:
    module = _load_module()
    scenarios = module.resolve_scenarios(["all"])
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=None,
        timeout_seconds=10.0,
        widget_timeout_seconds=1.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
    )
    seen: list[str] = []

    def _fake_runner(argv, **_kwargs):
        scenario_name = Path(argv[argv.index("--json-output") + 1]).stem
        seen.append(scenario_name)
        summary_path = Path(argv[argv.index("--json-output") + 1])
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(
                {
                    "success": False,
                    "page_count": 1,
                    "widget_count": 1,
                    "interacted_count": 0,
                    "probed_count": 0,
                    "skipped_count": 0,
                    "failed_count": 1,
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(argv, 1, stdout="")

    results = module.run_matrix(scenarios, options=options, runner=_fake_runner, keep_going=False)
    summary = module.summarize_matrix(results)

    assert seen == ["isolated-core-pages"]
    assert summary["success"] is False
    assert summary["failed_scenarios"] == ["isolated-core-pages"]


def test_run_matrix_reuses_cached_successful_result_with_progress_log(tmp_path, monkeypatch) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["isolated-core-pages"]
    cache_path = tmp_path / "cache.json"
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path / "out",
        screenshot_dir=None,
        timeout_seconds=10.0,
        widget_timeout_seconds=1.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
        result_cache_path=cache_path,
    )
    progress_log = (
        '{"event":"page_done","app":"flight_telemetry_project","page":"ORCHESTRATE",'
        '"status":"passed","success":true,"duration_seconds":1.0}\n'
    )
    monkeypatch.setattr(module, "_result_cache_run_fingerprint", lambda: {"fingerprint": "stable"})
    seen: list[str] = []

    def _fake_runner(argv, **_kwargs):
        seen.append("run")
        summary_path = Path(argv[argv.index("--json-output") + 1])
        progress_path = Path(argv[argv.index("--progress-log") + 1])
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(
                {
                    "success": True,
                    "app_count": 1,
                    "page_count": 1,
                    "widget_count": 2,
                    "interacted_count": 1,
                    "probed_count": 1,
                    "skipped_count": 0,
                    "failed_count": 0,
                }
            ),
            encoding="utf-8",
        )
        progress_path.write_text(progress_log, encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="")

    first = module.run_matrix([scenario], options=options, runner=_fake_runner, keep_going=True)
    second = module.run_matrix(
        [scenario],
        options=options,
        runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cache miss")),
        keep_going=True,
    )
    summary = module.summarize_matrix(second)

    assert seen == ["run"]
    assert first[0].cached is False
    assert second[0].cached is True
    assert second[0].progress_path.read_text(encoding="utf-8") == progress_log
    assert summary["cached_count"] == 1
    assert summary["scenarios"][0]["cached"] is True


def test_run_matrix_cache_key_invalidates_when_source_fingerprint_changes(tmp_path, monkeypatch) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["isolated-core-pages"]
    cache_path = tmp_path / "cache.json"
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path / "out",
        screenshot_dir=None,
        timeout_seconds=10.0,
        widget_timeout_seconds=1.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
        result_cache_path=cache_path,
    )
    fingerprints = iter([{"fingerprint": "a"}, {"fingerprint": "b"}])
    monkeypatch.setattr(module, "_result_cache_run_fingerprint", lambda: next(fingerprints))
    seen: list[str] = []

    def _fake_runner(argv, **_kwargs):
        seen.append(Path(argv[argv.index("--json-output") + 1]).stem)
        summary_path = Path(argv[argv.index("--json-output") + 1])
        progress_path = Path(argv[argv.index("--progress-log") + 1])
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(
                {
                    "success": True,
                    "page_count": 1,
                    "widget_count": 1,
                    "interacted_count": 1,
                    "probed_count": 0,
                    "skipped_count": 0,
                    "failed_count": 0,
                }
            ),
            encoding="utf-8",
        )
        progress_path.write_text(
            '{"event":"page_done","app":"flight_telemetry_project","page":"ORCHESTRATE",'
            '"status":"passed","success":true,"duration_seconds":1.0}\n',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(argv, 0, stdout="")

    first = module.run_matrix([scenario], options=options, runner=_fake_runner, keep_going=True)
    second = module.run_matrix([scenario], options=options, runner=_fake_runner, keep_going=True)

    assert seen == ["isolated-core-pages", "isolated-core-pages"]
    assert first[0].cached is False
    assert second[0].cached is False


def test_run_matrix_does_not_cache_failed_or_progressless_results(tmp_path, monkeypatch) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["isolated-core-pages"]
    cache_path = tmp_path / "cache.json"
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path / "out",
        screenshot_dir=None,
        timeout_seconds=10.0,
        widget_timeout_seconds=1.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
        result_cache_path=cache_path,
    )
    monkeypatch.setattr(module, "_result_cache_run_fingerprint", lambda: {"fingerprint": "stable"})

    def _failed_runner(argv, **_kwargs):
        summary_path = Path(argv[argv.index("--json-output") + 1])
        progress_path = Path(argv[argv.index("--progress-log") + 1])
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(
                {
                    "success": False,
                    "page_count": 1,
                    "widget_count": 1,
                    "interacted_count": 0,
                    "probed_count": 1,
                    "skipped_count": 0,
                    "failed_count": 1,
                }
            ),
            encoding="utf-8",
        )
        progress_path.write_text(
            '{"event":"page_done","app":"flight_telemetry_project","page":"ORCHESTRATE",'
            '"status":"failed","success":false,"duration_seconds":1.0}\n',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(argv, 1, stdout="")

    module.run_matrix([scenario], options=options, runner=_failed_runner, keep_going=True)

    assert not cache_path.exists()

    progressless_options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path / "out-progressless",
        screenshot_dir=None,
        timeout_seconds=10.0,
        widget_timeout_seconds=1.0,
        quiet_progress=True,
        no_seed_demo_artifacts=False,
        result_cache_path=cache_path,
    )

    def _progressless_runner(argv, **_kwargs):
        summary_path = Path(argv[argv.index("--json-output") + 1])
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(
                {
                    "success": True,
                    "page_count": 1,
                    "widget_count": 1,
                    "interacted_count": 1,
                    "probed_count": 0,
                    "skipped_count": 0,
                    "failed_count": 0,
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(argv, 0, stdout="")

    module.run_matrix([scenario], options=progressless_options, runner=_progressless_runner, keep_going=True)

    assert not cache_path.exists()


def test_summarize_matrix_reports_failure_samples(tmp_path) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["current-home-orchestrate-journey"]
    result = module.ScenarioResult(
        scenario=scenario,
        argv=["robot"],
        returncode=1,
        duration_seconds=1.0,
        summary_path=tmp_path / "summary.json",
        progress_path=tmp_path / "progress.ndjson",
        summary={
            "success": False,
            "page_count": 1,
            "widget_count": 3,
            "interacted_count": 1,
            "probed_count": 1,
            "skipped_count": 0,
            "failed_count": 1,
            "pages": [
                {
                    "app": "flight_telemetry_project",
                    "page": "ORCHESTRATE",
                    "failures": [
                        {
                            "kind": "button",
                            "label": "Run -> Load -> Export",
                            "detail": "AGI execution failed.",
                        }
                    ],
                }
            ],
        },
        output="",
    )

    summary = module.summarize_matrix([result])

    assert summary["success"] is False
    assert summary["failed_scenarios"] == ["current-home-orchestrate-journey"]
    assert summary["failure_samples"] == [
        {
            "scenario": "current-home-orchestrate-journey",
            "app": "flight_telemetry_project",
            "page": "ORCHESTRATE",
            "kind": "button",
            "label": "Run -> Load -> Export",
            "detail": "AGI execution failed.",
        }
    ]


def test_main_print_only_json_lists_commands(tmp_path, capsys) -> None:
    module = _load_module()

    exit_code = module.main(
        [
            "--scenario",
            "current-home-actions",
            "--apps",
            "flight_telemetry_project",
            "--output-dir",
            str(tmp_path),
            "--print-only",
            "--json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == module.SCHEMA
    assert len(payload["commands"]) == 1
    command = payload["commands"][0]
    assert command["scenario"]["name"] == "current-home-actions"
    assert command["summary_path"] == str(tmp_path / "current-home-actions.json")
    assert command["argv"][command["argv"].index("--apps") + 1] == "flight_telemetry_project"


def test_main_print_only_text_lists_commands(tmp_path, capsys) -> None:
    module = _load_module()

    exit_code = module.main(
        [
            "--scenario",
            "current-home-actions",
            "--apps",
            "flight_telemetry_project",
            "--output-dir",
            str(tmp_path),
            "--print-only",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "current-home-actions:" in output
    assert "flight_telemetry_project" in output


def test_render_human_reports_artifact_retry_status() -> None:
    module = _load_module()

    output = module.render_human(
        {
            "success": False,
            "scenario_count": 1,
            "page_count": 1,
            "widget_count": 2,
            "interacted_count": 0,
            "probed_count": 2,
            "skipped_count": 0,
            "failed_count": 1,
            "cached_count": 0,
            "failure_artifact_retry_count": 1,
            "scenarios": [
                {
                    "name": "demo",
                    "success": False,
                    "cached": False,
                    "page_count": 1,
                    "widget_count": 2,
                    "failed_count": 1,
                    "summary_path": "demo.json",
                    "failure_artifact_retry": {"success": False},
                }
            ],
        }
    )

    assert "artifact_retries=1" in output
    assert "artifact-retry=FAIL" in output


def test_main_json_and_text_outputs_use_matrix_results(monkeypatch, tmp_path, capsys) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["current-home-actions"]

    def _result(success: bool) -> module.ScenarioResult:
        return module.ScenarioResult(
            scenario=scenario,
            argv=["robot"],
            returncode=0 if success else 1,
            duration_seconds=0.1,
            summary_path=tmp_path / "summary.json",
            progress_path=tmp_path / "progress.ndjson",
            summary={
                "success": success,
                "page_count": 1,
                "widget_count": 1,
                "interacted_count": int(success),
                "probed_count": 1,
                "skipped_count": 0,
                "failed_count": 0 if success else 1,
            },
            output="",
        )

    monkeypatch.setattr(module, "run_matrix", lambda *_args, **_kwargs: [_result(True)])
    assert module.main(["--scenario", "current-home-actions", "--output-dir", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["success"] is True

    monkeypatch.setattr(module, "run_matrix", lambda *_args, **_kwargs: [_result(False)])
    assert module.main(["--scenario", "current-home-actions", "--output-dir", str(tmp_path)]) == 1
    assert "[FAIL] widget robot matrix" in capsys.readouterr().out
