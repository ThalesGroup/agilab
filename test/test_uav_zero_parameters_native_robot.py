"""Exercise saved zero values through the real UAV forms and native browser host."""

import importlib
import sys
from pathlib import Path

import pytest

test_support_root = str(Path(__file__).resolve().parent)
if test_support_root not in sys.path:
    sys.path.insert(0, test_support_root)
native_zero_support = importlib.import_module("_native_form_zero_robot_support")


@pytest.fixture(scope="session")
def uav_zero_chromium_executable() -> str:
    return native_zero_support.native_chromium_executable()


@pytest.mark.parametrize("app_name", ["uav_queue_project", "uav_relay_queue_project"])
def test_uav_zero_parameters_survive_native_rerun_autosave_and_fresh_session(
    app_name: str, uav_zero_chromium_executable: str
) -> None:
    native_zero_support.assert_native_zero_form_roundtrip(
        native_zero_support.NativeZeroFormCase(
            case_id=f"uav-zero-parameters-{app_name}",
            app_name=app_name,
            zero_values={"queue_weight": 0.0, "random_seed": 0},
            numeric_controls={
                "queue_weight": "Queue weight",
                "random_seed": "Random seed",
            },
        ),
        uav_zero_chromium_executable,
        Path(__file__),
    )
