"""Chapter coverage, objective scores and preserved school/engineering provenance."""

from __future__ import annotations

import copy
import csv
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

APP_ROOT = (
    Path(__file__).resolve().parents[1]
    / "src/agilab/apps/builtin/learning_assessment_project"
)


@pytest.fixture
def surface(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(APP_ROOT / "src"))
    module = importlib.import_module("learning_assessment.ui.app_surface")
    monkeypatch.setattr(module, "_runtime_context", lambda _: (None, None))
    monkeypatch.setattr(module, "classroom_artifact_dirs", lambda *a, **k: [tmp_path])
    monkeypatch.setattr(
        module, "classroom_submission_inbox_dir", lambda *a, **k: tmp_path / "inbox"
    )
    return module


def test_all_requested_chapters_have_objective_questions_and_sources(surface):
    from learning_assessment.domain.education import (
        build_education_coverage_report,
        load_course_registry,
    )

    cases = surface.load_cases()
    registry = load_course_registry()
    counts = {c["id"]: len(c["sections"]) for c in registry["courses"]}
    assert counts == {
        "ensae_algebre": 9,
        "ensae_statistique_1": 11,
        "ensae_optimal_transport": 4,
        "ensae_mesure_lebesgue": 6,
        "ensae_hmm_smc": 6,
        "ensae_probabilites_2ad": 5,
        "ensae_haute_dimension": 4,
        "ensae_mathematiques_financieres": 5,
        "ensae_fondements_probabilites": 7,
        "ensae_analyse": 13,
        "ensae_calcul_differentiel_integral": 15,
        "ensae_analyse_fonctionnelle_convexe": 4,
        "extra_ondelettes": 6,
        "extra_chiffrement_homomorphe": 7,
    }
    report = build_education_coverage_report(cases)
    assert report["quality_passed"]
    assert report["syllabus_course_count"] == 12
    assert report["extra_course_count"] == 2
    assert report["section_count"] == 102
    assert report["question_count"] == 239
    assert report["stage_case_counts"] == {
        "college": 2,
        "lycee": 8,
        "engineering_school": 102,
        "transversal": 26,
    }
    for course in registry["courses"]:
        for section in course["sections"]:
            assert len(section["questions"]) >= 2
            assert all(q["explanation"] for q in section["questions"])
    # The existing 28 school domains remain covered by their original 10 scenarios.
    from learning_assessment.curriculum import build_math_program_2026_coverage_report

    school = build_math_program_2026_coverage_report(cases)
    assert school["required_count"] == 28
    assert school["quality_passed"]


def test_removed_chapter_and_removed_question_fail_material_coverage(surface):
    from learning_assessment.domain.education import build_education_coverage_report

    cases = copy.deepcopy(surface.load_cases())
    removed = next(c for c in cases if c["case_id"] == "ensae_algebre_01")
    cases.remove(removed)
    report = build_education_coverage_report(cases)
    assert not report["quality_passed"]
    assert "ensae_algebre/01" in report["missing_sections"]
    affected = next(
        r
        for r in report["sections"]
        if r["course_id"] == "ensae_algebre" and r["section_id"] == "01"
    )
    assert len(affected["missing_notions"]) == 3

    cases.append(removed)
    removed["academic_assessment"]["question_ids"].remove("01_q3")
    affected = next(
        r
        for r in build_education_coverage_report(cases)["sections"]
        if r["course_id"] == "ensae_algebre" and r["section_id"] == "01"
    )
    assert not affected["quality_passed"]
    assert affected["missing_questions"] == ["01_q3"]
    assert affected["missing_notions"] == ["Sommes directes et projecteurs"]


def test_scores_require_actual_answers_and_ignore_free_text_confidence(surface):
    from learning_assessment.domain.education import resolve_academic_assessment

    for case in surface.filter_cases(
        surface.load_cases(), education_stage="engineering_school"
    ):
        _, _, questions = resolve_academic_assessment(case)
        empty = surface.score_student_submission(
            case, {"academic_answers": {}, "confidence": 1}
        )
        assert empty["student_score"] == 0
        assert empty["self_evaluation"]["status"] == "not_submitted"
        assert surface.diagnose_case(case)["student_score"] == 0

        correct = {q["id"]: q["correct_choice"] for q in questions}
        report = surface.score_student_submission(case, {"academic_answers": correct})
        assert report["student_score"] == 100
        assert report["self_evaluation"]["correct_count"] == len(questions)
        wrong = {
            q["id"]: next(k for k in q["choices"] if k != q["correct_choice"])
            for q in questions
        }
        assert (
            surface.score_student_submission(
                case,
                {"academic_answers": wrong, "confidence": 1, "root_cause": "correct"},
            )["student_score"]
            == 0
        )

        partial = {questions[0]["id"]: questions[0]["correct_choice"]}
        assert surface.score_student_submission(case, {"academic_answers": partial})[
            "student_score"
        ] == round(100 / len(questions), 2)


