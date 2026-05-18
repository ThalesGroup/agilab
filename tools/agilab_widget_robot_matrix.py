#!/usr/bin/env python3
"""Run high-value AGILAB widget robot validation scenarios."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
ROBOT_PATH = REPO_ROOT / "tools" / "agilab_widget_robot.py"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "test-results" / "ui-robot-matrix"
SCHEMA = "agilab.widget_robot_matrix.v1"
FAILURE_BUNDLE_SCHEMA = "agilab.widget_robot_matrix_failure_bundle.v1"
FAILURE_BUNDLE_TAIL_LINES = 120
FAILURE_BUNDLE_TEXT_LIMIT = 30_000


@dataclass(frozen=True)
class RobotScenario:
    name: str
    description: str
    pages: str
    apps_pages: str
    runtime_isolation: str
    action_button_policy: str
    click_action_labels: str = ""
    preselect_labels: str = ""
    route_query: str = ""
    missing_selected_action_policy: str = "fail"
    action_timeout_seconds: float = 90.0
    page_timeout_seconds: float = 420.0
    target_seconds: float = 1800.0
    assert_orchestrate_artifacts: bool = False
    assert_workflow_artifacts: bool = False
    assert_analysis_artifacts: bool = False
    browser_history_check: bool = False
    keyboard_focus_check: bool = False
    layout_integrity_check: bool = False
    viewport_width: int | None = None
    viewport_height: int | None = None
    fresh_browser_context_per_page: bool = False
    success_screenshot: bool = False
    max_first_render_seconds: float = 0.0
    max_widgets_ready_seconds: float = 0.0
    max_action_settle_seconds: float = 0.0


@dataclass(frozen=True)
class MatrixOptions:
    apps: str
    output_dir: Path
    screenshot_dir: Path | None
    timeout_seconds: float
    widget_timeout_seconds: float
    quiet_progress: bool
    no_seed_demo_artifacts: bool
    browser: str = "chromium"
    headful: bool = False
    url: str | None = None
    active_app: str | None = None
    remote_app_root: str | None = None
    failure_bundle_dir: Path | None = None


@dataclass(frozen=True)
class ScenarioResult:
    scenario: RobotScenario
    argv: list[str]
    returncode: int
    duration_seconds: float
    summary_path: Path
    progress_path: Path
    summary: dict
    output: str


def _run_robot_command_streaming(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run a robot child process while keeping matrix stdout JSON-clean."""

    print(f"[ui-robot-matrix] start: {' '.join(argv)}", file=sys.stderr, flush=True)
    proc = subprocess.Popen(
        list(argv),
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    output_lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        output_lines.append(line)
        print(line, end="", file=sys.stderr, flush=True)
    returncode = proc.wait()
    print(f"[ui-robot-matrix] exit={returncode}: {' '.join(argv)}", file=sys.stderr, flush=True)
    return subprocess.CompletedProcess(list(argv), returncode, stdout="".join(output_lines))


DEFAULT_SCENARIOS: dict[str, RobotScenario] = {
    "isolated-core-pages": RobotScenario(
        name="isolated-core-pages",
        description=(
            "Sweep ORCHESTRATE, WORKFLOW, and ANALYSIS for every built-in app "
            "with an isolated runtime and trial action buttons."
        ),
        pages="ORCHESTRATE,WORKFLOW,ANALYSIS",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="trial",
        assert_workflow_artifacts=True,
    ),
    "isolated-entry-and-app-pages": RobotScenario(
        name="isolated-entry-and-app-pages",
        description=(
            "Sweep the entry shell plus each app's configured analysis "
            "views with an isolated runtime and guarded safe-click navigation."
        ),
        pages="HOME",
        apps_pages="configured",
        runtime_isolation="isolated",
        action_button_policy="safe-click",
        action_timeout_seconds=30.0,
        page_timeout_seconds=300.0,
    ),
    "isolated-project-page": RobotScenario(
        name="isolated-project-page",
        description=(
            "Sweep the PROJECT route for every built-in app through the guarded "
            "source navigation wrapper."
        ),
        pages="PROJECT",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="safe-click",
        action_timeout_seconds=30.0,
        page_timeout_seconds=300.0,
    ),
    "isolated-project-notebook-import": RobotScenario(
        name="isolated-project-notebook-import",
        description=(
            "Open the PROJECT notebook-import deep link for every built-in app "
            "and exercise its guarded upload/create controls without firing "
            "destructive project actions."
        ),
        pages="PROJECT",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="safe-click",
        route_query="start=notebook-import",
        action_timeout_seconds=30.0,
        page_timeout_seconds=300.0,
    ),
    "isolated-project-import-sidebar": RobotScenario(
        name="isolated-project-import-sidebar",
        description=(
            "Select the PROJECT Import sidebar mode for every built-in app and "
            "exercise the archive import controls without firing destructive "
            "project import callbacks."
        ),
        pages="PROJECT",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="safe-click",
        preselect_labels="Import",
        action_timeout_seconds=30.0,
        page_timeout_seconds=300.0,
    ),
    "isolated-project-rename-sidebar": RobotScenario(
        name="isolated-project-rename-sidebar",
        description=(
            "Select the PROJECT Rename sidebar mode for every built-in app and "
            "exercise the rename controls without firing destructive project "
            "rename callbacks."
        ),
        pages="PROJECT",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="safe-click",
        preselect_labels="Rename",
        action_timeout_seconds=30.0,
        page_timeout_seconds=300.0,
    ),
    "isolated-settings-page": RobotScenario(
        name="isolated-settings-page",
        description=(
            "Sweep the hidden SETTINGS route for every built-in app through the "
            "guarded source navigation wrapper."
        ),
        pages="SETTINGS",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="safe-click",
        action_timeout_seconds=30.0,
        page_timeout_seconds=300.0,
    ),
    "current-home-actions": RobotScenario(
        name="current-home-actions",
        description=(
            "Fire high-risk ORCHESTRATE actions against the current installed "
            "worker environment."
        ),
        pages="ORCHESTRATE",
        apps_pages="none",
        runtime_isolation="current-home",
        action_button_policy="click-selected",
        click_action_labels="CHECK distribute,Run -> Load -> Export",
        preselect_labels="Run now",
        missing_selected_action_policy="ignore-absent",
        action_timeout_seconds=180.0,
    ),
    "current-home-orchestrate-journey": RobotScenario(
        name="current-home-orchestrate-journey",
        description=(
            "Exercise the stateful ORCHESTRATE journey that human users follow: "
            "check distribution, run/load/export, reload output, export dataframe, "
            "and delete the generated output."
        ),
        pages="ORCHESTRATE",
        apps_pages="none",
        runtime_isolation="current-home",
        action_button_policy="click-selected",
        click_action_labels=(
            "CHECK distribute,Run -> Load -> Export,Load output,"
            "EXPORT dataframe,Delete output,Confirm delete"
        ),
        preselect_labels="Run now",
        missing_selected_action_policy="ignore-absent",
        action_timeout_seconds=60.0,
        page_timeout_seconds=240.0,
        target_seconds=2400.0,
        assert_orchestrate_artifacts=True,
    ),
}


OPT_IN_SCENARIOS: dict[str, RobotScenario] = {
    "isolated-browser-history": RobotScenario(
        name="isolated-browser-history",
        description=(
            "Navigate PROJECT, ORCHESTRATE, and ANALYSIS with an isolated runtime, "
            "then exercise browser back/forward and assert dark theme plus active_app routing survive."
        ),
        pages="PROJECT",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="safe-click",
        action_timeout_seconds=30.0,
        page_timeout_seconds=360.0,
        target_seconds=900.0,
        browser_history_check=True,
    ),
    "isolated-mobile-core-pages": RobotScenario(
        name="isolated-mobile-core-pages",
        description=(
            "Sweep PROJECT, ORCHESTRATE, and ANALYSIS through a mobile viewport "
            "to catch responsive layout and overflow regressions."
        ),
        pages="PROJECT,ORCHESTRATE,ANALYSIS",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="trial",
        action_timeout_seconds=30.0,
        page_timeout_seconds=420.0,
        target_seconds=1200.0,
        viewport_width=390,
        viewport_height=844,
    ),
    "isolated-release-evidence": RobotScenario(
        name="isolated-release-evidence",
        description=(
            "Sweep core pages with success screenshots and coarse render/widget "
            "budgets for release evidence."
        ),
        pages="PROJECT,ORCHESTRATE,ANALYSIS",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="trial",
        action_timeout_seconds=30.0,
        page_timeout_seconds=420.0,
        target_seconds=1200.0,
        success_screenshot=True,
        max_first_render_seconds=90.0,
        max_widgets_ready_seconds=30.0,
        max_action_settle_seconds=30.0,
    ),
    "isolated-fresh-session-core-pages": RobotScenario(
        name="isolated-fresh-session-core-pages",
        description=(
            "Open each core page in a fresh browser context to catch localStorage "
            "and session-state assumptions."
        ),
        pages="PROJECT,ORCHESTRATE,ANALYSIS",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="trial",
        action_timeout_seconds=30.0,
        page_timeout_seconds=420.0,
        target_seconds=1200.0,
        fresh_browser_context_per_page=True,
    ),
    "isolated-keyboard-focus-core-pages": RobotScenario(
        name="isolated-keyboard-focus-core-pages",
        description=(
            "Tab through HOME, PROJECT, ORCHESTRATE, ANALYSIS, and SETTINGS "
            "to catch focus traps and off-screen keyboard targets."
        ),
        pages="HOME,PROJECT,ORCHESTRATE,ANALYSIS,SETTINGS",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="trial",
        action_timeout_seconds=30.0,
        page_timeout_seconds=420.0,
        target_seconds=1200.0,
        keyboard_focus_check=True,
    ),
    "isolated-layout-integrity-desktop": RobotScenario(
        name="isolated-layout-integrity-desktop",
        description=(
            "Sweep core pages at desktop width and fail on obvious overflow, "
            "zero-size controls, or major visible control overlaps."
        ),
        pages="HOME,PROJECT,ORCHESTRATE,ANALYSIS,SETTINGS",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="trial",
        action_timeout_seconds=30.0,
        page_timeout_seconds=420.0,
        target_seconds=1200.0,
        layout_integrity_check=True,
    ),
    "isolated-layout-integrity-mobile": RobotScenario(
        name="isolated-layout-integrity-mobile",
        description=(
            "Sweep core pages at mobile width and fail on obvious overflow, "
            "zero-size controls, or major visible control overlaps."
        ),
        pages="HOME,PROJECT,ORCHESTRATE,ANALYSIS,SETTINGS",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="trial",
        action_timeout_seconds=30.0,
        page_timeout_seconds=420.0,
        target_seconds=1200.0,
        layout_integrity_check=True,
        viewport_width=390,
        viewport_height=844,
    ),
    "current-home-first-proof-golden-path": RobotScenario(
        name="current-home-first-proof-golden-path",
        description=(
            "Exercise the local first-proof path through INSTALL, CHECK, RUN/LOAD/EXPORT, "
            "then reopen ANALYSIS and assert first-proof artifacts are available."
        ),
        pages="ORCHESTRATE,ANALYSIS",
        apps_pages="none",
        runtime_isolation="current-home",
        action_button_policy="click-selected",
        click_action_labels="INSTALL,CHECK distribute,Run -> Load -> Export,Load output,EXPORT dataframe",
        preselect_labels="Run now",
        missing_selected_action_policy="ignore-absent",
        action_timeout_seconds=600.0,
        page_timeout_seconds=1200.0,
        target_seconds=1800.0,
        assert_orchestrate_artifacts=True,
        assert_analysis_artifacts=True,
        success_screenshot=True,
    ),
    "hf-flight-telemetry-install": RobotScenario(
        name="hf-flight-telemetry-install",
        description=(
            "Run the hosted Hugging Face flight telemetry INSTALL action and fail "
            "on fatal install feedback rendered in the page or action log."
        ),
        pages="ORCHESTRATE",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="click-selected",
        click_action_labels="INSTALL",
        missing_selected_action_policy="fail",
        action_timeout_seconds=600.0,
        page_timeout_seconds=900.0,
        target_seconds=1200.0,
    ),
}

ALL_SCENARIOS: dict[str, RobotScenario] = {
    **DEFAULT_SCENARIOS,
    **OPT_IN_SCENARIOS,
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a small matrix of Playwright widget-robot scenarios that catches "
            "page-level, action-level, and runtime-isolation UI regressions."
        )
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=["all", *ALL_SCENARIOS.keys()],
        help="Scenario to run. May be passed multiple times. Defaults to all.",
    )
    parser.add_argument("--apps", default="all", help="Built-in apps or app paths to pass to the widget robot.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--screenshot-dir", type=Path, help="Directory for failure screenshots and manifest files.")
    parser.add_argument("--failure-bundle-dir", type=Path, help="Directory for failure evidence bundles.")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--widget-timeout", type=float, default=3.0)
    parser.add_argument("--browser", choices=("chromium", "firefox", "webkit"), default="chromium")
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--url", help="Existing AGILAB URL to test instead of launching source Streamlit.")
    parser.add_argument("--active-app", help="Override active_app when --url is used.")
    parser.add_argument("--remote-app-root", help="Remote app root used for current_page paths when --url is used.")
    parser.add_argument("--no-seed-demo-artifacts", action="store_true")
    parser.add_argument("--quiet-progress", action="store_true", default=False)
    parser.add_argument("--fail-fast", action="store_true", help="Stop after the first failed scenario.")
    parser.add_argument("--print-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def resolve_scenarios(names: Sequence[str] | None) -> list[RobotScenario]:
    selected = list(names or ["all"])
    resolved: list[RobotScenario] = []
    seen: set[str] = set()
    for name in selected:
        scenario_names = list(DEFAULT_SCENARIOS) if name == "all" else [name]
        for scenario_name in scenario_names:
            if scenario_name in seen:
                continue
            resolved.append(ALL_SCENARIOS[scenario_name])
            seen.add(scenario_name)
    return resolved


def options_from_args(args: argparse.Namespace) -> MatrixOptions:
    return MatrixOptions(
        apps=args.apps,
        output_dir=args.output_dir,
        screenshot_dir=args.screenshot_dir,
        failure_bundle_dir=args.failure_bundle_dir,
        timeout_seconds=args.timeout,
        widget_timeout_seconds=args.widget_timeout,
        quiet_progress=args.quiet_progress,
        no_seed_demo_artifacts=args.no_seed_demo_artifacts,
        browser=args.browser,
        headful=args.headful,
        url=args.url,
        active_app=args.active_app,
        remote_app_root=args.remote_app_root,
    )


def _scenario_paths(output_dir: Path, scenario: RobotScenario) -> tuple[Path, Path]:
    return (
        output_dir / f"{scenario.name}.json",
        output_dir / f"{scenario.name}.ndjson",
    )


def build_robot_command(
    scenario: RobotScenario,
    *,
    options: MatrixOptions,
) -> tuple[list[str], Path, Path]:
    summary_path, progress_path = _scenario_paths(options.output_dir, scenario)
    argv = [
        sys.executable,
        str(ROBOT_PATH),
        "--apps",
        options.apps,
        "--pages",
        scenario.pages,
        "--apps-pages",
        scenario.apps_pages,
        "--json",
        "--json-output",
        str(summary_path),
        "--progress-log",
        str(progress_path),
        "--timeout",
        str(options.timeout_seconds),
        "--widget-timeout",
        str(options.widget_timeout_seconds),
        "--browser",
        options.browser,
        "--page-timeout",
        str(scenario.page_timeout_seconds),
        "--target-seconds",
        str(scenario.target_seconds),
        "--interaction-mode",
        "full",
        "--action-button-policy",
        scenario.action_button_policy,
        "--missing-selected-action-policy",
        scenario.missing_selected_action_policy,
        "--action-timeout",
        str(scenario.action_timeout_seconds),
        "--runtime-isolation",
        scenario.runtime_isolation,
    ]
    if scenario.click_action_labels:
        argv.extend(["--click-action-labels", scenario.click_action_labels])
    if scenario.preselect_labels:
        argv.extend(["--preselect-labels", scenario.preselect_labels])
    if scenario.route_query:
        argv.extend(["--route-query", scenario.route_query])
    if scenario.assert_orchestrate_artifacts:
        argv.append("--assert-orchestrate-artifacts")
    if scenario.assert_workflow_artifacts:
        argv.append("--assert-workflow-artifacts")
    if scenario.assert_analysis_artifacts:
        argv.append("--assert-analysis-artifacts")
    if scenario.browser_history_check:
        argv.append("--browser-history-check")
    if scenario.keyboard_focus_check:
        argv.append("--keyboard-focus-check")
    if scenario.layout_integrity_check:
        argv.append("--layout-integrity-check")
    if scenario.viewport_width is not None:
        argv.extend(["--viewport-width", str(scenario.viewport_width)])
    if scenario.viewport_height is not None:
        argv.extend(["--viewport-height", str(scenario.viewport_height)])
    if scenario.fresh_browser_context_per_page:
        argv.append("--fresh-browser-context-per-page")
    if scenario.success_screenshot:
        argv.append("--success-screenshot")
    if scenario.max_first_render_seconds > 0:
        argv.extend(["--max-first-render-seconds", str(scenario.max_first_render_seconds)])
    if scenario.max_widgets_ready_seconds > 0:
        argv.extend(["--max-widgets-ready-seconds", str(scenario.max_widgets_ready_seconds)])
    if scenario.max_action_settle_seconds > 0:
        argv.extend(["--max-action-settle-seconds", str(scenario.max_action_settle_seconds)])
    if options.url:
        argv.extend(["--url", options.url])
    if options.active_app:
        argv.extend(["--active-app", options.active_app])
    if options.remote_app_root:
        argv.extend(["--remote-app-root", options.remote_app_root])
    if options.no_seed_demo_artifacts:
        argv.append("--no-seed-demo-artifacts")
    if options.headful:
        argv.append("--headful")
    if options.quiet_progress:
        argv.append("--quiet-progress")
    if options.screenshot_dir is not None:
        argv.extend(["--screenshot-dir", str(options.screenshot_dir / scenario.name)])
    if options.failure_bundle_dir is not None:
        argv.extend(["--failure-bundle-dir", str(options.failure_bundle_dir / scenario.name)])
    return argv, summary_path, progress_path


def _load_summary(path: Path, output: str) -> dict:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return {
            "success": False,
            "failed_count": 1,
            "skipped_count": 0,
            "page_count": 0,
            "widget_count": 0,
            "interacted_count": 0,
            "probed_count": 0,
            "error": "robot did not emit a JSON summary",
        }


def _tail_text_file(path: Path | None, *, lines: int = FAILURE_BUNDLE_TAIL_LINES) -> str:
    if path is None or not path.is_file():
        return ""
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(content[-lines:]) + ("\n" if content else "")


def _limited_text(value: str, *, limit: int = FAILURE_BUNDLE_TEXT_LIMIT) -> str:
    if len(value) <= limit:
        return value
    return value[-limit:] + "\n...[tail truncated]\n"


def _write_matrix_failure_bundle(result: ScenarioResult, *, options: MatrixOptions) -> Path | None:
    if options.failure_bundle_dir is None:
        return None
    if result.returncode == 0 and bool(result.summary.get("success", False)):
        return None
    bundle_dir = options.failure_bundle_dir / result.scenario.name / "_scenario"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "summary.json").write_text(json.dumps(result.summary, indent=2) + "\n", encoding="utf-8")
    (bundle_dir / "command.json").write_text(json.dumps(result.argv, indent=2) + "\n", encoding="utf-8")
    output_tail = _limited_text(result.output or "")
    if output_tail:
        (bundle_dir / "output-tail.txt").write_text(output_tail, encoding="utf-8")
    progress_tail = _tail_text_file(result.progress_path)
    if progress_tail:
        (bundle_dir / "progress-tail.ndjson").write_text(progress_tail, encoding="utf-8")
    screenshot_root = options.screenshot_dir / result.scenario.name if options.screenshot_dir is not None else None
    screenshots = (
        sorted(str(path) for path in screenshot_root.rglob("*.png"))
        if screenshot_root is not None and screenshot_root.exists()
        else []
    )
    manifest = {
        "schema": FAILURE_BUNDLE_SCHEMA,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scenario": result.scenario.name,
        "returncode": result.returncode,
        "duration_seconds": result.duration_seconds,
        "summary_path": str(result.summary_path),
        "progress_path": str(result.progress_path),
        "screenshots": screenshots,
        "command": result.argv,
    }
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return bundle_dir


