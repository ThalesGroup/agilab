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


def test_autopilot_tolerates_malformed_history_and_data_rows_without_reusing_unknown_outputs():
    manifest = {"stage_results": [
        None, {"stage": "bad", "status": "success"},
        {"stage": -1, "status": "invalid"}, {"index": "0", "state": "failed"},
        {"stage_index": "2", "result": "completed"}, {"stage": 3},
    ]}
    preflight = insights.build_autopilot_preflight(
        stages=[{"R": "agi.run"}, {"R": "agi.run"}, {"R": "agi.run"}],
        sequence=[-1, 0, 1, 2, 99], quality={},
        data_availability={"rows": [
            None, {"kind": "output", "stage": "broken"},
            {"kind": "input", "stage": []}, {"kind": "output", "stage": 0},
            {"kind": "input", "stage": 0},
        ], "missing_inputs": [None]},
        model_artifacts=[], manifest=manifest,
    )
    assert preflight["summary"]["stage_count"] == 3
    assert [row["manifest_status"] for row in preflight["stage_plan"]] == ["failed", "completed", ""]
    assert all(row["decision"] == "run" for row in preflight["stage_plan"])
    assert preflight["status"] == "ready"


def test_autopilot_dependency_and_model_incompatibilities_block_before_execution():
    preflight = insights.build_autopilot_preflight(
        stages=[{"R": "agi.run"}], sequence=[0],
        quality={"dependency_error": "cycle: train -> evaluate -> train"},
        data_availability={}, current_versions={"sklearn_version": "1.8"},
        model_artifacts=[
            {"name": "missing.pkl", "metadata": None, "metadata_status": "missing"},
            {"name": "old.pkl", "metadata_status": "versioned",
             "metadata": {"scikit_learn_version": "1.7"}},
        ],
        manifest={"stages": "corrupt"},
    )
    assert preflight["ready"] is False
    assert preflight["status"] == "blocked"
    assert {row["kind"] for row in preflight["blockers"]} == {"dependency", "model-compatibility"}
    compatibility = next(row for row in preflight["blockers"] if row["kind"] == "model-compatibility")
    assert compatibility["recorded"] == "1.7"
    assert compatibility["current"] == "1.8"
    assert {row["issue"] for row in preflight["warnings"]} == {
        "missing model metadata", "missing feature shape/schema metadata",
    }


def test_model_artifact_discovery_respects_depth_limits_duplicates_and_metadata_integrity(tmp_path):
    root = tmp_path / "models"
    root.mkdir()
    model = root / "a.pkl"
    model.write_bytes(b"opaque-model")
    model.with_suffix(".pkl.json").write_text("[]", encoding="utf-8")
    model.with_suffix(".json").write_text('{"torch_version": "2.0", "input_dim": 4}', encoding="utf-8")
    nested = root / "deep"
    nested.mkdir()
    (nested / "b.pkl").write_bytes(b"nested")
    hidden = root / ".cache"
    hidden.mkdir()
    (hidden / "secret.pkl").write_bytes(b"hidden")
    (root / "readme.txt").write_text("not a model", encoding="utf-8")
    found = insights.discover_model_artifacts([root, root, tmp_path / "missing"], max_depth=0)
    assert len(found) == 1
    assert found[0]["path"] == str(model)
    assert found[0]["metadata_status"] == "versioned"
    assert found[0]["metadata"]["input_dim"] == 4
    assert len(insights.discover_model_artifacts([root], max_files=1)) == 1
    assert insights.discover_model_artifacts([model])[0]["path"] == str(model)


def test_pandas_audit_skips_unreadable_source_and_reports_bounded_findings(tmp_path):
    (tmp_path / "broken.py").write_bytes(b"\xff")
    source = tmp_path / "pandas_usage.py"
    source.write_text(
        "import pandas as pd\ndf['x'][0] = 1\ndf['y'][0] = 2\n",
        encoding="utf-8",
    )
    report = insights.audit_pandas_compat([tmp_path / "missing", tmp_path], max_findings=1)
    assert report["total"] == 1
    assert report["truncated"] is True
    assert report["findings"][0]["line"] == 2
    assert report["findings"][0]["kind"] == "chained-assignment"
    assert insights.audit_pandas_compat([tmp_path / "broken.py"])["total"] == 0


def test_stage_path_specs_preserve_nested_paths_and_remove_exact_duplicates():
    result = insights.stage_path_specs({
        "inputs": {"z": [None, False, " ", Path("data/b")], "a": ("data/a", "data/a")},
        "model_path": " model.pkl ",
        "artifact_path": "artifact.json",
        "automation": {"outputs": {"out/b", "out/a"}},
    })
    assert {(row["kind"], row["path"]) for row in result} == {
        ("input", "data/a"), ("input", "data/b"), ("artifact", "model.pkl"),
        ("artifact", "artifact.json"), ("output", "out/a"), ("output", "out/b"),
    }
    assert len(result) == 6
