from __future__ import annotations

import builtins
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


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


class _FakePage:
    def __init__(self) -> None:
        self.url = "about:blank"
        self.contents: list[str] = []
        self.evaluated: list[str] = []
        self.waits: list[int] = []
        self.browser_issues: list[dict[str, str]] | None = None

    def set_content(self, html: str, *, wait_until: str) -> None:
        assert wait_until == "domcontentloaded"
        self.contents.append(html)

    def evaluate(self, script: str):
        self.evaluated.append(script)
        if script == _FakeBrowserWidgetRobot.ABOVE_FOLD_COLLECTOR_JS:
            return {
                "fold": 700,
                "targets": [
                    {"label": "ORCHESTRATE", "inFold": True},
                    {"label": "INSTALL", "inFold": False},
                ],
            }
        if self.browser_issues is not None and "console.error" in script:
            self.browser_issues.append({"kind": "console", "detail": "Uncaught TypeError: canary browser issue"})
        return None

    def wait_for_timeout(self, milliseconds: int) -> None:
        self.waits.append(milliseconds)


class _FakeBrowserContext:
    def __init__(self) -> None:
        self.page = _FakePage()
        self.closed = False

    def new_page(self) -> _FakePage:
        return self.page


class _FakeBrowser:
    def __init__(self) -> None:
        self.context: _FakeBrowserContext | None = None
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeBrowserType:
    def __init__(self) -> None:
        self.browser = _FakeBrowser()
        self.launched_headless: bool | None = None

    def launch(self, *, headless: bool) -> _FakeBrowser:
        self.launched_headless = headless
        return self.browser


class _FakeSyncPlaywright:
    def __init__(self, playwright) -> None:
        self.playwright = playwright

    def __enter__(self):
        return self.playwright

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeBrowserWidgetRobot(_FakeWidgetRobot):
    ABOVE_FOLD_COLLECTOR_JS = "above-fold-collector-js"

    def __init__(self) -> None:
        self.closed_contexts: list[tuple[_FakeBrowserContext, str]] = []

    def _new_robot_context(
        self,
        browser: _FakeBrowser,
        *,
        viewport_width: int,
        viewport_height: int,
        artifact_label: str,
    ) -> _FakeBrowserContext:
        assert (viewport_width, viewport_height, artifact_label) == (900, 700, "ui-robot-canary")
        browser.context = _FakeBrowserContext()
        return browser.context

    def _close_robot_context(self, context: _FakeBrowserContext, *, artifact_label: str) -> None:
        context.closed = True
        self.closed_contexts.append((context, artifact_label))

    @staticmethod
    def _accessibility_probe(_page, **_kwargs):
        return SimpleNamespace(
            kind="accessibility",
            status="failed",
            detail="missing_accessible_name: button has no accessible name",
        )

    @staticmethod
    def _layout_integrity_probe(_page, **_kwargs):
        return SimpleNamespace(
            kind="layout_integrity",
            status="failed",
            detail="zero_size_control: button is too small",
        )

    @staticmethod
    def _keyboard_focus_probe(_page, **_kwargs):
        return SimpleNamespace(
            kind="keyboard_focus",
            status="failed",
            detail="off-screen focus target was reached",
        )

    @staticmethod
    def _attach_browser_issue_capture(page: _FakePage):
        page.browser_issues = []
        return page.browser_issues


def _patch_playwright_import(monkeypatch, fake_module) -> None:
    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "playwright.sync_api":
            return fake_module
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)


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


def test_load_module_rejects_unloadable_module(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module.importlib.util, "spec_from_file_location", lambda _name, _path: None)

    with pytest.raises(RuntimeError, match="Could not load"):
        module._load_module("missing_module", Path("missing.py"))


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


def test_browser_canaries_cover_success_path(monkeypatch) -> None:
    module = _load_module()
    browser_type = _FakeBrowserType()
    fake_module = SimpleNamespace(
        sync_playwright=lambda: _FakeSyncPlaywright(SimpleNamespace(chromium=browser_type))
    )
    _patch_playwright_import(monkeypatch, fake_module)
    robot = _FakeBrowserWidgetRobot()

    results = module.run_browser_canaries(robot, browser_name="chromium", headless=False)

    assert [result.name for result in results] == [
        "browser-accessibility-collector",
        "browser-layout-collector",
        "browser-keyboard-collector",
        "browser-above-fold-collector",
        "browser-error-event-capture",
    ]
    assert all(result.success for result in results)
    assert browser_type.launched_headless is False
    assert browser_type.browser.closed is True
    assert browser_type.browser.context is not None
    assert browser_type.browser.context.closed is True
    assert [artifact for _context, artifact in robot.closed_contexts] == ["ui-robot-canary"]

    page = browser_type.browser.context.page
    assert len(page.contents) == 4
    assert page.evaluated == [
        _FakeBrowserWidgetRobot.ABOVE_FOLD_COLLECTOR_JS,
        "() => console.error('Uncaught TypeError: canary browser issue')",
    ]
    assert page.waits == [100]
    assert page.browser_issues == [{"kind": "console", "detail": "Uncaught TypeError: canary browser issue"}]


def test_load_module_and_visual_canary_detects_baseline_mismatch() -> None:
    module = _load_module()

    loaded = module._load_module("ui_robot_canary_self_for_test", MODULE_PATH)
    visual = module.run_visual_canary()

    assert loaded.SCHEMA == module.SCHEMA
    assert visual.name == "visual-baseline-diff"
    assert visual.success is True
    assert "mismatch was detected" in visual.detail


def test_visual_canary_reports_missing_pillow(monkeypatch) -> None:
    module = _load_module()
    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "PIL":
            raise ModuleNotFoundError("No module named 'PIL'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    result = module.run_visual_canary()

    assert result.name == "visual-baseline-diff"
    assert result.success is False
    assert "pillow is unavailable" in result.detail


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


def test_cli_runs_browser_and_visual_canaries_by_default(monkeypatch, capsys) -> None:
    module = _load_module()
    browser_calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(module, "_load_module", lambda _name, _path: _FakeWidgetRobot())

    def _fake_browser_canaries(_widget_robot, *, browser_name: str, headless: bool):
        browser_calls.append((browser_name, headless))
        return [module.CanaryResult("browser", True, "ok", "ok")]

    monkeypatch.setattr(module, "run_browser_canaries", _fake_browser_canaries)
    monkeypatch.setattr(module, "run_visual_canary", lambda: module.CanaryResult("visual", True, "ok", "ok"))

    exit_code = module.main(["--headful"])

    assert exit_code == 0
    assert browser_calls == [("chromium", False)]
    assert "verdict: PASS" in capsys.readouterr().out


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