def run_scenario(
    scenario: RobotScenario,
    *,
    options: MatrixOptions,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> ScenarioResult:
    options.output_dir.mkdir(parents=True, exist_ok=True)
    argv, summary_path, progress_path = build_robot_command(scenario, options=options)
    started = time.perf_counter()
    if runner is subprocess.run:
        completed = _run_robot_command_streaming(argv)
    else:
        completed = runner(
            argv,
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    output = completed.stdout or ""
    result = ScenarioResult(
        scenario=scenario,
        argv=argv,
        returncode=completed.returncode,
        duration_seconds=time.perf_counter() - started,
        summary_path=summary_path,
        progress_path=progress_path,
        summary=_load_summary(summary_path, output),
        output=output,
    )
    _write_matrix_failure_bundle(result, options=options)
    return result


def run_matrix(
    scenarios: Sequence[RobotScenario],
    *,
    options: MatrixOptions,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    keep_going: bool = False,
) -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
    for scenario in scenarios:
        result = run_scenario(scenario, options=options, runner=runner)
        results.append(result)
        if result.returncode != 0 and not keep_going:
            break
    return results


def summarize_matrix(results: Sequence[ScenarioResult]) -> dict:
    summaries = [result.summary for result in results]
    success = bool(results) and all(
        result.returncode == 0 and result.summary.get("success") is True
        for result in results
    )
    return {
        "schema": SCHEMA,
        "success": success,
        "scenario_count": len(results),
        "page_count": sum(int(summary.get("page_count") or 0) for summary in summaries),
        "widget_count": sum(int(summary.get("widget_count") or 0) for summary in summaries),
        "interacted_count": sum(int(summary.get("interacted_count") or 0) for summary in summaries),
        "probed_count": sum(int(summary.get("probed_count") or 0) for summary in summaries),
        "skipped_count": sum(int(summary.get("skipped_count") or 0) for summary in summaries),
        "failed_count": sum(int(summary.get("failed_count") or 0) for summary in summaries),
        "duration_seconds": sum(result.duration_seconds for result in results),
        "failed_scenarios": [
            result.scenario.name
            for result in results
            if result.returncode != 0 or result.summary.get("success") is not True
        ],
        "failure_samples": _failure_samples(results),
        "scenarios": [
            {
                "name": result.scenario.name,
                "description": result.scenario.description,
                "success": result.returncode == 0 and result.summary.get("success") is True,
                "returncode": result.returncode,
                "duration_seconds": result.duration_seconds,
                "summary_path": str(result.summary_path),
                "progress_path": str(result.progress_path),
                "page_count": int(result.summary.get("page_count") or 0),
                "widget_count": int(result.summary.get("widget_count") or 0),
                "interacted_count": int(result.summary.get("interacted_count") or 0),
                "probed_count": int(result.summary.get("probed_count") or 0),
                "skipped_count": int(result.summary.get("skipped_count") or 0),
                "failed_count": int(result.summary.get("failed_count") or 0),
            }
            for result in results
        ],
    }


def _failure_samples(results: Sequence[ScenarioResult], *, limit: int = 20) -> list[dict[str, str]]:
    samples: list[dict[str, str]] = []
    for result in results:
        for page in result.summary.get("pages") or []:
            if not isinstance(page, dict):
                continue
            for failure in page.get("failures") or []:
                if not isinstance(failure, dict):
                    continue
                samples.append(
                    {
                        "scenario": result.scenario.name,
                        "app": str(page.get("app") or failure.get("app") or ""),
                        "page": str(page.get("page") or failure.get("page") or ""),
                        "kind": str(failure.get("kind") or ""),
                        "label": str(failure.get("label") or ""),
                        "detail": str(failure.get("detail") or ""),
                    }
                )
                if len(samples) >= limit:
                    return samples
    return samples


def render_human(summary: dict) -> str:
    status = "PASS" if summary["success"] else "FAIL"
    lines = [
        (
            f"[{status}] widget robot matrix: scenarios={summary['scenario_count']} "
            f"pages={summary['page_count']} widgets={summary['widget_count']} "
            f"interacted={summary['interacted_count']} probed={summary['probed_count']} "
            f"skipped={summary['skipped_count']} failed={summary['failed_count']}"
        )
    ]
    for scenario in summary["scenarios"]:
        scenario_status = "PASS" if scenario["success"] else "FAIL"
        lines.append(
            (
                f"- [{scenario_status}] {scenario['name']}: pages={scenario['page_count']} "
                f"widgets={scenario['widget_count']} failed={scenario['failed_count']} "
                f"summary={scenario['summary_path']}"
            )
        )
    return "\n".join(lines)


def _print_only_payload(scenarios: Sequence[RobotScenario], options: MatrixOptions) -> dict:
    commands = []
    for scenario in scenarios:
        argv, summary_path, progress_path = build_robot_command(scenario, options=options)
        commands.append(
            {
                "scenario": asdict(scenario),
                "argv": argv,
                "summary_path": str(summary_path),
                "progress_path": str(progress_path),
            }
        )
    return {"schema": SCHEMA, "commands": commands}


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    scenarios = resolve_scenarios(args.scenario)
    options = options_from_args(args)

    if args.print_only:
        payload = _print_only_payload(scenarios, options)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            for command in payload["commands"]:
                print(f"{command['scenario']['name']}: {' '.join(command['argv'])}")
        return 0

    results = run_matrix(scenarios, options=options, keep_going=not args.fail_fast)
    summary = summarize_matrix(results)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(render_human(summary))
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
