"""A replayable lesson around the existing drift decision evaluator."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .classroom import load_case_bank
from .diagnostic import evaluate_decision_policy

SCHEMA = "agilab.guided_lesson.v1"
LESSON_ID = "drift_decision"
CASE_ID = "data_scientist_2026_conformal_drift_uncertainty"
BASELINE = {"drift_score": 0.1, "empirical_coverage": 0.95}
MAX_EVIDENCE_BYTES = 100_000
PREDICTIONS = ("normal", "fallback")


def _encoded(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_encoded(value)).hexdigest()


def lesson_case() -> dict[str, Any]:
    """Use the bundled case and policy as the single teaching source."""
    return next(case for case in load_case_bank() if case["case_id"] == CASE_ID)


def _source() -> dict[str, str]:
    return {
        "case_id": CASE_ID,
        "case_sha256": _digest(lesson_case()),
        "evaluator_sha256": hashlib.sha256(
            Path(__file__).with_name("diagnostic.py").read_bytes()
        ).hexdigest(),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_lesson() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "lesson_id": LESSON_ID,
        "producer": "learning_assessment.domain.guided_lesson",
        "source": _source(),
        "started_at": _now(),
        "attempts": [],
        "explanation": "",
        "learner_mastery": "not_assessed",
    }


def _observations(value: Any) -> dict[str, float]:
    if not isinstance(value, dict) or set(value) != set(BASELINE):
        raise ValueError(
            "Observations must contain drift_score and empirical_coverage."
        )
    for number in value.values():
        if (
            type(number) not in (int, float)
            or not 0 <= number <= 1
            or not math.isfinite(number)
        ):
            raise ValueError(
                "Each observation must be a finite number between 0 and 1."
            )
    return {key: float(value[key]) for key in BASELINE}


def _decision(observations: dict[str, float]) -> dict[str, Any]:
    case = deepcopy(lesson_case())
    case["decision_policy"]["observations"] = observations
    return evaluate_decision_policy(case)


def _timestamp(value: Any) -> None:
    if not isinstance(value, str):
        raise ValueError("Lesson timestamps must be timezone-aware ISO timestamps.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Invalid lesson timestamp.") from exc
    if parsed.tzinfo is None:
        raise ValueError("Lesson timestamps must include a timezone.")


def validate_lesson(state: Any) -> dict[str, Any]:
    """Replay recorded decisions; reject stale sources and invalid progress."""
    expected = {
        "schema",
        "lesson_id",
        "producer",
        "source",
        "started_at",
        "attempts",
        "explanation",
        "learner_mastery",
    }
    if not isinstance(state, dict) or set(state) != expected:
        raise ValueError("Invalid guided lesson fields.")
    if (
        state["schema"] != SCHEMA
        or state["lesson_id"] != LESSON_ID
        or state["producer"] != "learning_assessment.domain.guided_lesson"
        or state["learner_mastery"] != "not_assessed"
    ):
        raise ValueError("Unsupported guided lesson or mastery claim.")
    if state["source"] != _source():
        raise ValueError(
            "The lesson source or evaluator changed. Start a new lesson; keep the old evidence."
        )
    _timestamp(state["started_at"])
    attempts = state["attempts"]
    if not isinstance(attempts, list) or len(attempts) > 2:
        raise ValueError("A lesson has one baseline and at most one changed run.")
    for index, attempt in enumerate(attempts):
        if not isinstance(attempt, dict) or set(attempt) != {
            "step",
            "observations",
            "prediction",
            "decision",
            "recorded_at",
        }:
            raise ValueError("Invalid lesson checkpoint fields.")
        step = ("baseline", "changed")[index]
        if attempt["step"] != step or attempt["prediction"] not in PREDICTIONS:
            raise ValueError(
                "Record a prediction before running each checkpoint in order."
            )
        observations = _observations(attempt["observations"])
        changes = sum(observations[key] != BASELINE[key] for key in BASELINE)
        if (index == 0 and changes != 0) or (index == 1 and changes != 1):
            raise ValueError("Run the baseline first, then change exactly one input.")
        _timestamp(attempt["recorded_at"])
        if _encoded(attempt["decision"]) != _encoded(_decision(observations)):
            raise ValueError("Recorded decision does not match replay of its inputs.")
    explanation = state["explanation"]
    if not isinstance(explanation, str) or len(explanation) > 4000:
        raise ValueError("Keep the explanation to 4000 characters or fewer.")
    if explanation and len(attempts) != 2:
        raise ValueError("Run both checkpoints before saving the explanation.")
    return deepcopy(state)


def run_checkpoint(
    state: dict[str, Any], observations: dict[str, float], prediction: str
) -> dict[str, Any]:
    """Record only a real evaluator invocation, with its prior prediction."""
    result = validate_lesson(state)
    if len(result["attempts"]) == 2:
        raise ValueError("Both runs are recorded. Start a new lesson to try again.")
    if prediction not in PREDICTIONS:
        raise ValueError("Choose a prediction before running the checkpoint.")
    observed = _observations(observations)
    index = len(result["attempts"])
    changes = sum(observed[key] != BASELINE[key] for key in BASELINE)
    if changes != index:
        raise ValueError("Run the baseline first, then change exactly one input.")
    result["attempts"].append(
        {
            "step": ("baseline", "changed")[index],
            "observations": observed,
            "prediction": prediction,
            "decision": _decision(observed),
            "recorded_at": _now(),
        }
    )
    return result


def save_explanation(state: dict[str, Any], explanation: str) -> dict[str, Any]:
    result = validate_lesson(state)
    if not isinstance(explanation, str) or not explanation.strip():
        raise ValueError(
            "Explain which threshold caused the decision to change or stay the same."
        )
    result["explanation"] = explanation.strip()
    return validate_lesson(result)


def lesson_progress(state: dict[str, Any]) -> dict[str, Any]:
    state = validate_lesson(state)
    attempts = state["attempts"]
    review = [
        attempt["step"]
        for attempt in attempts
        if attempt["prediction"] != attempt["decision"]["status"]
    ]
    completed = len(attempts) == 2 and bool(state["explanation"].strip())
    if review:
        practice = "Revisit the threshold comparisons, then predict an input exactly on a threshold."
    elif completed:
        practice = "Try the other input next. Predict whether equality with its threshold triggers review."
    else:
        practice = "Record both predictions and runs, then explain the comparison."
    return {
        "status": "completed" if completed else "in_progress",
        "recorded_runs": len(attempts),
        "review_queue": review,
        "next_practice": practice,
        "explanation_review": "pending" if state["explanation"] else "not_submitted",
        "learner_mastery": "not_assessed",
    }


def export_lesson(state: dict[str, Any]) -> bytes:
    state = validate_lesson(state)
    payload = {"lesson": state, "progress": lesson_progress(state)}
    return _encoded({"schema": SCHEMA, "sha256": _digest(payload), "payload": payload})


def import_lesson(data: bytes) -> dict[str, Any]:
    """Verify a portable progress file without trusting its completion claims."""
    if len(data) > MAX_EVIDENCE_BYTES:
        raise ValueError("Lesson evidence exceeds the 100 KB limit.")
    try:
        envelope = json.loads(data)
        if not isinstance(envelope, dict) or set(envelope) != {
            "schema",
            "sha256",
            "payload",
        }:
            raise ValueError("Invalid evidence envelope.")
        payload = envelope["payload"]
        if (
            envelope["schema"] != SCHEMA
            or not isinstance(payload, dict)
            or set(payload) != {"lesson", "progress"}
            or envelope["sha256"] != _digest(payload)
        ):
            raise ValueError("Lesson evidence schema or checksum does not match.")
        state = validate_lesson(payload["lesson"])
        if _encoded(payload["progress"]) != _encoded(lesson_progress(state)):
            raise ValueError("Progress does not match the recorded checkpoints.")
        return state
    except (KeyError, TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid guided lesson evidence.") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify", type=Path, required=True, help="Replay a downloaded lesson JSON."
    )
    args = parser.parse_args()
    try:
        with args.verify.open("rb") as source:
            state = import_lesson(source.read(MAX_EVIDENCE_BYTES + 1))
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Lesson verification failed: {exc}\n")
    print(
        json.dumps({"verification": "passed", **lesson_progress(state)}, sort_keys=True)
    )


if __name__ == "__main__":
    main()
