from __future__ import annotations

import importlib
import importlib.metadata
import sys
import tomllib
from pathlib import Path
from types import ModuleType


AGI_GUI_ROOT = Path(__file__).resolve().parents[1]
AGI_GUI_PACKAGE_ROOT = AGI_GUI_ROOT / "src" / "agi_gui"
ENTRYPOINT_FILES = {"__init__.py"}


def test_agi_gui_package_metadata_points_to_pages_lib() -> None:
    data = tomllib.loads((AGI_GUI_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert data["project"]["name"] == "agi-gui"
    assert data["project"]["urls"]["Source"].endswith("/src/agilab/lib/agi-gui")


def test_agi_gui_exposes_version() -> None:
    module = importlib.import_module("agi_gui")

    assert module.__version__ == importlib.metadata.version("agi-gui")


def test_agi_gui_exports_file_picker_helpers() -> None:
    module = importlib.import_module("agi_gui")

    assert module.ActionStyle.__name__ == "ActionStyle"
    assert module.ActionSpec.__name__ == "ActionSpec"
    assert module.WidgetRegistry.__name__ == "WidgetRegistry"
    assert module.WidgetSpec.__name__ == "WidgetSpec"
    assert callable(module.agi_file_picker)
    assert callable(module.action_button)
    assert callable(module.action_row)
    assert callable(module.action_style)
    assert callable(module.list_file_picker_entries)
    assert callable(module.compact_choice)
    assert callable(module.confirm_button)
    assert callable(module.default_widget_registry)
    assert callable(module.empty_state)
    assert callable(module.get_widget)
    assert callable(module.normalize_action_kind)
    assert callable(module.normalize_message_state)
    assert callable(module.normalize_status_state)
    assert callable(module.notice)
    assert callable(module.status_container)
    assert callable(module.toast)
    assert callable(module.widget_registry_rows)


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


def test_top_level_agi_gui_modules_are_entrypoints_or_compatibility_shims() -> None:
    direct_modules = sorted(AGI_GUI_PACKAGE_ROOT.glob("*.py"))

    assert {path.name for path in direct_modules if path.name in ENTRYPOINT_FILES} == ENTRYPOINT_FILES

    for path in direct_modules:
        if path.name in ENTRYPOINT_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        assert "Compatibility shim" in text or "Compatibility import" in text
        assert (
            "activate_compat_module" in text
            or "alias_agi_env_module" in text
        ), path
