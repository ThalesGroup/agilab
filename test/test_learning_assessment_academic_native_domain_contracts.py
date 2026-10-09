"""Academic/native domain integration without weakening human-reviewed scoring."""

from copy import deepcopy
import importlib
import json
from pathlib import Path

import pytest

APP_ROOT = (
    Path(__file__).resolve().parents[1]
    / "src/agilab/apps/builtin/learning_assessment_project"
)


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(APP_ROOT / "src"))
    result = {
        name: importlib.import_module("learning_assessment.domain." + name)
        for name in ("diagnostic", "education", "assessment_session", "classroom")
    }
    for module in result.values():
        assert Path(module.__file__).resolve().is_relative_to(APP_ROOT)
    return result


@pytest.fixture
def academic_case():
    payload = json.loads(
        (
            APP_ROOT
            / "src/learning_assessment/sample_data/tescia_diagnostic_cases.json"
        ).read_text(encoding="utf-8")
    )
    return deepcopy(
        next(case for case in payload["cases"] if case["case_id"] == "ensae_algebre_01")
    )


@pytest.fixture
def open_case():
    return {
        "case_id": "engineering_reasoning",
        "title": "Explain the limits",
        "student_prompt": "Explain the assumptions and their limits.",
        "question_assessment": {
            "schema": "agilab.learning_assessment.question.v1",
            "kind": "open_response",
            "reference_answer": "State the assumptions and a counterexample.",
            "criteria": ["Assumptions", "Limits"],
            "explanation": "A correct choice does not prove a complete argument.",
            "remediation": "Discuss a distinct example with your teacher.",
        },
    }


@pytest.mark.parametrize("entrypoint", ["validate", "diagnose", "academic_score"])
def test_dual_assessment_authorities_are_rejected(
    modules, academic_case, open_case, entrypoint
):
    academic_case["question_assessment"] = open_case["question_assessment"]
    diagnostic = modules["diagnostic"]
    with pytest.raises(ValueError, match="cannot combine"):
        if entrypoint == "validate":
            diagnostic.validate_case_payload(
                {"schema": diagnostic.CASE_SCHEMA, "cases": [academic_case]}
            )
        elif entrypoint == "diagnose":
            diagnostic.diagnose_case(academic_case)
        else:
            modules["education"].score_academic_answer(academic_case)


@pytest.mark.parametrize("case_kind", ["academic", "open"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("original_bank_sha256", "forged"),
        ("attempt_number", True),
        ("mode", "example"),
    ],
)
def test_submission_context_is_checked_before_either_assessment_dispatch(
    modules, academic_case, open_case, case_kind, field, value
):
    case = academic_case if case_kind == "academic" else open_case
    case["submission_context"] = {
        "original_bank_sha256": "a" * 64,
        "attempt_id": "b" * 32,
        "attempt_number": 1,
        "mode": "practice",
        "previous_attempt_id": None,
    }
    case["submission_context"][field] = value
    with pytest.raises(ValueError, match="Invalid"):
        modules["diagnostic"].validate_case_payload(
            {"schema": modules["diagnostic"].CASE_SCHEMA, "cases": [case]}
        )


@pytest.mark.parametrize("value", [None, 12])
def test_academic_classroom_identity_requires_a_nonempty_string(
    modules, academic_case, value
):
    academic_case["student_ref"] = value
    with pytest.raises(ValueError, match="student_ref"):
        modules["diagnostic"].validate_case_payload(
            {"schema": modules["diagnostic"].CASE_SCHEMA, "cases": [academic_case]}
        )


def test_academic_blank_score_is_not_a_recorded_attempt_or_learner_mastery(
    modules, academic_case
):
    sessions = modules["assessment_session"]
    bank = {"schema": modules["diagnostic"].CASE_SCHEMA, "cases": [academic_case]}
    evaluation = modules["education"].score_academic_answer(academic_case)
    assert evaluation["student_score"] == 0
    assert evaluation["status"] == "not_submitted"
    assert evaluation["score_scope"] == "objective_choices_only"
    assert evaluation["learner_mastery"] == "not_assessed"
    session = sessions.new_session(bank, "learner")
    before = deepcopy(session)
    with pytest.raises(ValueError, match="vide"):
        sessions.submit_attempt(
            session,
            bank,
            academic_case["case_id"],
            {"academic_answers": {}},
            mode="practice",
        )
    assert session == before


