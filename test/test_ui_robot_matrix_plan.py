from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PLAN_MODULE_PATH = Path("tools/testing/ui_robot_matrix_plan.py").resolve()
MATRIX_MODULE_PATH = Path("tools/agilab_widget_robot_matrix.py").resolve()
EXPECTED_WORKFLOW_SCENARIOS = {
    "isolated-core-pages",
    "isolated-entry-and-app-pages",
    "isolated-project-page",
    "isolated-project-editor-page",
    "isolated-project-notebook-import",
    "isolated-project-import-sidebar",
    "isolated-project-rename-sidebar",
    "isolated-settings-page",
    "isolated-all-builtins-orchestrate-smoke",
    "isolated-execution-pandas-orchestrate-pool-executor",
    "isolated-all-builtins-core-render-smoke",
    "isolated-fresh-session-core-pages",
    "isolated-browser-history",
    "isolated-browser-error-core-pages",
    "isolated-pytorch-playground-analysis",
    "isolated-release-evidence",
    "isolated-above-fold-core-pages",
    "isolated-keyboard-focus-core-pages",
    "isolated-accessibility-core-pages",
    "isolated-layout-integrity-desktop",
    "isolated-mobile-core-pages",
    "isolated-layout-integrity-mobile",
}


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _scenario_names(plan) -> list[str]:
    return [
        scenario
        for shard in plan["matrix"]["include"]
        for scenario in str(shard["scenarios"]).split()
    ]


def _page_count(raw_pages: str) -> int:
    if raw_pages == "none":
        return 0
    return len([item for item in raw_pages.split(",") if item.strip()])


def test_current_all_app_plan_is_complete_bounded_and_deterministic() -> None:
    planner = _load_module("ui_robot_matrix_plan_test_module", PLAN_MODULE_PATH)
    matrix = _load_module("ui_robot_matrix_plan_matrix_module", MATRIX_MODULE_PATH)

    plan = planner.build_plan()
    filesystem_apps = sorted(
        path.name
        for path in planner.DEFAULT_APPS_ROOT.glob("*_project")
        if path.is_dir()
    )
    shards = plan["matrix"]["include"]

    assert filesystem_apps == [
        "data_quality_gate_project",
        "execution_pandas_project",
        "execution_polars_project",
        "flight_telemetry_project",
        "minimal_app_project",
        "mission_decision_project",
        "multi_app_dag_project",
        "pytorch_playground_project",
        "r_runtime_bridge_project",
        "sklearn_pipeline_project",
        "tescia_diagnostic_project",
        "uav_queue_project",
        "uav_relay_queue_project",
        "weather_forecast_project",
    ]
    assert plan["apps"] == filesystem_apps
    assert plan["app_count"] == 14
    assert plan["shard_count"] == 34
    assert plan["estimated_page_count"] == 951
    assert plan["max_estimated_pages"] == 32
    assert max(int(shard["estimated_pages"]) for shard in shards) <= 32
    assert plan["expected_shards"] == [str(shard["shard"]) for shard in shards]

    planned_scenarios = set(_scenario_names(plan))
    configured_scenarios = {
        *planner.CORE_SCENARIOS,
        *planner.STATE_MOBILE_SCENARIOS,
        *planner.QUALITY_SCENARIOS,
        *planner.LAYOUT_SCENARIOS,
        *(scenario for scenario, _app in planner.FOCUSED_SCENARIOS),
    }
    assert configured_scenarios == EXPECTED_WORKFLOW_SCENARIOS
    assert planned_scenarios == EXPECTED_WORKFLOW_SCENARIOS
    assert planned_scenarios <= set(matrix.ALL_SCENARIOS)
    assert sum(_page_count(matrix.ALL_SCENARIOS[name].pages) for name in planner.CORE_SCENARIOS) == 12
    assert (
        sum(_page_count(matrix.ALL_SCENARIOS[name].pages) for name in planner.STATE_MOBILE_SCENARIOS)
        == 9
    )
    assert sum(_page_count(matrix.ALL_SCENARIOS[name].pages) for name in planner.QUALITY_SCENARIOS) == 32
    assert sum(_page_count(matrix.ALL_SCENARIOS[name].pages) for name in planner.LAYOUT_SCENARIOS) == 14

    prefix_scenarios = {
        "core": planner.CORE_SCENARIOS,
        "state-mobile": planner.STATE_MOBILE_SCENARIOS,
        "quality": planner.QUALITY_SCENARIOS,
        "layout": planner.LAYOUT_SCENARIOS,
    }
    for prefix, scenarios in prefix_scenarios.items():
        covered_apps = [
            app
            for shard in shards
            if str(shard["shard"]).startswith(f"{prefix}-")
            for app in str(shard["apps"]).split(",")
        ]
        assert sorted(covered_apps) == filesystem_apps
        assert len(covered_apps) == len(set(covered_apps))
        for scenario in scenarios:
            assert _scenario_names(plan).count(scenario) == len(
                [shard for shard in shards if str(shard["shard"]).startswith(f"{prefix}-")]
            )

    for scenario, _app in planner.FOCUSED_SCENARIOS:
        assert _scenario_names(plan).count(scenario) == 1


