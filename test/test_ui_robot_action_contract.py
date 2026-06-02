from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


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


class _FakeWidgetRobot:
    RISKY_ACTION_LABEL_TOKENS = {"delete", "reset"}

    @staticmethod
    def _normalized_label(label: str) -> str:
        return " ".join(label.casefold().split())

    @staticmethod
    def _action_label_has_safe_prefix(label: str) -> bool:
        return label.casefold().startswith(("cancel ", "check "))

    @staticmethod
    def _action_label_tokens(label: str) -> set[str]:
        return {token.strip(" .:-_").casefold() for token in label.split()}

    @staticmethod
    def parse_csv(raw: str) -> list[str]:
        return [part.strip() for part in raw.split(",") if part.strip()]


def _patch_fake_runtime(monkeypatch, module) -> None:
    def _fake_load_module(name: str, _path: Path):
        if "matrix" in name:
            return SimpleNamespace(ALL_SCENARIOS={})
        if "widget_robot" in name:
            return _FakeWidgetRobot
        raise AssertionError(f"unexpected module load: {name}")

    monkeypatch.setattr(module, "_load_module", _fake_load_module)


def test_ui_robot_action_contract_passes_for_current_ui_surface() -> None:
    module = _load_module()

    payload = module.evaluate_contract()
    actions_by_label = {action["label"]: action for action in payload["actions"]}

    assert payload["schema"] == module.SCHEMA
    assert payload["success"] is True
    assert payload["issues"] == []
    assert actions_by_label["Install"]["disposition"] == "selected-click"
    assert actions_by_label["Run -> Load -> Export"]["disposition"] == "selected-click"
    assert actions_by_label["Delete"]["disposition"] == "trial-only"
    assert "Export" not in actions_by_label
    assert actions_by_label["Apply"]["disposition"] == "trial-only"
    assert actions_by_label["Overwrite"]["disposition"] == "ignored"
    assert actions_by_label["Rebuild Universal Offline knowledge base"]["disposition"] == "ignored"
    assert actions_by_label["Reset"]["disposition"] == "trial-only"
    assert actions_by_label["Train / refresh"]["disposition"] == "trial-only"
    assert payload["summary"]["unused_disposition_count"] == 0


def test_ui_robot_action_contract_load_module_rejects_missing_spec(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module.importlib.util, "spec_from_file_location", lambda _name, _path: None)

    with pytest.raises(RuntimeError, match="Could not load"):
        module._load_module("missing", Path("missing.py"))


def test_ui_robot_action_contract_scanner_handles_ast_edge_cases(tmp_path: Path) -> None:
    module = _load_module()
    _write_page(
        tmp_path,
        """
from streamlit import button

ANNOTATED_LABEL: str = "Reset project"
CONCAT_LABEL = "Delete " + "cache"
DYNAMIC_LABEL = f"Delete {object()}"

button(ANNOTATED_LABEL)
button(CONCAT_LABEL)
button(DYNAMIC_LABEL)
""",
    )
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    occurrences = module.scan_action_occurrences(
        [tmp_path / "missing", tmp_path],
        widget_robot=_FakeWidgetRobot,
    )

    assert [(item.label, item.kind) for item in occurrences] == [
        ("Delete cache", "button"),
        ("Reset project", "button"),
    ]


def test_ui_robot_action_contract_selected_scenarios_ignore_blank_labels() -> None:
    module = _load_module()
    widget_robot = SimpleNamespace(
        _normalized_label=lambda label: " ".join(str(label).casefold().split()),
        parse_csv=lambda raw: [part.strip() for part in str(raw).split(",")],
    )
    matrix = SimpleNamespace(
        ALL_SCENARIOS={
            "selected": SimpleNamespace(
                name="selected",
                action_button_policy="click-selected",
                click_action_labels=" , Reset project",
            )
        }
    )

    selected = module._selected_action_scenarios(widget_robot, matrix)

    assert selected == {"reset project": ["selected"]}


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


def test_ui_robot_action_contract_rejects_empty_explicit_reason(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    _patch_fake_runtime(monkeypatch, module)
    monkeypatch.setattr(module, "EXPLICIT_ACTION_DISPOSITIONS", {"Delete": ("trial-only", "")})
    _write_page(
        tmp_path,
        """
import streamlit as st

st.button("Delete")
""",
    )

    payload = module.evaluate_contract((tmp_path,))

    assert payload["success"] is False
    assert payload["issues"] == [
        {
            "kind": "missing_action_reason",
            "label": "Delete",
            "detail": "trial-only action must include a non-empty reason",
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


def test_ui_robot_action_contract_human_rendering_and_cli(capsys, monkeypatch) -> None:
    module = _load_module()
    payload = {
        "schema": module.SCHEMA,
        "success": False,
        "summary": {
            "action_count": 1,
            "high_risk_action_count": 1,
            "unclassified_high_risk_action_count": 1,
        },
        "issues": [
            {
                "kind": "unclassified_high_risk_action",
                "label": "Reset project",
                "detail": "needs coverage",
                "path": "src/agilab/page.py",
                "line": 12,
            }
        ],
        "actions": [],
        "unused_dispositions": [],
    }
    monkeypatch.setattr(module, "evaluate_contract", lambda _roots: payload)

    exit_code = module.main([])

    assert exit_code == 1
    rendered = capsys.readouterr().out
    assert "AGILAB UI robot action contract" in rendered
    assert "verdict: FAIL" in rendered
    assert "src/agilab/page.py:12" in rendered


def test_ui_robot_action_contract_json_cli(capsys, monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module,
        "evaluate_contract",
        lambda _roots: {
            "schema": module.SCHEMA,
            "success": True,
            "summary": {"action_count": 0},
            "issues": [],
            "actions": [],
            "unused_dispositions": [],
        },
    )

    exit_code = module.main(["--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    assert payload["schema"] == module.SCHEMA
