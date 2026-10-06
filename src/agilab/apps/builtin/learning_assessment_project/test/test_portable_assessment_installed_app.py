"""Exercise portable assessment using the app's own installed environment."""

from importlib.resources import files
import json

import pytest

from learning_assessment.domain import assessment_session as sessions
from learning_assessment.domain.diagnostic import diagnose_case
from learning_assessment.ui.program_learning import read_bank_bytes


def test_installed_bank_supports_review_and_portable_resume():
    bank = read_bank_bytes(
        files("learning_assessment")
        .joinpath("sample_data/tescia_diagnostic_cases.json")
        .read_bytes()
    )
    case = bank["cases"][0]
    session = sessions.new_session(bank, "installed_app_learner")
    attempt = sessions.submit_attempt(
        session, bank, case["case_id"], case["student_answer"], mode="practice"
    )
    assert attempt["evaluation"]["student_score"] is None
    sessions.review_attempt(
        session,
        bank,
        attempt["attempt_id"],
        reviewer="teacher",
        rationale="Evidence checked.",
        scores={
            "Exactitude du raisonnement": 3,
            "Justification par les preuves": 3,
            "Limites et contre-exemples": 2,
        },
    )
    saved = sessions.export_session(session)
    assert sessions.restore_session(saved, bank) == session
    exported = sessions.worker_submission(session, bank)
    assert exported["cases"][0]["student_ref"] == "installed_app_learner"
    assert diagnose_case(exported["cases"][0])["student_score"] is None
    forged = json.loads(saved)
    forged["payload"]["reviews"][0]["rubric_score"] = 4
    forged["sha256"] = sessions.fingerprint(forged["payload"])
    with pytest.raises(ValueError, match="incohérente"):
        sessions.restore_session(sessions.canonical_bytes(forged), bank)


def test_installed_app_rejects_non_object_attempt_on_resume():
    bank = read_bank_bytes(
        files("learning_assessment")
        .joinpath("sample_data/tescia_diagnostic_cases.json")
        .read_bytes()
    )
    session = sessions.new_session(bank, "installed_app_learner")
    session["attempts"] = [None]
    with pytest.raises(ValueError, match="doit être un objet"):
        sessions.restore_session(sessions.export_session(session), bank)
