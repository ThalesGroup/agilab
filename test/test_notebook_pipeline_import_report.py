from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/notebook_pipeline_import_report.py").resolve()
CORE_PATH = Path("src/agilab/notebook_pipeline_import.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_notebook_pipeline_import_report_passes(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "notebook_pipeline_import_report_test_module")
    output_path = tmp_path / "notebook_import.json"

    report = module.build_report(repo_root=Path.cwd(), output_path=output_path)

    assert report["report"] == "Notebook pipeline import report"
    assert report["status"] == "pass"
    assert output_path.is_file()
    assert report["summary"]["schema"] == "agilab.notebook_pipeline_import.v1"
    assert report["summary"]["run_status"] == "imported"
    assert report["summary"]["execution_mode"] == "not_executed_import"
    assert report["summary"]["round_trip_ok"] is True
    assert report["summary"]["cell_count"] == 4
    assert report["summary"]["code_cell_count"] == 2
    assert report["summary"]["markdown_cell_count"] == 2
    assert report["summary"]["pipeline_stage_count"] == 2
    assert report["summary"]["context_block_count"] == 2
    assert report["summary"]["env_hint_count"] == 3
    assert report["summary"]["artifact_reference_count"] == 3
    assert report["summary"]["lab_stages_preview_stage_count"] == 2
    assert report["summary"]["stage_ids"] == ["cell-2", "cell-4"]
    assert {check["id"] for check in report["checks"]} == {
        "notebook_pipeline_import_schema",
        "notebook_pipeline_import_cells",
        "notebook_pipeline_import_metadata",
        "notebook_pipeline_import_context_links",
        "notebook_pipeline_import_execution_boundary",
        "notebook_pipeline_import_lab_stages_preview",
        "notebook_pipeline_import_persistence",
        "notebook_pipeline_import_docs_reference",
    }


def test_notebook_pipeline_import_reads_fixture_and_round_trips(tmp_path: Path) -> None:
    core_module = _load_module(CORE_PATH, "notebook_pipeline_import_core_test_module")
    fixture = Path.cwd() / "docs/source/data/notebook_pipeline_import_sample.ipynb"
    output_path = tmp_path / "notebook_import.json"

    proof = core_module.persist_notebook_pipeline_import(
        repo_root=Path.cwd(),
        output_path=output_path,
        notebook_path=fixture,
    )

    assert proof.ok is True
    assert proof.round_trip_ok is True
    assert proof.pipeline_stage_count == 2
    assert proof.env_hint_count == 3
    assert proof.artifact_reference_count == 3
    imported = proof.notebook_import
    assert imported["execution_mode"] == "not_executed_import"
    assert imported["provenance"]["executes_notebook"] is False
    assert imported["env_hints"] == ["json", "pandas", "pathlib"]
    assert [stage["context_ids"] for stage in imported["pipeline_stages"]] == [
        ["markdown-1"],
        ["markdown-3"],
    ]
    assert {
        reference["path"]
        for reference in imported["artifact_references"]
    } == {
        "data/flights.csv",
        "artifacts/summary.json",
        "artifacts/trajectory.png",
    }
    preview = core_module.build_lab_stages_preview(
        imported,
        module_name="flight_telemetry_project",
    )
    assert [stage["NB_CELL_ID"] for stage in preview["flight_telemetry_project"]] == [
        "cell-2",
        "cell-4",
    ]
    assert preview["flight_telemetry_project"][0]["D"] == "Flight import context"
    assert preview["flight_telemetry_project"][0]["NB_ENV_HINTS"] == ["pandas", "pathlib"]
    assert preview["flight_telemetry_project"][1]["NB_ARTIFACT_REFERENCES"] == [
        "artifacts/summary.json",
        "artifacts/trajectory.png",
    ]


def test_notebook_pipeline_import_report_handles_load_failure(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "notebook_pipeline_import_report_failure_test_module")
    missing = tmp_path / "missing.ipynb"

    report = module.build_report(
        repo_root=Path.cwd(),
        notebook_path=missing,
        output_path=tmp_path / "notebook_import.json",
    )

    assert report["status"] == "fail"
    assert report["checks"] == [
        {
            "details": {
                "error": f"[Errno 2] No such file or directory: '{missing}'",
            },
            "evidence": [str(missing)],
            "id": "notebook_pipeline_import_load",
            "label": "Notebook pipeline import load",
            "status": "fail",
            "summary": "notebook-to-pipeline import could not be persisted",
        }
    ]
