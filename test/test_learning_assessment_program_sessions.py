"""Regressions for honest scoring, portable evidence and external programmes."""

from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path

import pytest


APP = (
    Path(__file__).resolve().parents[1]
    / "src/agilab/apps/builtin/learning_assessment_project"
)


@pytest.fixture
def domain(monkeypatch):
    monkeypatch.syspath_prepend(str(APP / "src"))
    return importlib.import_module("learning_assessment.domain.assessment_session")


@pytest.fixture
def bank():
    question = {
        "schema": "agilab.learning_assessment.question.v1",
        "kind": "open_response",
        "reference_answer": "A queue adds delay even when capacity is sufficient.",
        "criteria": ["Mechanism", "Limits"],
        "explanation": "Distinguish transmission and queueing delays.",
        "remediation": "Read the queueing chapter; try another load.",
    }
    case = {
        "case_id": "queue_reasoning",
        "title": "Queues",
        "student_prompt": "Explain queueing delay.",
        "question_assessment": question,
    }
    numeric = {
        "case_id": "delay_calculation",
        "title": "Delay",
        "student_prompt": "Compute transmission delay.",
        "question_assessment": {
            **question,
            "kind": "numeric",
            "expected": 0.2,
            "unit": "s",
            "absolute_tolerance": 0.001,
            "relative_tolerance": 0,
        },
    }
    choice = {
        "case_id": "delay_choices",
        "title": "Components",
        "student_prompt": "Select delay components.",
        "question_assessment": {
            **question,
            "kind": "multiple_choice",
            "choices": {
                "queue": "Queue",
                "propagation": "Propagation",
                "label": "Packet label",
            },
            "correct_choices": ["queue", "propagation"],
        },
    }
    variant = {
        **deepcopy(case),
        "case_id": "queue_transfer",
        "transfer_variant": {
            "of": "queue_reasoning",
            "dimensions": ["topology", "load"],
            "changes": "A satellite link replaces the LAN and the load doubles.",
        },
    }
    sources = [
        {
            "source_id": "book",
            "title": "Synthetic book",
            "revision": "1",
            "sha256": hashlib.sha256(b"synthetic").hexdigest(),
        }
    ]
    return {
        "schema": "agilab.tescia_diagnostic.cases.v1",
        "cases": [case, numeric, choice, variant],
        "assessment_program": {
            "schema": "tescia-assessment-program.v1",
            "program_id": "synthetic_network",
            "title": "Synthetic network programme",
            "version": "1",
            "sources": sources,
            "competencies": [
                {
                    "competency_id": "queues",
                    "title": "Queues",
                    "outcome": "Explain, calculate and measure delay",
                    "source_refs": [{"source_id": "book", "section": "queues"}],
                    "diagnostic_case_ids": [
                        "queue_reasoning",
                        "delay_calculation",
                        "delay_choices",
                        "queue_transfer",
                    ],
                    "practical_assessment": {
                        "instructions": "Measure delay with a reproducible fixture.",
                        "deliverables": ["report"],
                        "artifact_refs": [],
                        "rubric": [
                            {"criterion_id": c, "description": c}
                            for c in (
                                "explanation",
                                "reproduction",
                                "diagnosis",
                                "synthesis",
                                "defence",
                            )
                        ],
                    },
                }
            ],
        },
    }


def test_negation_and_paraphrase_do_not_receive_a_reasoning_grade(domain):
    diagnostic = importlib.import_module("learning_assessment.domain.diagnostic")
    cases = json.loads(
        (
            APP / "src/learning_assessment/sample_data/tescia_diagnostic_cases.json"
        ).read_text()
    )["cases"]
    case = deepcopy(cases[0])
    for root in (
        case["root_cause"],
        "It is false that " + case["root_cause"],
        "Une reformulation française indépendante.",
    ):
        case["student_answer"]["root_cause"] = root
        result = diagnostic.diagnose_case(case)
        assert result["student_score"] is None
        assert result["self_evaluation"]["status"] == "pending_review"
        assert result["self_evaluation"]["scores"]["root_cause"] is None


def test_selecting_distractors_reduces_objective_score(domain):
    diagnostic = importlib.import_module("learning_assessment.domain.diagnostic")
    case = json.loads(
        (
            APP / "src/learning_assessment/sample_data/tescia_diagnostic_cases.json"
        ).read_text()
    )["cases"][0]
    before = diagnostic.diagnose_case(case)["self_evaluation"]
    case["student_answer"]["evidence_ids"] = [e["id"] for e in case["evidence"]]
    after = diagnostic.diagnose_case(case)["self_evaluation"]
    assert after["scores"]["evidence_selection"] < 1
    assert after["objective_score"] < before["objective_score"]


