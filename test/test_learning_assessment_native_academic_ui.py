"""Academic native controls coexist with portable, human-reviewed programme sessions."""

from __future__ import annotations

import builtins
from copy import deepcopy
import importlib
import json
from pathlib import Path

import pytest

from agi_web import python_ui as ui
from agi_web.testing import AppTest


APP_SRC = (
    Path(__file__).resolve().parents[1]
    / "src/agilab/apps/builtin/learning_assessment_project/src"
)


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(APP_SRC))
    original_import = builtins.__import__

    def native_import(name, *args, **kwargs):
        if name == "streamlit" or name.startswith("streamlit."):
            raise AssertionError("Academic native views must not import Streamlit")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", native_import)
    return (
        importlib.import_module("learning_assessment.ui.app_surface"),
        importlib.import_module("learning_assessment.ui.academic_assessment"),
        importlib.import_module("learning_assessment.ui.program_learning"),
        importlib.import_module("learning_assessment.domain.assessment_session"),
        importlib.import_module("learning_assessment.domain.education"),
    )


@pytest.fixture
def academic(modules):
    surface, *_ = modules
    return deepcopy(
        next(case for case in surface.load_cases() if "academic_assessment" in case)
    )


@pytest.fixture
def mixed_bank(academic):
    common = {
        "schema": "agilab.learning_assessment.question.v1",
        "reference_answer": "A queue adds delay even when capacity is sufficient.",
        "criteria": ["Mechanism", "Limits"],
        "explanation": "Distinguish transmission and queueing delays.",
        "remediation": "Read the queueing chapter; try another load.",
    }
    return {
        "schema": "agilab.tescia_diagnostic.cases.v1",
        "cases": [
            academic,
            {
                "case_id": "native_numeric",
                "title": "Native numeric result",
                "student_prompt": "Compute transmission delay.",
                "question_assessment": {
                    **common,
                    "kind": "numeric",
                    "expected": 0.2,
                    "unit": "s",
                    "absolute_tolerance": 0.001,
                    "relative_tolerance": 0,
                },
            },
            {
                "case_id": "native_choices",
                "title": "Native multiple choice",
                "student_prompt": "Select delay components.",
                "question_assessment": {
                    **common,
                    "kind": "multiple_choice",
                    "choices": {
                        "queue": "Queue",
                        "propagation": "Propagation",
                        "label": "Packet label",
                    },
                    "correct_choices": ["queue", "propagation"],
                },
            },
            {
                "case_id": "native_reasoning",
                "title": "Native reasoning review",
                "student_prompt": "Explain queueing delay.",
                "question_assessment": {**common, "kind": "open_response"},
            },
        ],
    }


def _control(collection, label):
    return next(control for control in collection if control.label == label)


def _retained_session(app):
    return next(
        value
        for value in app.session_state.values()
        if isinstance(value, dict) and "attempts" in value and "reviews" in value
    )


def test_academic_blank_drafts_and_worked_examples_have_separate_native_state(
    modules, academic
):
    _, controls, _, _, education = modules
    _, _, questions = education.resolve_academic_assessment(academic)
    answers = []

    def view():
        mode = ui.selectbox(
            "Mode", ["Practice", "Worked example", "Positioning"], key="mode"
        )
        initial = (
            {
                "academic_answers": {
                    question["id"]: question["correct_choice"] for question in questions
                }
            }
            if mode == "Worked example"
            else None
        )
        answers.append(
            controls.render_academic_answer(
                academic, academic["case_id"] + "_" + mode, initial
            )
        )

    app = AppTest.from_function(view).run()
    assert not app.exception
    assert answers[-1] == {"academic_answers": {}}
    assert all(radio.value is None for radio in app.radio)
    first = questions[0]
    selected = next(
        choice for choice in first["choices"] if choice != first["correct_choice"]
    )
    app.radio[0].set_value(selected).run()
    app.run()
    assert answers[-1]["academic_answers"][first["id"]] == selected
    app.selectbox[0].select("Worked example").run()
    assert answers[-1]["academic_answers"] == {
        question["id"]: question["correct_choice"] for question in questions
    }
    app.selectbox[0].select("Positioning").run()
    assert answers[-1] == {"academic_answers": {}}
    app.selectbox[0].select("Practice").run()
    assert answers[-1]["academic_answers"][first["id"]] == selected


