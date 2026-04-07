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


def test_format_percent_rounds_to_nearest_integer() -> None:
    module = _load_module()

    assert module.format_percent(83.5298) == "84%"
    assert module.format_percent(83.4999) == "83%"
    assert module.format_percent(86.5596) == "87%"