@pytest.mark.parametrize(
    "field,value",
    [
        ("course_id", "unknown"),
        ("section_id", "unknown"),
        ("source_revision", "stale"),
        ("question_ids", ["unknown"]),
        ("question_ids", ["01_q1", "01_q1"]),
    ],
)
def test_forged_or_stale_assessment_references_are_rejected(surface, field, value):
    case = copy.deepcopy(
        next(c for c in surface.load_cases() if c["case_id"] == "ensae_algebre_01")
    )
    case["academic_assessment"][field] = value
    with pytest.raises(ValueError):
        surface.score_student_submission(case, {"academic_answers": {}})


def test_unknown_answers_and_unsupported_paths_are_rejected(surface):
    case = next(c for c in surface.load_cases() if c["case_id"] == "ensae_algebre_01")
    for answers in ({"unknown": "a"}, {"01_q1": "unknown"}, {"01_q1": ["a"]}):
        with pytest.raises(ValueError):
            surface.score_student_submission(case, {"academic_answers": answers})
    with pytest.raises(ValueError):
        surface.score_student_submission(case, {"diagnosis": "correct"})
    with pytest.raises(ValueError):
        surface.score_student_submission(
            {**case, "learning_track": "mathematics_2026"}, {"academic_answers": {}}
        )


def test_sources_and_notions_survive_classroom_export_and_merge(surface, tmp_path):
    from learning_assessment.classroom import (
        CLASSROOM_SCHEMA,
        build_classroom_run_report,
        expand_classroom_submissions,
        merge_classroom_run_reports,
        score_classroom_submissions,
        write_classroom_artifacts,
    )
    from learning_assessment.domain.education import resolve_academic_assessment
    from learning_assessment.exports import diagnostic_report_to_markdown

    case = next(
        c
        for c in surface.load_cases()
        if c["case_id"] == "extra_chiffrement_homomorphe_01"
    )
    _, _, questions = resolve_academic_assessment(case)
    payload = {
        "schema": CLASSROOM_SCHEMA,
        "classroom": {"class_id": "engineers", "session_id": "session_1"},
        "submissions": [
            {
                "student_id": "private_name",
                "submission_id": "submission_extra_1",
                "case_id": case["case_id"],
                "answer": {
                    "academic_answers": {
                        q["id"]: q["correct_choice"] for q in questions
                    }
                },
            }
        ],
    }
    expanded = expand_classroom_submissions(payload, case_bank=surface.load_cases())
    reports = [surface.diagnose_case(case) for case in expanded]
    assert reports[0]["student_score"] == 100
    markdown = diagnostic_report_to_markdown(reports[0])
    assert (
        "Chiffrement homomorphe" in markdown
        and "https://homomorphicencryption.org/introduction/" in markdown
    )
    assert "Arithmétique modulaire" in markdown and "Révision des sources" in markdown
    assert "Réponse attendue" in markdown and questions[0]["explanation"] in markdown
    assert "private_name" not in markdown

    classroom = score_classroom_submissions(payload, case_bank=surface.load_cases())
    assert classroom == build_classroom_run_report(reports)
    merged = merge_classroom_run_reports([classroom])
    row = merged["progress_rows"][0]
    assert row["education_stage"] == "engineering_school"
    assert row["education_course_kind"] == "extra"
    assert row["education_course_id"] == "extra_chiffrement_homomorphe"
    assert row["education_section_id"] == "01"
    assert row["education_notion_ids"] == "n1,n2"
    assert len(row["education_source_revision"]) == 64
    paths = write_classroom_artifacts(merged, tmp_path)
    with paths["progress"].open(encoding="utf-8", newline="") as stream:
        exported = next(csv.DictReader(stream))
    assert exported["education_source_revision"] == row["education_source_revision"]
    assert exported["education_source_urls"] == row["education_source_urls"]
    assert "private_name" not in json.dumps(merged)


