from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


MODULE_PATH = Path(
    "src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py"
)
APP_SETTINGS_PATH = Path("src/agilab/apps/builtin/flight_project/src/app_settings.toml")


def _load_view_maps_network_module():
    spec = importlib.util.spec_from_file_location("view_maps_network_test_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    active_app = Path("src/agilab/apps/builtin/flight_project").resolve()
    argv = [MODULE_PATH.name, "--active-app", str(active_app)]
    with patch("sys.argv", argv):
        spec.loader.exec_module(module)
    return module


def test_view_maps_network_reads_builtin_flight_page_defaults() -> None:
    module = _load_view_maps_network_module()

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
