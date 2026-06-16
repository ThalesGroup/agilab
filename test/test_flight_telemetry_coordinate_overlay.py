from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path

import polars as pl


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "src/agilab/apps/builtin/flight_telemetry_project"
PROJECT_SRC = PROJECT_ROOT / "src"
WORKER_PATH = PROJECT_SRC / "flight_telemetry_worker/flight_telemetry_worker.py"


def _load_worker_module():
    sys.path.insert(0, str(PROJECT_SRC))
    module_name = "flight_telemetry_coordinate_overlay_worker_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, WORKER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_flight_telemetry_output_adds_generic_coordinate_overlay_columns() -> None:
    module = _load_worker_module()
    df = pl.DataFrame(
        {
            "aircraft": ["A001", "A001", "B002"],
            "lat": [48.0, 50.0, 52.0],
            "long": [2.0, 4.0, 6.0],
        }
    )

    result = module._add_coordinate_overlay_columns(df)

    assert {
        "overlay_lat",
        "overlay_long",
        "overlay_label",
        "overlay_kind",
    } <= set(result.columns)

    rows = (
        result.select(
            "aircraft",
            "overlay_lat",
            "overlay_long",
            "overlay_label",
            "overlay_kind",
        )
        .unique()
        .sort("aircraft")
        .to_dicts()
    )
    assert rows == [
        {
            "aircraft": "A001",
            "overlay_lat": 49.0,
            "overlay_long": 3.0,
            "overlay_label": "route centroid: A001",
            "overlay_kind": "route_centroid",
        },
        {
            "aircraft": "B002",
            "overlay_lat": 52.0,
            "overlay_long": 6.0,
            "overlay_label": "route centroid: B002",
            "overlay_kind": "route_centroid",
        },
    ]


def test_flight_telemetry_view_maps_defaults_select_coordinate_overlay_columns() -> None:
    settings = tomllib.loads(
        (PROJECT_ROOT / "src/app_settings.toml").read_text(encoding="utf-8")
    )

    view_maps = settings["view_maps"]
    assert view_maps["show_coordinate_overlay"] is True
    assert view_maps["overlay_lat"] == "overlay_lat"
    assert view_maps["overlay_long"] == "overlay_long"
    assert view_maps["overlay_label"] == "overlay_label"
