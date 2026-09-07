"""Generic program metadata describes assessment coverage, never learner mastery."""

from __future__ import annotations

from copy import deepcopy
import importlib
from pathlib import Path

import pytest

APP_SRC = (
    Path(__file__).resolve().parents[1]
    / "src/agilab/apps/builtin/learning_assessment_project/src"
)


@pytest.fixture
def contract(monkeypatch):
    monkeypatch.syspath_prepend(str(APP_SRC))
    return importlib.import_module("learning_assessment.domain.assessment_program")


@pytest.fixture
def cases():
    return [{"case_id": "diagnostic-1"}, {"case_id": "diagnostic-2"}]


@pytest.fixture
def program():
    return {
        "schema": "tescia-assessment-program.v1",
        "program_id": "example-program",
        "title": "Example assessment program",
        "version": "1.0",
        "sources": [
            {
                "source_id": "source-1",
                "title": "Example handbook",
                "revision": "1",
                "sha256": "a" * 64,
            }
        ],
        "competencies": [
            {
                "competency_id": "competency-1",
                "title": "Evaluate a result",
                "outcome": "Compare a measured result with its stated acceptance criterion.",
                "source_refs": [{"source_id": "source-1", "section": "1.2"}],
                "prerequisites": [],
                "diagnostic_case_ids": ["diagnostic-1"],
                "practical_assessment": {
                    "instructions": "Measure a sample and justify whether its result meets the criterion.",
                    "deliverables": ["A measurement table and written interpretation"],
                    "rubric": [
                        {
                            "criterion_id": "interpretation",
                            "description": "Use the stated criterion correctly.",
                        }
                    ],
                    "artifact_refs": [],
                },
            }
        ],
    }


def test_ready_program_keeps_mastery_unassessed(contract, program, cases):
    report = contract.build_program_coverage_report(program, cases)

    assert report["schema"] == "tescia-assessment-program-coverage.v1"
    assert report["program_id"] == program["program_id"]
    assert report["status"] == "curriculum_ready"
    assert report["learner_mastery"] == "not_assessed"
    assert report["sources"] == program["sources"]
    assert report["competency_count"] == report["ready_competency_count"] == 1
    assert report["diagnostic_covered_count"] == report["practical_covered_count"] == 1
    assert report["linked_case_count"] == 1
    assert report["competencies"][0]["missing_material"] == []
    assert report["competencies"][0]["learner_mastery"] == "not_assessed"


def test_case_links_preserve_exact_whitespace_distinct_identities(contract, program):
    cases = [{"case_id": "a"}, {"case_id": " a "}]
    program["competencies"][0]["diagnostic_case_ids"] = ["a", " a "]

    normalized = contract.validate_assessment_program(program, cases)
    report = contract.build_program_coverage_report(program, cases)

    assert normalized["competencies"][0]["diagnostic_case_ids"] == ["a", " a "]
    assert report["competencies"][0]["diagnostic_case_ids"] == ["a", " a "]
    assert report["linked_case_count"] == 2


def test_case_links_do_not_alias_trimmed_identity(contract, program):
    program["competencies"][0]["diagnostic_case_ids"] = ["a"]

    with pytest.raises(ValueError, match="unknown case IDs"):
        contract.validate_assessment_program(program, [{"case_id": " a "}])


def test_missing_material_is_valid_but_incomplete(contract, program):
    competency = program["competencies"][0]
    competency.pop("diagnostic_case_ids")
    competency.pop("prerequisites")
    competency.pop("practical_assessment")

    normalized = contract.validate_assessment_program(program, [])
    assert normalized["competencies"][0]["diagnostic_case_ids"] == []
    assert normalized["competencies"][0]["prerequisites"] == []
    report = contract.build_program_coverage_report(program, [])
    assert report["status"] == "incomplete"
    assert report["ready_competency_count"] == 0
    assert report["competencies"][0]["missing_material"] == [
        "diagnostic_cases",
        "practical_assessment",
    ]


@pytest.mark.parametrize(
    ("missing_field", "missing_material"),
    [
        ("diagnostic_case_ids", "diagnostic_cases"),
        ("practical_assessment", "practical_assessment"),
    ],
)
def test_either_missing_assessment_keeps_competency_incomplete(
    contract, program, cases, missing_field, missing_material
):
    program["competencies"][0].pop(missing_field)
    report = contract.build_program_coverage_report(program, cases)
    assert report["status"] == "incomplete"
    assert report["competencies"][0]["missing_material"] == [missing_material]


