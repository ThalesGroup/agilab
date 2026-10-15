"""Native cold/save/fresh regressions for valid mission and data-quality zeros."""

import importlib
import sys
from pathlib import Path

import pytest

test_support_root = str(Path(__file__).resolve().parent)
if test_support_root not in sys.path:
    sys.path.insert(0, test_support_root)
native_zero_support = importlib.import_module("_native_form_zero_robot_support")
NativeZeroFormCase = native_zero_support.NativeZeroFormCase


MISSION_WEIGHT_CONTROLS = {
    "latency_weight": "Latency weight",
    "cost_weight": "Cost weight",
    "reliability_weight": "Reliability weight",
    "risk_weight": "Risk weight",
}
CASES = [
    NativeZeroFormCase(
        case_id=f"mission-decision-{weight}-zero",
        app_name="mission_decision_project",
        zero_values={weight: 0.0, "random_seed": 0},
        numeric_controls={**MISSION_WEIGHT_CONTROLS, "random_seed": "Random seed"},
    )
    for weight in MISSION_WEIGHT_CONTROLS
] + [
    NativeZeroFormCase(
        case_id="data-quality-gate-drift-and-seed-zero",
        app_name="data_quality_gate_project",
        zero_values={"drift_strength": 0.0, "seed": 0},
        numeric_controls={"drift_strength": "Drift strength", "seed": "Seed"},
        change_key="baseline_rows",
        change_label="Baseline rows",
        initial_change_value=240,
        changed_value=250,
    ),
]


@pytest.fixture(scope="session")
def mission_data_quality_chromium_executable() -> str:
    return native_zero_support.native_chromium_executable()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.case_id)
def test_mission_data_quality_zeros_survive_native_autosave_and_fresh_session(
    case: NativeZeroFormCase, mission_data_quality_chromium_executable: str
) -> None:
    native_zero_support.assert_native_zero_form_roundtrip(
        case, mission_data_quality_chromium_executable, Path(__file__)
    )
