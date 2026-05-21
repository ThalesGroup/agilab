"""Deterministic TeSciA-style diagnostic scoring."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
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


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


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


def student_score(
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
    root_cause = str(case.get("root_cause", "")).strip()

    return {
        "schema": "agilab.tescia_diagnostic.report.v1",
        "case_id": str(case.get("case_id", "")),
        "symptom": str(case.get("symptom", "")),
        "proposed_diagnosis": str(case.get("proposed_diagnosis", "")),
        "root_cause": root_cause,
        "weak_assumptions": weak_assumptions,
        "evidence_quality": evidence_score,
        "regression_coverage": regression_score,
        "student_score": score,
        "status": status,
        "selected_fix": selected_fix,
        "ranked_fixes": ranked_fixes,
        "regression_plan": _as_list(case.get("regression_tests")),
        "plain_repro": str(case.get("plain_repro", "")),
        "thresholds": {
            "minimum_evidence_confidence": float(minimum_evidence_confidence),
            "minimum_regression_coverage": float(minimum_regression_coverage),
        },
    }


def summarize_report(report: Mapping[str, Any], *, worker_id: int = 0, source_file: str = "") -> dict[str, Any]:
    selected_fix = report.get("selected_fix", {})
    selected_fix_id = selected_fix.get("id", "") if isinstance(selected_fix, Mapping) else ""
    return {
        "schema": "agilab.tescia_diagnostic.summary.v1",
        "case_id": str(report.get("case_id", "")),
        "status": str(report.get("status", "")),
        "root_cause": str(report.get("root_cause", "")),
        "selected_fix_id": str(selected_fix_id),
        "evidence_quality": float(report.get("evidence_quality", 0.0)),
        "regression_coverage": float(report.get("regression_coverage", 0.0)),
        "student_score": float(report.get("student_score", 0.0)),
        "weak_assumption_count": len(_as_list(report.get("weak_assumptions"))),
        "regression_step_count": len(_as_list(report.get("regression_plan"))),
        "worker_id": int(worker_id),
        "source_file": source_file,
    }


__all__ = [
    "CASE_SCHEMA",
    "diagnose_case",
    "evidence_quality",
    "rank_candidate_fixes",
    "regression_coverage",
    "student_score",
    "summarize_report",
    "validate_case_payload",
]