def test_generator_is_reproducible_and_preserves_all_original_cases(surface):
    result = subprocess.run(
        [
            sys.executable,
            str(APP_ROOT / "tools/generate_engineering_course_assessments_fr.py"),
            "--check",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    original = [c for c in surface.load_cases() if "academic_assessment" not in c]
    assert len(original) == 36
    assert sum(c["learning_track"] == "mathematics_2026" for c in original) == 10


def test_ui_levels_courses_extras_and_unanswered_scoring(surface):
    from streamlit.testing.v1 import AppTest
    from learning_assessment.domain.education import resolve_academic_assessment

    app = AppTest.from_string(
        "from learning_assessment.ui.app_surface import render\nrender(mode='analysis')",
        default_timeout=30,
    ).run()
    assert not app.exception
    app.selectbox(key="learning_education_stage").select("college").run()
    assert not app.exception
    assert len(app.selectbox(key="tescia_answer_case").options) == 2
    app.selectbox(key="learning_education_stage").select("lycee").run()
    assert not app.exception
    assert len(app.selectbox(key="tescia_answer_case").options) == 8

    app.selectbox(key="learning_education_stage").select("engineering_school").run()
    app.selectbox(key="learning_education_course").select("extra_ondelettes").run()
    assert not app.exception
    assert len(app.selectbox(key="tescia_answer_case").options) == 6
    assert all(r.value is None for r in app.radio)
    assert any("Extra" in info.value for info in app.info)
    assert any("ocw.mit.edu" in m.value for m in app.markdown)
    app.button(key="tescia_answer_evaluate").click().run()
    assert not app.exception
    assert next(float(m.value) for m in app.metric if m.label == "Student score") == 0

    case_id = app.selectbox(key="tescia_answer_case").value
    case = next(c for c in surface.load_cases() if c["case_id"] == case_id)
    _, _, questions = resolve_academic_assessment(case)
    for q in questions:
        app.radio(key=f"academic_answer_{case_id}_{q['id']}").set_value(
            q["correct_choice"]
        )
    app.button(key="tescia_answer_evaluate").click().run()
    assert not app.exception
    assert next(float(m.value) for m in app.metric if m.label == "Student score") == 100
    # Changing learning path invalidates the previous stage/course safely.
    app.segmented_control(key="tescia_learning_track").set_value(
        "mathematics_2026"
    ).run()
    assert not app.exception
    assert app.selectbox(key="learning_education_course").value == ""
    assert app.selectbox(key="tescia_answer_case").value.startswith("math_2026_")


def test_academic_provenance_survives_worker_dataframe_transport(
    surface, monkeypatch, tmp_path
):
    from io import StringIO
    from types import SimpleNamespace

    import pandas as pd

    from learning_assessment.domain.education import resolve_academic_assessment
    from learning_assessment_worker import learning_assessment_worker as worker_module

    case = copy.deepcopy(
        next(c for c in surface.load_cases() if c["case_id"] == "ensae_hmm_smc_03")
    )
    _, _, questions = resolve_academic_assessment(case)
    case["student_answer"] = {
        "academic_answers": {q["id"]: q["correct_choice"] for q in questions}
    }
    source = tmp_path / "kalman_academic_answers.json"
    source.write_text(
        json.dumps({"schema": "agilab.tescia_diagnostic.cases.v1", "cases": [case]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(worker_module, "_runtime", {})
    worker = worker_module.LearningAssessmentWorker()
    worker.args = SimpleNamespace(reset_target=False)
    worker.data_out = tmp_path / "reports"
    worker.artifact_dir = tmp_path / "artifacts"
    worker._worker_id = 0
    frame = worker.work_pool(source)
    assert frame.iloc[0]["student_score"] == 100
    assert frame.iloc[0]["education_course_id"] == "ensae_hmm_smc"
    revision = frame.iloc[0]["education_source_revision"]
    transported = pd.read_json(StringIO(frame.to_json(orient="records")), dtype=False)
    worker.work_done(transported)
    csv_path = Path(worker.data_out) / "learning_assessment_summary.csv"
    with csv_path.open(encoding="utf-8", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["education_source_revision"] == revision
    assert row["education_section_id"] == "03"
    report = json.loads(transported.iloc[0]["report_json"])
    assert report["catalog"]["education_trace"]["source_revision"] == revision
    assert report["self_evaluation"]["correct_count"] == 2
    assert any(
        "Réponse attendue" in path.read_text(encoding="utf-8")
        for path in Path(worker.data_out).rglob("*.md")
    )
