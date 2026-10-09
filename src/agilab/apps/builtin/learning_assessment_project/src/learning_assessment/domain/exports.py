"""Printable TeSciA report exports."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def case_artifact_stem(case_id: str) -> str:
    """Keep canonical IDs readable and preserve every other ID in a stable name.

    Hashed names use a reserved separator and lowercase ASCII so distinct IDs
    remain distinct on case-insensitive and Unicode-normalizing filesystems.
    The bounded prefix also leaves room for the worker's report suffixes.
    """
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError("case_id must be a non-empty string for artifact export")
    if len(case_id) <= 96 and re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", case_id):
        return case_id
    prefix = re.sub(r"[^a-z0-9_-]+", "_", case_id.lower()).strip("_-")
    prefix = prefix[:48] or "tescia_case"
    return f"{prefix}~{hashlib.sha256(case_id.encode('utf-8')).hexdigest()}"


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _bullet_lines(values: Sequence[Any], *, fallback: str = "None") -> str:
    rows = [str(value).strip() for value in values if str(value).strip()]
    if not rows:
        return f"- {fallback}"
    return "\n".join(f"- {row}" for row in rows)


def _json_block(value: Any) -> str:
    return "```json\n" + json.dumps(value, indent=2, sort_keys=True) + "\n```"


def _education_markdown(catalog: Mapping[str, Any]) -> list[str]:
    trace = catalog.get("education_trace", {})
    if not isinstance(trace, Mapping) or not trace:
        return []
    lines = [
        "## Traçabilité pédagogique",
        "",
        f"- Niveau : {trace.get('stage_label', '')}",
        f"- Cours : {trace.get('course_title', '')} (`{trace.get('course_id', '')}`)",
        f"- Chapitre : {trace.get('section_id', '')} — {trace.get('section_title', '')}",
        f"- Type : {trace.get('course_kind', '')} / {trace.get('assessment_kind', '')}",
        "- Notions : " + " ; ".join(n["label"] for n in trace.get("notions", [])),
        f"- Révision des sources et questions : `{trace.get('source_revision', '')}`",
    ]
    for source in trace.get("sources", []):
        lines.append(
            f"- Source : [{source['title']}]({source['url']}) ; revue le {source['reviewed_on']}"
        )
        if source.get("scope"):
            lines.append(f"  {source['scope']}")
    lines.append("")
    return lines


def _academic_report_markdown(report: Mapping[str, Any]) -> str:
    catalog = report["catalog"]
    evaluation = report["self_evaluation"]
    lines = [
        f"# {catalog['title']}",
        "",
        f"- Exercice : `{report['case_id']}`",
        f"- Note : {report['student_score']}/100",
        f"- Réponses : {evaluation['answered_count']}/{evaluation['question_count']}",
        f"- Réponses correctes : {evaluation['correct_count']}/{evaluation['question_count']}",
        f"- Statut : {evaluation['status']}",
        "",
        "Chaque question a le même poids. Une réponse incorrecte ou absente vaut zéro.",
        "Exercices originaux Learning & Assessment ; ce ne sont pas des sujets officiels ENSAE.",
        "",
        *_education_markdown(catalog),
    ]
    for result in evaluation["question_results"]:
        lines.extend(
            [
                f"## {result['question_id']}",
                "",
                result["prompt"],
                "",
                f"- Votre réponse : {result['submitted_text'] or 'Non répondue'}",
                f"- Résultat : {'Correct' if result['correct'] else 'À retravailler'}",
                f"- Réponse attendue : {result['correct_text']}",
                f"- Notions : {', '.join(result['notion_ids'])}",
                "",
                result["explanation"],
                "",
            ]
        )
    return "\n".join(lines)


def diagnostic_report_to_markdown(report: Mapping[str, Any]) -> str:
    """Render one diagnostic report as a printable correction sheet."""

    catalog = report.get("catalog", {})
    if not isinstance(catalog, Mapping):
        catalog = {}
    self_eval = report.get("self_evaluation", {})
    if not isinstance(self_eval, Mapping):
        self_eval = {}
    if catalog.get("assessment_kind") == "objective_questions":
        return _academic_report_markdown(report)
    expected = self_eval.get("expected", {})
    if not isinstance(expected, Mapping):
        expected = {}
    student = self_eval.get("student", {})
    if not isinstance(student, Mapping):
        student = {}
    selected_fix = report.get("selected_fix", {})
    if not isinstance(selected_fix, Mapping):
        selected_fix = {}
    decision = report.get("decision", {})
    if not isinstance(decision, Mapping):
        decision = {}

    title = str(catalog.get("title") or report.get("case_id") or "TeSciA correction")
    if self_eval.get("schema") == "agilab.learning_assessment.question_evaluation.v1":
        return "\n".join(
            [
                f"# {title}",
                "",
                str(catalog.get("student_prompt", "")),
                "",
                f"Statut : {self_eval.get('status')}",
                f"Note automatique : {self_eval.get('student_score') if self_eval.get('student_score') is not None else 'non évaluée'}",
                "",
                "## Réponse",
                "",
                _json_block(student),
                "",
                "## Correction et critères",
                "",
                _json_block(expected),
                "",
                "## Travail conseillé",
                "",
                str(self_eval.get("remediation", "")),
                "",
            ]
        )
    lines = [
        f"# {title}",
        "",
        f"- Case id: `{report.get('case_id', '')}`",
        f"- Learning path: `{catalog.get('learning_track_label', '')}`",
        f"- Difficulty: `{catalog.get('difficulty', '')}`",
        f"- Student score: `{report.get('student_score') if report.get('student_score') is not None else 'not assessed'}`",
        f"- Objective selections only: `{self_eval.get('objective_score', 'not assessed')}`",
        f"- Score band: `{self_eval.get('score_band', 'not_submitted')}`",
        f"- Case quality score: `{report.get('case_quality_score', 0.0)}`",
        "",
        *_education_markdown(catalog),
        "## Exercise",
        "",
        str(catalog.get("student_prompt") or report.get("symptom", "")),
        "",
        "## Student Answer",
        "",
        _json_block(student),
        "",
        "## Feedback",
        "",
        _bullet_lines(_as_list(self_eval.get("feedback")), fallback="No feedback."),
        "",
        "## Reference",
        "",
        f"- Root cause: {report.get('root_cause', '')}",
        f"- Selected fix: `{selected_fix.get('id', '')}` - {selected_fix.get('summary', '')}",
        f"- Expected evidence ids: `{', '.join(str(item) for item in _as_list(expected.get('evidence_ids')))}`",
        f"- Expected regression test ids: `{', '.join(str(item) for item in _as_list(expected.get('regression_test_ids')))}`",
        "",
        "## Deterministic Decision Guard",
        "",
        f"- Status: `{decision.get('status', 'not_configured')}`",
        f"- Action: `{decision.get('action', '')}`",
        f"- Triggers: `{', '.join(str(item) for item in _as_list(decision.get('triggers')))}`",
        "",
        "## Weak Assumptions",
        "",
        _bullet_lines(
            _as_list(report.get("weak_assumptions")),
            fallback="No weak assumptions recorded.",
        ),
        "",
        "## Regression Plan",
        "",
        _bullet_lines(
            [
                f"{row.get('id', '')}: {row.get('description', '')}"
                for row in _as_list(report.get("regression_plan"))
                if isinstance(row, Mapping)
            ],
            fallback="No regression plan recorded.",
        ),
        "",
    ]
    return "\n".join(lines)


def write_correction_sheet(report: Mapping[str, Any], output_dir: str | Path) -> Path:
    """Export a sheet, retaining the legacy default only for an absent case ID."""
    case_id = report.get("case_id")
    safe_stem = case_artifact_stem("tescia_case" if case_id is None else case_id)
    output_path = Path(output_dir) / f"{safe_stem}_correction.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(diagnostic_report_to_markdown(report), encoding="utf-8")
    return output_path


def write_correction_index(paths: Sequence[Path], output_dir: str | Path) -> Path:
    output_path = Path(output_dir) / "correction_sheets_index.md"
    lines = ["# Learning & Assessment Correction Sheets", ""]
    for path in sorted(paths):
        lines.append(f"- [{path.name}]({path.name})")
    lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


__all__ = [
    "case_artifact_stem",
    "diagnostic_report_to_markdown",
    "write_correction_index",
    "write_correction_sheet",
]
