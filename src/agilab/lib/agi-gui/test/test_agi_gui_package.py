from __future__ import annotations

import importlib
import sys
import tomllib
from pathlib import Path
from types import ModuleType


AGI_GUI_ROOT = Path(__file__).resolve().parents[1]


def test_agi_gui_package_metadata_points_to_pages_lib() -> None:
    data = tomllib.loads((AGI_GUI_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert data["project"]["name"] == "agi-gui"
    assert data["project"]["urls"]["Source"].endswith("/src/agilab/lib/agi-gui")


def test_agi_gui_exposes_version() -> None:
    module = importlib.import_module("agi_gui")

    assert module.__version__ == "2026.4.27.post6"


def test_agi_gui_exports_file_picker_helpers() -> None:
    module = importlib.import_module("agi_gui")

    assert callable(module.agi_file_picker)
    assert callable(module.list_file_picker_entries)
    assert callable(module.compact_choice)
    assert callable(module.confirm_button)
    assert callable(module.status_container)
    assert callable(module.toast)


def test_compat_alias_exposes_source_module(monkeypatch) -> None:
    compat = importlib.import_module("agi_gui._compat")
    source = ModuleType("demo_source_module")
    monkeypatch.setitem(sys.modules, "demo_source_module", source)

    result = compat.alias_agi_env_module("agi_gui.demo_alias", "demo_source_module")

    assert result is source
    assert sys.modules["agi_gui.demo_alias"] is source


def test_compatibility_proxy_modules_import_from_agi_env() -> None:
    proxy_names = [
        "pagelib",
        "pagelib_data_support",
        "pagelib_execution_support",
        "pagelib_navigation_support",
        "pagelib_preview_support",
        "pagelib_project_support",
        "pagelib_resource_support",
        "pagelib_runtime_support",
        "pagelib_selection_support",
        "pagelib_session_support",
        "streamlit_args",
        "ui_docs_support",
        "ui_state_support",
        "ui_support",
    ]

    for proxy_name in proxy_names:
        module = importlib.import_module(f"agi_gui.{proxy_name}")
        assert module.__name__ == f"agi_env.{proxy_name}"
