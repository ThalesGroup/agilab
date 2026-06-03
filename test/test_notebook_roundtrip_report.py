from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/notebook_roundtrip_report.py").resolve()
CORE_PATH = Path("src/agilab/notebook_pipeline_import.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_notebook_roundtrip_report_passes(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "notebook_roundtrip_report_test_module")

    report = module.build_report(repo_root=Path.cwd(), output_dir=tmp_path)

    assert report["report"] == "Notebook round-trip report"
    assert report["status"] == "pass"
    assert report["summary"]["execution_mode"] == "not_executed_import"
    assert report["summary"]["import_mode"] == "agilab_supervisor_metadata"
    assert report["summary"]["supervisor_stage_count"] == 2
    assert report["summary"]["pipeline_stage_count"] == 2
    assert report["summary"]["lab_stages_round_trip_ok"] is True
    assert report["summary"]["env_hint_count"] == 3
    assert report["summary"]["artifact_reference_count"] == 3
    assert Path(report["summary"]["original_lab_stages_path"]).is_file()
    assert Path(report["summary"]["notebook_path"]).is_file()
    assert Path(report["summary"]["preview_path"]).is_file()
    assert {check["id"] for check in report["checks"]} == {
        "notebook_roundtrip_supervisor_export",
        "notebook_roundtrip_import_mode",
        "notebook_roundtrip_lab_stages_fields",
        "notebook_roundtrip_artifacts_env_hints",
        "notebook_roundtrip_docs_reference",
    }


def test_notebook_pipeline_import_reads_supervisor_metadata(tmp_path: Path) -> None:
    report_module = _load_module(
        REPORT_PATH,
        "notebook_roundtrip_report_core_fixture_module",
    )
    core_module = _load_module(CORE_PATH, "notebook_pipeline_import_supervisor_test_module")
    report = report_module.build_report(repo_root=Path.cwd(), output_dir=tmp_path)

    proof = core_module.persist_notebook_pipeline_import(
        repo_root=Path.cwd(),
        output_path=tmp_path / "direct_import.json",
        notebook_path=Path(report["summary"]["notebook_path"]),
    )

    assert proof.ok is True
    assert proof.notebook_import["source"]["import_mode"] == "agilab_supervisor_metadata"
    assert proof.notebook_import["summary"]["supervisor_stage_count"] == 2
    preview = core_module.build_lab_stages_preview(
        proof.notebook_import,
        module_name="notebook_roundtrip_project",
    )
    assert [stage["D"] for stage in preview["notebook_roundtrip_project"]] == [
        "Seed notebook round-trip inputs",
        "Summarize notebook round-trip output",
    ]
    assert [stage["R"] for stage in preview["notebook_roundtrip_project"]] == [
        "runpy",
        "runpy",
    ]
