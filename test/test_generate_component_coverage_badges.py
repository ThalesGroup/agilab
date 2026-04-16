from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path("tools/generate_component_coverage_badges.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("generate_component_coverage_badges_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_format_percent_truncates_for_ci_stability() -> None:
    module = _load_module()

    assert module.format_percent(83.5298) == "83%"
    assert module.format_percent(83.4999) == "83%"
    assert module.format_percent(86.5596) == "86%"


def test_selected_component_items_preserves_requested_subset_order() -> None:
    module = _load_module()

    selected = module.selected_component_items(["agi-gui", "agi-env"])

    assert [name for name, _ in selected] == ["agi-gui", "agi-env"]


def test_selected_component_items_defaults_to_all_components() -> None:
    module = _load_module()

    selected = module.selected_component_items(None)

    assert [name for name, _ in selected] == list(module.COMPONENTS)


def test_component_badges_use_component_name_in_label() -> None:
    module = _load_module()

    assert module.COMPONENTS["agilab"]["label"] == "agilab coverage"
    assert module.COMPONENTS["agi-env"]["label"] == "agi-env coverage"
    assert module.COMPONENTS["agi-node"]["label"] == "agi-node coverage"
    assert module.COMPONENTS["agi-cluster"]["label"] == "agi-cluster coverage"
    assert module.COMPONENTS["agi-gui"]["label"] == "agi-gui coverage"
    assert module.COMPONENTS["agi-core"]["label"] == "agi-core coverage"
