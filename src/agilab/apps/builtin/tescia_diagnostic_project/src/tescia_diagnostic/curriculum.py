"""2026 French mathematics curriculum coverage helpers for TeSciA."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import Any


CURRICULUM_SCHEMA = "agilab.tescia_diagnostic.math_program_coverage.v1"


def default_curriculum_path() -> Path:
    return Path(__file__).resolve().parent / "curriculum" / "math_program_2026.json"


def load_math_program_2026(path: str | Path | None = None) -> dict[str, Any]:
    source = Path(path) if path is not None else default_curriculum_path()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Math curriculum coverage file must contain a JSON object: {source}")
    validate_math_program_2026(payload)
    return payload


def required_curriculum_ids(curriculum: Mapping[str, Any]) -> set[str]:
    return {
        str(item.get("id", "")).strip()
        for item in curriculum.get("required_program_ids", [])
        if isinstance(item, Mapping) and str(item.get("id", "")).strip()
    }


def case_curriculum_ids(case: Mapping[str, Any]) -> list[str]:
    raw_ids = case.get("curriculum_ids")
    if not isinstance(raw_ids, list):
        return []
    return [str(item).strip() for item in raw_ids if str(item).strip()]


def covered_curriculum_ids(cases: Sequence[Mapping[str, Any]]) -> set[str]:
    covered: set[str] = set()
    for case in cases:
        covered.update(case_curriculum_ids(case))
    return covered


def curriculum_id_counts(cases: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in cases:
        for curriculum_id in set(case_curriculum_ids(case)):
            counts[curriculum_id] = counts.get(curriculum_id, 0) + 1
    return dict(sorted(counts.items()))


def required_min_cases_per_id(curriculum: Mapping[str, Any]) -> int:
    try:
        value = int(curriculum.get("required_min_cases_per_id", 1))
    except (TypeError, ValueError):
        value = 1
    return max(value, 1)


def validate_math_program_2026(curriculum: Mapping[str, Any]) -> None:
    if curriculum.get("schema") != CURRICULUM_SCHEMA:
        raise ValueError(f"Math curriculum coverage must declare schema {CURRICULUM_SCHEMA!r}.")
    sources = curriculum.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("Math curriculum coverage must declare non-empty sources.")
    source_ids = {
        str(item.get("id", "")).strip()
        for item in sources
        if isinstance(item, Mapping) and str(item.get("id", "")).strip()
    }
    required = curriculum.get("required_program_ids")
    if not isinstance(required, list) or not required:
        raise ValueError("Math curriculum coverage must declare required_program_ids.")
    if required_min_cases_per_id(curriculum) < 1:
        raise ValueError("Math curriculum coverage required_min_cases_per_id must be at least 1.")
    seen: set[str] = set()
    for item in required:
        if not isinstance(item, Mapping):
            raise ValueError("Each required curriculum entry must be an object.")
        program_id = str(item.get("id", "")).strip()
        if not program_id:
            raise ValueError("Each required curriculum entry must have an id.")
        if program_id in seen:
            raise ValueError(f"Duplicate curriculum id: {program_id}")
        seen.add(program_id)
        if str(item.get("source_id", "")).strip() not in source_ids:
            raise ValueError(f"Curriculum id {program_id!r} references an unknown source_id.")
        for field in ("track", "level", "domain", "effective_school_year"):
            if not str(item.get(field, "")).strip():
                raise ValueError(f"Curriculum id {program_id!r} is missing {field}.")


def validate_case_curriculum_ids(
    cases: Sequence[Mapping[str, Any]],
    curriculum: Mapping[str, Any],
) -> None:
    known = required_curriculum_ids(curriculum)
    unknown: list[str] = []
    for case in cases:
        case_id = str(case.get("case_id", "<unknown>"))
        for curriculum_id in case_curriculum_ids(case):
            if curriculum_id not in known:
                unknown.append(f"{case_id}:{curriculum_id}")
    if unknown:
        raise ValueError("Cases reference unknown 2026 math curriculum ids: " + ", ".join(sorted(unknown)))


def build_math_program_2026_coverage_report(
    cases: Sequence[Mapping[str, Any]],
    curriculum: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return deterministic coverage of cases over the declared 2026 math program."""

    curriculum_payload = dict(curriculum or load_math_program_2026())
    validate_math_program_2026(curriculum_payload)
    validate_case_curriculum_ids(cases, curriculum_payload)
    required = required_curriculum_ids(curriculum_payload)
    covered = covered_curriculum_ids(cases)
    counts = curriculum_id_counts(cases)
    min_cases = required_min_cases_per_id(curriculum_payload)
    missing = sorted(required - covered)
    undercovered = sorted(
        curriculum_id
        for curriculum_id in required
        if curriculum_id not in missing and counts.get(curriculum_id, 0) < min_cases
    )
    case_map = {
        str(case.get("case_id", "")): case_curriculum_ids(case)
        for case in cases
        if str(case.get("case_id", "")).strip()
    }
    return {
        "schema": "agilab.tescia_diagnostic.math_program_coverage_report.v1",
        "coverage_scope": str(curriculum_payload.get("coverage_scope", "")),
        "coverage_granularity": str(curriculum_payload.get("coverage_granularity", "")),
        "required_count": len(required),
        "required_min_cases_per_id": min_cases,
        "covered_count": len(required - set(missing)),
        "coverage_ratio": round((len(required) - len(missing)) / len(required), 4) if required else 0.0,
        "quality_passed": not missing and not undercovered,
        "missing_curriculum_ids": missing,
        "undercovered_curriculum_ids": undercovered,
        "curriculum_id_counts": counts,
        "covered_curriculum_ids": sorted(required & covered),
        "extra_curriculum_ids": sorted(covered - required),
        "case_curriculum_ids": case_map,
        "sources": curriculum_payload.get("sources", []),
    }


def require_complete_math_program_2026_coverage(
    cases: Sequence[Mapping[str, Any]],
    curriculum: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    report = build_math_program_2026_coverage_report(cases, curriculum)
    missing = report["missing_curriculum_ids"]
    if missing:
        raise ValueError("Missing 2026 math curriculum coverage: " + ", ".join(missing))
    undercovered = report["undercovered_curriculum_ids"]
    if undercovered:
        raise ValueError("Undercovered 2026 math curriculum ids: " + ", ".join(undercovered))
    return report


__all__ = [
    "CURRICULUM_SCHEMA",
    "build_math_program_2026_coverage_report",
    "case_curriculum_ids",
    "covered_curriculum_ids",
    "curriculum_id_counts",
    "default_curriculum_path",
    "load_math_program_2026",
    "required_min_cases_per_id",
    "required_curriculum_ids",
    "require_complete_math_program_2026_coverage",
    "validate_case_curriculum_ids",
    "validate_math_program_2026",
]
