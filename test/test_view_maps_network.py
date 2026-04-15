from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agi_env import AgiEnv
import pandas as pd

MODULE_PATH = Path(
    "src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py"
)
APP_SETTINGS_PATH = Path("src/agilab/apps/builtin/flight_project/src/app_settings.toml")


def _load_view_maps_network_module(monkeypatch, tmp_path: Path):
    spec = importlib.util.spec_from_file_location("view_maps_network_test_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    active_app = Path("src/agilab/apps/builtin/flight_project").resolve()
    argv = [MODULE_PATH.name, "--active-app", str(active_app)]
    AgiEnv.reset()
    with patch("sys.argv", argv):
        spec.loader.exec_module(module)
    return module


def test_view_maps_network_reads_builtin_flight_page_defaults(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    with APP_SETTINGS_PATH.open("rb") as handle:
        app_settings = tomllib.load(handle)

    module.st = SimpleNamespace(session_state={"app_settings": app_settings})
    settings = module._get_view_maps_page_settings()

    assert settings["dataset_base_choice"] == "AGI_SHARE_DIR"
    assert settings["dataset_subpath"] == "flight/dataframe"
    assert settings["default_traj_globs"] == [
        "flight/dataframe/*.parquet",
        "flight/dataframe/*.csv",
    ]


def test_view_maps_network_normalizes_settings_sources(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    assert module._coerce_str_list(" alpha, beta; alpha\n gamma ") == ["alpha", "beta", "gamma"]
    assert module._get_first_nonempty_setting(
        [{"unused": " "}, "ignored", {"primary": " ", "secondary": " chosen "}],
        "primary",
        "secondary",
    ) == "chosen"
    assert module._get_setting_list(
        [{"paths": "one, two;one"}, {"paths": ["two", "three"]}, {"paths": None}],
        "paths",
    ) == ["one", "two", "three"]


def test_view_maps_network_reads_query_params_and_subdirectories(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)
    module.st = SimpleNamespace(query_params={"multi": ["first", "second"], "single": "value"})

    scan_root = tmp_path / "scan_root"
    scan_root.mkdir()
    (scan_root / "visible_b").mkdir()
    (scan_root / "visible_a").mkdir()
    (scan_root / ".hidden").mkdir()
    (scan_root / "file.txt").write_text("payload", encoding="utf-8")

    assert module._read_query_param("multi") == "second"
    assert module._read_query_param("single") == "value"
    assert module._read_query_param("missing") is None
    assert module._list_subdirectories(scan_root) == ["visible_a", "visible_b"]


def test_view_maps_network_loads_missing_settings_as_empty(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)
    module.st = SimpleNamespace(session_state={})

    module._ensure_app_settings_loaded(SimpleNamespace(app_settings_file=tmp_path / "missing.toml"))

    assert module.st.session_state["app_settings"] == {}


def test_view_maps_network_persists_app_settings(tmp_path: Path, monkeypatch) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)
    settings_path = tmp_path / "app_settings.toml"
    module.st = SimpleNamespace(
        session_state={
            "app_settings": {
                "view_maps_network": {
                    "dataset_base_choice": "AGI_SHARE_DIR",
                }
            }
        }
    )

    module._persist_app_settings(SimpleNamespace(app_settings_file=settings_path))

    written = settings_path.read_text(encoding="utf-8")
    assert "view_maps_network" in written
    assert 'dataset_base_choice = "AGI_SHARE_DIR"' in written


def test_view_maps_network_drops_ambiguous_index_levels(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)
    df = pd.DataFrame(
        {
            "classique_plane": ["A", "B"],
            "time_index": [0, 1],
        },
        index=pd.Index(["A", "B"], name="classique_plane"),
    )

    normalized = module._drop_index_levels_shadowing_columns(df)

    assert list(normalized.columns) == ["classique_plane", "time_index"]
    assert normalized.index.name is None
    assert normalized["classique_plane"].tolist() == ["A", "B"]


def test_view_maps_network_warns_when_no_dataset_exists(
    tmp_path: Path, create_temp_app_project, run_page_app_test
) -> None:
    project_dir = create_temp_app_project(
        "demo_map_project",
        "demo_map",
        "[view_maps_network]\n"
        'base_dir_choice = "AGILAB_EXPORT"\n'
        'file_ext_choice = "all"\n',
        pyproject_name="demo-map-project",
    )

    at = run_page_app_test(str(MODULE_PATH), project_dir, export_root=tmp_path / "export")

    assert not at.exception
    assert any("Maps Network Graph" in title.value for title in at.title)
    assert any("No files found" in warning.value for warning in at.warning)
