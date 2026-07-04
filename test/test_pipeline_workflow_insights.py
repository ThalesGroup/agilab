from __future__ import annotations

import importlib
import json
import os
from pathlib import Path


insights = importlib.import_module("agilab.pipeline_workflow_insights")


def test_workflow_cockpit_model_scores_data_models_and_waits(tmp_path: Path) -> None:
    data_root = tmp_path / "localshare" / "agi"
    input_dir = data_root / "flight_trajectory" / "pipeline"
    output_dir = data_root / "network_sim" / "pipeline"
    model_dir = data_root / "sb3_trainer" / "pipeline"
    input_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    model_dir.mkdir(parents=True)
    (input_dir / "traj.parquet").write_text("data", encoding="utf-8")
    (output_dir / "summary.json").write_text("{}", encoding="utf-8")
    model_path = model_dir / "policy.pkl"
    model_path.write_text("model", encoding="utf-8")
    model_path.with_suffix(".json").write_text(
        json.dumps({"sklearn_version": "1.9.0", "n_features_in_": 42}),
        encoding="utf-8",
    )
    stages = [
        {
            "id": "flight_export",
            "data_out": "flight_trajectory/pipeline/traj.parquet",
            "automation": {"outputs": ["flight_trajectory/pipeline/traj.parquet"]},
        },
        {
            "id": "network_build",
            "deps": ["flight_export"],
            "C": "AGI.run(data_in='flight_trajectory/pipeline/traj.parquet', data_out='network_sim/pipeline/summary.json')",
        },
    ]

    model = insights.build_workflow_cockpit_model(
        stages=stages,
        sequence=[0, 1],
        waves=[[0], [1]],
        stage_ids={0: "flight_export", 1: "network_build"},
        stage_deps={"flight_export": [], "network_build": ["flight_export"]},
        roots=[data_root],
        manifest={"status": "success", "outputs": [{"exists": True, "sha256": "abc"}]},
        pandas_paths=[],
    )

    assert model["quality"]["waits"][1]["waits_for"] == ["flight_export"]
    assert model["data"]["missing"] == 0
    assert any(item["metadata_status"] == "versioned" for item in model["models"])
    assert model["evidence"]["score"] >= 85
    assert model["evidence"]["label"] == "strong"


def test_workflow_cockpit_model_reports_missing_data_and_pandas_risks(tmp_path: Path) -> None:
    source = tmp_path / "page.py"
    source.write_text(
        "import pandas as pd\n"
        "df.drop(columns=['x'], inplace=True)\n"
        "df[df.a > 1]['b'] = 2\n",
        encoding="utf-8",
    )
    stages = [
        {
            "id": "needs_data",
            "data_in": "missing/input.parquet",
            "C": "AGI.run(data_out='generated/output.parquet')",
        }
    ]

    model = insights.build_workflow_cockpit_model(
        stages=stages,
        sequence=[0],
        waves=[[0]],
        stage_ids={0: "needs_data"},
        stage_deps={"needs_data": []},
        roots=[tmp_path],
        manifest=None,
        pandas_paths=[source],
    )

    assert model["data"]["missing"] == 2
    assert "Generate or select upstream input artifacts" in model["data"]["recommendations"][0]
    assert model["pandas"]["by_kind"]["inplace"] == 1
    assert model["pandas"]["by_kind"]["chained-assignment"] == 1
    assert "Run the workflow once" in model["evidence"]["gaps"][0]


def test_autopilot_preflight_blocks_missing_inputs_and_reuses_cached_outputs(tmp_path: Path) -> None:
    data_root = tmp_path / "localshare" / "agi"
    cached_output = data_root / "flight_trajectory" / "pipeline" / "traj.parquet"
    cached_output.parent.mkdir(parents=True)
    cached_output.write_text("cached", encoding="utf-8")
    stages = [
        {
            "id": "flight_export",
            "data_out": "flight_trajectory/pipeline/traj.parquet",
        },
        {
            "id": "network_build",
            "deps": ["flight_export"],
            "data_in": "network_sim/dataset/link_metrics.parquet",
            "data_out": "network_sim/pipeline/summary.json",
        },
    ]

    model = insights.build_workflow_cockpit_model(
        stages=stages,
        sequence=[0, 1],
        waves=[[0], [1]],
        stage_ids={0: "flight_export", 1: "network_build"},
        stage_deps={"flight_export": [], "network_build": ["flight_export"]},
        roots=[data_root],
        manifest=None,
        pandas_paths=[],
    )

    autopilot = model["autopilot"]
    actions = {row["stage"]: row["autopilot_action"] for row in autopilot["stage_plan"]}
    assert autopilot["status"] == "blocked"
    assert autopilot["ready"] is False
    assert actions[1] == "reuse-latest-valid-artifact"
    assert actions[2] == "generate-upstream"
    assert any(row["kind"] == "missing-input" for row in autopilot["blockers"])


def test_autopilot_preflight_detects_stale_outputs(tmp_path: Path) -> None:
    data_root = tmp_path / "localshare" / "agi"
    input_path = data_root / "network_sim" / "dataset" / "links.parquet"
    output_path = data_root / "network_sim" / "pipeline" / "summary.json"
    input_path.parent.mkdir(parents=True)
    output_path.parent.mkdir(parents=True)
    input_path.write_text("input", encoding="utf-8")
    output_path.write_text("output", encoding="utf-8")
    os.utime(output_path, (1000, 1000))
    os.utime(input_path, (2000, 2000))
    stages = [
        {
            "id": "network_build",
            "data_in": "network_sim/dataset/links.parquet",
            "data_out": "network_sim/pipeline/summary.json",
        }
    ]

    model = insights.build_workflow_cockpit_model(
        stages=stages,
        sequence=[0],
        waves=[[0]],
        stage_ids={0: "network_build"},
        stage_deps={"network_build": []},
        roots=[data_root],
        manifest=None,
        pandas_paths=[],
    )

    plan = model["autopilot"]["stage_plan"]
    assert plan[0]["decision"] == "run"
    assert plan[0]["autopilot_action"] == "rerun-stale-stage"


def test_autopilot_preflight_detects_model_version_mismatch(tmp_path: Path) -> None:
    model_path = tmp_path / "policy.pkl"
    model_path.write_text("model", encoding="utf-8")
    model_path.with_suffix(".json").write_text(
        json.dumps({"sklearn_version": "1.8.0", "n_features_in_": 10}),
        encoding="utf-8",
    )

    artifacts = insights.discover_model_artifacts([tmp_path])
    preflight = insights.build_autopilot_preflight(
        stages=[],
        sequence=[],
        quality={"critical_steps": 0, "parallel_width": 0},
        data_availability={"rows": [], "missing_inputs": [], "missing_outputs": []},
        model_artifacts=artifacts,
        current_versions={"sklearn_version": "1.9.0"},
    )

    assert preflight["status"] == "blocked"
    assert any(
        row["kind"] == "model-compatibility" and row["issue"] == "sklearn_version mismatch"
        for row in preflight["blockers"]
    )


def test_pipeline_workflow_insights_root_shim_exports_schema() -> None:
    shim = importlib.import_module("agilab.pipeline_workflow_insights")
    classified = importlib.import_module("agilab.pipeline.pipeline_workflow_insights")

    assert shim.PIPELINE_WORKFLOW_INSIGHTS_SCHEMA == classified.PIPELINE_WORKFLOW_INSIGHTS_SCHEMA
    assert shim.PIPELINE_AUTOPILOT_PREFLIGHT_SCHEMA == classified.PIPELINE_AUTOPILOT_PREFLIGHT_SCHEMA
