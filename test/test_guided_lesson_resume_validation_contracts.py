"""Guided lesson imports reject malformed progress without changing the source."""

from copy import deepcopy
import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def lesson(monkeypatch):
    root = (
        Path(__file__).resolve().parents[1]
        / "src/agilab/apps/builtin/learning_assessment_project/src"
    )
    monkeypatch.syspath_prepend(str(root))
    return importlib.import_module("learning_assessment.domain.guided_lesson")


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("started_at", None, "timezone-aware"),
        ("started_at", "not-a-date", "Invalid lesson timestamp"),
        ("started_at", "2026-01-01T10:00:00", "include a timezone"),
        ("attempts", {}, "at most one changed run"),
        ("attempts", [None], "checkpoint fields"),
        ("attempts", [{}, {}, {}], "at most one changed run"),
        ("explanation", [], "4000 characters"),
        ("explanation", "x" * 4001, "4000 characters"),
        ("explanation", "Premature completion claim", "both checkpoints"),
        ("learner_mastery", "mastered", "mastery claim"),
    ],
)
def test_lesson_rejects_invalid_saved_state_shape(lesson, field, value, message):
    original = lesson.new_lesson()
    corrupted = deepcopy(original)
    corrupted[field] = value
    with pytest.raises(ValueError, match=message):
        lesson.validate_lesson(corrupted)
    assert original["attempts"] == []
    assert original["learner_mastery"] == "not_assessed"


@pytest.mark.parametrize(
    "observations",
    [
        None,
        [],
        {},
        {"drift_score": 0.1},
        {"drift_score": 0.1, "empirical_coverage": 0.95, "extra": 0.1},
    ],
)
def test_checkpoint_requires_exact_observation_contract(lesson, observations):
    state = lesson.new_lesson()
    with pytest.raises(ValueError, match="must contain"):
        lesson.run_checkpoint(state, observations, "normal")
    assert state["attempts"] == []


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("step", "changed", "checkpoint in order"),
        ("prediction", "guess", "checkpoint in order"),
        ("recorded_at", None, "timezone-aware"),
    ],
)
def test_lesson_rejects_invalid_checkpoint_metadata(lesson, field, value, message):
    state = lesson.run_checkpoint(lesson.new_lesson(), lesson.BASELINE, "normal")
    state["attempts"][0][field] = value
    with pytest.raises(ValueError, match=message):
        lesson.validate_lesson(state)


def test_lesson_rejects_replayed_baseline_with_changed_inputs(lesson):
    state = lesson.run_checkpoint(lesson.new_lesson(), lesson.BASELINE, "normal")
    state["attempts"][0]["observations"]["drift_score"] = 0.3
    with pytest.raises(ValueError, match="baseline first"):
        lesson.validate_lesson(state)


@pytest.mark.parametrize(
    "data",
    [
        b"[]",
        b"{}",
        b"null",
        b'{"schema":"other","payload":{},"sha256":"invalid"}',
        b"\xff",
    ],
)
def test_lesson_import_reports_invalid_envelopes(lesson, data):
    with pytest.raises(ValueError):
        lesson.import_lesson(data)


@pytest.mark.parametrize("input_state", ["valid", "missing", "malformed"])
def test_guided_lesson_cli_verifies_actual_file_and_reports_failures(
    lesson, monkeypatch, tmp_path, capsys, input_state
):
    path = tmp_path / "guided-lesson.json"
    if input_state == "valid":
        path.write_bytes(lesson.export_lesson(lesson.new_lesson()))
    elif input_state == "malformed":
        path.write_bytes(b"{")
    monkeypatch.setattr("sys.argv", ["guided_lesson", "--verify", str(path)])
    if input_state == "valid":
        lesson.main()
        result = json.loads(capsys.readouterr().out)
        assert result["verification"] == "passed"
        assert result["recorded_runs"] == 0
        assert result["learner_mastery"] == "not_assessed"
    else:
        with pytest.raises(SystemExit) as raised:
            lesson.main()
        assert raised.value.code == 1
        assert "Lesson verification failed" in capsys.readouterr().err
