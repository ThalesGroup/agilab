from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/ui_robot_action_contract.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("ui_robot_action_contract_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_page(root: Path, source: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "page.py").write_text(source, encoding="utf-8")


def test_ui_robot_action_contract_passes_for_current_ui_surface() -> None:
    module = _load_module()

    payload = module.evaluate_contract()
    actions_by_label = {action["label"]: action for action in payload["actions"]}

    assert payload["schema"] == module.SCHEMA
    assert payload["success"] is True
    assert payload["issues"] == []
    assert actions_by_label["INSTALL"]["disposition"] == "selected-click"
    assert actions_by_label["Run -> Load -> Export"]["disposition"] == "selected-click"
    assert actions_by_label["Delete"]["disposition"] == "trial-only"
    assert actions_by_label["Export"]["disposition"] == "trial-only"


def test_ui_robot_action_contract_rejects_unclassified_high_risk_action(tmp_path: Path) -> None:
    module = _load_module()
    _write_page(
        tmp_path,
        """
import streamlit as st

st.button("Reset project")
""",
    )

    payload = module.evaluate_contract((tmp_path,))

    assert payload["success"] is False
    assert payload["issues"] == [
        {
            "kind": "unclassified_high_risk_action",
            "label": "Reset project",
            "detail": "high-risk Streamlit action needs selected-click coverage or an explicit trial-only/ignored reason",
            "path": str(tmp_path / "page.py"),
            "line": 4,
        }
    ]


def test_ui_robot_action_contract_ignores_safe_prefix_and_download_actions(tmp_path: Path) -> None:
    module = _load_module()
    _write_page(
        tmp_path,
        """
import streamlit as st

st.button("Cancel import")
st.download_button("Export report", data="x")
""",
    )

    payload = module.evaluate_contract((tmp_path,))

    assert payload["success"] is True
    assert payload["issues"] == []
    assert payload["summary"]["high_risk_action_count"] == 0


def test_ui_robot_action_contract_json_cli(capsys) -> None:
    module = _load_module()

    exit_code = module.main(["--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    assert payload["schema"] == module.SCHEMA
