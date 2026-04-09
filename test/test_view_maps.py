from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


PAGE_PATH = "src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py"


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