def test_normalization_is_json_safe_and_does_not_mutate_input(contract, program, cases):
    import json

    program["title"] = "  Example program  "
    program["sources"][0]["sha256"] = "A" * 64
    original = deepcopy(program)
    normalized = contract.validate_assessment_program(program, tuple(cases))
    assert normalized["title"] == "Example program"
    assert normalized["sources"][0]["sha256"] == "a" * 64
    assert json.loads(json.dumps(normalized)) == normalized
    normalized["competencies"][0]["diagnostic_case_ids"].append("another-case")
    assert program == original


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("schema",), "unknown", "schema"),
        (("program_id",), "bad id", "program_id"),
        (("version",), 1, "version"),
        (("title",), " ", "title"),
        (("sources",), [], "sources"),
        (("sources", 0, "sha256"), "z" * 64, "sha256"),
        (("sources", 0, "sha256"), "a" * 63, "sha256"),
        (("sources", 0, "revision"), False, "revision"),
        (("competencies",), [], "competencies"),
        (("competencies", 0, "outcome"), None, "outcome"),
        (("competencies", 0, "source_refs"), [], "source_refs"),
        (("competencies", 0, "source_refs", 0, "section"), "", "section"),
        (("competencies", 0, "prerequisites"), "competency-2", "prerequisites"),
        (
            ("competencies", 0, "diagnostic_case_ids"),
            "diagnostic-1",
            "diagnostic_case_ids",
        ),
        (("competencies", 0, "practical_assessment"), None, "practical_assessment"),
        (
            ("competencies", 0, "practical_assessment", "instructions"),
            "",
            "instructions",
        ),
        (
            ("competencies", 0, "practical_assessment", "deliverables"),
            [],
            "deliverables",
        ),
        (("competencies", 0, "practical_assessment", "rubric"), [], "rubric"),
        (
            ("competencies", 0, "practical_assessment", "artifact_refs"),
            None,
            "artifact_refs",
        ),
    ],
)
def test_invalid_manifest_structure_is_rejected(
    contract, program, cases, path, value, message
):
    target = program
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError, match=message):
        contract.validate_assessment_program(program, cases)


def test_unknown_fields_and_missing_required_fields_are_rejected(
    contract, program, cases
):
    program["unexpected"] = "metadata"
    with pytest.raises(ValueError, match="unexpected"):
        contract.validate_assessment_program(program, cases)
    program.pop("unexpected")
    program["competencies"][0]["practical_assessment"].pop("artifact_refs")
    with pytest.raises(ValueError, match="artifact_refs"):
        contract.validate_assessment_program(program, cases)


@pytest.mark.parametrize("collection", ["sources", "competencies"])
def test_duplicate_ids_are_rejected(contract, program, cases, collection):
    program[collection].append(deepcopy(program[collection][0]))
    with pytest.raises(ValueError, match="duplicate"):
        contract.validate_assessment_program(program, cases)


@pytest.mark.parametrize(
    "field", ["source_refs", "prerequisites", "diagnostic_case_ids"]
)
def test_dangling_references_are_rejected(contract, program, cases, field):
    competency = program["competencies"][0]
    competency[field] = (
        [{"source_id": "missing", "section": "1"}]
        if field == "source_refs"
        else ["missing"]
    )
    with pytest.raises(ValueError, match=field):
        contract.validate_assessment_program(program, cases)


def test_prerequisite_cycles_are_rejected_and_acyclic_links_preserved(
    contract, program, cases
):
    first = program["competencies"][0]
    second = deepcopy(first)
    second["competency_id"] = "competency-2"
    second["prerequisites"] = ["competency-1"]
    program["competencies"].append(second)
    assert (
        contract.build_program_coverage_report(program, cases)["ready_competency_count"]
        == 2
    )
    assert (
        contract.build_program_coverage_report(program, cases)["linked_case_count"] == 1
    )

    first["prerequisites"] = ["competency-2"]
    with pytest.raises(ValueError, match="cycle"):
        contract.validate_assessment_program(program, cases)
    first["prerequisites"] = ["competency-1"]
    with pytest.raises(ValueError, match="cycle"):
        contract.validate_assessment_program(program, cases)


def test_ambiguous_case_ids_and_duplicate_rubric_ids_are_rejected(
    contract, program, cases
):
    with pytest.raises(ValueError, match="duplicate.*case_id"):
        contract.validate_assessment_program(program, cases + cases[:1])
    rubric = program["competencies"][0]["practical_assessment"]["rubric"]
    rubric.append(deepcopy(rubric[0]))
    with pytest.raises(ValueError, match="criterion_id.*duplicate"):
        contract.validate_assessment_program(program, cases)


def test_artifact_references_are_opaque_and_never_accessed(
    contract, program, cases, monkeypatch
):
    import subprocess
    import urllib.request

    references = ["../../untrusted-script.py", "https://example.invalid/evidence"]
    program["competencies"][0]["practical_assessment"]["artifact_refs"] = references

    def forbidden(*_args, **_kwargs):
        raise AssertionError(
            "Assessment metadata must not access or execute artifact references"
        )

    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(Path, "exists", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    report = contract.build_program_coverage_report(program, cases)
    assert (
        report["competencies"][0]["practical_assessment"]["artifact_refs"] == references
    )
    assert report["learner_mastery"] == "not_assessed"
