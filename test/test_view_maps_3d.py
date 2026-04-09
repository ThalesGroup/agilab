from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

PAGE_PATH = "src/agilab/apps-pages/view_maps_3d/src/view_maps_3d/view_maps_3d.py"
MODULE_PATH = Path(PAGE_PATH)


def _load_view_maps_3d_module():
    spec = importlib.util.spec_from_file_location("view_maps_3d_test_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch("streamlit.title", lambda *args, **kwargs: None):
        spec.loader.exec_module(module)
    return module


def test_view_maps_3d_warns_when_no_dataset_exists(tmp_path, create_temp_app_project, run_page_app_test) -> None:
    missing_export_root = tmp_path / "export"
    beam_dir = tmp_path / "beams"
    project_dir = create_temp_app_project(
        "demo_map_3d_project",
        "demo_map_3d",
        "[view_maps_3d]\n"
        f"datadir = \"{(missing_export_root / 'demo_map_3d').as_posix()}\"\n"
        f"beamdir = \"{beam_dir.as_posix()}\"\n"
        "file_ext_choice = \"all\"\n"
        "df_select_mode = \"Single file\"\n",
        pyproject_name="demo-map-3d-project",
    )
    at = run_page_app_test(PAGE_PATH, project_dir, export_root=missing_export_root)

    assert not at.exception
    assert any("Cartography-3D Visualisation" in title.value for title in at.title)
    assert any("No dataset found" in warning.value for warning in at.warning)
    assert any(widget.label == "Data Directory" for widget in at.text_input)


def test_view_maps_3d_lists_dataset_files_sorted_without_duplicates(monkeypatch, tmp_path) -> None:
    module = _load_view_maps_3d_module()
    datadir = tmp_path / "datasets"

    a = datadir / "b.csv"
    b = datadir / "a.csv"
    monkeypatch.setattr(module, "find_files", lambda base, ext: [a, b, a] if ext == ".csv" else [])

    listed = module._list_dataset_files(datadir, "csv")

    assert listed == [b, a]


def test_view_maps_3d_converts_hex_and_geojson_helpers() -> None:
    module = _load_view_maps_3d_module()
    geojson_data = {
        "features": [
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[2.0, 48.0], [2.1, 48.0], [2.0, 48.1], [2.0, 48.0]]],
                }
            },
            {
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [[[3.0, 47.0], [3.1, 47.0], [3.0, 47.1], [3.0, 47.0]]],
                    ],
                }
            },
        ]
    }

    assert module.hex_to_rgb("#A1B2C3") == (161, 178, 195)
    assert module.hex_to_rgb("oops") == (0, 0, 0)

    df = module.poly_geojson_to_csv(geojson_data)

    assert list(df.columns) == ["polygon_index", "longitude", "latitude"]
    assert len(df) == 8
    assert set(df["polygon_index"]) == {0, 1}


def test_view_maps_3d_update_datadir_clears_cached_dataset_state(monkeypatch) -> None:
    module = _load_view_maps_3d_module()
    session_state = {
        "df_file": "old.csv",
        "df_files_selected": ["old.csv"],
        "csv_files": ["old.csv"],
        "dataset_files": [Path("old.csv")],
        "loaded_df": pd.DataFrame({"lat": [1.0]}),
        "input_datadir": "/tmp/new-datadir",
    }
    initialize_calls: list[str] = []

    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=session_state))
    monkeypatch.setattr(module, "initialize_csv_files", lambda: initialize_calls.append("called"))

    module.update_datadir("datadir", "input_datadir")

    for key in ("df_file", "df_files_selected", "csv_files", "dataset_files", "loaded_df"):
        assert key not in session_state
    assert session_state["datadir"] == "/tmp/new-datadir"
    assert initialize_calls == ["called"]
