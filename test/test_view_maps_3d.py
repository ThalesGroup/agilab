from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

PAGE_PATH = "src/agilab/apps-pages/view_maps_3d/src/view_maps_3d/view_maps_3d.py"
MODULE_PATH = Path(PAGE_PATH)


class _State(dict):
    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:
            raise AttributeError(item) from exc

    def __setattr__(self, item, value):
        self[item] = value


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


def test_view_maps_3d_initializes_visible_dataset_files(monkeypatch, tmp_path) -> None:
    module = _load_view_maps_3d_module()
    datadir = tmp_path / "datasets"
    visible = datadir / "visible.csv"
    hidden = datadir / ".shadow" / "ignored.csv"

    monkeypatch.setattr(module, "_list_dataset_files", lambda base_dir, ext_choice="all": [visible, hidden])
    state = _State(datadir=datadir)
    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=state))

    module.initialize_csv_files()

    assert state["dataset_files"] == [visible]
    assert state["csv_files"] == [visible]
    assert state["df_file"] == "visible.csv"


def test_view_maps_3d_initializes_visible_beam_files(monkeypatch, tmp_path) -> None:
    module = _load_view_maps_3d_module()
    beamdir = tmp_path / "beams"
    visible = beamdir / "beam.csv"
    hidden = beamdir / ".shadow" / "ignored.csv"

    monkeypatch.setattr(module, "find_files", lambda base: [visible, hidden])
    state = _State(beamdir=beamdir)
    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=state))

    module.initialize_beam_files()

    assert state["beam_csv_files"] == [visible]
    assert state["beam_file"] == "beam.csv"


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


def test_view_maps_3d_get_palette_and_update_beamdir(monkeypatch, tmp_path) -> None:
    module = _load_view_maps_3d_module()
    messages: list[str] = []
    monkeypatch.setattr(module.st, "error", lambda message: messages.append(message))

    assert module.get_palette("Plotly")
    assert module.get_palette("NoSuchPalette") == []
    assert messages and "Palette 'NoSuchPalette' not found." in messages[-1]

    state = _State(
        beamdir="old",
        beam_file="old.csv",
        beam_csv_files=["old.csv"],
        input_beamdir=str(tmp_path / "new_beams"),
    )
    calls: list[str] = []
    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(module, "initialize_beam_files", lambda: calls.append("called"))

    module.update_beamdir("beamdir", "input_beamdir")

    assert "beam_file" not in state
    assert "beam_csv_files" not in state
    assert state["beamdir"] == str(tmp_path / "new_beams")
    assert calls == ["called"]


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


def test_view_maps_3d_generates_palette_maps_and_basic_state_updates(monkeypatch) -> None:
    module = _load_view_maps_3d_module()

    randint_values = iter([101, 102, 103, 104, 105, 106])
    monkeypatch.setattr(module.random, "randint", lambda low, high: next(randint_values))
    assert module.generate_random_colors(2) == [[101, 102, 103], [104, 105, 106]]

    color_map = module.get_category_color_map(
        pd.DataFrame({"kind": ["A", "B", "C"]}),
        "kind",
        "Plotly",
    )
    assert set(color_map) == {"A", "B", "C"}
    assert all(len(rgb) == 3 for rgb in color_map.values())

    state = _State(input_value="fresh")
    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=state))
    module.update_var("saved_value", "input_value")
    module.continious()
    assert state["saved_value"] == "fresh"
    assert state["coltype"] == "continious"
    module.discrete()
    assert state["coltype"] == "discrete"
    assert module._vm3d_key("dataset") == "view_maps_3d:dataset"


def test_view_maps_3d_moves_data_and_downsamples_deterministically(monkeypatch, tmp_path) -> None:
    module = _load_view_maps_3d_module()

    messages: list[str] = []
    update_calls: list[tuple[str, str]] = []
    beamdir = tmp_path / "beamdir"
    beamdir.mkdir()
    state = _State(beamdir=str(beamdir))
    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(session_state=state, sidebar=SimpleNamespace(success=messages.append)),
    )
    monkeypatch.setattr(module, "update_beamdir", lambda var_key, widget_key: update_calls.append((var_key, widget_key)))

    module.move_to_data("beam.csv", "a,b\n1,2\n")

    written = (beamdir / "beam.csv").read_text(encoding="utf-8")
    assert written == "a,b\n1,2\n"
    assert messages == [f"File moved to {beamdir / 'beam.csv'}"]
    assert update_calls == [("beamdir", "input_beamdir")]

    df = pd.DataFrame({"value": [10, 20, 30, 40]}, index=[9, 8, 7, 6])
    downsampled = module.downsample_df_deterministic(df, 2)
    assert downsampled.to_dict("records") == [{"value": 10}, {"value": 30}]
    with pytest.raises(ValueError, match="positive integer"):
        module.downsample_df_deterministic(df, 0)


def test_view_maps_3d_lists_multiple_extensions_and_preserves_existing_dataset_choice(monkeypatch, tmp_path) -> None:
    module = _load_view_maps_3d_module()
    datadir = tmp_path / "datasets"
    csv_file = datadir / "b.csv"
    parquet_file = datadir / "a.parquet"
    json_file = datadir / "c.json"

    def fake_find_files(base, ext=None):
        mapping = {
            ".csv": [csv_file, csv_file],
            ".parquet": [parquet_file],
            ".json": [json_file],
        }
        return mapping.get(ext, [])

    monkeypatch.setattr(module, "find_files", fake_find_files)
    assert module._list_dataset_files(datadir, "all") == [parquet_file, csv_file, json_file]

    state = _State(datadir=datadir, dataset_files=[csv_file], csv_files=[csv_file], df_file="already.csv")
    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=state))
    module.initialize_csv_files()
    assert state["df_file"] == "already.csv"
