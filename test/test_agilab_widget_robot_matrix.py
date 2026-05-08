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
        "current-home-actions",
    ]
    isolated, current_home = scenarios
    assert isolated.pages == "ORCHESTRATE,WORKFLOW,ANALYSIS"
    assert isolated.runtime_isolation == "isolated"
    assert isolated.action_button_policy == "trial"
    assert current_home.pages == "ORCHESTRATE"
    assert current_home.runtime_isolation == "current-home"
    assert current_home.action_button_policy == "click-selected"
    assert current_home.click_action_labels == "CHECK distribute,Run -> Load -> Export"
    assert current_home.preselect_labels == "Run now"
    assert current_home.missing_selected_action_policy == "ignore-absent"


def test_build_robot_command_contains_scenario_controls(tmp_path) -> None:
    module = _load_module()
    scenario = module.DEFAULT_SCENARIOS["current-home-actions"]
    options = module.MatrixOptions(
        apps="flight_project",
        output_dir=tmp_path,
        timeout_seconds=12.0,
        widget_timeout_seconds=2.0,
        quiet_progress=True,
        no_seed_demo_artifacts=True,
        browser="webkit",
        headful=True,
    )

    argv, summary_path, progress_path = module.build_robot_command(scenario, options=options)

    assert Path(argv[1]).name == "agilab_widget_robot.py"
    assert argv[argv.index("--apps") + 1] == "flight_project"
    assert argv[argv.index("--pages") + 1] == "ORCHESTRATE"
    assert argv[argv.index("--apps-pages") + 1] == "none"
    assert argv[argv.index("--runtime-isolation") + 1] == "current-home"
    assert argv[argv.index("--action-button-policy") + 1] == "click-selected"
    assert argv[argv.index("--click-action-labels") + 1] == "CHECK distribute,Run -> Load -> Export"
    assert argv[argv.index("--preselect-labels") + 1] == "Run now"
    assert argv[argv.index("--browser") + 1] == "webkit"
    assert "--headful" in argv
    assert "--quiet-progress" in argv
    assert "--no-seed-demo-artifacts" in argv
    assert summary_path == tmp_path / "current-home-actions.json"
    assert progress_path == tmp_path / "current-home-actions.ndjson"


def test_run_matrix_aggregates_json_summaries(tmp_path) -> None:
    module = _load_module()
    scenarios = module.resolve_scenarios(["all"])
    options = module.MatrixOptions(
        apps="flight_project",
        output_dir=tmp_path,
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

    assert seen == ["isolated-core-pages", "current-home-actions"]
    assert summary["success"] is True
    assert summary["scenario_count"] == 2
    assert summary["page_count"] == 4
    assert summary["widget_count"] == 10
    assert summary["interacted_count"] == 6
    assert summary["probed_count"] == 4
    assert summary["failed_scenarios"] == []


def test_run_matrix_fail_fast_stops_on_first_failed_scenario(tmp_path) -> None:
    module = _load_module()
    scenarios = module.resolve_scenarios(["all"])
    options = module.MatrixOptions(
        apps="flight_project",
        output_dir=tmp_path,
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


def test_main_print_only_json_lists_commands(tmp_path, capsys) -> None:
    module = _load_module()

    exit_code = module.main(
        [
            "--scenario",
            "current-home-actions",
            "--apps",
            "flight_project",
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
    assert command["argv"][command["argv"].index("--apps") + 1] == "flight_project"
