"""Coverage thresholds must not silently weaken curriculum quality checks."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

APP_SRC = (
    Path(__file__).resolve().parents[1]
    / "src/agilab/apps/builtin/tescia_diagnostic_project/src"
)


@pytest.fixture
def curriculum_module(monkeypatch):
    monkeypatch.syspath_prepend(str(APP_SRC))
    return importlib.import_module("tescia_diagnostic.curriculum")


def _cases_per_curriculum_id(module, curriculum, count=1):
    return [
        {"case_id": f"case-{index}-{variant}", "curriculum_ids": [program_id]}
        for index, program_id in enumerate(
            sorted(module.required_curriculum_ids(curriculum))
        )
        for variant in range(count)
    ]


@pytest.mark.parametrize(
    "threshold",
    [
        0,
        -1,
        True,
        False,
        1.0,
        2.9,
        float("nan"),
        float("inf"),
        "2",
        "bad",
        "",
        None,
        [],
        {},
    ],
)
def test_explicit_invalid_curriculum_threshold_is_rejected(curriculum_module, threshold):
    curriculum = curriculum_module.load_math_program_2026()
    curriculum["required_min_cases_per_id"] = threshold

    with pytest.raises(ValueError, match="required_min_cases_per_id"):
        curriculum_module.required_min_cases_per_id(curriculum)
    with pytest.raises(ValueError, match="required_min_cases_per_id"):
        curriculum_module.validate_math_program_2026(curriculum)


@pytest.mark.parametrize("threshold", [1, 2, 100])
def test_positive_integer_curriculum_threshold_is_preserved(curriculum_module, threshold):
    curriculum = curriculum_module.load_math_program_2026()
    curriculum["required_min_cases_per_id"] = threshold

    curriculum_module.validate_math_program_2026(curriculum)
    assert curriculum_module.required_min_cases_per_id(curriculum) == threshold


def test_omitted_curriculum_threshold_defaults_to_one(curriculum_module):
    curriculum = curriculum_module.load_math_program_2026()
    curriculum.pop("required_min_cases_per_id")
    cases = _cases_per_curriculum_id(curriculum_module, curriculum)

    assert curriculum_module.required_min_cases_per_id(curriculum) == 1
    report = curriculum_module.build_math_program_2026_coverage_report(cases, curriculum)
    assert report["required_min_cases_per_id"] == 1
    assert report["quality_passed"] is True
    assert report["undercovered_curriculum_ids"] == []


def test_invalid_threshold_cannot_produce_passing_coverage(curriculum_module):
    curriculum = curriculum_module.load_math_program_2026()
    cases = _cases_per_curriculum_id(curriculum_module, curriculum)
    curriculum["required_min_cases_per_id"] = "invalid"

    with pytest.raises(ValueError, match="required_min_cases_per_id"):
        curriculum_module.build_math_program_2026_coverage_report(cases, curriculum)


def test_bundled_curriculum_requires_two_cases_per_id(curriculum_module):
    curriculum = curriculum_module.load_math_program_2026()
    assert curriculum["required_min_cases_per_id"] == 2
    cases = _cases_per_curriculum_id(curriculum_module, curriculum)

    report = curriculum_module.build_math_program_2026_coverage_report(cases, curriculum)
    assert report["quality_passed"] is False
    assert report["missing_curriculum_ids"] == []
    assert report["undercovered_curriculum_ids"] == sorted(
        curriculum_module.required_curriculum_ids(curriculum)
    )

    cases = _cases_per_curriculum_id(curriculum_module, curriculum, count=2)
    report = curriculum_module.build_math_program_2026_coverage_report(cases, curriculum)
    assert report["quality_passed"] is True
    assert report["undercovered_curriculum_ids"] == []
