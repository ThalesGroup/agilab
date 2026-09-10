from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

APP_SRC = (
    Path(__file__).resolve().parents[1]
    / "src/agilab/apps/builtin/learning_assessment_project/src"
)


@pytest.fixture
def lesson(monkeypatch):
    monkeypatch.syspath_prepend(str(APP_SRC))
    return importlib.import_module("learning_assessment.domain.guided_lesson")


def baseline(lesson, prediction="normal"):
    return lesson.run_checkpoint(lesson.new_lesson(), dict(lesson.BASELINE), prediction)


@pytest.mark.parametrize(
    ("metric", "value", "expected"),
    [
        ("drift_score", 0.2, "normal"),
        ("drift_score", 0.21, "fallback"),
        ("empirical_coverage", 0.9, "normal"),
        ("empirical_coverage", 0.89, "fallback"),
    ],
)
def test_real_policy_boundaries_and_portable_completion(
    lesson, metric, value, expected
):
    original = lesson.lesson_case()
    state = baseline(lesson)
    observations = {**lesson.BASELINE, metric: value}
    state = lesson.run_checkpoint(state, observations, expected)
    assert state["attempts"][1]["decision"]["status"] == expected
    assert lesson.lesson_progress(state)["status"] == "in_progress"
    state = lesson.save_explanation(
        state, "Equality does not cross either strict threshold."
    )
    assert lesson.lesson_progress(state) == {
        "status": "completed",
        "recorded_runs": 2,
        "review_queue": [],
        "next_practice": "Try the other input next. Predict whether equality with its threshold triggers review.",
        "explanation_review": "pending",
        "learner_mastery": "not_assessed",
    }
    assert lesson.import_lesson(lesson.export_lesson(state)) == state
    assert lesson.lesson_case() == original


def test_prediction_mistakes_route_to_practice_without_claiming_mastery(lesson):
    state = baseline(lesson, "fallback")
    assert lesson.lesson_progress(state)["review_queue"] == ["baseline"]
    assert lesson.import_lesson(lesson.export_lesson(state)) == state
    state = lesson.run_checkpoint(
        state, {**lesson.BASELINE, "drift_score": 0.4}, "normal"
    )
    state = lesson.save_explanation(state, "I overlooked the drift threshold.")
    progress = lesson.lesson_progress(state)
    assert progress["review_queue"] == ["baseline", "changed"]
    assert progress["learner_mastery"] == "not_assessed"
    assert "Revisit" in progress["next_practice"]


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), True, "0.3", -0.1, 1.1, 10**500]
)
def test_invalid_observations_do_not_record_an_execution(lesson, value):
    state = baseline(lesson)
    original = deepcopy(state)
    with pytest.raises(ValueError, match="finite number"):
        lesson.run_checkpoint(
            state, {**lesson.BASELINE, "drift_score": value}, "normal"
        )
    assert state == original


def test_checkpoint_order_and_one_input_change_are_required(lesson):
    empty = lesson.new_lesson()
    with pytest.raises(ValueError, match="prediction"):
        lesson.run_checkpoint(empty, dict(lesson.BASELINE), "")
    with pytest.raises(ValueError, match="baseline first"):
        lesson.run_checkpoint(empty, {**lesson.BASELINE, "drift_score": 0.3}, "normal")
    with pytest.raises(ValueError, match="both checkpoints"):
        lesson.save_explanation(empty, "A proposed explanation")
    state = baseline(lesson)
    for observations in (
        dict(lesson.BASELINE),
        {"drift_score": 0.3, "empirical_coverage": 0.8},
    ):
        with pytest.raises(ValueError, match="exactly one"):
            lesson.run_checkpoint(state, observations, "fallback")
    state = lesson.run_checkpoint(
        state, {**lesson.BASELINE, "drift_score": 0.3}, "fallback"
    )
    with pytest.raises(ValueError, match="Both runs"):
        lesson.run_checkpoint(state, dict(lesson.BASELINE), "normal")
    with pytest.raises(ValueError, match="Explain"):
        lesson.save_explanation(state, "  ")


def _rehash(lesson, envelope):
    envelope["sha256"] = lesson._digest(envelope["payload"])
    return json.dumps(envelope).encode()


def test_evidence_rejects_checksum_replayed_decision_and_false_progress(lesson):
    original = json.loads(lesson.export_lesson(baseline(lesson)))
    damaged = deepcopy(original)
    damaged["payload"]["lesson"]["attempts"][0]["prediction"] = "fallback"
    with pytest.raises(ValueError, match="checksum"):
        lesson.import_lesson(json.dumps(damaged).encode())
    damaged = deepcopy(original)
    damaged["payload"]["lesson"]["attempts"][0]["decision"]["status"] = "fallback"
    with pytest.raises(ValueError, match="replay"):
        lesson.import_lesson(_rehash(lesson, damaged))
    damaged = deepcopy(original)
    damaged["payload"]["progress"]["status"] = "completed"
    with pytest.raises(ValueError, match="Progress"):
        lesson.import_lesson(_rehash(lesson, damaged))
    damaged = deepcopy(original)
    damaged["payload"]["lesson"]["learner_mastery"] = "mastered"
    with pytest.raises(ValueError, match="mastery"):
        lesson.import_lesson(_rehash(lesson, damaged))
    damaged = deepcopy(original)
    damaged["payload"]["lesson"]["attempts"][0]["observations"]["drift_score"] = 10**500
    with pytest.raises(ValueError, match="finite number"):
        lesson.import_lesson(_rehash(lesson, damaged))


