from __future__ import annotations

PAGE_PATH = "src/agilab/apps-pages/view_maps_3d/src/view_maps_3d/view_maps_3d.py"


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
