from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/ui_robot_coverage_contract.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("ui_robot_coverage_contract_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_ui_robot_coverage_contract_passes_for_current_matrix() -> None:
    module = _load_module()

    payload = module.evaluate_contract()

    assert payload["schema"] == module.SCHEMA
    assert payload["success"] is True
    assert payload["issues"] == []
    for page in module.REQUIRED_CORE_PAGES:
        assert payload["coverage"]["core_pages"][page]
    for action in module.REQUIRED_HIGH_RISK_ACTIONS:
        assert payload["coverage"]["high_risk_actions"][action]
    assert payload["coverage"]["configured_apps_pages_scenarios"] == ["isolated-entry-and-app-pages"]


def test_ui_robot_coverage_contract_json_cli(capsys) -> None:
    module = _load_module()

    exit_code = module.main(["--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    assert payload["schema"] == module.SCHEMA
