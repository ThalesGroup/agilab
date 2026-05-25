"""Classroom batch scoring helpers for TeSciA."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from .diagnostic import classroom_metadata, diagnose_case, validate_case_payload


CLASSROOM_SCHEMA = "agilab.tescia_diagnostic.classroom.v1"


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _as_string(value: Any) -> str:
    return str(value or "").strip()


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _safe_slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "submission"


def anonymized_student_ref(
    student_id: str,
    *,
    class_id: str = "",
    session_id: str = "",
    length: int = 12,
) -> str:
    """Return a deterministic non-reversible student reference for teacher artifacts."""

    raw = f"{class_id.strip()}:{session_id.strip()}:{student_id.strip()}".encode("utf-8")
    return "student_" + hashlib.sha256(raw).hexdigest()[: max(6, length)]


def default_case_bank_path() -> Path:
    return Path(__file__).resolve().parent / "sample_data" / "tescia_diagnostic_cases.json"


def default_classroom_payload_path() -> Path:
    return Path(__file__).resolve().parent / "sample_data" / "tescia_classroom_submissions.json"


def load_case_bank(path: str | Path | None = None) -> list[dict[str, Any]]:
    source = Path(path) if path is not None else default_case_bank_path()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"TeSciA case bank must be a JSON object: {source}")
    return list(validate_case_payload(payload)["cases"])


def load_classroom_payload(path: str | Path | None = None) -> dict[str, Any]:
    source = Path(path) if path is not None else default_classroom_payload_path()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"TeSciA classroom submissions must be a JSON object: {source}")
    return validate_classroom_payload(payload)


def validate_classroom_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a classroom submission batch without requiring the case bank."""

    if payload.get("schema") != CLASSROOM_SCHEMA:
        raise ValueError(f"Classroom submissions must declare schema {CLASSROOM_SCHEMA!r}.")

    classroom = dict(_as_mapping(payload.get("classroom")))
    class_id = _as_string(classroom.get("class_id"))
    session_id = _as_string(classroom.get("session_id"))
    if not class_id:
        raise ValueError("Classroom submissions must declare classroom.class_id.")
    if not session_id:
        raise ValueError("Classroom submissions must declare classroom.session_id.")

    submissions = payload.get("submissions")
    if not isinstance(submissions, list) or not submissions:
        raise ValueError("Classroom submissions must include a non-empty submissions list.")

    normalized: list[dict[str, Any]] = []
    seen_submission_ids: set[str] = set()
    for index, submission in enumerate(submissions, start=1):
        if not isinstance(submission, Mapping):
            raise ValueError(f"Classroom submission #{index} must be an object.")
        student_id = _as_string(submission.get("student_id"))
        case_id = _as_string(submission.get("case_id"))
        answer = submission.get("answer")
        if not student_id:
            raise ValueError(f"Classroom submission #{index} must declare student_id.")
        if not case_id:
            raise ValueError(f"Classroom submission #{index} must declare case_id.")
        if not isinstance(answer, Mapping):
            raise ValueError(f"Classroom submission #{index} must declare answer as an object.")
        submission_id = _as_string(submission.get("submission_id")) or f"{student_id}_{case_id}"
        if submission_id in seen_submission_ids:
            raise ValueError(f"Duplicate classroom submission_id: {submission_id}")
        seen_submission_ids.add(submission_id)
        normalized.append(
            {
                "submission_id": submission_id,
                "student_id": student_id,
                "display_name": _as_string(submission.get("display_name")),
                "case_id": case_id,
                "submitted_at": _as_string(submission.get("submitted_at")),
                "answer": dict(answer),
                "class_id": _as_string(submission.get("class_id")) or class_id,
                "session_id": _as_string(submission.get("session_id")) or session_id,
                "anonymize_student": _as_bool(
                    submission.get("anonymize_student"),
                    default=_as_bool(classroom.get("anonymize_student"), default=True),
                ),
            }
        )

    result: dict[str, Any] = {
        "schema": CLASSROOM_SCHEMA,
        "classroom": {
            "class_id": class_id,
            "session_id": session_id,
            "anonymize_student": _as_bool(classroom.get("anonymize_student"), default=True),
        },
        "submissions": normalized,
    }
    case_bank = payload.get("case_bank")
    if isinstance(case_bank, Mapping):
        result["case_bank"] = validate_case_payload(case_bank)
    return result


