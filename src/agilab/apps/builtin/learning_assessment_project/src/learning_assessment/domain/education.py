"""Course provenance, objective grading and chapter coverage for school pathways."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .curriculum import load_math_program_2026

REGISTRY_SCHEMA = "agilab.learning_assessment.engineering_course_sources.v1"
ASSESSMENT_SCHEMA = "agilab.learning_assessment.academic_assessment.v1"
STAGE_LABELS = {
    "college": "Collège",
    "lycee": "Lycée",
    "engineering_school": "École d'ingénieur",
    "transversal": "Transversal",
}
_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TRACE_FIELDS = (
    "education_stage",
    "education_stage_label",
    "education_course_id",
    "education_course_title",
    "education_section_id",
    "education_section_title",
    "education_notion_ids",
    "education_notion_labels",
    "education_source_urls",
    "education_reviewed_on",
    "education_source_revision",
    "education_course_kind",
    "assessment_kind",
)


def registry_path() -> Path:
    return (
        _PACKAGE_ROOT / "curriculum" / "engineering_course_assessments_fr_sources.json"
    )


def source_revision(course: Mapping[str, Any]) -> str:
    """Bind the syllabus, questions and answer key to a reproducible revision."""
    serialized = json.dumps(
        course, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _unique_ids(rows: Any, location: str) -> set[str]:
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{location} must be a non-empty list.")
    ids: set[str] = set()
    for row in rows:
        if (
            not isinstance(row, Mapping)
            or not isinstance(row.get("id"), str)
            or not row["id"].strip()
        ):
            raise ValueError(f"{location} requires non-empty string ids.")
        if row["id"] in ids:
            raise ValueError(f"{location} contains duplicate id {row['id']!r}.")
        ids.add(row["id"])
    return ids


def validate_course_registry(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != REGISTRY_SCHEMA:
        raise ValueError("Unsupported engineering course registry schema.")
    course_ids = _unique_ids(payload.get("courses"), "courses")
    for course in payload["courses"]:
        location = f"Course {course['id']}"
        if course.get("education_stage") != "engineering_school" or not course.get(
            "title"
        ):
            raise ValueError(
                f"{location} requires an engineering-school stage and title."
            )
        source = course.get("source", {})
        if not isinstance(source, Mapping):
            raise ValueError(f"{location} requires a source.")
        kind = course.get("course_kind", "syllabus")
        if kind not in {"syllabus", "extra"}:
            raise ValueError(f"{location} has an unknown course kind.")
        hosts = (
            {"www.ensae.fr", "synapses.polytechnique.fr", "synapses.ensta-paris.fr"}
            if kind == "syllabus"
            else {"ocw.mit.edu", "homomorphicencryption.org"}
        )
        url = urlparse(str(source.get("url", "")))
        if url.scheme != "https" or url.hostname not in hosts:
            raise ValueError(f"{location} requires an authoritative source URL.")
        prerequisites = course.get("prerequisite_course_ids", [])
        if not isinstance(prerequisites, list) or any(
            not isinstance(ref, str) or ref not in course_ids or ref == course["id"]
            for ref in prerequisites
        ):
            raise ValueError(f"{location} has unknown prerequisite course ids.")
        date.fromisoformat(str(source.get("reviewed_on", "")))
        _unique_ids(course.get("sections"), f"{location} sections")
        for section in course["sections"]:
            if not section.get("title"):
                raise ValueError(f"{location} section requires a title.")
            notion_ids = _unique_ids(section.get("notions"), f"{location} notions")
            if any(not n.get("label") for n in section["notions"]):
                raise ValueError(f"{location} notions require labels.")
            _unique_ids(section.get("questions"), f"{location} questions")
            if len(section["questions"]) < 2:
                raise ValueError(
                    f"{location} requires at least two questions per section."
                )
            covered: set[str] = set()
            for question in section["questions"]:
                refs = question.get("notion_ids")
                if (
                    not isinstance(refs, list)
                    or not refs
                    or any(
                        not isinstance(ref, str) or ref not in notion_ids
                        for ref in refs
                    )
                ):
                    raise ValueError(
                        f"{location} question has unknown or empty notion ids."
                    )
                choices = question.get("choices")
                if (
                    not isinstance(choices, Mapping)
                    or len(choices) < 3
                    or any(
                        not isinstance(k, str)
                        or not k
                        or not isinstance(v, str)
                        or not v.strip()
                        for k, v in choices.items()
                    )
                    or len(set(choices.values())) != len(choices)
                ):
                    raise ValueError(
                        f"{location} question requires distinct labelled choices."
                    )
                if question.get("correct_choice") not in choices:
                    raise ValueError(
                        f"{location} question has an unknown correct choice."
                    )
                if not question.get("prompt") or not question.get("explanation"):
                    raise ValueError(
                        f"{location} questions require prompts and explanations."
                    )
                covered.update(refs)
            if covered != notion_ids:
                raise ValueError(f"{location} section has notions without questions.")


@lru_cache(maxsize=1)
def load_course_registry() -> dict[str, Any]:
    payload = json.loads(registry_path().read_text(encoding="utf-8"))
    validate_course_registry(payload)
    return payload


@lru_cache(maxsize=1)
def _school_curriculum() -> dict[str, Any]:
    return load_math_program_2026()


def resolve_academic_assessment(
    case: Mapping[str, Any], registry: Mapping[str, Any] | None = None
) -> tuple[Mapping[str, Any], Mapping[str, Any], list[Mapping[str, Any]]]:
    assessment = case.get("academic_assessment")
    if (
        not isinstance(assessment, Mapping)
        or assessment.get("schema") != ASSESSMENT_SCHEMA
    ):
        raise ValueError("Academic assessment requires a supported schema.")
    if case.get("learning_track") != "engineering_ensae":
        raise ValueError("Academic assessment requires the ENSAE learning track.")
    registry = registry if registry is not None else load_course_registry()
    course = next(
        (c for c in registry["courses"] if c["id"] == assessment.get("course_id")), None
    )
    if course is None:
        raise ValueError("Academic assessment references an unknown course.")
    if assessment.get("source_revision") != source_revision(course):
        raise ValueError("Academic assessment has a stale source revision.")
    section = next(
        (s for s in course["sections"] if s["id"] == assessment.get("section_id")), None
    )
    if section is None:
        raise ValueError("Academic assessment references an unknown section.")
    ids = assessment.get("question_ids")
    if not isinstance(ids, list) or not ids or any(not isinstance(q, str) for q in ids):
        raise ValueError("Academic assessment requires non-empty question ids.")
    by_id = {q["id"]: q for q in section["questions"]}
    if len(ids) != len(set(ids)) or set(ids) - by_id.keys():
        raise ValueError(
            "Academic assessment references duplicate or unknown questions."
        )
    return course, section, [by_id[q] for q in ids]


def validate_academic_answer(case: Mapping[str, Any]) -> None:
    _, _, questions = resolve_academic_assessment(case)
    answer = case.get("student_answer")
    if answer is None:
        return
    if not isinstance(answer, Mapping) or not isinstance(
        answer.get("academic_answers"), Mapping
    ):
        raise ValueError("Academic student answer requires an academic_answers object.")
    submitted = answer["academic_answers"]
    by_id = {q["id"]: q for q in questions}
    if set(submitted) - by_id.keys():
        raise ValueError("Academic answer references unknown questions.")
    for question_id, option in submitted.items():
        if not isinstance(option, str) or option not in by_id[question_id]["choices"]:
            raise ValueError("Academic answer references an unknown choice.")


def education_trace(case: Mapping[str, Any]) -> dict[str, Any]:
    """Derive provenance from canonical ids; never infer a stage from free text."""
    if "academic_assessment" in case:
        course, section, questions = resolve_academic_assessment(case)
        notion_ids = {n for q in questions for n in q["notion_ids"]}
        return {
            "stage": "engineering_school",
            "stage_label": STAGE_LABELS["engineering_school"],
            "course_id": course["id"],
            "course_title": course["title"],
            "course_code": course.get("code", ""),
            "section_id": section["id"],
            "course_kind": course.get("course_kind", "syllabus"),
            "prerequisite_course_ids": course.get("prerequisite_course_ids", []),
            "section_title": section["title"],
            "block": section.get("block", ""),
            "notions": [n for n in section["notions"] if n["id"] in notion_ids],
            "sources": [dict(course["source"])],
            "source_revision": source_revision(course),
            "assessment_kind": "objective_questions",
        }
    curriculum = _school_curriculum()
    wanted = set(case.get("curriculum_ids") or [])
    rows = [row for row in curriculum["required_program_ids"] if row["id"] in wanted]
    if rows:
        stages = {"college" if r["track"] == "college" else "lycee" for r in rows}
        stage = next(iter(stages)) if len(stages) == 1 else "transversal"
        sources = {s["id"]: s for s in curriculum["sources"]}
        levels = sorted({r["level"] for r in rows})
        return {
            "stage": stage,
            "stage_label": STAGE_LABELS[stage],
            "course_id": "school_" + "_".join(levels),
            "course_title": " / ".join(levels),
            "section_id": ",".join(r["id"] for r in rows),
            "section_title": " / ".join(r["domain"] for r in rows),
            "notions": [{"id": r["id"], "label": r["domain"]} for r in rows],
            "sources": [
                {**sources[s], "reviewed_on": curriculum["last_reviewed"]}
                for s in sorted({r["source_id"] for r in rows})
            ],
            "source_revision": source_revision(curriculum),
            "assessment_kind": "curriculum_audit",
            "course_kind": "school_curriculum",
        }
    return {
        "stage": "transversal",
        "stage_label": STAGE_LABELS["transversal"],
        "course_id": "",
        "course_title": "",
        "section_id": "",
        "section_title": "",
        "notions": [],
        "sources": [],
        "source_revision": "",
        "assessment_kind": "diagnostic",
        "course_kind": "transversal",
    }


def flatten_education_trace(trace: Mapping[str, Any]) -> dict[str, str]:
    return {
        "education_stage": str(trace.get("stage", "")),
        "education_stage_label": str(trace.get("stage_label", "")),
        "education_course_id": str(trace.get("course_id", "")),
        "education_course_title": str(trace.get("course_title", "")),
        "education_section_id": str(trace.get("section_id", "")),
        "education_section_title": str(trace.get("section_title", "")),
        "education_notion_ids": ",".join(n["id"] for n in trace.get("notions", [])),
        "education_notion_labels": " / ".join(
            n["label"] for n in trace.get("notions", [])
        ),
        "education_source_urls": " ".join(s["url"] for s in trace.get("sources", [])),
        "education_reviewed_on": ",".join(
            sorted({s["reviewed_on"] for s in trace.get("sources", [])})
        ),
        "education_source_revision": str(trace.get("source_revision", "")),
        "education_course_kind": str(trace.get("course_kind", "")),
        "assessment_kind": str(trace.get("assessment_kind", "")),
    }


def score_academic_answer(case: Mapping[str, Any]) -> dict[str, Any]:
    validate_academic_answer(case)
    _, _, questions = resolve_academic_assessment(case)
    answer = case.get("student_answer")
    submitted = (
        answer.get("academic_answers", {}) if isinstance(answer, Mapping) else {}
    )
    results = []
    for q in questions:
        selected = submitted.get(q["id"], "")
        results.append(
            {
                "question_id": q["id"],
                "prompt": q["prompt"],
                "notion_ids": q["notion_ids"],
                "submitted_choice": selected,
                "submitted_text": q["choices"].get(selected, ""),
                "correct_choice": q["correct_choice"],
                "correct_text": q["choices"][q["correct_choice"]],
                "correct": selected == q["correct_choice"],
                "explanation": q["explanation"],
            }
        )
    correct_count = sum(r["correct"] for r in results)
    score = round(100 * correct_count / len(results), 2)
    band = (
        "excellent"
        if score >= 85
        else "solid"
        if score >= 70
        else "partial"
        if score >= 50
        else "needs_work"
    )
    feedback = [
        f"{r['question_id']} : {r['explanation']}" for r in results if not r["correct"]
    ]
    return {
        "status": "submitted" if submitted else "not_submitted",
        "student_score": score,
        "score_band": band,
        "rubric": "Exact choices, equal weights; blank and wrong answers earn zero points.",
        "submitted_answer": dict(answer) if isinstance(answer, Mapping) else {},
        "reference_answer": {
            "academic_answers": {q["id"]: q["correct_choice"] for q in questions}
        },
        "component_scores": {"knowledge_score": score},
        "correct_count": correct_count,
        "question_count": len(results),
        "answered_count": len(submitted),
        "question_results": results,
        "feedback": feedback,
    }


def build_education_coverage_report(
    cases: Sequence[Mapping[str, Any]], registry: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Material coverage only: report absent chapters/questions/notions explicitly."""
    registry = registry if registry is not None else load_course_registry()
    validate_course_registry(registry)
    covered: dict[tuple[str, str], set[str]] = {}
    case_counts: dict[tuple[str, str], int] = {}
    stages = {stage: 0 for stage in STAGE_LABELS}
    for case in cases:
        if "academic_assessment" in case:
            course, section, questions = resolve_academic_assessment(case, registry)
            key = (course["id"], section["id"])
            covered.setdefault(key, set()).update(q["id"] for q in questions)
            case_counts[key] = case_counts.get(key, 0) + 1
            stages["engineering_school"] += 1
        else:
            stages[education_trace(case)["stage"]] += 1
    rows = []
    for course in registry["courses"]:
        for section in course["sections"]:
            key = (course["id"], section["id"])
            question_ids = covered.get(key, set())
            notions = {
                n
                for q in section["questions"]
                if q["id"] in question_ids
                for n in q["notion_ids"]
            }
            missing = [n["label"] for n in section["notions"] if n["id"] not in notions]
            absent_questions = [
                q["id"] for q in section["questions"] if q["id"] not in question_ids
            ]
            rows.append(
                {
                    "course_id": course["id"],
                    "course_title": course["title"],
                    "section_id": section["id"],
                    "section_title": section["title"],
                    "block": section.get("block", ""),
                    "exercise_count": case_counts.get(key, 0),
                    "course_kind": course.get("course_kind", "syllabus"),
                    "question_count": len(question_ids),
                    "missing_notions": missing,
                    "missing_questions": absent_questions,
                    "quality_passed": bool(question_ids)
                    and not missing
                    and not absent_questions,
                    "source_url": course["source"]["url"],
                    "source_revision": source_revision(course),
                }
            )
    return {
        "schema": "agilab.learning_assessment.education_coverage.v1",
        "scope": registry["coverage_scope"],
        "question_origin": registry["question_origin"],
        "stage_case_counts": stages,
        "course_count": len(registry["courses"]),
        "syllabus_course_count": sum(
            c.get("course_kind", "syllabus") == "syllabus" for c in registry["courses"]
        ),
        "extra_course_count": sum(
            c.get("course_kind") == "extra" for c in registry["courses"]
        ),
        "section_count": len(rows),
        "question_count": sum(r["question_count"] for r in rows),
        "quality_passed": all(r["quality_passed"] for r in rows),
        "missing_sections": [
            f"{r['course_id']}/{r['section_id']}"
            for r in rows
            if not r["exercise_count"]
        ],
        "sections": rows,
    }
