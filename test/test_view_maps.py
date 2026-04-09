from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

PAGE_PATH = "src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py"
MODULE_PATH = Path(PAGE_PATH)


def _load_view_maps_module():
    spec = importlib.util.spec_from_file_location("view_maps_test_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch("streamlit.title", lambda *args, **kwargs: None):
        spec.loader.exec_module(module)
    return module


def test_view_maps_renders_minimal_export_dataset(tmp_path, monkeypatch) -> None:
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    project_dir = apps_dir / "demo_map_project"
    (project_dir / "src" / "demo_map").mkdir(parents=True)
    (project_dir / "pyproject.toml").write_text("[project]\nname='demo-map-project'\n", encoding="utf-8")
    dataset_dir = tmp_path / "export" / "demo_map"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "export.csv").write_text(
        "lat,long,beam,alt_m\n"
        "48.8566,2.3522,A,1200\n"
        "43.6045,1.4440,B,1250\n"
        "45.7640,4.8357,A,1300\n",
        encoding="utf-8",
    )
    (project_dir / "src" / "app_settings.toml").write_text(
        "[view_maps]\n"
        f"datadir = \"{dataset_dir.as_posix()}\"\n"
        "file_ext_choice = \"all\"\n"
        "df_select_mode = \"Single file\"\n",
        encoding="utf-8",
    )
    (project_dir / "src" / "demo_map" / "__init__.py").write_text("", encoding="utf-8")

    argv = [Path(PAGE_PATH).name, "--active-app", str(project_dir)]
    with patch.object(sys, "argv", argv):
        monkeypatch.setenv("AGI_EXPORT_DIR", str(tmp_path / "export"))
        monkeypatch.setenv("AGI_LOCAL_SHARE", str(tmp_path / "localshare"))
        monkeypatch.setenv("AGI_CLUSTER_SHARE", str(tmp_path / "clustershare"))
        monkeypatch.setenv("OPENAI_API_KEY", "dummy")
        monkeypatch.setenv("IS_SOURCE_ENV", "1")
        at = AppTest.from_file(PAGE_PATH, default_timeout=20)
        at.run()

    assert not at.exception
    assert any("Cartography Visualisation" in title.value for title in at.title)
    assert any(widget.label == "Dataset selection" for widget in at.radio)
    assert any(widget.label == "File type" for widget in at.selectbox)
    assert any(widget.label == "DataFrame" for widget in at.selectbox)
    assert at.session_state["datadir"] == str(dataset_dir)
    assert at.session_state["file_ext_choice"] == "all"
    assert at.session_state["df_select_mode"] == "Single file"
    assert [path.name for path in at.session_state["dataset_files"]] == ["export.csv"]
    assert at.session_state["view_maps:df_files_selected"] == ["export.csv"]


def test_view_maps_filters_hidden_dataset_files() -> None:
    module = _load_view_maps_module()
    datadir = Path("/tmp/demo-datasets")

    files = [
        datadir / "visible.csv",
        datadir / ".hidden.csv",
        datadir / "nested" / ".shadow" / "ignored.parquet",
        Path("/elsewhere/outside.json"),
    ]

    visible = module._visible_dataset_files(datadir, files)

    assert visible == [datadir / "visible.csv", Path("/elsewhere/outside.json")]


def test_view_maps_computes_viewport_for_numeric_coordinates() -> None:
    module = _load_view_maps_module()
    df = pd.DataFrame(
        {
            "lat": ["48.0", "49.0", "bad"],
            "lon": [2.0, 2.8, None],
        }
    )

    viewport = module._compute_viewport(df, "lat", "lon")

    assert viewport == {
        "center_lat": 48.5,
        "center_lon": 2.4,
        "default_zoom": 9,
    }


def test_view_maps_persists_view_settings(tmp_path) -> None:
    module = _load_view_maps_module()
    settings_path = tmp_path / "app_settings.toml"
    env = SimpleNamespace(app_settings_file=settings_path)

    payload = module._persist_view_maps_settings(
        env,
        {"ui": {"map": {"center_lat": 0.0}}},
        {"datadir": "/tmp/export", "file_ext_choice": "csv"},
    )

    assert payload["ui"]["map"]["center_lat"] == 0.0
    assert payload["view_maps"]["datadir"] == "/tmp/export"
    written = settings_path.read_text(encoding="utf-8")
    assert "view_maps" in written
    assert "datadir = \"/tmp/export\"" in written