def test_questions_use_units_tolerances_and_exact_multiple_selections(domain, bank):
    diagnostic = importlib.import_module("learning_assessment.domain.diagnostic")
    numeric, choice = bank["cases"][1:3]
    assert diagnostic.diagnose_case(numeric)["student_score"] is None
    for response, unit, expected in (
        (0.2005, "s", 100),
        (0.2, "ms", 0),
        (0.202, "s", 0),
    ):
        result = diagnostic.diagnose_case(
            {**numeric, "student_answer": {"response": response, "unit": unit}}
        )
        assert result["student_score"] == expected
    for selected, expected in (
        (["queue", "propagation"], 100),
        (["queue", "propagation", "label"], 0),
        (["queue"], 0),
    ):
        assert (
            diagnostic.diagnose_case(
                {**choice, "student_answer": {"response": selected}}
            )["student_score"]
            == expected
        )


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), "0.2"])
def test_invalid_numeric_answers_fail_closed(domain, bank, value):
    diagnostic = importlib.import_module("learning_assessment.domain.diagnostic")
    with pytest.raises(ValueError):
        diagnostic.diagnose_case(
            {**bank["cases"][1], "student_answer": {"response": value, "unit": "s"}}
        )


def test_attempts_and_review_survive_restart_and_preserve_history(domain, bank):
    session = domain.new_session(bank, "learner_01")
    first = domain.submit_attempt(
        session, bank, "queue_reasoning", {"response": "A reason"}, mode="positioning"
    )
    second = domain.submit_attempt(
        session,
        bank,
        "queue_reasoning",
        {"response": "A revised reason"},
        mode="practice",
    )
    assert second["previous_attempt_id"] == first["attempt_id"]
    assert first["evaluation"]["student_score"] is None
    domain.review_attempt(
        session,
        bank,
        first["attempt_id"],
        reviewer="teacher",
        rationale="The mechanism is missing its limits.",
        scores={"Mechanism": 3, "Limits": 1},
    )
    restored = domain.restore_session(domain.export_session(session), bank)
    assert restored == session
    assert restored["reviews"][0]["rubric_score"] == 2
    assert restored["attempts"][0]["evaluation"]["status"] == "pending_review"


def test_modified_bank_or_forged_evaluation_cannot_resume(domain, bank):
    session = domain.new_session(bank, "learner_01")
    domain.submit_attempt(
        session,
        bank,
        "delay_calculation",
        {"response": 0.2, "unit": "s"},
        mode="practice",
    )
    changed = deepcopy(bank)
    changed["cases"][1]["question_assessment"]["expected"] = 0.3
    with pytest.raises(ValueError, match="programme a changé"):
        domain.restore_session(domain.export_session(session), changed)
    session["attempts"][0]["evaluation"]["student_score"] = 0
    with pytest.raises(ValueError, match="rejeu"):
        domain.restore_session(domain.export_session(session), bank)


@pytest.mark.parametrize(
    "collection", ["attempts", "reviews", "practical_reviews", "sources_verified"]
)
@pytest.mark.parametrize("record", [None, [], "invalid", 1, True])
def test_resume_rejects_non_object_records(domain, bank, collection, record):
    session = domain.new_session(bank, "learner_01")
    session[collection] = [record]
    before = deepcopy(session)
    with pytest.raises(ValueError, match="doit être un objet"):
        domain.restore_session(domain.export_session(session), bank)
    assert session == before


def test_transfer_requires_a_distinct_changed_scenario(domain, bank):
    session = domain.new_session(bank, "learner_01")
    with pytest.raises(ValueError, match="variante"):
        domain.submit_attempt(
            session, bank, "queue_reasoning", {"response": "reason"}, mode="transfer"
        )
    domain.submit_attempt(
        session,
        bank,
        "queue_transfer",
        {"response": "A changed scenario needs fresh reasoning."},
        mode="transfer",
    )
    assert domain.restore_session(domain.export_session(session), bank) == session


