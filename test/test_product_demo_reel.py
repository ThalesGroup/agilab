from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image
import tomllib


MODULE_PATH = Path("tools/build_product_demo_reel.py").resolve()
THREE_PROJECT_MODULE_PATH = Path("tools/build_three_project_demo_reel.py").resolve()
FLIGHT_SETTINGS = Path("src/agilab/apps/builtin/flight_telemetry_project/src/app_settings.toml")
PUBLIC_DEMO_GUIDE = Path("docs/source/demo_capture_script.md")
CAPTURE_THREE_PROJECT = Path("tools/capture_three_project_demo.sh")
DATA_IO_CARD = Path("docs/source/diagrams/agilab_mission_decision_card.svg")


def _load_module():
    spec = importlib.util.spec_from_file_location("build_product_demo_reel_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_three_project_module():
    tools_dir = str(THREE_PROJECT_MODULE_PATH.parent)
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    spec = importlib.util.spec_from_file_location("build_three_project_demo_reel_test_module", THREE_PROJECT_MODULE_PATH)
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


def test_three_project_reel_uses_data_io_decision_positioning() -> None:
    module = _load_three_project_module()

    assert module.DEMO_SLUG == "agilab-mission-decision"
    assert "Mission Data -> Decision Engine" in module.MISSION_TITLE
    assert "executable routing decision" in module.MISSION_SUBTITLE
    assert "agilab_mission_decision" in module.DEFAULT_MP4
    assert "data_ml_rl" not in module.DEFAULT_MP4


def test_public_demo_guide_avoids_private_routing_app_names() -> None:
    text = PUBLIC_DEMO_GUIDE.read_text(encoding="utf-8")

    assert "Mission Decision autonomous decision demo" in text
    assert "`mission_decision_project` is the first-class public demo" in text
    assert "Primary run path:" in text
    assert "agilab-mission-decision" in text
    assert "routing / optimization project" in text
    assert "sensor-style streams" in text
    assert "air-gapped mode" in text
    assert "Mission / network optimization" in text
    assert "diagrams/agilab_mission_decision_card.svg" in text
    assert "MP4/GIF remain generated local artifacts" in text
    assert "sb3_trainer_project" not in text
    assert "thales_agilab/apps" not in text
    assert "FCAS" not in text


def test_capture_three_project_demo_defaults_to_public_apps() -> None:
    text = CAPTURE_THREE_PROJECT.read_text(encoding="utf-8")

    assert "agilab-mission-decision" in text
    assert "src/agilab/apps/builtin/uav_relay_queue_project" in text
    assert "AGILAB turns mission data into decisions" in text
    assert "sb3_trainer_project" not in text
    assert "thales_agilab/apps" not in text


def test_capture_three_project_demo_generates_six_step_cue_sheet() -> None:
    name = "pytest-mission-decision"
    cue_dir = Path("artifacts/demo_media") / name
    cue_file = cue_dir / f"{name}_cue_sheet.md"
    shutil.rmtree(cue_dir, ignore_errors=True)
    try:
        subprocess.run(
            [str(CAPTURE_THREE_PROJECT), "--name", name, "--print-only"],
            check=True,
            text=True,
            capture_output=True,
        )
        text = cue_file.read_text(encoding="utf-8")
    finally:
        shutil.rmtree(cue_dir, ignore_errors=True)

    assert "## Demo steps" in text
    assert "1. Live Data Ingestion" in text
    assert "2. Automatic Pipeline Generation" in text
    assert "3. Distributed Execution" in text
    assert "4. AI + Optimization Loop" in text
    assert "5. Real-Time Adaptation" in text
    assert "6. Final Output" in text
    assert "latency down, cost down, reliability up" in text


def test_data_io_companion_card_is_valid_public_svg() -> None:
    text = DATA_IO_CARD.read_text(encoding="utf-8")
    root = ElementTree.fromstring(text)

    assert root.tag.endswith("svg")
    assert root.attrib["viewBox"] == "0 0 1200 675"
    assert "Autonomous Mission Data" in text
    assert "Final output: selected strategy" in text
    assert ("fr" + "ed") not in text.lower()
    assert ("obs" + "olete") not in text.lower()
    assert "sb3_trainer_project" not in text