def _case_bank_by_id(cases: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    case_bank: dict[str, dict[str, Any]] = {}
    for case in cases:
        case_id = _as_string(case.get("case_id"))
        if case_id:
            case_bank[case_id] = dict(case)
    return case_bank


def expand_classroom_submissions(
    payload: Mapping[str, Any],
    case_bank: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Merge submission answers with their referenced exercises."""

    validated = validate_classroom_payload(payload)
    if case_bank is None:
        embedded_case_bank = validated.get("case_bank")
        cases = (
            list(embedded_case_bank["cases"])
            if isinstance(embedded_case_bank, Mapping)
            else load_case_bank()
        )
    else:
        cases = [dict(case) for case in case_bank]
    by_id = _case_bank_by_id(cases)

    expanded: list[dict[str, Any]] = []
    for submission in validated["submissions"]:
        exercise_id = str(submission["case_id"])
        if exercise_id not in by_id:
            raise ValueError(f"Classroom submission references unknown case_id: {exercise_id}")
        base_case = dict(by_id[exercise_id])
        class_id = str(submission["class_id"])
        session_id = str(submission["session_id"])
        student_id = str(submission["student_id"])
        anonymize = bool(submission["anonymize_student"])
        student_ref = (
            anonymized_student_ref(student_id, class_id=class_id, session_id=session_id)
            if anonymize
            else _safe_slug(student_id)
        )
        submission_id = _safe_slug(str(submission["submission_id"]))
        base_case.update(
            {
                "case_id": submission_id,
                "exercise_id": exercise_id,
                "student_answer": dict(submission["answer"]),
                "class_id": class_id,
                "session_id": session_id,
                "student_ref": student_ref,
                "submitted_at": str(submission.get("submitted_at", "")),
                "anonymize_student": anonymize,
            }
        )
        if not anonymize:
            base_case["student_id"] = student_id
            if submission.get("display_name"):
                base_case["display_name"] = str(submission["display_name"])
        expanded.append(base_case)

    return validate_case_payload({"schema": "agilab.tescia_diagnostic.cases.v1", "cases": expanded})["cases"]


def _report_classroom(report: Mapping[str, Any]) -> Mapping[str, Any]:
    return _as_mapping(report.get("classroom"))


def classroom_progress_row(report: Mapping[str, Any]) -> dict[str, Any]:
    classroom = _report_classroom(report)
    catalog = _as_mapping(report.get("catalog"))
    self_eval = _as_mapping(report.get("self_evaluation"))
    scores = _as_mapping(self_eval.get("scores"))
    feedback = _as_list(self_eval.get("feedback"))
    return {
        "class_id": _as_string(classroom.get("class_id")),
        "session_id": _as_string(classroom.get("session_id")),
        "student_ref": _as_string(classroom.get("student_ref")),
        "exercise_id": _as_string(classroom.get("exercise_id")),
        "submission_id": _as_string(report.get("case_id")),
        "submitted_at": _as_string(classroom.get("submitted_at")),
        "title": _as_string(catalog.get("title")),
        "difficulty": _as_string(catalog.get("difficulty")),
        "curriculum_ids": ",".join(str(item) for item in _as_list(catalog.get("curriculum_ids"))),
        "student_score": float(report.get("student_score", 0.0)),
        "score_band": _as_string(self_eval.get("score_band")),
        "feedback_count": len(feedback),
        "needs_attention": bool(float(report.get("student_score", 0.0)) < 70.0 or len(feedback) > 1),
        "root_cause_score": float(scores.get("root_cause", 0.0) or 0.0),
        "evidence_selection_score": float(scores.get("evidence_selection", 0.0) or 0.0),
        "fix_selection_score": float(scores.get("fix_selection", 0.0) or 0.0),
        "regression_selection_score": float(scores.get("regression_selection", 0.0) or 0.0),
    }


def _average(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 1) if values else 0.0


def _aggregate_rows(rows: Sequence[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for raw_key in str(row.get(key, "")).split(","):
            item_key = raw_key.strip()
            if item_key:
                grouped[item_key].append(row)
    result = []
    for item_key, item_rows in sorted(grouped.items()):
        scores = [float(row["student_score"]) for row in item_rows]
        result.append(
            {
                key: item_key,
                "submission_count": len(item_rows),
                "average_score": _average(scores),
                "needs_attention_count": sum(1 for row in item_rows if bool(row["needs_attention"])),
            }
        )
    return result


def build_classroom_run_report(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build a teacher-facing aggregate from scored diagnostic reports."""

    classroom_reports = [
        report
        for report in reports
        if _as_string(_report_classroom(report).get("student_ref"))
    ]
    rows = sorted(
        (classroom_progress_row(report) for report in classroom_reports),
        key=lambda row: (row["class_id"], row["session_id"], row["student_ref"], row["exercise_id"]),
    )
    score_values = [float(row["student_score"]) for row in rows]
    band_counts = Counter(str(row["score_band"]) for row in rows)
    heatmap_rows = [
        {
            "student_ref": row["student_ref"],
            "exercise_id": row["exercise_id"],
            "student_score": row["student_score"],
            "score_band": row["score_band"],
        }
        for row in rows
    ]
    needs_attention = [row for row in rows if bool(row["needs_attention"])]
    unique_students = sorted({str(row["student_ref"]) for row in rows if row["student_ref"]})
    class_ids = sorted({str(row["class_id"]) for row in rows if row["class_id"]})
    session_ids = sorted({str(row["session_id"]) for row in rows if row["session_id"]})
    return {
        "schema": "agilab.tescia_diagnostic.classroom_run_report.v1",
        "class_ids": class_ids,
        "session_ids": session_ids,
        "submission_count": len(rows),
        "unique_student_count": len(unique_students),
        "average_score": _average(score_values),
        "score_band_counts": dict(sorted(band_counts.items())),
        "needs_attention_count": len(needs_attention),
        "progress_rows": rows,
        "heatmap_rows": heatmap_rows,
        "needs_attention_rows": needs_attention,
        "case_rows": _aggregate_rows(rows, key="exercise_id"),
        "curriculum_rows": _aggregate_rows(rows, key="curriculum_ids"),
        "cluster_execution": {
            "parallel_unit": "classroom submission",
            "submission_count": len(rows),
            "recommended_worker_count": min(max(len(unique_students), 1), max(len(rows), 1), 32),
        },
    }


def score_classroom_submissions(
    payload: Mapping[str, Any],
    case_bank: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    cases = expand_classroom_submissions(payload, case_bank=case_bank)
    reports = [diagnose_case(case) for case in cases]
    return build_classroom_run_report(reports)


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(str(key))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_classroom_artifacts(
    reports_or_report: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    output_dir: str | Path,
) -> dict[str, Path]:
    """Write teacher-facing classroom JSON/CSV artifacts."""

    if isinstance(reports_or_report, Mapping) and reports_or_report.get("schema") == "agilab.tescia_diagnostic.classroom_run_report.v1":
        report = dict(reports_or_report)
    elif isinstance(reports_or_report, Mapping):
        report = build_classroom_run_report([reports_or_report])
    else:
        report = build_classroom_run_report(reports_or_report)

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    paths = {
        "report": root / "classroom_run_report.json",
        "teacher_summary": root / "classroom_teacher_summary.md",
        "progress": root / "classroom_progress.csv",
        "heatmap": root / "classroom_heatmap.csv",
        "needs_attention": root / "classroom_needs_attention.csv",
        "curriculum": root / "classroom_curriculum.csv",
    }
    paths["report"].write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    paths["teacher_summary"].write_text(classroom_report_to_markdown(report), encoding="utf-8")
    _write_csv(paths["progress"], report["progress_rows"])
    _write_csv(paths["heatmap"], report["heatmap_rows"])
    _write_csv(paths["needs_attention"], report["needs_attention_rows"])
    _write_csv(paths["curriculum"], report["curriculum_rows"])
    return paths


def _markdown_table(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> list[str]:
    if not rows:
        return ["No rows."]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return lines


def classroom_report_to_markdown(report: Mapping[str, Any]) -> str:
    """Render a printable teacher summary for one classroom run."""

    class_ids = ", ".join(str(item) for item in _as_list(report.get("class_ids"))) or "unknown"
    session_ids = ", ".join(str(item) for item in _as_list(report.get("session_ids"))) or "unknown"
    band_counts = _as_mapping(report.get("score_band_counts"))
    curriculum_rows = sorted(
        [dict(row) for row in _as_list(report.get("curriculum_rows")) if isinstance(row, Mapping)],
        key=lambda row: (float(row.get("average_score", 0.0) or 0.0), str(row.get("curriculum_ids", ""))),
    )
    case_rows = sorted(
        [dict(row) for row in _as_list(report.get("case_rows")) if isinstance(row, Mapping)],
        key=lambda row: (float(row.get("average_score", 0.0) or 0.0), str(row.get("exercise_id", ""))),
    )
    needs_attention = [
        dict(row)
        for row in _as_list(report.get("needs_attention_rows"))
        if isinstance(row, Mapping)
    ]
    lines = [
        "# TeSciA Classroom Teacher Summary",
        "",
        f"- Class: `{class_ids}`",
        f"- Session: `{session_ids}`",
        f"- Submissions: `{report.get('submission_count', 0)}`",
        f"- Students: `{report.get('unique_student_count', 0)}`",
        f"- Average score: `{report.get('average_score', 0.0)}`",
        f"- Needs attention: `{report.get('needs_attention_count', 0)}`",
        "",
        "## Score Bands",
        "",
    ]
    if band_counts:
        for band, count in sorted(band_counts.items()):
            lines.append(f"- `{band}`: {count}")
    else:
        lines.append("- No submitted answers.")
    lines.extend(
        [
            "",
            "## Needs Attention",
            "",
            *_markdown_table(
                needs_attention,
                ["student_ref", "exercise_id", "student_score", "score_band"],
            ),
            "",
            "## Weakest Curriculum Areas",
            "",
            *_markdown_table(
                curriculum_rows[:8],
                ["curriculum_ids", "submission_count", "average_score", "needs_attention_count"],
            ),
            "",
            "## Suggested Next Exercise Ids",
            "",
        ]
    )
    if case_rows:
        for row in case_rows[:8]:
            lines.append(
                f"- `{row.get('exercise_id', '')}` "
                f"(average `{row.get('average_score', 0.0)}`, "
                f"attention `{row.get('needs_attention_count', 0)}`)"
            )
    else:
        lines.append("- No exercise evidence yet.")
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "CLASSROOM_SCHEMA",
    "anonymized_student_ref",
    "build_classroom_run_report",
    "classroom_report_to_markdown",
    "classroom_metadata",
    "classroom_progress_row",
    "default_case_bank_path",
    "default_classroom_payload_path",
    "expand_classroom_submissions",
    "load_case_bank",
    "load_classroom_payload",
    "score_classroom_submissions",
    "validate_classroom_payload",
    "write_classroom_artifacts",
]
