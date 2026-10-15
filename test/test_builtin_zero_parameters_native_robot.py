"""Native cold/save/fresh regressions for valid zeros in seven public app forms."""

import importlib
import sys
from pathlib import Path

import pytest

test_support_root = str(Path(__file__).resolve().parent)
if test_support_root not in sys.path:
    sys.path.insert(0, test_support_root)
native_zero_support = importlib.import_module("_native_form_zero_robot_support")
NativeZeroFormCase = native_zero_support.NativeZeroFormCase


CASES = [
    NativeZeroFormCase(
        case_id="sklearn-pipeline-seed-zero",
        app_name="sklearn_pipeline_project",
        zero_values={"seed": 0},
        numeric_controls={"seed": "Seed"},
        change_key="sample_count",
        change_label="Samples",
        initial_change_value=240,
        changed_value=260,
    ),
    NativeZeroFormCase(
        case_id="weather-forecast-random-state-zero",
        app_name="weather_forecast_project",
        zero_values={"random_state": 0},
        numeric_controls={"random_state": "Random state"},
    ),
    *[
        NativeZeroFormCase(
            case_id=f"execution-{engine}-seed-zero",
            app_name=f"execution_{engine}_project",
            zero_values={"seed": 0},
            numeric_controls={"seed": "Seed"},
            change_label="Files",
            initial_change_value=16,
            changed_value=17,
        )
        for engine in ("polars", "pandas")
    ],
    *[
        NativeZeroFormCase(
            case_id=f"learning-assessment-{parameter}-zero",
            app_name="learning_assessment_project",
            zero_values={parameter: 0.0},
            numeric_controls={parameter: label},
            seed_overrides={
                "case_source": "standalone_ai",
                "ai_topic": "Zero temperature regression",
            }
            if parameter == "ai_temperature"
            else None,
        )
        for parameter, label in (
            ("minimum_evidence_confidence", "Minimum evidence confidence"),
            ("minimum_regression_coverage", "Minimum regression coverage"),
            ("ai_temperature", "AI temperature"),
        )
    ],
    NativeZeroFormCase(
        case_id="flight-telemetry-sampling-rate-zero",
        app_name="flight_telemetry_project",
        zero_values={"sampling_rate": 0.0},
        numeric_controls={"sampling_rate": "Sampling rate"},
        change_label="Number of files to read",
    ),
    NativeZeroFormCase(
        case_id="minimal-app-all-files-zero",
        app_name="minimal_app_project",
        zero_values={"nfile": 0},
        numeric_controls={"nfile": "Number of files"},
        change_key="nskip",
        change_label="Lines to skip",
        initial_change_value=0,
        changed_value=1,
        seed_overrides={"nskip": 0},
    ),
]


@pytest.fixture(scope="session")
def builtin_zero_parameters_chromium_executable() -> str:
    return native_zero_support.native_chromium_executable()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.case_id)
def test_builtin_zeros_survive_native_autosave_and_fresh_session(
    case: NativeZeroFormCase, builtin_zero_parameters_chromium_executable: str
) -> None:
    native_zero_support.assert_native_zero_form_roundtrip(
        case, builtin_zero_parameters_chromium_executable, Path(__file__)
    )