def test_subset_plan_excludes_unrequested_apps_and_focused_overrides() -> None:
    planner = _load_module("ui_robot_matrix_plan_subset_module", PLAN_MODULE_PATH)

    plan = planner.build_plan(
        requested_apps="pytorch_playground,flight_telemetry_project"
    )
    selected = {"flight_telemetry_project", "pytorch_playground_project"}
    shards = plan["matrix"]["include"]
    focused = next(shard for shard in shards if shard["shard"] == "focused")

    assert plan["apps"] == sorted(selected)
    assert all(set(str(shard["apps"]).split(",")) <= selected for shard in shards)
    assert focused["scenarios"] == "isolated-pytorch-playground-analysis"
    assert "execution_pandas_project" not in focused["apps"]
    assert _scenario_names(plan).count("isolated-pytorch-playground-analysis") == 1
    assert "isolated-execution-pandas-orchestrate-pool-executor" not in _scenario_names(plan)


def test_plan_rejects_unknown_empty_and_overweight_inventory(tmp_path: Path) -> None:
    planner = _load_module("ui_robot_matrix_plan_errors_module", PLAN_MODULE_PATH)
    apps_root = tmp_path / "builtin"
    app_dir = apps_root / "demo_project" / "src"
    app_dir.mkdir(parents=True)
    (app_dir / "app_settings.toml").write_text(
        "[pages]\nview_module = [\"view_a\", \"view_b\"]\n",
        encoding="utf-8",
    )

    assert planner.configured_apps_page_count(app_dir.parent) == 2
    with pytest.raises(ValueError, match="unknown built-in app"):
        planner.build_plan(requested_apps="missing", apps_root=apps_root)
    with pytest.raises(ValueError, match="no built-in apps"):
        planner.build_plan(apps_root=tmp_path / "empty")
    with pytest.raises(ValueError, match="maximum is 10 pages"):
        planner.build_plan(apps_root=apps_root, max_estimated_pages=10)


def test_plan_cli_writes_compact_json_and_github_outputs(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    planner = _load_module("ui_robot_matrix_plan_cli_module", PLAN_MODULE_PATH)
    output = tmp_path / "plan.json"
    github_output = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))

    exit_code = planner.main(
        [
            "--apps",
            "flight_telemetry_project",
            "--output",
            str(output),
            "--github-output",
            "--compact",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    outputs = dict(
        line.split("=", 1)
        for line in github_output.read_text(encoding="utf-8").splitlines()
    )
    assert exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8")) == payload
    assert json.loads(outputs["matrix"]) == payload["matrix"]
    assert outputs["expected_apps"] == "flight_telemetry_project"
    assert outputs["expected_shards"] == ",".join(payload["expected_shards"])
