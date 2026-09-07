from __future__ import annotations

import json
from pathlib import Path

import pytest


APP_SRC = (
    Path(__file__).resolve().parents[1]
    / "src/agilab/apps/builtin/tescia_diagnostic_project/src"
)


@pytest.fixture
def diagnostic_modules(monkeypatch):
    monkeypatch.syspath_prepend(str(APP_SRC))
    from tescia_diagnostic.domain import diagnostic, generator

    return diagnostic, generator


@pytest.fixture
def case_payload():
    sample = APP_SRC / "tescia_diagnostic/sample_data/tescia_diagnostic_cases.json"
    payload = json.loads(sample.read_text(encoding="utf-8"))
    payload["cases"] = payload["cases"][:1]
    return payload


@pytest.mark.parametrize("entrypoint", ["validate_case_payload", "diagnose_case"])
@pytest.mark.parametrize("field", ["automated", "discriminator"])
@pytest.mark.parametrize("value", ["false", "true", 0, 1, None])
def test_regression_flags_reject_non_boolean_values(
    diagnostic_modules, case_payload, entrypoint, field, value
):
    diagnostic, _ = diagnostic_modules
    case = case_payload["cases"][0]
    case["regression_tests"][0][field] = value
    argument = case_payload if entrypoint == "validate_case_payload" else case

    with pytest.raises(
        ValueError,
        match=rf"{case['case_id']}.*regression_tests\[0\].*{field}.*boolean",
    ):
        getattr(diagnostic, entrypoint)(argument)


@pytest.mark.parametrize("entrypoint", ["validate_case_payload", "diagnose_case"])
@pytest.mark.parametrize("row", [None, "invalid test", 0, []])
def test_regression_tests_require_object_rows(
    diagnostic_modules, case_payload, entrypoint, row
):
    diagnostic, _ = diagnostic_modules
    case = case_payload["cases"][0]
    case["regression_tests"][0] = row
    argument = case_payload if entrypoint == "validate_case_payload" else case

    with pytest.raises(
        ValueError, match=rf"{case['case_id']}.*regression_tests\[0\].*object"
    ):
        getattr(diagnostic, entrypoint)(argument)


@pytest.mark.parametrize(
    ("flags", "expected_coverage"),
    [
        ({}, 0.0),
        ({"automated": False, "discriminator": False}, 0.0),
        ({"automated": True}, 0.35),
        ({"discriminator": True}, 0.65),
        ({"automated": True, "discriminator": True}, 1.0),
    ],
)
def test_regression_flags_preserve_boolean_scoring_and_optional_defaults(
    diagnostic_modules, case_payload, flags, expected_coverage
):
    diagnostic, _ = diagnostic_modules
    for row in case_payload["cases"][0]["regression_tests"]:
        row.pop("automated", None)
        row.pop("discriminator", None)
        row.update(flags)

    case = diagnostic.validate_case_payload(case_payload)["cases"][0]
    assert diagnostic.regression_coverage(case) == expected_coverage
    report = diagnostic.diagnose_case(case)
    assert report["regression_coverage"] == expected_coverage
    expected_status = "actionable" if expected_coverage >= 0.6 else "needs_more_evidence"
    assert report["status"] == expected_status


@pytest.mark.parametrize("field", ["automated", "discriminator"])
def test_generator_rejects_string_false_regression_flags(
    diagnostic_modules, case_payload, field
):
    _, generator = diagnostic_modules
    case = case_payload["cases"][0]
    case["regression_tests"][0][field] = "false"

    def fake_post_json(_url, _payload, _timeout):
        return {"output_text": json.dumps(case_payload)}

    with pytest.raises(
        generator.DiagnosticCaseGenerationError,
        match=rf"{case['case_id']}.*regression_tests\[0\].*{field}.*boolean",
    ):
        generator.generate_cases_with_engine(
            provider="gpt-oss",
            endpoint="http://127.0.0.1:8000/v1/responses",
            model="fixture",
            topic="regression evidence",
            case_count=1,
            post_json=fake_post_json,
        )


def test_valid_bundled_case_keeps_its_diagnostic_scores(diagnostic_modules, case_payload):
    diagnostic, _ = diagnostic_modules
    case = diagnostic.validate_case_payload(case_payload)["cases"][0]

    report = diagnostic.diagnose_case(case)

    assert report["status"] == "actionable"
    assert report["regression_coverage"] == 1.0
    assert report["case_quality_score"] == 94.0
    assert report["student_score"] == 99.7
    assert report["selected_fix"]["id"] == "mount_scheduler_share_with_sshfs"
