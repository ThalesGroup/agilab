"""External assessment banks survive loading, worker transport, and export."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


APP_SRC = (
    Path(__file__).resolve().parents[1]
    / "src/agilab/apps/builtin/tescia_diagnostic_project/src"
)


@pytest.fixture
def bank(monkeypatch):
    monkeypatch.syspath_prepend(str(APP_SRC))
    payload = json.loads(
        (
            APP_SRC / "tescia_diagnostic/sample_data/tescia_diagnostic_cases.json"
        ).read_text()
    )
    payload["cases"] = payload["cases"][:2]
    payload["assessment_program"] = {
        "schema": "tescia-assessment-program.v1",
        "program_id": "example_program",
        "title": "Synthetic assessment program",
        "version": "1",
        "sources": [
            {
                "source_id": "notes",
                "title": "Example notes",
                "revision": "1",
                "sha256": "a" * 64,
            }
        ],
        "competencies": [
            {
                "competency_id": "evidence_review",
                "title": "Review evidence",
                "outcome": "Distinguish an observed failure from a proposed explanation.",
                "source_refs": [{"source_id": "notes", "section": "Evidence"}],
                "prerequisites": [],
                "diagnostic_case_ids": [payload["cases"][0]["case_id"]],
                "practical_assessment": {
                    "instructions": "Reproduce an isolated failure and challenge an alternative explanation.",
                    "deliverables": ["Minimal reproducer", "Observation table"],
                    "rubric": [
                        {
                            "criterion_id": "counterexample",
                            "description": "The observation distinguishes the competing explanations.",
                        }
                    ],
                    "artifact_refs": [],
                },
            }
        ],
    }
    return payload


@pytest.fixture
def worker(monkeypatch, tmp_path, bank):
    from tescia_diagnostic_worker import tescia_diagnostic_worker as module

    monkeypatch.setattr(module, "_runtime", {})
    instance = module.TesciaDiagnosticWorker()
    instance.args = SimpleNamespace(reset_target=False)
    instance.data_out = tmp_path / "reports"
    instance.artifact_dir = tmp_path / "artifacts"
    instance._worker_id = 0
    return instance


def write_bank(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_loaders_preserve_and_validate_program(bank, worker, tmp_path):
    from tescia_diagnostic.diagnostic import validate_case_payload

    source = write_bank(tmp_path / "cases.json", bank)
    validated = validate_case_payload(bank)
    assert validated["assessment_program"] == bank["assessment_program"]
    assert worker._load_payload(source) == validated
    assert worker._load_cases(source) == validated["cases"]


def test_invalid_program_fails_before_scoring(bank, worker, monkeypatch, tmp_path):
    from tescia_diagnostic_worker import tescia_diagnostic_worker as module

    bank["assessment_program"] = None
    source = write_bank(tmp_path / "invalid.json", bank)

    def unexpected_score(*args, **kwargs):
        pytest.fail("Invalid program was scored before validation")

    monkeypatch.setattr(module, "diagnose_case", unexpected_score)
    with pytest.raises(ValueError, match="Invalid TeSciA diagnostic file"):
        worker.work_pool(source)
    assert not Path(worker.data_out).exists()


def test_classroom_batch_cannot_silently_drop_program(bank, worker, tmp_path):
    from tescia_diagnostic.classroom import CLASSROOM_SCHEMA

    payload = {
        "schema": CLASSROOM_SCHEMA,
        "assessment_program": bank["assessment_program"],
    }
    source = write_bank(tmp_path / "classroom.json", payload)
    with pytest.raises(ValueError, match="belongs in a diagnostic case bank"):
        worker._load_cases(source)


def test_worker_exports_material_coverage_without_claiming_mastery(
    bank, worker, tmp_path
):
    source = write_bank(tmp_path / "cases.json", bank)
    frame = worker.work_pool(source)
    assert frame["assessment_program_coverage_json"].notna().sum() == 1
    worker.work_done(frame)
    first_paths = sorted((Path(worker.data_out) / "assessment_programs").glob("*.json"))
    assert len(first_paths) == 1
    report = json.loads(first_paths[0].read_text())
    assert report["status"] == "curriculum_ready"
    assert report["learner_mastery"] == "not_assessed"
    from tescia_diagnostic.diagnostic import validate_case_payload

    expected_digest = hashlib.sha256(
        json.dumps(
            validate_case_payload(bank), sort_keys=True, ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    assert report["case_bank_sha256"] == expected_digest
    assert report["competencies"][0]["practical_assessment"]["artifact_refs"] == []
    mirror = Path(worker.artifact_dir) / "assessment_programs" / first_paths[0].name
    assert mirror.read_bytes() == first_paths[0].read_bytes()
    summary = (Path(worker.data_out) / "tescia_diagnostic_summary.csv").read_text()
    assert "assessment_program_coverage_json" not in summary
    assert "practical_assessment" not in summary
    # Coverage survives worker transport and stable replay, not just a loader call.
    worker.work_done(frame.iloc[::-1])
    assert (
        sorted((Path(worker.data_out) / "assessment_programs").glob("*.json"))
        == first_paths
    )


def test_distinct_banks_with_same_program_id_keep_distinct_coverage(
    bank, worker, tmp_path
):
    first = worker.work_pool(write_bank(tmp_path / "first.json", bank))
    second_bank = copy.deepcopy(bank)
    second_bank["assessment_program"]["version"] = "2"
    for case in second_bank["cases"]:
        case["case_id"] += "_second"
    second_bank["assessment_program"]["competencies"][0]["diagnostic_case_ids"] = [
        second_bank["cases"][0]["case_id"]
    ]
    second = worker.work_pool(write_bank(tmp_path / "second.json", second_bank))
    worker.work_done(pd.concat([first, second], ignore_index=True))
    reports = [
        json.loads(path.read_text())
        for path in sorted(
            (Path(worker.data_out) / "assessment_programs").glob("*.json")
        )
    ]
    assert len(reports) == 2
    assert {report["version"] for report in reports} == {"1", "2"}
    assert len({report["case_bank_sha256"] for report in reports}) == 2


def test_legacy_bank_has_no_program_transport_column(bank, worker, tmp_path):
    bank.pop("assessment_program")
    frame = worker.work_pool(write_bank(tmp_path / "legacy.json", bank))
    assert "assessment_program_coverage_json" not in frame
    assert worker._materialize_program_reports(frame) == {}


def test_changed_case_content_changes_fingerprint_without_program_changes(
    bank, worker, tmp_path
):
    first = worker.work_pool(write_bank(tmp_path / "first.json", bank))
    bank["cases"][0]["root_cause"] += " Additional observation to review."
    second = worker.work_pool(write_bank(tmp_path / "second.json", bank))
    first_report = json.loads(
        first["assessment_program_coverage_json"].dropna().iloc[0]
    )
    second_report = json.loads(
        second["assessment_program_coverage_json"].dropna().iloc[0]
    )
    assert first_report["case_bank_sha256"] != second_report["case_bank_sha256"]
    assert first_report["program_id"] == second_report["program_id"]
    assert first_report["version"] == second_report["version"]


def test_malformed_worker_program_report_is_not_exported(worker):
    with pytest.raises(ValueError, match="Invalid assessment program coverage"):
        worker._materialize_program_reports(
            pd.DataFrame({"assessment_program_coverage_json": ["[]"]})
        )