def test_source_drift_and_polluted_saved_progress_are_not_silently_accepted(
    lesson, monkeypatch, tmp_path
):
    data = lesson.export_lesson(baseline(lesson))
    unrelated = Path.home() / ".agilab" / "LEARNING.md"
    unrelated.parent.mkdir(exist_ok=True)
    unrelated.write_text("All lessons mastered", encoding="utf-8")
    assert lesson.new_lesson()["attempts"] == []
    assert unrelated.read_text() == "All lessons mastered"
    source = lesson._source()
    monkeypatch.setattr(lesson, "_source", lambda: {**source, "case_sha256": "changed"})
    with pytest.raises(ValueError, match="source or evaluator changed"):
        lesson.import_lesson(data)


@pytest.mark.parametrize(
    "data", [b"[]", b"null", b"{}", b"not json", b"\xff", b"x" * 100_001]
)
def test_bad_resume_files_are_actionable(lesson, data):
    with pytest.raises(ValueError):
        lesson.import_lesson(data)


def test_documented_verifier_reports_pass_and_invalid_input(lesson, tmp_path):
    evidence = tmp_path / "lesson.json"
    evidence.write_bytes(lesson.export_lesson(baseline(lesson)))
    command = [
        sys.executable,
        "-m",
        "learning_assessment.domain.guided_lesson",
        "--verify",
        str(evidence),
    ]
    env = {**os.environ, "PYTHONPATH": str(APP_SRC)}
    passed = subprocess.run(
        command, cwd=tmp_path, env=env, text=True, capture_output=True
    )
    assert passed.returncode == 0, passed.stderr
    result = json.loads(passed.stdout)
    assert result["verification"] == "passed"
    assert result["status"] == "in_progress"
    evidence.write_text("{}", encoding="utf-8")
    failed = subprocess.run(
        command, cwd=tmp_path, env=env, text=True, capture_output=True
    )
    assert failed.returncode == 1
    assert "Lesson verification failed" in failed.stderr
    assert "Traceback" not in failed.stderr


def _element(elements, label):
    return next(element for element in elements if element.label == label)


def test_guided_browser_state_requires_predictions_and_survives_reruns(lesson):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(
        "from learning_assessment.ui.guided_lesson import render_guided_lesson\nrender_guided_lesson()",
        default_timeout=30,
    ).run()
    assert not app.exception
    assert _element(app.button, "Run baseline").disabled
    assert not app.dataframe
    _element(app.selectbox, "Predicted action").select("normal").run()
    _element(app.button, "Run baseline").click().run()
    assert not app.exception
    assert _element(app.button, "Run changed input").disabled
    _element(app.number_input, "Drift score").set_value(0.3).run()
    _element(app.selectbox, "Predicted action").select("fallback").run()
    _element(app.button, "Run changed input").click().run()
    assert not app.exception
    assert (
        not app.selectbox
    )  # Predictions and inputs are recorded, not editable after the run.
    _element(app.button, "Save explanation").click().run()
    assert app.error
    app.text_area[0].set_value("Drift crossed 0.2; equality would keep serving.")
    _element(app.button, "Save explanation").click().run()
    app.run()
    assert not app.exception
    assert any("Lesson recorded" in success.value for success in app.success)
    prefix = "guided_lesson_" + hashlib.sha256(b"bundled").hexdigest()[:12]
    state = app.session_state[prefix + "_progress"]
    assert lesson.import_lesson(lesson.export_lesson(state)) == state
    assert len(state["attempts"]) == 2
    _element(app.button, "Start a new lesson").click().run()
    assert not app.exception
    restarted = app.session_state[prefix + "_progress"]
    assert restarted["attempts"] == []
    assert restarted["explanation"] == ""
    assert _element(app.button, "Run baseline").disabled
    assert not app.text_area
    assert not app.success
    assert len(state["attempts"]) == 2  # Restart leaves exported progress intact.


def test_progress_is_scoped_to_active_project(lesson):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(
        "from pathlib import Path\nimport streamlit as st\n"
        "from learning_assessment.ui.guided_lesson import render_guided_lesson\n"
        "project = st.selectbox('Project', ['project_a', 'project_b'])\n"
        "render_guided_lesson(Path(project))",
        default_timeout=30,
    ).run()
    _element(app.selectbox, "Predicted action").select("normal").run()
    _element(app.button, "Run baseline").click().run()
    _element(app.selectbox, "Project").select("project_b").run()
    assert not app.exception
    assert _element(app.button, "Run baseline").disabled
    _element(app.selectbox, "Project").select("project_a").run()
    assert not app.exception
    assert _element(app.button, "Run changed input").disabled


def test_resuming_earlier_export_rehydrates_explanation_widgets(lesson, monkeypatch):
    from streamlit.testing.v1 import AppTest

    upload = [None]
    monkeypatch.setattr("streamlit.file_uploader", lambda *args, **kwargs: upload[0])
    state = lesson.run_checkpoint(
        baseline(lesson), {**lesson.BASELINE, "drift_score": 0.3}, "fallback"
    )
    earlier = lesson.save_explanation(state, "Earlier saved explanation")
    later = lesson.save_explanation(state, "Later saved explanation")
    app = AppTest.from_string(
        "from learning_assessment.ui.guided_lesson import render_guided_lesson\nrender_guided_lesson()",
        default_timeout=30,
    )
    prefix = "guided_lesson_" + hashlib.sha256(b"bundled").hexdigest()[:12]
    app.session_state[prefix + "_progress"] = later
    app.run()
    assert app.text_area[0].value == "Later saved explanation"
    upload[0] = io.BytesIO(lesson.export_lesson(earlier))
    app.run()
    _element(app.button, "Resume lesson").click().run()
    assert not app.exception
    assert app.text_area[0].value == "Earlier saved explanation"
    _element(app.button, "Save explanation").click().run()
    assert app.session_state[prefix + "_progress"] == earlier
