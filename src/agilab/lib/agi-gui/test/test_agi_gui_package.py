from __future__ import annotations

import importlib
import tomllib
from pathlib import Path


AGI_GUI_ROOT = Path(__file__).resolve().parents[1]


def test_agi_gui_package_metadata_points_to_pages_lib() -> None:
    data = tomllib.loads((AGI_GUI_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert data["project"]["name"] == "agi-gui"
    assert data["project"]["urls"]["Source"].endswith("/src/agilab/lib/agi-gui")


def test_agi_gui_exposes_version() -> None:
    module = importlib.import_module("agi_gui")

    assert module.__version__ == "2026.4.27.post5"
