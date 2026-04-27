from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from PIL import Image
import tomllib


MODULE_PATH = Path("tools/build_product_demo_reel.py").resolve()
FLIGHT_SETTINGS = Path("src/agilab/apps/builtin/flight_project/src/app_settings.toml")


def _load_module():
    spec = importlib.util.spec_from_file_location("build_product_demo_reel_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_flight_reel_finale_targets_view_maps_not_network_view() -> None:
    module = _load_module()

    finale = module.FLIGHT_SCENES[-1]

    assert finale.name == "finale"
    assert finale.image.name == "analysis-page.png"
    assert finale.stage == "ANALYSIS"
    assert finale.overlay == "view_maps"
    assert finale.highlight_label == "view_maps"
    assert "view_maps" in finale.title


def test_view_maps_overlay_draws_visible_panel() -> None:
    module = _load_module()
    canvas = Image.new("RGBA", (module.W, module.H), (0, 0, 0, 0))

    before = canvas.getbbox()
    module.draw_view_maps_overlay(canvas, module.FLIGHT_SCENES[-1], 0, 0)

    assert before is None
    assert canvas.getbbox() is not None


def test_flight_view_maps_seed_defaults_are_portable() -> None:
    settings = tomllib.loads(FLIGHT_SETTINGS.read_text(encoding="utf-8"))
    view_maps = settings["view_maps"]

    assert view_maps["datadir"] == ""
    assert view_maps["df_file"] == ""
    assert view_maps["df_files_selected"] == []
    assert view_maps["discrete"] == "aircraft"
    assert view_maps["lat"] == "lat"
    assert view_maps["long"] == "long"
    assert "/home/agi" not in FLIGHT_SETTINGS.read_text(encoding="utf-8")
