"""Deterministic TeSciA-style diagnostic scoring."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import re
from typing import Any


CASE_SCHEMA = "agilab.tescia_diagnostic.cases.v1"

_REQUIRED_CASE_FIELDS = {
    "case_id",
    "symptom",
    "proposed_diagnosis",
    "root_cause",
    "plain_repro",
    "weak_assumptions",
    "evidence",
    "candidate_fixes",
    "regression_tests",
}

_STOPWORDS = {
    "after",
    "and",
    "are",
    "because",
    "before",
    "from",
    "into",
    "must",
    "needs",
    "not",
    "that",
    "the",
    "this",
    "through",
    "with",
}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _ids_from_rows(rows: Sequence[Mapping[str, Any]]) -> set[str]:
    return {str(row.get("id", "")).strip() for row in rows if str(row.get("id", "")).strip()}


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _safe_slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "student"


def _anonymized_student_ref(student_id: str, *, class_id: str = "", session_id: str = "") -> str:
    raw = f"{class_id.strip()}:{session_id.strip()}:{student_id.strip()}".encode("utf-8")
    return "student_" + hashlib.sha256(raw).hexdigest()[:12]


def _weighted_mean(rows: Sequence[Mapping[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return round(sum(_as_float(row.get(key)) for row in rows) / len(rows), 4)


def _require_float_range(value: Any, *, field: str, case_id: str) -> None:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Case {case_id!r} field {field!r} must be numeric.") from exc
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"Case {case_id!r} field {field!r} must be between 0.0 and 1.0.")


def _validate_string_list(value: Any, *, field: str, case_id: str, required: bool = False) -> None:
    if value is None and not required:
        return
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"Case {case_id!r} field {field!r} must be a list of non-empty strings.")


def _validate_student_answer(case: Mapping[str, Any], *, case_id: str) -> None:
    answer = case.get("student_answer")
    if answer is None:
        return
    if not isinstance(answer, Mapping):
        raise ValueError(f"Case {case_id!r} field 'student_answer' must be an object.")

    for field in ("diagnosis", "root_cause", "selected_fix_id"):
        if not str(answer.get(field, "")).strip():
            raise ValueError(f"Case {case_id!r} student_answer.{field} must be a non-empty string.")
    _validate_string_list(answer.get("evidence_ids"), field="student_answer.evidence_ids", case_id=case_id, required=True)
    _validate_string_list(
        answer.get("regression_test_ids"),
        field="student_answer.regression_test_ids",
        case_id=case_id,
        required=True,
    )
    if "confidence" in answer:
        _require_float_range(answer.get("confidence"), field="student_answer.confidence", case_id=case_id)

    evidence_ids = _ids_from_rows([row for row in _as_list(case.get("evidence")) if isinstance(row, Mapping)])
    fix_ids = _ids_from_rows([row for row in _as_list(case.get("candidate_fixes")) if isinstance(row, Mapping)])
    test_ids = _ids_from_rows([row for row in _as_list(case.get("regression_tests")) if isinstance(row, Mapping)])

    unknown_evidence = sorted(set(_as_string_list(answer.get("evidence_ids"))) - evidence_ids)
    unknown_tests = sorted(set(_as_string_list(answer.get("regression_test_ids"))) - test_ids)
    selected_fix_id = str(answer.get("selected_fix_id", "")).strip()
    if unknown_evidence:
        raise ValueError(f"Case {case_id!r} student_answer references unknown evidence ids: {', '.join(unknown_evidence)}.")
    if selected_fix_id not in fix_ids:
        raise ValueError(f"Case {case_id!r} student_answer references unknown selected_fix_id: {selected_fix_id}.")
    if unknown_tests:
        raise ValueError(
            f"Case {case_id!r} student_answer references unknown regression test ids: {', '.join(unknown_tests)}."
        )


def validate_case_payload(payload: Mapping[str, Any], *, expected_case_count: int | None = None) -> dict[str, Any]:
    """Validate a TeSciA case file and return a normalized payload."""

    if payload.get("schema") != CASE_SCHEMA:
        raise ValueError(f"Diagnostic cases must declare schema {CASE_SCHEMA!r}.")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Diagnostic cases must include a non-empty cases list.")
    if expected_case_count is not None and len(cases) != expected_case_count:
        raise ValueError(f"Diagnostic cases contain {len(cases)} case(s), expected {expected_case_count}.")

    normalized_cases: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            raise ValueError(f"Case #{index + 1} must be an object.")
        case_id = str(case.get("case_id", f"case_{index + 1}"))
        missing = sorted(field for field in _REQUIRED_CASE_FIELDS if field not in case)
        if missing:
            raise ValueError(f"Case {case_id!r} is missing fields: {', '.join(missing)}.")

        evidence = case.get("evidence")
        fixes = case.get("candidate_fixes")
        tests = case.get("regression_tests")
        if not isinstance(evidence, list) or len(evidence) < 2:
            raise ValueError(f"Case {case_id!r} must include at least two evidence items.")
        if not isinstance(fixes, list) or len(fixes) < 2:
            raise ValueError(f"Case {case_id!r} must include at least two candidate fixes.")
        if not isinstance(tests, list) or len(tests) < 2:
            raise ValueError(f"Case {case_id!r} must include at least two regression tests.")
        _validate_string_list(case.get("curriculum_ids"), field="curriculum_ids", case_id=case_id)
        _validate_string_list(case.get("topic_tags"), field="topic_tags", case_id=case_id)
        for optional_field in ("class_id", "session_id", "student_id", "student_ref", "exercise_id", "submitted_at"):
            if optional_field in case and not str(case.get(optional_field, "")).strip():
                raise ValueError(f"Case {case_id!r} field {optional_field!r} must be a non-empty string when provided.")
        if "anonymize_student" in case and not isinstance(case.get("anonymize_student"), bool):
            raise ValueError(f"Case {case_id!r} field 'anonymize_student' must be a boolean when provided.")
        if "difficulty" in case:
            difficulty = str(case.get("difficulty", "")).strip()
            if difficulty not in {"intro", "intermediate", "advanced"}:
                raise ValueError(f"Case {case_id!r} field 'difficulty' must be intro, intermediate, or advanced.")
        if "estimated_minutes" in case:
            minutes = int(_as_float(case.get("estimated_minutes"), -1))
            if minutes <= 0 or minutes > 180:
                raise ValueError(f"Case {case_id!r} field 'estimated_minutes' must be between 1 and 180.")

        for row in evidence:
            if not isinstance(row, Mapping):
                raise ValueError(f"Case {case_id!r} has invalid evidence.")
            _require_float_range(row.get("confidence"), field="evidence.confidence", case_id=case_id)
            _require_float_range(row.get("relevance"), field="evidence.relevance", case_id=case_id)
        for fix in fixes:
            if not isinstance(fix, Mapping):
                raise ValueError(f"Case {case_id!r} has invalid candidate fix.")
            _require_float_range(fix.get("expected_impact"), field="fix.expected_impact", case_id=case_id)
            _require_float_range(fix.get("blast_radius"), field="fix.blast_radius", case_id=case_id)
            _require_float_range(fix.get("reversibility"), field="fix.reversibility", case_id=case_id)
        _validate_student_answer(case, case_id=case_id)

        normalized_cases.append(dict(case))

    return {"schema": CASE_SCHEMA, "cases": normalized_cases}


def evidence_quality(case: Mapping[str, Any]) -> float:
    evidence = [row for row in _as_list(case.get("evidence")) if isinstance(row, Mapping)]
    if not evidence:
        return 0.0
    confidence = _weighted_mean(evidence, "confidence")
    relevance = _weighted_mean(evidence, "relevance")
    return round((confidence * 0.6) + (relevance * 0.4), 4)


def regression_coverage(case: Mapping[str, Any]) -> float:
    tests = [row for row in _as_list(case.get("regression_tests")) if isinstance(row, Mapping)]
    if not tests:
        return 0.0
    discriminators = sum(1 for row in tests if bool(row.get("discriminator")))
    automated = sum(1 for row in tests if bool(row.get("automated")))
    return round(((discriminators / len(tests)) * 0.65) + ((automated / len(tests)) * 0.35), 4)


def _fix_score(fix: Mapping[str, Any], evidence_score: float, regression_score: float) -> float:
    impact = _as_float(fix.get("expected_impact"))
    blast_radius = _as_float(fix.get("blast_radius"))
    reversibility = _as_float(fix.get("reversibility"), 0.5)
    return round(
        (impact * 0.38)
        + (evidence_score * 0.25)
        + (regression_score * 0.22)
        + ((1.0 - blast_radius) * 0.1)
        + (reversibility * 0.05),
        4,
    )


def rank_candidate_fixes(
    case: Mapping[str, Any],
    *,
    evidence_score: float,
    regression_score: float,
) -> list[dict[str, Any]]:
    fixes = [row for row in _as_list(case.get("candidate_fixes")) if isinstance(row, Mapping)]
    ranked = []
    for fix in fixes:
        ranked.append(
            {
                "id": str(fix.get("id", "")),
                "summary": str(fix.get("summary", "")),
                "expected_impact": _as_float(fix.get("expected_impact")),
                "blast_radius": _as_float(fix.get("blast_radius")),
                "reversibility": _as_float(fix.get("reversibility"), 0.5),
                "score": _fix_score(fix, evidence_score, regression_score),
            }
        )
    return sorted(ranked, key=lambda row: (-row["score"], row["blast_radius"], row["id"]))


def case_quality_score(
    *,
    evidence_score: float,
    regression_score: float,
    selected_fix: Mapping[str, Any],
    actionable: bool,
) -> float:
    """Return a readable 0-100 score for the diagnostic exercise."""

    fix_score = _as_float(selected_fix.get("score")) if selected_fix else 0.0
    gate_bonus = 1.0 if actionable else 0.0
    return round(
        (
            (evidence_score * 0.35)
            + (regression_score * 0.3)
            + (fix_score * 0.25)
            + (gate_bonus * 0.1)
        )
        * 100,
        1,
    )


def _token_set(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_'-]{3,}", value.lower())
        if token not in _STOPWORDS
    }


def _text_overlap_score(student_text: str, reference_text: str) -> float:
    reference_tokens = _token_set(reference_text)
    if not reference_tokens:
        return 0.0
    student_tokens = _token_set(student_text)
    return round(len(student_tokens & reference_tokens) / len(reference_tokens), 4)


def _selection_score(selected_ids: Sequence[str], expected_ids: Sequence[str]) -> float:
    expected = set(expected_ids)
    if not expected:
        return 0.0
    selected = set(selected_ids)
    return round(len(selected & expected) / len(expected), 4)


def _score_band(score: float) -> str:
    if score >= 85.0:
        return "excellent"
    if score >= 70.0:
        return "solid"
    if score >= 50.0:
        return "partial"
    return "needs_work"


def catalog_metadata(case: Mapping[str, Any]) -> dict[str, Any]:
    """Return user-facing exercise metadata for catalog/self-evaluation views."""

    return {
        "title": str(case.get("title") or case.get("case_id") or "").strip(),
        "difficulty": str(case.get("difficulty", "intermediate")).strip() or "intermediate",
        "topic_tags": _as_string_list(case.get("topic_tags")),
        "curriculum_ids": _as_string_list(case.get("curriculum_ids")),
        "estimated_minutes": int(_as_float(case.get("estimated_minutes"), 20)),
        "learner_level": str(case.get("learner_level", "engineering student")).strip() or "engineering student",
        "student_prompt": str(case.get("student_prompt") or case.get("symptom") or "").strip(),
    }


def classroom_metadata(case: Mapping[str, Any]) -> dict[str, Any]:
    """Return privacy-aware classroom metadata for a submitted answer."""

    class_id = str(case.get("class_id", "")).strip()
    session_id = str(case.get("session_id", "")).strip()
    student_id = str(case.get("student_id", "")).strip()
    student_ref = str(case.get("student_ref", "")).strip()
    anonymize = _as_bool(case.get("anonymize_student"), default=bool(student_id))
    if not student_ref and student_id:
        student_ref = (
            _anonymized_student_ref(student_id, class_id=class_id, session_id=session_id)
            if anonymize
            else _safe_slug(student_id)
        )
    metadata = {
        "class_id": class_id,
        "session_id": session_id,
        "student_ref": student_ref,
        "exercise_id": str(case.get("exercise_id") or case.get("case_id") or "").strip(),
        "submitted_at": str(case.get("submitted_at", "")).strip(),
        "anonymized": anonymize,
    }
    if student_id and not anonymize:
        metadata["student_id"] = student_id
    display_name = str(case.get("display_name", "")).strip()
    if display_name and not anonymize:
        metadata["display_name"] = display_name
    return metadata


def evaluate_student_answer(
    case: Mapping[str, Any],
    *,
    ranked_fixes: Sequence[Mapping[str, Any]],
    evidence_score: float,
    regression_score: float,
) -> dict[str, Any]:
    """Score a submitted student answer against the deterministic case rubric."""

    answer = case.get("student_answer")
    expected_evidence = [
        str(row.get("id", "")).strip()
        for row in _as_list(case.get("evidence"))
        if isinstance(row, Mapping) and _as_float(row.get("relevance")) >= 0.8 and str(row.get("id", "")).strip()
    ]
    if not expected_evidence:
        expected_evidence = sorted(_ids_from_rows([row for row in _as_list(case.get("evidence")) if isinstance(row, Mapping)]))
    expected_tests = [
        str(row.get("id", "")).strip()
        for row in _as_list(case.get("regression_tests"))
        if isinstance(row, Mapping) and bool(row.get("discriminator")) and str(row.get("id", "")).strip()
    ]
    expected_fix_id = str(ranked_fixes[0].get("id", "")) if ranked_fixes else ""
    expected = {
        "root_cause": str(case.get("root_cause", "")),
        "evidence_ids": expected_evidence,
        "selected_fix_id": expected_fix_id,
        "regression_test_ids": expected_tests,
    }
    if not isinstance(answer, Mapping):
        return {
            "schema": "agilab.tescia_diagnostic.self_evaluation.v1",
            "status": "not_submitted",
            "student_score": 0.0,
            "score_band": "not_submitted",
            "scores": {
                "root_cause": 0.0,
                "evidence_selection": 0.0,
                "fix_selection": 0.0,
                "regression_selection": 0.0,
                "confidence_calibration": 0.0,
            },
            "expected": expected,
            "student": {},
            "feedback": [
                "Submit a student_answer with root_cause, evidence_ids, selected_fix_id, and regression_test_ids.",
            ],
        }

    student_evidence = _as_string_list(answer.get("evidence_ids"))
    student_tests = _as_string_list(answer.get("regression_test_ids"))
    student_fix = str(answer.get("selected_fix_id", "")).strip()
    confidence = _as_float(answer.get("confidence"), 0.5)
    reference_quality = round((evidence_score + regression_score + _as_float(ranked_fixes[0].get("score")) if ranked_fixes else 0.0) / 3, 4)
    scores = {
        "root_cause": _text_overlap_score(str(answer.get("root_cause", "")), str(case.get("root_cause", ""))),
        "evidence_selection": _selection_score(student_evidence, expected_evidence),
        "fix_selection": 1.0 if student_fix == expected_fix_id and expected_fix_id else 0.0,
        "regression_selection": _selection_score(student_tests, expected_tests),
        "confidence_calibration": round(max(0.0, 1.0 - abs(confidence - reference_quality)), 4),
    }
    score = round(
        (
            (scores["root_cause"] * 0.25)
            + (scores["evidence_selection"] * 0.25)
            + (scores["fix_selection"] * 0.25)
            + (scores["regression_selection"] * 0.20)
            + (scores["confidence_calibration"] * 0.05)
        )
        * 100,
        1,
    )
    feedback = []
    if scores["root_cause"] < 0.65:
        feedback.append("Root cause explanation misses important reference terms.")
    if scores["evidence_selection"] < 1.0:
        missing = sorted(set(expected_evidence) - set(student_evidence))
        feedback.append(f"Evidence selection is incomplete; missing: {', '.join(missing)}.")
    if scores["fix_selection"] < 1.0:
        feedback.append(f"Selected fix should be {expected_fix_id!r}.")
    if scores["regression_selection"] < 1.0:
        missing = sorted(set(expected_tests) - set(student_tests))
        feedback.append(f"Regression plan is incomplete; missing: {', '.join(missing)}.")
    if not feedback:
        feedback.append("Answer is aligned with the reference diagnostic contract.")

    return {
        "schema": "agilab.tescia_diagnostic.self_evaluation.v1",
        "status": "submitted",
        "student_score": score,
        "score_band": _score_band(score),
        "scores": scores,
        "expected": expected,
        "student": {
            "diagnosis": str(answer.get("diagnosis", "")),
            "root_cause": str(answer.get("root_cause", "")),
            "evidence_ids": student_evidence,
            "selected_fix_id": student_fix,
            "regression_test_ids": student_tests,
            "confidence": confidence,
        },
        "feedback": feedback,
    }


def student_score(
    *,
    evidence_score: float,
    regression_score: float,
    selected_fix: Mapping[str, Any],
    actionable: bool,
) -> float:
    """Case-quality score used when no student answer exists."""

    return case_quality_score(
        evidence_score=evidence_score,
        regression_score=regression_score,
        selected_fix=selected_fix,
        actionable=actionable,
    )


def diagnose_case(
    case: Mapping[str, Any],
    *,
    minimum_evidence_confidence: float = 0.65,
    minimum_regression_coverage: float = 0.6,
) -> dict[str, Any]:
    """Build a repeatable diagnostic recommendation for one case."""

    evidence_score = evidence_quality(case)
    regression_score = regression_coverage(case)
    ranked_fixes = rank_candidate_fixes(
        case,
        evidence_score=evidence_score,
        regression_score=regression_score,
    )
    selected_fix = ranked_fixes[0] if ranked_fixes else {}
    weak_assumptions = [
        str(item)
        for item in _as_list(case.get("weak_assumptions"))
        if str(item).strip()
    ]
    confidence_gate = evidence_score >= minimum_evidence_confidence
    regression_gate = regression_score >= minimum_regression_coverage
    status = "actionable" if confidence_gate and regression_gate and selected_fix else "needs_more_evidence"
    score = student_score(
        evidence_score=evidence_score,
        regression_score=regression_score,
        selected_fix=selected_fix,
        actionable=status == "actionable",
    )
    self_evaluation = evaluate_student_answer(
        case,
        ranked_fixes=ranked_fixes,
        evidence_score=evidence_score,
        regression_score=regression_score,
    )
    has_student_answer = self_evaluation["status"] == "submitted"
    root_cause = str(case.get("root_cause", "")).strip()

    return {
        "schema": "agilab.tescia_diagnostic.report.v1",
        "case_id": str(case.get("case_id", "")),
        "catalog": catalog_metadata(case),
        "classroom": classroom_metadata(case),
        "symptom": str(case.get("symptom", "")),
        "proposed_diagnosis": str(case.get("proposed_diagnosis", "")),
        "root_cause": root_cause,
        "weak_assumptions": weak_assumptions,
        "evidence_quality": evidence_score,
        "regression_coverage": regression_score,
        "case_quality_score": score,
        "student_score": self_evaluation["student_score"] if has_student_answer else score,
        "status": status,
        "selected_fix": selected_fix,
        "ranked_fixes": ranked_fixes,
        "regression_plan": _as_list(case.get("regression_tests")),
        "self_evaluation": self_evaluation,
        "plain_repro": str(case.get("plain_repro", "")),
        "thresholds": {
            "minimum_evidence_confidence": float(minimum_evidence_confidence),
            "minimum_regression_coverage": float(minimum_regression_coverage),
        },
    }


def summarize_report(report: Mapping[str, Any], *, worker_id: int = 0, source_file: str = "") -> dict[str, Any]:
    selected_fix = report.get("selected_fix", {})
    selected_fix_id = selected_fix.get("id", "") if isinstance(selected_fix, Mapping) else ""
    catalog = report.get("catalog", {})
    if not isinstance(catalog, Mapping):
        catalog = {}
    self_evaluation = report.get("self_evaluation", {})
    if not isinstance(self_evaluation, Mapping):
        self_evaluation = {}
    classroom = report.get("classroom", {})
    if not isinstance(classroom, Mapping):
        classroom = {}
    feedback = _as_list(self_evaluation.get("feedback"))
    return {
        "schema": "agilab.tescia_diagnostic.summary.v1",
        "case_id": str(report.get("case_id", "")),
        "class_id": str(classroom.get("class_id", "")),
        "session_id": str(classroom.get("session_id", "")),
        "student_ref": str(classroom.get("student_ref", "")),
        "exercise_id": str(classroom.get("exercise_id", "")),
        "submitted_at": str(classroom.get("submitted_at", "")),
        "case_title": str(catalog.get("title", "")),
        "difficulty": str(catalog.get("difficulty", "")),
        "topic_tags": ",".join(_as_string_list(catalog.get("topic_tags"))),
        "curriculum_ids": ",".join(_as_string_list(catalog.get("curriculum_ids"))),
        "status": str(report.get("status", "")),
        "root_cause": str(report.get("root_cause", "")),
        "selected_fix_id": str(selected_fix_id),
        "evidence_quality": float(report.get("evidence_quality", 0.0)),
        "regression_coverage": float(report.get("regression_coverage", 0.0)),
        "case_quality_score": float(report.get("case_quality_score", report.get("student_score", 0.0))),
        "student_score": float(report.get("student_score", 0.0)),
        "self_evaluation_status": str(self_evaluation.get("status", "not_submitted")),
        "self_evaluation_band": str(self_evaluation.get("score_band", "not_submitted")),
        "feedback_count": len(feedback),
        "weak_assumption_count": len(_as_list(report.get("weak_assumptions"))),
        "regression_step_count": len(_as_list(report.get("regression_plan"))),
        "worker_id": int(worker_id),
        "source_file": source_file,
    }


__all__ = [
    "CASE_SCHEMA",
    "catalog_metadata",
    "case_quality_score",
    "classroom_metadata",
    "diagnose_case",
    "evidence_quality",
    "evaluate_student_answer",
    "rank_candidate_fixes",
    "regression_coverage",
    "student_score",
    "summarize_report",
    "validate_case_payload",
]
