"""Validate generic assessment material without asserting learner mastery.

Source hashes and artifact references are declarations. This module never reads,
downloads, hashes, or executes the referenced material.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
import re
from typing import Any

ASSESSMENT_PROGRAM_SCHEMA = "tescia-assessment-program.v1"
PROGRAM_COVERAGE_SCHEMA = "tescia-assessment-program-coverage.v1"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*")
_SHA256 = re.compile(r"[A-Fa-f0-9]{64}")


def _object(
    value: Any,
    context: str,
    required: set[str],
    optional: set[str] | None = None,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object.")
    unknown = set(value) - required - (optional or set())
    if unknown:
        names = ", ".join(sorted(repr(key) for key in unknown))
        raise ValueError(f"{context} contains unexpected fields: {names}.")
    missing = required - set(value)
    if missing:
        raise ValueError(
            f"{context} is missing required fields: {', '.join(sorted(missing))}."
        )
    return value


def _text(
    value: Any,
    context: str,
    *,
    identifier: bool = False,
    preserve_whitespace: bool = False,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a nonblank string.")
    text = value if preserve_whitespace else value.strip()
    if identifier and _IDENTIFIER.fullmatch(text) is None:
        raise ValueError(
            f"{context} must be a stable ID using ASCII letters, digits, '_', '-', '.', or ':', "
            "starting with a letter or digit."
        )
    return text


def _list(value: Any, context: str, *, allow_empty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (not value and not allow_empty):
        qualifier = "a list" if allow_empty else "a nonempty list"
        raise ValueError(f"{context} must be {qualifier}.")
    return value


def _unique(value: str, seen: set[str], context: str) -> None:
    if value in seen:
        raise ValueError(f"{context} contains duplicate ID {value!r}.")
    seen.add(value)


def _text_list(
    value: Any,
    context: str,
    *,
    allow_empty: bool = False,
    identifiers: bool = False,
    preserve_whitespace: bool = False,
) -> list[str]:
    result = []
    seen: set[str] = set()
    for index, item in enumerate(_list(value, context, allow_empty=allow_empty)):
        text = _text(
            item,
            f"{context}[{index}]",
            identifier=identifiers,
            preserve_whitespace=preserve_whitespace,
        )
        _unique(text, seen, context)
        result.append(text)
    return result


def _practical_assessment(value: Any, context: str) -> dict[str, Any]:
    assessment = _object(
        value, context, {"instructions", "deliverables", "rubric", "artifact_refs"}
    )
    rubric = []
    criterion_ids: set[str] = set()
    for index, item in enumerate(_list(assessment["rubric"], f"{context}.rubric")):
        row_context = f"{context}.rubric[{index}]"
        row = _object(item, row_context, {"criterion_id", "description"})
        criterion_id = _text(
            row["criterion_id"], f"{row_context}.criterion_id", identifier=True
        )
        _unique(criterion_id, criterion_ids, f"{context}.rubric criterion_id")
        rubric.append(
            {
                "criterion_id": criterion_id,
                "description": _text(row["description"], f"{row_context}.description"),
            }
        )
    return {
        "instructions": _text(assessment["instructions"], f"{context}.instructions"),
        "deliverables": _text_list(
            assessment["deliverables"], f"{context}.deliverables"
        ),
        "rubric": rubric,
        "artifact_refs": _text_list(
            assessment["artifact_refs"], f"{context}.artifact_refs", allow_empty=True
        ),
    }


def _validate_prerequisites(competencies: list[dict[str, Any]]) -> None:
    identifiers = {row["competency_id"] for row in competencies}
    indegrees: dict[str, int] = {}
    dependents: dict[str, list[str]] = defaultdict(list)
    for row in competencies:
        competency_id = row["competency_id"]
        prerequisites = row["prerequisites"]
        unknown = sorted(set(prerequisites) - identifiers)
        if unknown:
            raise ValueError(
                f"Competency {competency_id!r} prerequisites reference unknown IDs: {', '.join(unknown)}."
            )
        indegrees[competency_id] = len(prerequisites)
        for prerequisite in prerequisites:
            dependents[prerequisite].append(competency_id)
    ready = deque(sorted(key for key, count in indegrees.items() if count == 0))
    visited = 0
    while ready:
        prerequisite = ready.popleft()
        visited += 1
        for dependent in dependents[prerequisite]:
            indegrees[dependent] -= 1
            if indegrees[dependent] == 0:
                ready.append(dependent)
    if visited != len(competencies):
        unresolved = ", ".join(sorted(key for key, count in indegrees.items() if count))
        raise ValueError(
            f"Assessment program prerequisites contain a cycle; unresolved competencies: {unresolved}."
        )


def validate_assessment_program(
    program: Mapping[str, Any], cases: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Return independent JSON-safe metadata with all references validated.

    Missing diagnostic links and practical assessments describe incomplete
    material. Present fields must meet the contract; case contents themselves
    remain the responsibility of the diagnostic case validator.
    """
    payload = _object(
        program,
        "assessment_program",
        {"schema", "program_id", "title", "version", "sources", "competencies"},
    )
    if payload["schema"] != ASSESSMENT_PROGRAM_SCHEMA:
        raise ValueError(
            f"assessment_program.schema must be {ASSESSMENT_PROGRAM_SCHEMA!r}."
        )
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes, bytearray)):
        raise ValueError("cases must be a sequence of case objects.")
    case_ids: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            raise ValueError(f"cases[{index}] must be an object.")
        # Existing case identities are nonblank strings, not normalized stable IDs.
        case_id = _text(
            case.get("case_id"), f"cases[{index}].case_id", preserve_whitespace=True
        )
        if case_id in case_ids:
            raise ValueError(f"cases contain duplicate case_id {case_id!r}.")
        case_ids.add(case_id)

    sources = []
    source_ids: set[str] = set()
    for index, item in enumerate(
        _list(payload["sources"], "assessment_program.sources")
    ):
        context = f"assessment_program.sources[{index}]"
        source = _object(item, context, {"source_id", "title", "revision", "sha256"})
        source_id = _text(source["source_id"], f"{context}.source_id", identifier=True)
        _unique(source_id, source_ids, "assessment_program.sources source_id")
        digest = _text(source["sha256"], f"{context}.sha256")
        if _SHA256.fullmatch(digest) is None:
            raise ValueError(
                f"{context}.sha256 must contain exactly 64 hexadecimal characters."
            )
        sources.append(
            {
                "source_id": source_id,
                "title": _text(source["title"], f"{context}.title"),
                "revision": _text(source["revision"], f"{context}.revision"),
                "sha256": digest.lower(),
            }
        )

    competencies = []
    competency_ids: set[str] = set()
    for index, item in enumerate(
        _list(payload["competencies"], "assessment_program.competencies")
    ):
        context = f"assessment_program.competencies[{index}]"
        competency = _object(
            item,
            context,
            {"competency_id", "title", "outcome", "source_refs"},
            {"prerequisites", "diagnostic_case_ids", "practical_assessment"},
        )
        competency_id = _text(
            competency["competency_id"], f"{context}.competency_id", identifier=True
        )
        _unique(
            competency_id,
            competency_ids,
            "assessment_program.competencies competency_id",
        )
        source_refs = []
        seen_refs: set[tuple[str, str]] = set()
        for ref_index, item_ref in enumerate(
            _list(competency["source_refs"], f"{context}.source_refs")
        ):
            ref_context = f"{context}.source_refs[{ref_index}]"
            source_ref = _object(item_ref, ref_context, {"source_id", "section"})
            source_id = _text(
                source_ref["source_id"], f"{ref_context}.source_id", identifier=True
            )
            section = _text(source_ref["section"], f"{ref_context}.section")
            if source_id not in source_ids:
                raise ValueError(
                    f"{ref_context} references unknown source_id {source_id!r}."
                )
            ref_key = (source_id, section)
            if ref_key in seen_refs:
                raise ValueError(
                    f"{context}.source_refs contains duplicate source and section references."
                )
            seen_refs.add(ref_key)
            source_refs.append({"source_id": source_id, "section": section})
        diagnostic_case_ids = _text_list(
            competency.get("diagnostic_case_ids", []),
            f"{context}.diagnostic_case_ids",
            allow_empty=True,
            preserve_whitespace=True,
        )
        unknown_cases = sorted(set(diagnostic_case_ids) - case_ids)
        if unknown_cases:
            raise ValueError(
                f"{context}.diagnostic_case_ids reference unknown case IDs: {', '.join(unknown_cases)}."
            )
        normalized = {
            "competency_id": competency_id,
            "title": _text(competency["title"], f"{context}.title"),
            "outcome": _text(competency["outcome"], f"{context}.outcome"),
            "source_refs": source_refs,
            "prerequisites": _text_list(
                competency.get("prerequisites", []),
                f"{context}.prerequisites",
                allow_empty=True,
                identifiers=True,
            ),
            "diagnostic_case_ids": diagnostic_case_ids,
        }
        if "practical_assessment" in competency:
            normalized["practical_assessment"] = _practical_assessment(
                competency["practical_assessment"], f"{context}.practical_assessment"
            )
        competencies.append(normalized)
    _validate_prerequisites(competencies)
    return {
        "schema": ASSESSMENT_PROGRAM_SCHEMA,
        "program_id": _text(
            payload["program_id"], "assessment_program.program_id", identifier=True
        ),
        "title": _text(payload["title"], "assessment_program.title"),
        "version": _text(payload["version"], "assessment_program.version"),
        "sources": sources,
        "competencies": competencies,
    }


