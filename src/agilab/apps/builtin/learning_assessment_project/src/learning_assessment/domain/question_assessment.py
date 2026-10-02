"""Objective questions and reviewable open answers for external programmes.

Open reasoning is deliberately never graded by token overlap. This module has
no model, filesystem, network, or execution dependency.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import math
from typing import Any


QUESTION_SCHEMA = "agilab.learning_assessment.question.v1"


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonempty text.")
    return value


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number.")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f"{field} must be a finite number.")
    return float(value)


def validate_question_case(case: Mapping[str, Any]) -> None:
    for field in ("case_id", "title", "student_prompt"):
        _text(case.get(field), field)
    question = case.get("question_assessment")
    if not isinstance(question, Mapping) or question.get("schema") != QUESTION_SCHEMA:
        raise ValueError("Unsupported question_assessment schema.")
    kind = question.get("kind")
    if kind not in {"open_response", "numeric", "multiple_choice"}:
        raise ValueError("Unknown question kind.")
    _text(question.get("explanation"), "explanation")
    _text(question.get("remediation"), "remediation")
    if kind == "open_response":
        _text(question.get("reference_answer"), "reference_answer")
        criteria = question.get("criteria")
        if not isinstance(criteria, list) or not criteria:
            raise ValueError("Open responses need an explicit review rubric.")
        for criterion in criteria:
            _text(criterion, "criterion")
        if len(set(criteria)) != len(criteria):
            raise ValueError("Review criteria must be unique.")
    elif kind == "numeric":
        _number(question.get("expected"), "expected")
        _text(question.get("unit"), "unit (use '1' for dimensionless values)")
        for field in ("absolute_tolerance", "relative_tolerance"):
            if _number(question.get(field, 0), field) < 0:
                raise ValueError("Numeric tolerances cannot be negative.")
    else:
        choices = question.get("choices")
        if not isinstance(choices, Mapping) or len(choices) < 2:
            raise ValueError("Multiple choice questions need at least two choices.")
        for identity, label in choices.items():
            _text(identity, "choice id")
            _text(label, "choice label")
        expected = question.get("correct_choices")
        if (
            not isinstance(expected, list)
            or not expected
            or any(
                not isinstance(item, str) or item not in choices for item in expected
            )
            or len(set(expected)) != len(expected)
        ):
            raise ValueError("correct_choices must contain distinct known choice ids.")
    answer = case.get("student_answer")
    if answer is None:
        return
    if not isinstance(answer, Mapping) or set(answer) - {"response", "unit"}:
        raise ValueError("Question answers accept only response and unit.")
    response = answer.get("response")
    if response is None:
        return
    if kind == "open_response" and not isinstance(response, str):
        raise ValueError("Open response must be text.")
    if kind == "numeric":
        _number(response, "response")
        if not isinstance(answer.get("unit"), str):
            raise ValueError("Numeric answers require an explicit unit.")
    if kind == "multiple_choice" and (
        not isinstance(response, list)
        or any(
            not isinstance(item, str) or item not in question["choices"]
            for item in response
        )
        or len(set(response)) != len(response)
    ):
        raise ValueError("Response contains duplicate or unknown choices.")


def score_question(case: Mapping[str, Any]) -> dict[str, Any]:
    validate_question_case(case)
    question = case["question_assessment"]
    answer = case.get("student_answer") or {}
    response = answer.get("response")
    submitted = response is not None and response != "" and response != []
    score = None
    status = "not_submitted"
    feedback = ["Répondez avant de consulter la correction."]
    if submitted:
        if question["kind"] == "open_response":
            status = "pending_review"
            feedback = [
                "Réponse enregistrée. Le raisonnement attend une revue selon la grille."
            ]
        else:
            status = "graded"
            if question["kind"] == "numeric":
                correct = answer.get("unit", "").strip() == question[
                    "unit"
                ] and math.isclose(
                    response,
                    question["expected"],
                    rel_tol=question.get("relative_tolerance", 0),
                    abs_tol=question.get("absolute_tolerance", 0),
                )
            else:
                correct = set(response) == set(question["correct_choices"])
            score = 100.0 if correct else 0.0
            feedback = ["Réponse correcte." if correct else "Réponse à reprendre."]
    return {
        "schema": "agilab.learning_assessment.question_evaluation.v1",
        "status": status,
        "student_score": score,
        "score_band": ("excellent" if score == 100 else "needs_work")
        if score is not None
        else status,
        "learner_mastery": "not_assessed",
        "scores": {},
        "student": deepcopy(dict(answer)),
        "expected": deepcopy(dict(question)),
        "feedback": feedback,
        "remediation": question["remediation"],
    }
