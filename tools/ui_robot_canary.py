#!/usr/bin/env python3
"""Run deliberate UI robot fault-injection canaries."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
WIDGET_ROBOT_PATH = REPO_ROOT / "tools" / "agilab_widget_robot.py"
VISUAL_BASELINE_PATH = REPO_ROOT / "tools" / "ui_visual_baseline_report.py"
SCHEMA = "agilab.ui_robot_canary.v1"


@dataclass(frozen=True)
class CanaryResult:
    name: str
    success: bool
    detail: str
    expected: str
    observed: str = ""


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _probe_canary(name: str, probe: Any, *, expected_kind: str, detail_needle: str = "") -> CanaryResult:
    detail = str(getattr(probe, "detail", ""))
    observed = f"{getattr(probe, 'kind', '')}:{getattr(probe, 'status', '')}:{detail}"
    success = (
        getattr(probe, "kind", "") == expected_kind
        and getattr(probe, "status", "") == "failed"
        and (not detail_needle or detail_needle.lower() in detail.lower())
    )
    return CanaryResult(
        name=name,
        success=success,
        detail="expected robot failure was detected" if success else f"unexpected probe result: {observed}",
        expected=f"{expected_kind}:failed",
        observed=observed,
    )


def run_probe_canaries(widget_robot: Any) -> list[CanaryResult]:
    probes: list[CanaryResult] = []
    probes.append(
        _probe_canary(
            "keyboard-focus-trap",
            widget_robot._keyboard_focus_result_probe(
                app_name="canary",
                display="PROJECT",
                url="about:blank",
                focusable_count=5,
                visited_labels=["INSTALL", "INSTALL"],
            ),
            expected_kind="keyboard_focus",
            detail_needle="expected at least",
        )
    )
    probes.append(
        _probe_canary(
            "layout-overflow",
            widget_robot._layout_integrity_result_probe(
                app_name="canary",
                display="ANALYSIS",
                url="about:blank",
                issues=[{"kind": "text_overflow", "label": "Run", "detail": "text exceeds container"}],
            ),
            expected_kind="layout_integrity",
            detail_needle="text_overflow",
        )
    )
    probes.append(
        _probe_canary(
            "accessibility-missing-name",
            widget_robot._accessibility_result_probe(
                app_name="canary",
                display="PROJECT",
                url="about:blank",
                issues=[{"kind": "missing_accessible_name", "label": "button", "detail": "no accessible name"}],
            ),
            expected_kind="accessibility",
            detail_needle="missing_accessible_name",
        )
    )
    probes.append(
        _probe_canary(
            "above-fold-missing-target",
            widget_robot._above_fold_result_probe(
                app_name="canary",
                display="ORCHESTRATE",
                url="about:blank",
                expected_labels=["INSTALL"],
                seen_labels=["ORCHESTRATE"],
                fold=900.0,
            ),
            expected_kind="above_fold",
            detail_needle="missing",
        )
    )
    browser_probes: list[Any] = []
    detected = widget_robot._append_browser_issue_probes(
        browser_probes,
        app_name="canary",
        display="PROJECT",
        url="about:blank",
        browser_issues=[{"kind": "pageerror", "detail": "Uncaught TypeError: canary"}],
        start_index=0,
    )
    probes.append(
        CanaryResult(
            name="browser-error-capture",
            success=bool(detected and browser_probes and browser_probes[0].status == "failed"),
            detail="expected browser issue was classified as fatal"
            if detected
            else "browser issue was not classified as fatal",
            expected="browser_error:failed",
            observed=f"{browser_probes[0].kind}:{browser_probes[0].status}" if browser_probes else "none",
        )
    )
    return probes


def run_browser_canaries(widget_robot: Any, *, browser_name: str, headless: bool) -> list[CanaryResult]:
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        return [
            CanaryResult(
                name="browser-canaries",
                success=False,
                detail=f"playwright is unavailable: {exc}",
                expected="playwright installed",
            )
        ]

    results: list[CanaryResult] = []
    with sync_playwright() as playwright:
        browser = getattr(playwright, browser_name).launch(headless=headless)
        context = widget_robot._new_robot_context(
            browser,
            viewport_width=900,
            viewport_height=700,
            artifact_label="ui-robot-canary",
        )
        try:
            page = context.new_page()

            page.set_content("<main><button></button></main>", wait_until="domcontentloaded")
            results.append(
                _probe_canary(
                    "browser-accessibility-collector",
                    widget_robot._accessibility_probe(page, app_name="canary", display="PROJECT"),
                    expected_kind="accessibility",
                    detail_needle="missing_accessible_name",
                )
            )

            page.set_content(
                "<main><button style='display:block;width:1px;height:1px;padding:0;border:0;overflow:hidden'>Tiny</button></main>",
                wait_until="domcontentloaded",
            )
            results.append(
                _probe_canary(
                    "browser-layout-collector",
                    widget_robot._layout_integrity_probe(page, app_name="canary", display="PROJECT"),
                    expected_kind="layout_integrity",
                    detail_needle="zero_size_control",
                )
            )

            page.set_content(
                "<main><button>One</button>"
                "<button style='position:absolute;left:-10000px;top:0'>Offscreen</button>"
                "<button>Three</button></main>",
                wait_until="domcontentloaded",
            )
            results.append(
                _probe_canary(
                    "browser-keyboard-collector",
                    widget_robot._keyboard_focus_probe(
                        page,
                        app_name="canary",
                        display="PROJECT",
                        widget_timeout_ms=50,
                        max_tabs=4,
                    ),
                    expected_kind="keyboard_focus",
                    detail_needle="off-screen",
                )
            )

            page.set_content(
                "<main><h1>ORCHESTRATE</h1><div style='margin-top:2000px'>INSTALL</div></main>",
                wait_until="domcontentloaded",
            )
            payload = page.evaluate(widget_robot.ABOVE_FOLD_COLLECTOR_JS)
            seen_labels = [
                str(item.get("label") or "")
                for item in payload.get("targets", [])
                if isinstance(item, dict) and bool(item.get("inFold"))
            ]
            results.append(
                _probe_canary(
                    "browser-above-fold-collector",
                    widget_robot._above_fold_result_probe(
                        app_name="canary",
                        display="ORCHESTRATE",
                        url=page.url,
                        expected_labels=["INSTALL"],
                        seen_labels=seen_labels,
                        fold=float(payload.get("fold") or 0),
                    ),
                    expected_kind="above_fold",
                    detail_needle="missing",
                )
            )

            issues = widget_robot._attach_browser_issue_capture(page)
            page.evaluate("() => console.error('Uncaught TypeError: canary browser issue')")
            page.wait_for_timeout(100)
            browser_probes: list[Any] = []
            detected = widget_robot._append_browser_issue_probes(
                browser_probes,
                app_name="canary",
                display="PROJECT",
                url=page.url,
                browser_issues=issues,
                start_index=0,
            )
            results.append(
                CanaryResult(
                    name="browser-error-event-capture",
                    success=bool(detected and browser_probes and browser_probes[0].status == "failed"),
                    detail="browser console event was captured and classified"
                    if detected
                    else f"browser issue capture missed injected event: {issues}",
                    expected="browser_error:failed",
                    observed=f"{browser_probes[0].kind}:{browser_probes[0].status}" if browser_probes else "none",
                )
            )
        finally:
            widget_robot._close_robot_context(context, artifact_label="ui-robot-canary")
            browser.close()
    return results


def run_visual_canary() -> CanaryResult:
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:
        return CanaryResult(
            name="visual-baseline-diff",
            success=False,
            detail=f"pillow is unavailable: {exc}",
            expected="Pillow installed",
        )
    visual = _load_module("ui_robot_canary_visual_baseline", VISUAL_BASELINE_PATH)
    with tempfile.TemporaryDirectory(prefix="agilab-ui-robot-canary-") as tmp_dir:
        root = Path(tmp_dir)
        current_dir = root / "current"
        baseline_dir = root / "baseline"
        current_dir.mkdir()
        baseline_dir.mkdir()
        Image.new("RGB", (4, 4), color=(0, 0, 0)).save(current_dir / "project-page.png")
        Image.new("RGB", (4, 4), color=(255, 255, 255)).save(baseline_dir / "project-page.png")
        visual.SCREENSHOTS.write_screenshot_manifest(
            visual.SCREENSHOTS.build_page_shots_manifest(current_dir, created_at="2026-05-18T00:00:00Z"),
            visual.SCREENSHOTS.screenshot_manifest_path(current_dir),
        )
        visual.SCREENSHOTS.write_screenshot_manifest(
            visual.SCREENSHOTS.build_page_shots_manifest(baseline_dir, created_at="2026-05-18T00:00:00Z"),
            visual.SCREENSHOTS.screenshot_manifest_path(baseline_dir),
        )
        report = visual.build_report(
            current_manifest_path=current_dir,
            baseline_manifest_path=baseline_dir,
            max_diff_ratio=0.0,
            channel_threshold=0,
            allow_missing_baseline=False,
        )
    failed = bool(report["summary"]["failed_count"])
    return CanaryResult(
        name="visual-baseline-diff",
        success=failed and report["success"] is False,
        detail="visual baseline mismatch was detected" if failed else "visual baseline mismatch was not detected",
        expected="visual baseline report failure",
        observed=f"success={report['success']} failed={report['summary']['failed_count']}",
    )


def build_report(results: Sequence[CanaryResult]) -> dict[str, Any]:
    failed = [result for result in results if not result.success]
    return {
        "schema": SCHEMA,
        "success": not failed,
        "summary": {
            "canary_count": len(results),
            "failed_count": len(failed),
        },
        "canaries": [asdict(result) for result in results],
    }


def render_human(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "AGILAB UI robot canary",
        f"verdict: {'PASS' if report['success'] else 'FAIL'}",
        f"canaries={summary['canary_count']} failed={summary['failed_count']}",
    ]
    for item in report["canaries"]:
        status = "OK" if item["success"] else "FAIL"
        lines.append(f"- {status}: {item['name']} - {item['detail']}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", choices=("chromium", "firefox", "webkit"), default="chromium")
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--skip-browser", action="store_true", help="Run only pure probe canaries.")
    parser.add_argument("--skip-visual", action="store_true", help="Skip visual-baseline canary.")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    widget_robot = _load_module("ui_robot_canary_widget_robot", WIDGET_ROBOT_PATH)
    results = run_probe_canaries(widget_robot)
    if not args.skip_browser:
        results.extend(run_browser_canaries(widget_robot, browser_name=args.browser, headless=not args.headful))
    if not args.skip_visual:
        results.append(run_visual_canary())
    report = build_report(results)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else render_human(report))
    return 0 if report["success"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