def build_program_coverage_report(
    program: Mapping[str, Any], cases: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Describe declared diagnostic and practical material, never its mastery.

    A manual practical assessment can be ready without artifact references.
    Neither a ready curriculum nor the presence of references proves that a
    learner has completed a practical task or that its materials were verified.
    """
    normalized = validate_assessment_program(program, cases)
    rows = []
    linked_cases: set[str] = set()
    diagnostic_covered = practical_covered = ready_count = 0
    for competency in normalized["competencies"]:
        missing = []
        if competency["diagnostic_case_ids"]:
            diagnostic_covered += 1
            linked_cases.update(competency["diagnostic_case_ids"])
        else:
            missing.append("diagnostic_cases")
        if "practical_assessment" in competency:
            practical_covered += 1
        else:
            missing.append("practical_assessment")
        if not missing:
            ready_count += 1
        rows.append(
            {
                **competency,
                "status": "incomplete" if missing else "curriculum_ready",
                "missing_material": missing,
                "learner_mastery": "not_assessed",
            }
        )
    return {
        "schema": PROGRAM_COVERAGE_SCHEMA,
        "program_id": normalized["program_id"],
        "title": normalized["title"],
        "version": normalized["version"],
        "status": "curriculum_ready" if ready_count == len(rows) else "incomplete",
        "learner_mastery": "not_assessed",
        "sources": normalized["sources"],
        "source_count": len(normalized["sources"]),
        "competency_count": len(rows),
        "diagnostic_covered_count": diagnostic_covered,
        "practical_covered_count": practical_covered,
        "ready_competency_count": ready_count,
        "linked_case_count": len(linked_cases),
        "competencies": rows,
    }


__all__ = [
    "ASSESSMENT_PROGRAM_SCHEMA",
    "PROGRAM_COVERAGE_SCHEMA",
    "build_program_coverage_report",
    "validate_assessment_program",
]
