from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


PAGE_PATH = "src/agilab/apps-pages/view_maps_3d/src/view_maps_3d/view_maps_3d.py"


def test_view_maps_3d_warns_when_no_dataset_exists(tmp_path, monkeypatch) -> None:
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    project_dir = apps_dir / "demo_map_3d_project"
    (project_dir / "src" / "demo_map_3d").mkdir(parents=True)
    (project_dir / "pyproject.toml").write_text("[project]\nname='demo-map-3d-project'\n", encoding="utf-8")
    missing_export_root = tmp_path / "export"
    beam_dir = tmp_path / "beams"
    (project_dir / "src" / "app_settings.toml").write_text(
        "[view_maps_3d]\n"
        f"datadir = \"{(missing_export_root / 'demo_map_3d').as_posix()}\"\n"
        f"beamdir = \"{beam_dir.as_posix()}\"\n"
        "file_ext_choice = \"all\"\n"
        "df_select_mode = \"Single file\"\n",
        encoding="utf-8",
    )
    (project_dir / "src" / "demo_map_3d" / "__init__.py").write_text("", encoding="utf-8")

    argv = [Path(PAGE_PATH).name, "--active-app", str(project_dir)]
    with patch.object(sys, "argv", argv):
        monkeypatch.setenv("AGI_EXPORT_DIR", str(missing_export_root))
        monkeypatch.setenv("AGI_LOCAL_SHARE", str(tmp_path / "localshare"))
        monkeypatch.setenv("AGI_CLUSTER_SHARE", str(tmp_path / "clustershare"))
        monkeypatch.setenv("OPENAI_API_KEY", "dummy")
        monkeypatch.setenv("IS_SOURCE_ENV", "1")
        at = AppTest.from_file(PAGE_PATH, default_timeout=20)
        at.run()

    assert not at.exception
    assert any("Cartography-3D Visualisation" in title.value for title in at.title)
    assert any("No dataset found" in warning.value for warning in at.warning)
    assert any(widget.label == "Data Directory" for widget in at.text_input)
