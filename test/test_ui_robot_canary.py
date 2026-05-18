from __future__ import annotations

import builtins
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path("tools/ui_robot_canary.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("ui_robot_canary_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeWidgetRobot:
    @staticmethod
    def _keyboard_focus_result_probe(**_kwargs):
        return SimpleNamespace(
            kind="keyboard_focus",
            status="failed",
            detail="expected at least 5 unique focus targets",
        )

    @staticmethod
    def _layout_integrity_result_probe(**_kwargs):
        return SimpleNamespace(
            kind="layout_integrity",
            status="failed",
            detail="text_overflow: text exceeds container",
        )

    @staticmethod
    def _accessibility_result_probe(**_kwargs):
        return SimpleNamespace(
            kind="accessibility",
            status="failed",
            detail="missing_accessible_name: no accessible name",
        )

    @staticmethod
    def _above_fold_result_probe(**_kwargs):
        return SimpleNamespace(
            kind="above_fold",
            status="failed",
            detail="missing expected target above fold",
        )

    @staticmethod
    def _append_browser_issue_probes(probes, **_kwargs):
        probes.append(SimpleNamespace(kind="browser_error", status="failed"))
        return True


def test_probe_canary_classifies_expected_failure() -> None:
    module = _load_module()

    result = module._probe_canary(
        "demo",
        SimpleNamespace(kind="accessibility", status="failed", detail="missing name"),
        expected_kind="accessibility",
        detail_needle="missing",
    )
    mismatch = module._probe_canary(
        "demo",
        SimpleNamespace(kind="accessibility", status="passed", detail="ok"),
        expected_kind="accessibility",
    )

    assert result.success is True
    assert result.observed == "accessibility:failed:missing name"
    assert mismatch.success is False
    assert "unexpected probe result" in mismatch.detail


def test_probe_canaries_cover_pure_widget_robot_faults() -> None:
    module = _load_module()

    results = module.run_probe_canaries(_FakeWidgetRobot())

    assert [result.name for result in results] == [
        "keyboard-focus-trap",
        "layout-overflow",
        "accessibility-missing-name",
        "above-fold-missing-target",
        "browser-error-capture",
    ]
    assert all(result.success for result in results)


def test_load_module_and_visual_canary_detects_baseline_mismatch() -> None:
    module = _load_module()

    loaded = module._load_module("ui_robot_canary_self_for_test", MODULE_PATH)
    visual = module.run_visual_canary()

    assert loaded.SCHEMA == module.SCHEMA
    assert visual.name == "visual-baseline-diff"
    assert visual.success is True
    assert "mismatch was detected" in visual.detail


def test_browser_canary_reports_missing_playwright(monkeypatch) -> None:
    module = _load_module()
    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "playwright.sync_api":
            raise ModuleNotFoundError("No module named 'playwright'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    results = module.run_browser_canaries(
        _FakeWidgetRobot(),
        browser_name="chromium",
        headless=True,
    )

    assert len(results) == 1
    assert results[0].name == "browser-canaries"
    assert results[0].success is False
    assert "playwright is unavailable" in results[0].detail


def test_report_rendering_and_json_cli(tmp_path, monkeypatch, capsys) -> None:
    module = _load_module()
    output = tmp_path / "canary.json"
    monkeypatch.setattr(module, "_load_module", lambda _name, _path: _FakeWidgetRobot())

    exit_code = module.main(["--skip-browser", "--skip-visual", "--output", str(output), "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == module.SCHEMA
    assert payload["summary"]["canary_count"] == 5
    assert payload["summary"]["failed_count"] == 0
    assert json.loads(output.read_text(encoding="utf-8")) == payload
    assert "AGILAB UI robot canary" in module.render_human(payload)