def test_practical_gates_cannot_be_compensated_by_good_scores(domain, bank):
    session = domain.new_session(bank, "learner_01")
    args = dict(
        reviewer="teacher",
        rationale="Results checked against the original fixture.",
        scores={c: 4 for c in domain.PRACTICAL_WEIGHTS},
        artifacts={"delay_measurements.txt": b"delay_s=0.2\n"},
        safety_authorized=False,
        integrity_verified=True,
    )
    result = domain.review_practical(session, bank, "queues", **args)
    assert result["rubric_score"] == 4
    assert result["status"] == "blocked"
    assert domain.restore_session(domain.export_session(session), bank) == session
    session["practical_reviews"][0]["status"] = "reviewed"
    with pytest.raises(ValueError, match="incohérente"):
        domain.restore_session(domain.export_session(session), bank)


def test_practical_requires_real_nonempty_artifact_bytes(domain, bank):
    session = domain.new_session(bank, "learner_01")
    with pytest.raises(ValueError):
        domain.review_practical(
            session,
            bank,
            "queues",
            reviewer="teacher",
            rationale="Reviewed",
            scores={c: 3 for c in domain.PRACTICAL_WEIGHTS},
            artifacts={},
            safety_authorized=True,
            integrity_verified=True,
        )
    with pytest.raises(ValueError):
        domain.pack_artifacts({"../../escape": b"data"})


@pytest.mark.parametrize("collection", ["attempts", "reviews", "practical_reviews"])
def test_rejected_oversize_write_preserves_exportable_history(
    domain, bank, monkeypatch, collection
):
    session = domain.new_session(bank, "learner_01")
    attempt = domain.submit_attempt(
        session,
        bank,
        "queue_reasoning",
        {"response": "Reasoned answer"},
        mode="practice",
    )

    def append():
        if collection == "attempts":
            domain.submit_attempt(
                session,
                bank,
                "queue_reasoning",
                {"response": "Another answer"},
                mode="practice",
            )
        elif collection == "reviews":
            domain.review_attempt(
                session,
                bank,
                attempt["attempt_id"],
                reviewer="teacher",
                rationale="Checked",
                scores={"Mechanism": 3, "Limits": 2},
            )
        else:
            domain.review_practical(
                session,
                bank,
                "queues",
                reviewer="teacher",
                rationale="Checked",
                scores={c: 3 for c in domain.PRACTICAL_WEIGHTS},
                artifacts={"measurements.txt": b"0.2 seconds\n" * 100},
                safety_authorized=True,
                integrity_verified=True,
            )

    append()
    saved = domain.export_session(session)
    monkeypatch.setattr(domain, "MAX_SESSION_BYTES", len(saved) + 100)
    with pytest.raises(ValueError, match="dépasse"):
        append()
    assert domain.export_session(session) == saved
    assert domain.restore_session(saved, bank) == session


def test_classroom_exports_preserve_unavailable_diagnostic_subscores(
    domain, bank, tmp_path
):
    from learning_assessment.domain import classroom, diagnostic

    case = json.loads(
        (
            APP / "src/learning_assessment/sample_data/tescia_diagnostic_cases.json"
        ).read_text()
    )["cases"][0]
    rows = []
    unanswered = {k: v for k, v in case.items() if k != "student_answer"}
    for source in (case, unanswered, bank["cases"][0]):
        report = diagnostic.diagnose_case(source)
        row = classroom.classroom_progress_row(report)
        row["student_ref"] = "learner_01"
        assert row["root_cause_score"] is None
        if "question_assessment" in source or "student_answer" not in source:
            assert all(
                row[name] is None
                for name in (
                    "evidence_selection_score",
                    "fix_selection_score",
                    "regression_selection_score",
                )
            )
        rows.append(row)
    report = classroom.build_classroom_run_report_from_rows(rows)
    assert all(row["root_cause_score"] is None for row in report["progress_rows"])
    classroom.write_classroom_artifacts(report, tmp_path)
    restored = json.loads((tmp_path / "classroom_run_report.json").read_text())
    assert all(row["root_cause_score"] is None for row in restored["progress_rows"])


def test_explicit_source_upload_checks_hash_without_following_paths(domain, bank):
    assert domain.verify_sources(bank, {"book": b"synthetic"})
    with pytest.raises(ValueError, match="Source absente ou modifiée"):
        domain.verify_sources(bank, {"book": b"changed"})


def test_worker_export_keeps_program_version_source_and_attempt_identity(domain, bank):
    session = domain.new_session(bank, "learner_01")
    attempt = domain.submit_attempt(
        session, bank, "queue_reasoning", {"response": "My reasoning"}, mode="practice"
    )
    exported = domain.worker_submission(session, bank)
    assert (
        exported["assessment_program"]["version"]
        == bank["assessment_program"]["version"]
    )
    assert (
        exported["assessment_program"]["sources"]
        == bank["assessment_program"]["sources"]
    )
    case = exported["cases"][0]
    assert case["exercise_id"] == "queue_reasoning"
    assert case["student_ref"] == "learner_01"
    assert case["case_id"] == "attempt_" + attempt["attempt_id"]


