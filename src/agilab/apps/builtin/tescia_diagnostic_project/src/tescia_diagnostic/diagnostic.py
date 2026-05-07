"""Deterministic TeSciA-style diagnostic scoring."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


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
    "diagnose_case",
    "evidence_quality",
    "rank_candidate_fixes",
    "regression_coverage",
    "student_score",
    "summarize_report",
]