def test_mixed_imported_bank_runs_native_answers_and_portable_human_review(
    modules, mixed_bank
):
    _, _, program, sessions, education = modules
    app = AppTest.from_function(lambda: program.render_program(mixed_bank)).run()
    assert not app.exception
    assert all(radio.value is None for radio in app.radio)
    _control(app.form_submit_button, "Enregistrer ma réponse").click().run()
    assert not app.exception
    assert not _retained_session(app)["attempts"]
    assert any("La réponse est vide" in error.value for error in app.error)

    _, _, questions = education.resolve_academic_assessment(mixed_bank["cases"][0])
    for radio, question in zip(app.radio, questions, strict=True):
        radio.set_value(question["correct_choice"])
    _control(app.form_submit_button, "Enregistrer ma réponse").click().run()
    assert not app.exception
    session = _retained_session(app)
    assert session["attempts"][-1]["evaluation"]["student_score"] == 100
    assert all(radio.value is None for radio in app.radio), "A new attempt starts blank"

    _control(app.selectbox, "Exercice").select("native_numeric").run()
    assert _control(app.number_input, "Votre résultat").value is None
    _control(app.number_input, "Votre résultat").set_value(0.2)
    _control(app.text_input, "Unité du résultat").set_value("s")
    _control(app.form_submit_button, "Enregistrer ma réponse").click().run()
    assert not app.exception
    assert _retained_session(app)["attempts"][-1]["evaluation"]["student_score"] == 100

    _control(app.selectbox, "Exercice").select("native_choices").run()
    _control(app.multiselect, "Vos choix").set_value(["queue", "propagation"])
    _control(app.form_submit_button, "Enregistrer ma réponse").click().run()
    assert not app.exception
    assert _retained_session(app)["attempts"][-1]["evaluation"]["student_score"] == 100

    _control(app.selectbox, "Exercice").select("native_reasoning").run()
    _control(app.text_area, "Votre raisonnement").set_value(
        "The queue adds waiting time; capacity alone does not bound delay."
    )
    _control(app.form_submit_button, "Enregistrer ma réponse").click().run()
    assert not app.exception
    session = _retained_session(app)
    assert len(session["attempts"]) == 4
    latest = session["attempts"][-1]
    assert latest["evaluation"]["student_score"] is None
    assert latest["evaluation"]["status"] == "pending_review"

    _control(app.selectbox, "Tentative à revoir").select(latest["attempt_id"]).run()
    assert _control(app.number_input, "Mechanism").value is None
    assert _control(app.number_input, "Limits").value is None
    _control(app.number_input, "Mechanism").set_value(3)
    _control(app.number_input, "Limits").set_value(2)
    _control(app.text_input, "Évaluateur").set_value("Synthetic teacher")
    _control(app.text_area, "Justification et prochaine activité").set_value(
        "Mechanism explained; add a counterexample for limits."
    )
    _control(app.form_submit_button, "Enregistrer la revue").click().run()
    assert not app.exception
    session = _retained_session(app)
    assert len(session["reviews"]) == 1
    assert session["attempts"][-1]["evaluation"]["student_score"] is None
    restored = sessions.restore_session(sessions.export_session(session), mixed_bank)
    assert restored == session
    submission = sessions.worker_submission(restored, mixed_bank)
    academic = submission["cases"][0]
    assert (
        academic["academic_assessment"] == mixed_bank["cases"][0]["academic_assessment"]
    )
    assert academic["student_answer"]["academic_answers"] == {
        question["id"]: question["correct_choice"] for question in questions
    }


def test_imported_academic_example_has_bound_correction_without_an_attempt(
    modules, academic
):
    _, _, program, _, education = modules
    bank = {"schema": "agilab.tescia_diagnostic.cases.v1", "cases": [academic]}
    app = AppTest.from_function(lambda: program.render_program(bank)).run()
    _control(app.selectbox, "Mode de travail").select("example").run()
    assert not app.exception
    assert not app.radio
    assert not _retained_session(app)["attempts"]
    _, _, questions = education.resolve_academic_assessment(academic)
    text = "\n".join(node.value for node in app.markdown)
    assert questions[0]["explanation"] in text
    assert questions[0]["choices"][questions[0]["correct_choice"]] in text
    assert any(
        "ne produit ni note ni preuve de maîtrise" in node.value for node in app.info
    )


@pytest.mark.parametrize("mode", ["practice", "positioning"])
def test_academic_corrections_follow_programme_mode_and_remain_in_review(
    modules, academic, mode
):
    _, _, program, sessions, education = modules
    bank = {"schema": "agilab.tescia_diagnostic.cases.v1", "cases": [academic]}
    _, _, questions = education.resolve_academic_assessment(academic)
    session = sessions.new_session(bank, "feedback_scope_learner")
    sessions.submit_attempt(
        session,
        bank,
        academic["case_id"],
        {
            "academic_answers": {
                question["id"]: next(
                    choice
                    for choice in question["choices"]
                    if choice != question["correct_choice"]
                )
                for question in questions
            }
        },
        mode=mode,
    )
    app = AppTest.from_function(
        lambda: program._render_learning(bank, session, "feedback_scope")
    ).run()
    _control(app.selectbox, "Mode de travail").select(mode).run()
    assert not app.exception
    text = "\n".join(node.value for node in app.markdown)
    for question in questions:
        assert (question["explanation"] in text) == (mode == "practice")

    review = AppTest.from_function(
        lambda: program._render_reviews(bank, session, "feedback_scope_review")
    ).run()
    assert not review.exception
    review_text = "\n".join(node.value for node in review.markdown)
    assert all(question["explanation"] in review_text for question in questions)


@pytest.mark.parametrize("host", ["bundled", "imported"])
def test_native_course_coverage_download_matches_displayed_bank(
    modules, academic, monkeypatch, host
):
    surface, _, program, _, _ = modules
    monkeypatch.setattr(surface, "_runtime_context", lambda _path: (None, None))
    bank = {"schema": "agilab.tescia_diagnostic.cases.v1", "cases": [academic]}
    def view():
        if host == "bundled":
            surface.render(mode="analysis")
        else:
            program.render_program(bank)
    app = AppTest.from_function(view).run()
    assert not app.exception
    downloads = [
        button
        for button in app.download_button
        if button.proto.filename
        == "learning_assessment_engineering_course_coverage_fr.json"
    ]
    assert len(downloads) == 1
    asset_id = downloads[0].proto.url.rsplit("/", 1)[-1]
    content, mime, filename = app._session.assets[asset_id]
    report = json.loads(content)
    assert mime == "application/json"
    assert filename == downloads[0].proto.filename
    assert report["schema"] == "agilab.learning_assessment.education_coverage.v1"
    assert report["course_count"] == 14
    expected_questions = 239 if host == "bundled" else 3
    assert report["question_count"] == expected_questions
    assert _control(app.metric, "Questions présentes").value == str(expected_questions)
    assert len(report["missing_sections"]) == (0 if host == "bundled" else 101)