def test_reducer_rejects_legacy_partials_without_a_graded_count(domain, bank):
    from agi_node.reduction import ReducePartial
    from learning_assessment.domain.diagnostic import diagnose_case, summarize_report
    from learning_assessment.runtime import reduction

    report = diagnose_case(bank["cases"][0])
    partial = reduction.partial_from_diagnostic_summary(
        summarize_report(report), partial_id="pending"
    )
    assert (
        reduction.build_reduce_artifact([partial]).payload["student_score_mean"] is None
    )
    legacy = {k: v for k, v in partial.payload.items() if k != "graded_count"}
    with pytest.raises(ValueError, match="graded_count"):
        reduction.build_reduce_artifact(
            [ReducePartial(partial_id="legacy", payload=legacy)]
        )


def test_external_program_uses_real_ui_and_records_blank_then_submitted_answer(
    domain, bank, tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from agi_web.testing import AppTest
    from learning_assessment.ui import app_surface

    source = tmp_path / "synthetic_network_program.json"
    source.write_text(json.dumps(bank))
    monkeypatch.setattr(
        app_surface,
        "_runtime_context",
        lambda _: (
            SimpleNamespace(),
            SimpleNamespace(data_in=tmp_path, files=source.name),
        ),
    )
    script = "from learning_assessment.ui import app_surface\napp_surface.render()\n"
    app = AppTest.from_string(script, default_timeout=30).run()
    assert not app.exception
    assert [t.label for t in app.tabs] == [
        "Catalogue",
        "Apprentissage",
        "Épreuves pratiques",
        "Progression et revue",
        "Couverture",
    ]
    response = next(t for t in app.text_area if t.label == "Votre raisonnement")
    assert response.value == ""
    assert not any("Student score" == m.label for m in app.metric)
    response.set_value("The bottleneck queue adds waiting time.")
    next(b for b in app.button if b.label == "Enregistrer ma réponse").click().run()
    assert not app.exception
    session_key = (
        "learning_program_"
        + domain.bank_fingerprint(bank)[:16]
        + "_session_"
        + domain.fingerprint("apprenant_01")[:16]
    )
    session = app.session_state[session_key]
    assert len(session["attempts"]) == 1
    assert session["attempts"][0]["evaluation"]["student_score"] is None
    assert session["attempts"][0]["context"]["program_version"] == "1"
    assert any("en attente de revue" in message.value for message in app.info)
    assert domain.restore_session(domain.export_session(session), bank) == session


def test_program_resume_rejects_malformed_attempt_without_replacing_progress(
    domain, bank
):
    from agi_web.testing import AppTest

    script = (
        "from learning_assessment.ui.program_learning import render_program\nrender_program("
        + repr(bank)
        + ")"
    )
    app = AppTest.from_string(script, default_timeout=30).run()
    assert not app.exception
    next(t for t in app.text_area if t.label == "Votre raisonnement").set_value(
        "My existing reasoning"
    )
    next(b for b in app.button if b.label == "Enregistrer ma réponse").click().run()
    assert not app.exception
    session_key = (
        "learning_program_"
        + domain.bank_fingerprint(bank)[:16]
        + "_session_"
        + domain.fingerprint("apprenant_01")[:16]
    )
    before = deepcopy(app.session_state[session_key])
    assert len(before["attempts"]) == 1
    malformed = domain.new_session(bank, "apprenant_01")
    malformed["attempts"] = [None]
    next(
        upload
        for upload in app.file_uploader
        if upload.label == "Dossier de progression JSON"
    ).upload(
        "learning_assessment_malformed_progression_fr.json",
        domain.export_session(malformed),
        "application/json",
    ).run()
    next(b for b in app.button if b.label == "Reprendre ce dossier").click().run()
    assert not app.exception
    assert any(
        "Reprise refusée" in message.value and "doit être un objet" in message.value
        for message in app.error
    )
    assert app.session_state[session_key] == before


def test_bundled_default_is_blank_and_example_is_an_explicit_choice(
    domain, monkeypatch
):
    from agi_web.testing import AppTest
    from learning_assessment.ui import app_surface

    monkeypatch.setattr(app_surface, "_runtime_context", lambda _: (None, None))
    app = AppTest.from_string(
        "from learning_assessment.ui.app_surface import render\nrender()",
        default_timeout=30,
    ).run()
    assert not app.exception
    assert app.selectbox(key="tescia_answer_mode").value == "Practice"
    assert (
        app.text_area(key="tescia_answer_root_cause_cluster_share_sshfs_Practice").value
        == ""
    )
    app.button(key="tescia_answer_evaluate").click().run()
    assert not app.exception
    assert not any(
        m.label in {"Student score", "Objective selections / 100"} for m in app.metric
    )
    app.selectbox(key="tescia_answer_mode").select("Worked example").run()
    assert app.text_area(
        key="tescia_answer_root_cause_cluster_share_sshfs_Worked example"
    ).value
    app.selectbox(key="tescia_answer_mode").select("Positioning").run()
    assert (
        app.text_area(
            key="tescia_answer_root_cause_cluster_share_sshfs_Positioning"
        ).value
        == ""
    )


def test_program_drafts_are_isolated_when_learner_or_session_changes(domain, bank):
    from agi_web.testing import AppTest

    script = (
        "from learning_assessment.ui.program_learning import render_program\nrender_program("
        + repr(bank)
        + ")"
    )
    app = AppTest.from_string(script, default_timeout=30).run()
    assert not app.exception
    next(t for t in app.text_area if t.label == "Votre raisonnement").set_value(
        "ALICE PRIVATE DRAFT"
    )
    next(
        t
        for t in app.text_area
        if t.label == "Vérifications réalisées, résultats négatifs et limites"
    ).set_value("ALICE PRIVATE EVIDENCE")
    next(
        t for t in app.checkbox if t.label == "Sécurité et autorisation vérifiées"
    ).check()
    app.run()
    next(t for t in app.text_input if t.label == "Pseudonyme de l'apprenant").set_value(
        "bob"
    ).run()
    assert not app.exception
    assert next(t for t in app.text_area if t.label == "Votre raisonnement").value == ""
    assert (
        next(
            t
            for t in app.text_area
            if t.label == "Vérifications réalisées, résultats négatifs et limites"
        ).value
        == ""
    )
    assert not next(
        t for t in app.checkbox if t.label == "Sécurité et autorisation vérifiées"
    ).value
    next(t for t in app.text_area if t.label == "Votre raisonnement").set_value(
        "BOB DRAFT"
    ).run()
    session_key = (
        "learning_program_"
        + domain.bank_fingerprint(bank)[:16]
        + "_session_"
        + domain.fingerprint("bob")[:16]
    )
    app.session_state[session_key] = domain.new_session(bank, "bob")
    app.run()
    assert not app.exception
    assert next(t for t in app.text_area if t.label == "Votre raisonnement").value == ""
    assert app.session_state[session_key]["attempts"] == []


def test_worker_mixed_graded_and_pending_answers_excludes_ungraded_from_mean(
    domain, bank, tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from learning_assessment_worker import learning_assessment_worker as module

    monkeypatch.setattr(module, "_runtime", {})
    session = domain.new_session(bank, "learner_01")
    domain.submit_attempt(
        session,
        bank,
        "queue_reasoning",
        {"response": "A causal explanation"},
        mode="practice",
    )
    domain.submit_attempt(
        session,
        bank,
        "delay_calculation",
        {"response": 0.2, "unit": "s"},
        mode="practice",
    )
    path = tmp_path / "network_program_submissions.json"
    path.write_bytes(domain.canonical_bytes(domain.worker_submission(session, bank)))
    worker = module.LearningAssessmentWorker()
    worker.args = SimpleNamespace(reset_target=False)
    worker.data_out = tmp_path / "reports"
    worker.artifact_dir = tmp_path / "artifacts"
    worker._worker_id = 0
    frame = worker.work_pool(path)
    reports = [json.loads(value) for value in frame["report_json"]]
    assert reports[0]["student_score"] is None
    assert reports[1]["student_score"] == 100
    assert (
        reports[0]["assessment_context"]["submission"]["original_bank_sha256"]
        == session["bank_sha256"]
    )
    worker.work_done(frame)
    summary = json.loads(
        (worker.data_out / "classroom/classroom_run_report.json").read_text()
    )
    assert summary["submission_count"] == 2
    assert summary["graded_count"] == 1
    assert summary["pending_review_count"] == 1
    assert summary["average_score"] == 100
    assert summary["progress_rows"][0]["student_score"] in (None, 100)
    assert summary["student_rows"][0]["graded_count"] == 1
    assert (
        "NaN"
        not in (worker.data_out / "classroom/classroom_run_report.json").read_text()
    )
