from __future__ import annotations

import json
from pathlib import Path

from agilab import workflow_validation


def test_validate_lab_stages_dry_run_accepts_declarative_stage_contract(tmp_path: Path) -> None:
    stages_file = tmp_path / "demo_project" / "lab_stages.toml"
    stages_file.parent.mkdir()
    stages_file.write_text(
        "\n".join(
            [
                "[[stages]]",
                'id = "build_data"',
                'label = "Build data"',
                'kind = "data"',
                'produces = ["features.csv"]',
                "",
                "[[stages]]",
                'id = "train_model"',
                'label = "Train model"',
                'kind = "model"',
                'depends_on = ["build_data"]',
                'consumes = ["features.csv"]',
                'produces = ["metrics.json"]',
                "",
            ]
        ),
        encoding="utf-8",
    )

    report = workflow_validation.validate_lab_stages_file(stages_file)

    assert report["status"] == "pass"
    assert report["summary"]["stage_count"] == 2
    assert report["dependency_edges"] == [{"kind": "depends_on", "source": "build_data", "target": "train_model"}]
    assert report["artifact_edges"] == [
        {
            "artifact": "features.csv",
            "kind": "artifact_flow",
            "source": "build_data",
            "target": "train_model",
        }
    ]
    assert report["external_inputs"] == []


def test_validate_lab_stages_reports_static_contract_errors(tmp_path: Path) -> None:
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text(
        "\n".join(
            [
                "[[stages]]",
                'id = "load"',
                'C = "APP = \\"missing_project\\"\\ndata_out = \\"shared.csv\\""',
                'R = "runpy"',
                "",
                "[[stages]]",
                'id = "train"',
                'depends_on = ["missing"]',
                'consumes = ["shared.csv"]',
                'produces = ["shared.csv"]',
                'C = "if broken("',
                'R = "shell"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    report = workflow_validation.validate_lab_stages_file(stages_file, apps_root=tmp_path / "apps")
    issue_ids = {issue["check_id"] for issue in report["issues"]}

    assert report["status"] == "fail"
    assert report["summary"]["error_count"] == 2
    assert "dependency-missing" in issue_ids
    assert "stage-code-syntax" in issue_ids
    assert "stage-engine-unknown" in issue_ids
    assert "app-reference-missing" in issue_ids


def test_validate_lab_stages_cli_json_and_strict_warning(tmp_path: Path, capsys) -> None:
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text(
        "\n".join(
            [
                "[[stages]]",
                'label = "Implicit id"',
                'produces = ["a"]',
                "",
            ]
        ),
        encoding="utf-8",
    )

    assert workflow_validation.main(["validate", str(stages_file), "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "warn"
    assert payload["issues"][0]["check_id"] == "metadata-missing"

    assert workflow_validation.main([str(stages_file), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["schema"] == workflow_validation.WORKFLOW_DRY_RUN_SCHEMA

    assert workflow_validation.main(["validate", str(stages_file), "--strict"]) == 1
