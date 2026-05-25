"""Printable TeSciA report exports."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _bullet_lines(values: Sequence[Any], *, fallback: str = "None") -> str:
    rows = [str(value).strip() for value in values if str(value).strip()]
    if not rows:
        return f"- {fallback}"
    return "\n".join(f"- {row}" for row in rows)


def _json_block(value: Any) -> str:
    return "```json\n" + json.dumps(value, indent=2, sort_keys=True) + "\n```"


def diagnostic_report_to_markdown(report: Mapping[str, Any]) -> str:
    """Render one diagnostic report as a printable correction sheet."""

    catalog = report.get("catalog", {})
    if not isinstance(catalog, Mapping):
        catalog = {}
    self_eval = report.get("self_evaluation", {})
    if not isinstance(self_eval, Mapping):
        self_eval = {}
    expected = self_eval.get("expected", {})
    if not isinstance(expected, Mapping):
        expected = {}
    student = self_eval.get("student", {})
    if not isinstance(student, Mapping):
        student = {}
    selected_fix = report.get("selected_fix", {})
    if not isinstance(selected_fix, Mapping):
        selected_fix = {}

    title = str(catalog.get("title") or report.get("case_id") or "TeSciA correction")
    lines = [
        f"# {title}",
        "",
        f"- Case id: `{report.get('case_id', '')}`",
        f"- Difficulty: `{catalog.get('difficulty', '')}`",
        f"- Student score: `{report.get('student_score', 0.0)}`",
        f"- Score band: `{self_eval.get('score_band', 'not_submitted')}`",
        f"- Case quality score: `{report.get('case_quality_score', 0.0)}`",
        "",
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
        "## Weak Assumptions",
        "",
        _bullet_lines(_as_list(report.get("weak_assumptions")), fallback="No weak assumptions recorded."),
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
    case_id = str(report.get("case_id") or "tescia_case").strip() or "tescia_case"
    safe_stem = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in case_id)
    output_path = Path(output_dir) / f"{safe_stem}_correction.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(diagnostic_report_to_markdown(report), encoding="utf-8")
    return output_path


def write_correction_index(paths: Sequence[Path], output_dir: str | Path) -> Path:
    output_path = Path(output_dir) / "correction_sheets_index.md"
    lines = ["# TeSciA Correction Sheets", ""]
    for path in sorted(paths):
        lines.append(f"- [{path.name}]({path.name})")
    lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


__all__ = [
    "diagnostic_report_to_markdown",
    "write_correction_index",
    "write_correction_sheet",
]
