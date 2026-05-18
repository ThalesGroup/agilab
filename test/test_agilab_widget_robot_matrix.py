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
    assert entry.pages == "HOME"
    assert entry.apps_pages == "configured"
    assert entry.runtime_isolation == "isolated"
    assert entry.action_button_policy == "safe-click"
    assert entry.action_timeout_seconds == 30.0
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
    assert "hf-flight-telemetry-install" not in [scenario.name for scenario in scenarios]


def test_opt_in_browser_history_scenario_is_not_part_of_default_all() -> None:
    module = _load_module()

    default_scenarios = module.resolve_scenarios(["all"])
    history = module.resolve_scenarios(["isolated-browser-history"])[0]

    assert "isolated-browser-history" not in [scenario.name for scenario in default_scenarios]
    assert history.name == "isolated-browser-history"
    assert history.pages == "PROJECT"
    assert history.apps_pages == "none"
    assert history.runtime_isolation == "isolated"
    assert history.action_button_policy == "safe-click"
    assert history.browser_history_check is True


def test_opt_in_hf_install_scenario_is_not_part_of_default_all() -> None:
    module = _load_module()

    default_scenarios = module.resolve_scenarios(["all"])
    hf_scenario = module.resolve_scenarios(["hf-flight-telemetry-install"])[0]

    assert "hf-flight-telemetry-install" not in [scenario.name for scenario in default_scenarios]
    assert hf_scenario.name == "hf-flight-telemetry-install"
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

    assert mobile.name not in default_names
    assert evidence.name not in default_names
    assert fresh.name not in default_names
    assert first_proof.name not in default_names
    assert mobile.viewport_width == 390
    assert mobile.viewport_height == 844
    assert evidence.success_screenshot is True
    assert evidence.max_first_render_seconds == 90.0
    assert evidence.max_widgets_ready_seconds == 30.0
    assert evidence.max_action_settle_seconds == 30.0
    assert fresh.fresh_browser_context_per_page is True
    assert first_proof.assert_orchestrate_artifacts is True
    assert first_proof.assert_analysis_artifacts is True


def test_build_robot_command_contains_scenario_controls(tmp_path) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["current-home-actions"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
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
    assert "--headful" in argv
    assert "--quiet-progress" in argv
    assert "--no-seed-demo-artifacts" in argv
    assert "--assert-orchestrate-artifacts" not in argv
    assert "--assert-workflow-artifacts" not in argv
    assert summary_path == tmp_path / "current-home-actions.json"
    assert progress_path == tmp_path / "current-home-actions.ndjson"


def test_build_robot_command_covers_hosted_hf_install_action(tmp_path) -> None:
    module = _load_module()
    scenario = module.ALL_SCENARIOS["hf-flight-telemetry-install"]
    options = module.MatrixOptions(
        apps="flight_telemetry_project",
        output_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        timeout_seconds=90.0,
        widget_timeout_seconds=3.0,
        quiet_progress=True,
        no_seed_demo_artifacts=True,
        url="https://huggingface.co/spaces/jpmorard/agilab?active_app=flight_telemetry_project",
        active_app="flight_telemetry_project",
    )

    argv, summary_path, progress_path = module.build_robot_command(scenario, options=options)

    assert argv[argv.index("--apps") + 1] == "flight_telemetry_project"
    assert argv[argv.index("--pages") + 1] == "ORCHESTRATE"
    assert argv[argv.index("--apps-pages") + 1] == "none"
    assert argv[argv.index("--action-button-policy") + 1] == "click-selected"
    assert argv[argv.index("--click-action-labels") + 1] == "INSTALL"
    assert argv[argv.index("--missing-selected-action-policy") + 1] == "fail"
    assert argv[argv.index("--action-timeout") + 1] == "600.0"
    assert argv[argv.index("--url") + 1] == "https://huggingface.co/spaces/jpmorard/agilab?active_app=flight_telemetry_project"
    assert argv[argv.index("--active-app") + 1] == "flight_telemetry_project"
    assert argv[argv.index("--screenshot-dir") + 1] == str(tmp_path / "screenshots" / "hf-flight-telemetry-install")
    assert summary_path == tmp_path / "hf-flight-telemetry-install.json"
    assert progress_path == tmp_path / "hf-flight-telemetry-install.ndjson"


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

    assert argv[argv.index("--pages") + 1] == "HOME"
    assert argv[argv.index("--apps-pages") + 1] == "configured"
    assert argv[argv.index("--runtime-isolation") + 1] == "isolated"
    assert argv[argv.index("--action-button-policy") + 1] == "safe-click"
    assert argv[argv.index("--action-timeout") + 1] == "30.0"
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
