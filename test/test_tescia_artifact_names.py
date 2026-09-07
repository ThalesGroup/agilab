"""Distinct TeSciA case identities must retain distinct exported evidence."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


APP_SRC = (
    Path(__file__).resolve().parents[1]
    / "src/agilab/apps/builtin/tescia_diagnostic_project/src"
)
SAMPLE_CASES = APP_SRC / "tescia_diagnostic/sample_data/tescia_diagnostic_cases.json"


@pytest.fixture
def app_modules(monkeypatch):
    monkeypatch.syspath_prepend(str(APP_SRC))
    from tescia_diagnostic import exports
    from tescia_diagnostic_worker import tescia_diagnostic_worker as worker_module

    return exports, worker_module


@pytest.mark.parametrize(
    ("first_id", "second_id"),
    [
        ("case/a", "case_a"),
        ("case.a", "case?a"),
        ("case", "CASE"),
        ("a__b", "a_b"),
        (" case ", "case"),
        ("é", "e\u0301"),
    ],
)
def test_distinct_case_ids_keep_separate_corrections(
    app_modules, tmp_path, first_id, second_id
):
    exports, worker_module = app_modules
    first = exports.write_correction_sheet({"case_id": first_id}, tmp_path)
    second = exports.write_correction_sheet({"case_id": second_id}, tmp_path)

    assert first.name.casefold() != second.name.casefold()
    assert worker_module._sanitize_slug(first_id).casefold() != (
        worker_module._sanitize_slug(second_id).casefold()
    )
    assert f"- Case id: `{first_id}`" in first.read_text(encoding="utf-8")
    assert f"- Case id: `{second_id}`" in second.read_text(encoding="utf-8")


def test_bundled_case_filenames_are_unchanged(app_modules, tmp_path):
    exports, worker_module = app_modules
    cases = json.loads(SAMPLE_CASES.read_text(encoding="utf-8"))["cases"]
    for case in cases:
        case_id = case["case_id"]
        assert worker_module._sanitize_slug(case_id) == case_id
        assert exports.write_correction_sheet(case, tmp_path).name == (
            f"{case_id}_correction.md"
        )


@pytest.mark.parametrize("case_id", ["a" * 400, "épreuve/" * 80])
def test_artifact_basenames_are_bounded_ascii(app_modules, tmp_path, case_id):
    exports, worker_module = app_modules
    path = exports.write_correction_sheet({"case_id": case_id}, tmp_path)
    stem = worker_module._sanitize_slug(case_id)

    assert path.name.isascii()
    assert len(path.name.encode("ascii")) <= 160
    assert len(f"{stem}_diagnostic_summary.csv".encode("ascii")) <= 160
    assert path.parent == tmp_path
    assert path.name == f"{stem}_correction.md"


def test_retries_are_stable_and_generated_names_have_a_reserved_namespace(
    app_modules, tmp_path
):
    exports, worker_module = app_modules
    report = {"case_id": "case/a"}
    first = exports.write_correction_sheet(report, tmp_path)
    assert exports.write_correction_sheet(report, tmp_path) == first
    assert len(list(tmp_path.glob("*_correction.md"))) == 1

    generated_stem = first.name.removesuffix("_correction.md")
    other = exports.write_correction_sheet({"case_id": generated_stem}, tmp_path)
    assert other.name.casefold() != first.name.casefold()
    assert worker_module._sanitize_slug(report["case_id"]) == generated_stem


@pytest.mark.parametrize("case_id", ["", "  "])
def test_explicit_blank_case_ids_are_rejected(app_modules, tmp_path, case_id):
    exports, worker_module = app_modules
    with pytest.raises(ValueError, match="case_id"):
        exports.write_correction_sheet({"case_id": case_id}, tmp_path)
    with pytest.raises(ValueError, match="case_id"):
        worker_module._sanitize_slug(case_id)

    for report in ({}, {"case_id": None}):
        assert exports.write_correction_sheet(report, tmp_path).name == (
            "tescia_case_correction.md"
        )


def test_worker_keeps_both_artifact_bundles_complete_on_retry(app_modules, tmp_path):
    _exports, worker_module = app_modules
    payload = json.loads(SAMPLE_CASES.read_text(encoding="utf-8"))
    original = payload["cases"][0]
    case_ids = {"case/a", "case_a", "CASE_A"}
    source_file = tmp_path / "cases.json"
    source_file.write_text(
        json.dumps(
            {
                **payload,
                "cases": [{**original, "case_id": value} for value in sorted(case_ids)],
            }
        ),
        encoding="utf-8",
    )
    worker = worker_module.TesciaDiagnosticWorker()
    worker._worker_id = 0
    worker.data_out = tmp_path / "reports"
    worker.artifact_dir = tmp_path / "export"
    worker._current_args = lambda: SimpleNamespace(reset_target=True)
    frame = worker.work_pool(source_file)

    worker.work_done(frame)
    worker.work_done(frame)

    for root in (worker.data_out, worker.artifact_dir):
        reports = sorted(root.glob("*/*_diagnostic_report.json"))
        assert len(reports) == len(case_ids)
        assert {
            json.loads(path.read_text(encoding="utf-8"))["case_id"] for path in reports
        } == case_ids
        summaries = sorted(root.glob("*/*_diagnostic_summary.csv"))
        assert len(summaries) == len(case_ids)
        summary_ids = set()
        for path in summaries:
            with path.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            assert len(rows) == 1
            summary_ids.add(rows[0]["case_id"])
        assert summary_ids == case_ids
        with (root / "tescia_diagnostic_summary.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            assert {row["case_id"] for row in csv.DictReader(stream)} == case_ids
        corrections = sorted((root / "correction_sheets").glob("*_correction.md"))
        assert len(corrections) == len(case_ids)
        index = (root / "correction_sheets/correction_sheets_index.md").read_text(
            encoding="utf-8"
        )
        assert all(f"]({path.name})" in index for path in corrections)
