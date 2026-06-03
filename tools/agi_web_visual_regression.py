#!/usr/bin/env python3
"""Render a deterministic agi-web WebGL component and capture visual evidence."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
AGI_WEB_SRC = REPO_ROOT / "src/agilab/lib/agi-web/src"
SCHEMA = "agilab.agi_web_visual_regression.v1"
SUPPORTED_BROWSERS = ("chromium", "firefox", "webkit")


def _ensure_import_paths() -> None:
    for path in (REPO_ROOT / "src", AGI_WEB_SRC):
        entry = path.as_posix()
        if entry not in sys.path:
            sys.path.insert(0, entry)


def build_demo_component() -> Any:
    _ensure_import_paths()
    from agi_web import AgiWebComponent, AgiWebRendererSpec

    samples = [
        {"x1": -0.85, "x2": -0.58, "target": 0},
        {"x1": -0.62, "x2": 0.56, "target": 0},
        {"x1": 0.74, "x2": -0.52, "target": 1},
        {"x1": 0.68, "x2": 0.60, "target": 1},
    ]
    snapshots: list[dict[str, float | int]] = []
    for epoch, offset in ((0, -0.18), (8, 0.0), (16, 0.18)):
        for ix in range(18):
            x1 = -1.0 + ix * (2.0 / 17)
            for iy in range(18):
                x2 = -1.0 + iy * (2.0 / 17)
                probability = max(0.02, min(0.98, 0.5 + (x1 * 0.36 + x2 * 0.18 + offset)))
                snapshots.append({"epoch": epoch, "x1": round(x1, 4), "x2": round(x2, 4), "probability": round(probability, 4)})
    return AgiWebComponent(
        component_id="agi-web-webgl-visual-regression",
        title="AGI Web WebGL Visual Guard",
        subtitle="Deterministic WebGL boundary replay fixture.",
        renderer=AgiWebRendererSpec(
            renderer_id="agi-web-webgl-visual-regression",
            technology="webgl",
            capabilities=("decision-boundary", "learning-replay", "gpu-heatmap", "visual-regression"),
        ),
        payload={
            "metrics": {"validation_accuracy": 0.91, "confidence": 0.73, "samples": len(samples)},
            "lessons": [
                {"preset": "visual guard", "lesson": "WebGL path", "watch": "Renderer must activate WebGL.", "state": "active"},
            ],
            "samples": samples,
            "snapshots": snapshots,
            "grid": [record for record in snapshots if record["epoch"] == 16],
            "history": [
                {"epoch": 0, "validation_accuracy": 0.58},
                {"epoch": 8, "validation_accuracy": 0.78},
                {"epoch": 16, "validation_accuracy": 0.91},
            ],
        },
    )


def write_static_fixture(output_dir: Path) -> Path:
    _ensure_import_paths()
    from agi_web import component_to_static_html

    output_dir.mkdir(parents=True, exist_ok=True)
    component = build_demo_component()
    html = "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            "<title>agi-web WebGL visual regression</title>",
            "<style>body{margin:0;padding:24px;background:#020617}</style>",
            "</head>",
            "<body>",
            component_to_static_html(component, height=620, width="960px"),
            "</body>",
            "</html>",
        ]
    )
    target = output_dir / "agi-web-webgl-visual-regression.html"
    target.write_text(html, encoding="utf-8")
    return target


def _write_manifest(
    *,
    screenshot_paths: Sequence[tuple[str, Path]],
    screenshot_dir: Path,
    source_command: Sequence[str],
    url: str,
) -> Path:
    _ensure_import_paths()
    from agilab import screenshot_manifest

    records = [
        screenshot_manifest.build_screenshot_record(
            screenshot_path,
            page=f"agi-web-webgl-{browser_name}",
            app="agi-web",
            project="agi-web-visual-regression",
            root=screenshot_dir,
            source_command=source_command,
            alt=f"AGI Web WebGL deterministic visual regression fixture in {browser_name}",
            url=url,
        )
        for browser_name, screenshot_path in screenshot_paths
    ]
    manifest = screenshot_manifest.build_screenshot_manifest(
        records,
        root=screenshot_dir,
        source_command=source_command,
    )
    return screenshot_manifest.write_screenshot_manifest(
        manifest,
        screenshot_manifest.screenshot_manifest_path(screenshot_dir),
    )


def expand_browser_names(browser_names: Sequence[str] | None) -> tuple[str, ...]:
    """Normalize CLI browser names while preserving deterministic order."""

    raw_names = tuple(browser_names or ("chromium",))
    if any(name == "all" for name in raw_names):
        raw_names = SUPPORTED_BROWSERS
    browsers: list[str] = []
    for name in raw_names:
        if name not in SUPPORTED_BROWSERS:
            raise ValueError(f"Unsupported browser: {name!r}")
        if name not in browsers:
            browsers.append(name)
    return tuple(browsers)


def evaluate_browser_result(
    *,
    browser_name: str,
    active_renderer: str,
    webgl_supported: bool,
    render_ms: float,
    require_webgl: bool,
    max_render_ms: float,
) -> tuple[bool, str]:
    """Return the pass/fail verdict for one browser run."""

    failures: list[str] = []
    if require_webgl and active_renderer != "webgl":
        failures.append("WebGL renderer did not activate")
    if max_render_ms > 0 and render_ms > max_render_ms:
        failures.append(f"render budget exceeded: {render_ms:.1f}ms > {max_render_ms:.1f}ms")
    if not failures:
        return True, "ok"
    supported = "yes" if webgl_supported else "no"
    return False, f"{browser_name}: {'; '.join(failures)}; webgl_supported={supported}"


def _run_browser_capture(
    *,
    playwright: Any,
    browser_name: str,
    url: str,
    screenshot_dir: Path,
    require_webgl: bool,
    max_render_ms: float,
) -> dict[str, Any]:
    browser_type = getattr(playwright, browser_name)
    screenshot_path = screenshot_dir / f"agi-web-webgl-{browser_name}.png"
    browser = browser_type.launch()
    try:
        page = browser.new_page(viewport={"width": 1040, "height": 720}, device_scale_factor=1)
        started = time.perf_counter()
        page.goto(url)
        page.wait_for_selector(".agi-web-shell", state="visible", timeout=30_000)
        page.wait_for_function(
            "() => !!document.querySelector('.agi-web-shell')?.getAttribute('data-agilab-renderer-active')",
            timeout=30_000,
        )
        render_ms = (time.perf_counter() - started) * 1000
        active_renderer = str(page.locator(".agi-web-shell").first.get_attribute("data-agilab-renderer-active") or "")
        webgl_supported = bool(
            page.evaluate(
                "() => { const c = document.createElement('canvas'); return !!(c.getContext('webgl') || c.getContext('experimental-webgl')); }"
            )
        )
        page.wait_for_timeout(250)
        page.locator(".agi-web-shell").first.screenshot(path=str(screenshot_path))
    finally:
        browser.close()
    success, detail = evaluate_browser_result(
        browser_name=browser_name,
        active_renderer=active_renderer,
        webgl_supported=webgl_supported,
        render_ms=render_ms,
        require_webgl=require_webgl,
        max_render_ms=max_render_ms,
    )
    return {
        "browser": browser_name,
        "success": success,
        "detail": detail,
        "active_renderer": active_renderer,
        "webgl_supported": webgl_supported,
        "render_ms": round(render_ms, 3),
        "max_render_ms": max_render_ms,
        "screenshot": str(screenshot_path),
    }


def _compare_baseline(*, current: Path, baseline: Path, max_diff_ratio: float, channel_threshold: int) -> dict[str, Any]:
    import importlib.util

    module_path = REPO_ROOT / "tools/ui_visual_baseline_report.py"
    spec = importlib.util.spec_from_file_location("agi_web_visual_baseline_report", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load visual baseline report module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report(
        current_manifest_path=current,
        baseline_manifest_path=baseline,
        max_diff_ratio=max_diff_ratio,
        channel_threshold=channel_threshold,
        allow_missing_baseline=False,
    )


def run_visual_regression(
    *,
    output_dir: Path,
    screenshot_dir: Path,
    baseline: Path | None,
    browsers: Sequence[str] | None = None,
    require_webgl: bool,
    max_render_ms: float,
    max_diff_ratio: float,
    channel_threshold: int,
    source_command: Sequence[str],
) -> dict[str, Any]:
    html_path = write_static_fixture(output_dir)
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    browser_names = expand_browser_names(browsers)
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise RuntimeError("Playwright is required; run with `uv run --with playwright`.") from exc

    url = html_path.resolve().as_uri()
    browser_results: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        for browser_name in browser_names:
            browser_results.append(
                _run_browser_capture(
                    playwright=playwright,
                    browser_name=browser_name,
                    url=url,
                    screenshot_dir=screenshot_dir,
                    require_webgl=require_webgl,
                    max_render_ms=max_render_ms,
                )
            )

    screenshot_paths = [(str(item["browser"]), Path(str(item["screenshot"]))) for item in browser_results]
    manifest_path = _write_manifest(
        screenshot_paths=screenshot_paths,
        screenshot_dir=screenshot_dir,
        source_command=source_command,
        url=url,
    )
    baseline_report = None
    success = all(bool(result["success"]) for result in browser_results)
    if baseline is not None:
        baseline_report = _compare_baseline(
            current=manifest_path,
            baseline=baseline,
            max_diff_ratio=max_diff_ratio,
            channel_threshold=channel_threshold,
        )
        success = success and bool(baseline_report.get("success"))
    first_result = browser_results[0] if browser_results else {}
    return {
        "schema": SCHEMA,
        "success": success,
        "active_renderer": first_result.get("active_renderer", ""),
        "webgl_supported": bool(first_result.get("webgl_supported")),
        "browser_count": len(browser_results),
        "browser_results": browser_results,
        "performance": {
            "max_render_ms": max_render_ms,
            "max_observed_render_ms": max((float(item["render_ms"]) for item in browser_results), default=0.0),
        },
        "html": str(html_path),
        "screenshot": str(first_result.get("screenshot", "")),
        "manifest": str(manifest_path),
        "baseline_report": baseline_report,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("test-results/agi-web-visual-regression"))
    parser.add_argument("--screenshot-dir", type=Path, default=Path("screenshots/agi-web-visual-regression"))
    parser.add_argument("--baseline", type=Path, help="Optional baseline screenshot manifest path or directory.")
    parser.add_argument(
        "--browser",
        action="append",
        choices=(*SUPPORTED_BROWSERS, "all"),
        help="Browser to validate. Repeat for several browsers or pass all. Defaults to chromium.",
    )
    parser.add_argument("--allow-canvas-fallback", action="store_true")
    parser.add_argument("--max-render-ms", type=float, default=0.0, help="Fail when any browser render exceeds this budget. Use 0 to disable.")
    parser.add_argument("--max-diff-ratio", type=float, default=0.02)
    parser.add_argument("--channel-threshold", type=int, default=10)
    parser.add_argument("--report-output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    browsers = expand_browser_names(args.browser)
    report = run_visual_regression(
        output_dir=args.output_dir,
        screenshot_dir=args.screenshot_dir,
        baseline=args.baseline,
        browsers=browsers,
        require_webgl=not args.allow_canvas_fallback,
        max_render_ms=args.max_render_ms,
        max_diff_ratio=args.max_diff_ratio,
        channel_threshold=args.channel_threshold,
        source_command=(Path(sys.argv[0]).name, *sys.argv[1:]),
    )
    if args.report_output:
        args.report_output.parent.mkdir(parents=True, exist_ok=True)
        args.report_output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        renderer = report.get("active_renderer") or "unknown"
        verdict = "PASS" if report.get("success") else "FAIL"
        observed = float(report.get("performance", {}).get("max_observed_render_ms") or 0.0)
        print(
            f"agi-web visual regression: {verdict} renderer={renderer} "
            f"browsers={','.join(browsers)} max_render_ms={observed:.1f} screenshot={report.get('screenshot', '')}"
        )
    return 0 if report.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