def test_mixed_academic_and_human_review_session_roundtrip_and_worker_export(
    modules, academic_case, open_case
):
    sessions = modules["assessment_session"]
    diagnostic = modules["diagnostic"]
    _, _, questions = modules["education"].resolve_academic_assessment(academic_case)
    bank = {
        "schema": diagnostic.CASE_SCHEMA,
        "cases": [academic_case, open_case],
    }
    session = sessions.new_session(bank, "learner_01")
    choices = {q["id"]: q["correct_choice"] for q in questions}
    academic = sessions.submit_attempt(
        session,
        bank,
        academic_case["case_id"],
        {"academic_answers": choices},
        mode="practice",
    )
    reasoning = sessions.submit_attempt(
        session,
        bank,
        open_case["case_id"],
        {"response": "The assumptions need an explicit counterexample."},
        mode="positioning",
    )
    assert academic["evaluation"]["student_score"] == 100
    assert (
        academic["evaluation"]["academic_assessment"]
        == academic_case["academic_assessment"]
    )
    assert academic["evaluation"]["learner_mastery"] == "not_assessed"
    assert reasoning["evaluation"]["student_score"] is None
    assert reasoning["evaluation"]["status"] == "pending_review"
    assert sessions.restore_session(sessions.export_session(session), bank) == session

    exported = sessions.worker_submission(session, bank)
    assert len(exported["cases"]) == 2
    summaries = []
    for source_case, exported_case, attempt in zip(
        bank["cases"], exported["cases"], session["attempts"], strict=True
    ):
        assert exported_case["exercise_id"] == source_case["case_id"]
        assert (
            exported_case["submission_context"]["attempt_id"] == attempt["attempt_id"]
        )
        assert (
            exported_case["submission_context"]["original_bank_sha256"]
            == session["bank_sha256"]
        )
        report = diagnostic.diagnose_case(exported_case)
        assert report["self_evaluation"] == attempt["evaluation"]
        summaries.append(
            diagnostic.summarize_report(
                report, worker_id=0, source_file="mixed_answers.json"
            )
        )
        if "academic_assessment" in exported_case:
            row = modules["classroom"].classroom_progress_row(report)
            assert (
                row["education_source_revision"]
                == source_case["academic_assessment"]["source_revision"]
            )
            assert row["education_course_id"] == "ensae_algebre"
    reduction = importlib.import_module("learning_assessment.runtime.reduction")
    artifact = reduction.build_reduce_artifact(
        tuple(
            reduction.partial_from_diagnostic_summary(
                summary, partial_id=summary["case_id"]
            )
            for summary in summaries
        )
    )
    assert artifact.payload["graded_count"] == 1
    assert artifact.payload["student_score_mean"] == 100


def test_academic_session_replay_rejects_forged_grades_and_source_revisions(
    modules, academic_case
):
    sessions = modules["assessment_session"]
    _, _, questions = modules["education"].resolve_academic_assessment(academic_case)
    bank = {"schema": modules["diagnostic"].CASE_SCHEMA, "cases": [academic_case]}
    session = sessions.new_session(bank, "learner")
    sessions.submit_attempt(
        session,
        bank,
        academic_case["case_id"],
        {"academic_answers": {q["id"]: q["correct_choice"] for q in questions}},
        mode="practice",
    )
    for mutation in ("grade", "source"):
        forged = deepcopy(session)
        evaluation = forged["attempts"][0]["evaluation"]
        if mutation == "grade":
            evaluation["student_score"] = 0
        else:
            evaluation["academic_assessment"]["source_revision"] = "0" * 64
        with pytest.raises(ValueError, match="rejeu"):
            sessions.restore_session(sessions.export_session(forged), bank)


@pytest.mark.parametrize("case_kind", ["academic", "open"])
def test_recomputed_session_cannot_restore_an_empty_attempt(
    modules, academic_case, open_case, case_kind
):
    sessions = modules["assessment_session"]
    diagnostic = modules["diagnostic"]
    case = academic_case if case_kind == "academic" else open_case
    if case_kind == "academic":
        _, _, questions = modules["education"].resolve_academic_assessment(case)
        answer = {"academic_answers": {q["id"]: q["correct_choice"] for q in questions}}
        empty = {"academic_answers": {}}
    else:
        answer = {"response": "An explicit argument."}
        empty = {"response": ""}
    bank = {"schema": diagnostic.CASE_SCHEMA, "cases": [case]}
    session = sessions.new_session(bank, "learner")
    sessions.submit_attempt(session, bank, case["case_id"], answer, mode="practice")
    # An envelope checksum alone cannot authorize an attempt that the live
    # submission flow rejects. Replay must enforce the same nonempty contract.
    attempt = session["attempts"][0]
    attempt["answer"] = empty
    attempt["evaluation"] = diagnostic.diagnose_case({**case, "student_answer": empty})[
        "self_evaluation"
    ]
    assert attempt["evaluation"]["status"] == "not_submitted"
    with pytest.raises(ValueError, match="vide"):
        sessions.restore_session(sessions.export_session(session), bank)
