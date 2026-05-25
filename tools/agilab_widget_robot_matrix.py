#!/usr/bin/env python3
"""Run high-value AGILAB widget robot validation scenarios."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Callable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
ROBOT_PATH = REPO_ROOT / "tools" / "agilab_widget_robot.py"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "test-results" / "ui-robot-matrix"
SCHEMA = "agilab.widget_robot_matrix.v1"
FAILURE_BUNDLE_SCHEMA = "agilab.widget_robot_matrix_failure_bundle.v1"
FAILURE_BUNDLE_TAIL_LINES = 120
FAILURE_BUNDLE_TEXT_LIMIT = 30_000
RESULT_CACHE_SCHEMA = "agilab.widget_robot_matrix_result_cache.v1"
DEFAULT_RESULT_CACHE_PATH = REPO_ROOT / ".pytest_cache" / "agilab" / "ui_robot_matrix_results.json"
RESULT_CACHE_MAX_ENTRIES = 256
RESULT_CACHE_HASH_LIMIT_BYTES = 5_000_000
RESULT_CACHE_PROGRESS_LOG_LIMIT_BYTES = 5_000_000
RESULT_CACHE_WATCHED_PATHS = (
    "src/agilab",
    "tools/agilab_widget_robot.py",
    "tools/agilab_widget_robot_matrix.py",
    "pyproject.toml",
    "uv.lock",
)


@dataclass(frozen=True)
class RobotScenario:
    name: str
    description: str
    pages: str
    apps_pages: str
    runtime_isolation: str
    action_button_policy: str
    apps: str = ""
    click_action_labels: str = ""
    preselect_labels: str = ""
    required_text: str = ""
    required_action_labels: str = ""
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
    accessibility_check: bool = False
    browser_error_check: bool = False
    above_fold_check: bool = False
    visual_mask_dynamic_regions: bool = False
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
    trace_dir: Path | None = None
    har_dir: Path | None = None
    video_dir: Path | None = None
    result_cache_path: Path | None = None
    retry_failed_with_artifacts: bool = False
    retry_trace_dir: Path | None = None
    retry_har_dir: Path | None = None
    retry_video_dir: Path | None = None


@dataclass(frozen=True)
class FailureArtifactRetry:
    argv: list[str]
    returncode: int
    duration_seconds: float
    summary_path: Path
    progress_path: Path
    summary: dict
    output: str
    trace_dir: Path | None
    har_dir: Path | None
    video_dir: Path | None


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
    cached: bool = False
    artifact_retry: FailureArtifactRetry | None = None


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
            "Tab through HOME, PROJECT, ORCHESTRATE, WORKFLOW, ANALYSIS, and SETTINGS "
            "to catch focus traps and off-screen keyboard targets."
        ),
        pages="HOME,PROJECT,ORCHESTRATE,WORKFLOW,ANALYSIS,SETTINGS",
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
        pages="HOME,PROJECT,ORCHESTRATE,WORKFLOW,ANALYSIS,SETTINGS",
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
        pages="HOME,PROJECT,ORCHESTRATE,WORKFLOW,ANALYSIS,SETTINGS",
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
    "isolated-accessibility-core-pages": RobotScenario(
        name="isolated-accessibility-core-pages",
        description=(
            "Sweep core pages and fail on missing accessible names, broken ARIA "
            "references, heading-order jumps, missing main landmarks, or severe contrast risks."
        ),
        pages="HOME,PROJECT,ORCHESTRATE,WORKFLOW,ANALYSIS,SETTINGS",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="trial",
        action_timeout_seconds=30.0,
        page_timeout_seconds=420.0,
        target_seconds=1200.0,
        accessibility_check=True,
    ),
    "isolated-browser-error-core-pages": RobotScenario(
        name="isolated-browser-error-core-pages",
        description=(
            "Sweep core pages with explicit console, pageerror, requestfailed, "
            "and HTTP error capture evidence."
        ),
        pages="HOME,PROJECT,ORCHESTRATE,WORKFLOW,ANALYSIS,SETTINGS",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="trial",
        action_timeout_seconds=30.0,
        page_timeout_seconds=420.0,
        target_seconds=1200.0,
        browser_error_check=True,
    ),
    "isolated-cross-browser-core-pages": RobotScenario(
        name="isolated-cross-browser-core-pages",
        description=(
            "Smoke core pages in non-Chromium Playwright browsers with explicit "
            "browser console/network error evidence."
        ),
        pages="HOME,PROJECT,ORCHESTRATE,WORKFLOW,ANALYSIS,SETTINGS",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="trial",
        action_timeout_seconds=30.0,
        page_timeout_seconds=420.0,
        target_seconds=1200.0,
        browser_error_check=True,
    ),
    "isolated-pytorch-playground-analysis": RobotScenario(
        name="isolated-pytorch-playground-analysis",
        description=(
            "Open the PyTorch Playground ANALYSIS app surface and assert the "
            "combined run controls plus reproducibility snippet are visible in "
            "the embedded app frame."
        ),
        pages="ANALYSIS",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="trial",
        apps="pytorch_playground_project",
        required_text="PyTorch Playground,Refresh evidence,Synced RUN snippet,Settings",
        required_action_labels="Refresh evidence",
        action_timeout_seconds=30.0,
        page_timeout_seconds=420.0,
        target_seconds=900.0,
        browser_error_check=True,
    ),
    "isolated-above-fold-core-pages": RobotScenario(
        name="isolated-above-fold-core-pages",
        description=(
            "Sweep core pages and fail when expected page headings or primary "
            "controls are not visible above the initial viewport fold."
        ),
        pages="HOME,PROJECT,ORCHESTRATE,WORKFLOW,ANALYSIS,SETTINGS",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="trial",
        action_timeout_seconds=30.0,
        page_timeout_seconds=420.0,
        target_seconds=1200.0,
        above_fold_check=True,
    ),
    "isolated-visual-baseline-core-pages": RobotScenario(
        name="isolated-visual-baseline-core-pages",
        description=(
            "Capture masked success screenshots for core pages so a separate "
            "visual-baseline report can compare them with committed docs baselines."
        ),
        pages="HOME,PROJECT,ORCHESTRATE,WORKFLOW,ANALYSIS,SETTINGS",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="trial",
        action_timeout_seconds=30.0,
        page_timeout_seconds=420.0,
        target_seconds=1200.0,
        success_screenshot=True,
        visual_mask_dynamic_regions=True,
        above_fold_check=True,
        browser_error_check=True,
    ),
    "hf-first-proof-visual-smoke": RobotScenario(
        name="hf-first-proof-visual-smoke",
        description=(
            "Capture hosted Hugging Face screenshots for first-proof demo apps "
            "across entry, PROJECT, ORCHESTRATE, WORKFLOW, and ANALYSIS without "
            "firing install/run actions."
        ),
        pages="HOME,PROJECT,ORCHESTRATE,WORKFLOW,ANALYSIS",
        apps_pages="none",
        runtime_isolation="isolated",
        action_button_policy="trial",
        action_timeout_seconds=30.0,
        page_timeout_seconds=420.0,
        target_seconds=1200.0,
        success_screenshot=True,
        visual_mask_dynamic_regions=True,
        above_fold_check=True,
        browser_error_check=True,
    ),
    "hf-first-proof-app-pages-visual-smoke": RobotScenario(
        name="hf-first-proof-app-pages-visual-smoke",
        description=(
            "Capture hosted Hugging Face screenshots for the first-proof apps-page "
            "bundles exposed by public demo routes."
        ),
        pages="none",
        apps_pages="view_maps,view_forecast_analysis,view_release_decision",
        runtime_isolation="isolated",
        action_button_policy="trial",
        action_timeout_seconds=30.0,
        page_timeout_seconds=420.0,
        target_seconds=1200.0,
        success_screenshot=True,
        visual_mask_dynamic_regions=True,
        above_fold_check=True,
        browser_error_check=True,
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
    "hf-first-proof-install": RobotScenario(
        name="hf-first-proof-install",
        description=(
            "Run the hosted Hugging Face first-proof app INSTALL actions and "
            "fail on fatal install feedback rendered in the page or action log."
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
    parser.add_argument("--trace-dir", type=Path, help="Directory for Playwright trace ZIP artifacts.")
    parser.add_argument("--har-dir", type=Path, help="Directory for Playwright HAR artifacts.")
    parser.add_argument("--video-dir", type=Path, help="Directory for Playwright video artifacts.")
    parser.add_argument(
        "--retry-failed-with-artifacts",
        action="store_true",
        help=(
            "When a scenario fails, rerun only that scenario once with trace, "
            "HAR, and video artifact directories enabled."
        ),
    )
    parser.add_argument(
        "--retry-trace-dir",
        type=Path,
        help="Directory for failure-retry Playwright trace artifacts.",
    )
    parser.add_argument(
        "--retry-har-dir",
        type=Path,
        help="Directory for failure-retry Playwright HAR artifacts.",
    )
    parser.add_argument(
        "--retry-video-dir",
        type=Path,
        help="Directory for failure-retry Playwright video artifacts.",
    )
    parser.add_argument(
        "--result-cache-path",
        type=Path,
        default=DEFAULT_RESULT_CACHE_PATH,
        help="Path for the successful scenario result cache. Defaults under .pytest_cache.",
    )
    parser.add_argument(
        "--no-result-cache",
        action="store_true",
        help="Disable reuse of previously passing scenario summaries.",
    )
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
        trace_dir=args.trace_dir,
        har_dir=args.har_dir,
        video_dir=args.video_dir,
        result_cache_path=None if args.no_result_cache else args.result_cache_path,
        retry_failed_with_artifacts=args.retry_failed_with_artifacts,
        retry_trace_dir=args.retry_trace_dir,
        retry_har_dir=args.retry_har_dir,
        retry_video_dir=args.retry_video_dir,
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
        scenario.apps or options.apps,
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
    if scenario.required_text:
        argv.extend(["--required-text", scenario.required_text])
    if scenario.required_action_labels:
        argv.extend(["--required-action-labels", scenario.required_action_labels])
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
    if scenario.accessibility_check:
        argv.append("--accessibility-check")
    if scenario.browser_error_check:
        argv.append("--browser-error-check")
    if scenario.above_fold_check:
        argv.append("--above-fold-check")
    if scenario.visual_mask_dynamic_regions:
        argv.append("--visual-mask-dynamic-regions")
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
    if options.trace_dir is not None:
        argv.extend(["--trace-dir", str(options.trace_dir / scenario.name)])
    if options.har_dir is not None:
        argv.extend(["--har-dir", str(options.har_dir / scenario.name)])
    if options.video_dir is not None:
        argv.extend(["--video-dir", str(options.video_dir / scenario.name)])
    return argv, summary_path, progress_path


def _scenario_failed(result: ScenarioResult) -> bool:
    return result.returncode != 0 or result.summary.get("success") is not True


def _failure_artifact_retry_options(options: MatrixOptions) -> MatrixOptions:
    retry_output_dir = options.output_dir / "failure-retry"
    retry_artifact_root = options.output_dir / "failure-artifacts"
    retry_screenshot_dir = (
        options.screenshot_dir / "failure-retry"
        if options.screenshot_dir is not None
        else retry_artifact_root / "screenshots"
    )
    return replace(
        options,
        output_dir=retry_output_dir,
        screenshot_dir=retry_screenshot_dir,
        failure_bundle_dir=None,
        trace_dir=options.retry_trace_dir or retry_artifact_root / "traces",
        har_dir=options.retry_har_dir or retry_artifact_root / "har",
        video_dir=options.retry_video_dir or retry_artifact_root / "video",
        result_cache_path=None,
        retry_failed_with_artifacts=False,
        retry_trace_dir=None,
        retry_har_dir=None,
        retry_video_dir=None,
    )


def run_failure_artifact_retry(
    scenario: RobotScenario,
    *,
    options: MatrixOptions,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> FailureArtifactRetry:
    retry_options = _failure_artifact_retry_options(options)
    retry_options.output_dir.mkdir(parents=True, exist_ok=True)
    argv, summary_path, progress_path = build_robot_command(scenario, options=retry_options)
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
    return FailureArtifactRetry(
        argv=argv,
        returncode=completed.returncode,
        duration_seconds=time.perf_counter() - started,
        summary_path=summary_path,
        progress_path=progress_path,
        summary=_load_summary(summary_path, output),
        output=output,
        trace_dir=retry_options.trace_dir / scenario.name if retry_options.trace_dir is not None else None,
        har_dir=retry_options.har_dir / scenario.name if retry_options.har_dir is not None else None,
        video_dir=retry_options.video_dir / scenario.name if retry_options.video_dir is not None else None,
    )


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
    retry_payload: dict[str, object] | None = None
    if result.artifact_retry is not None:
        retry = result.artifact_retry
        (bundle_dir / "retry-summary.json").write_text(
            json.dumps(retry.summary, indent=2) + "\n",
            encoding="utf-8",
        )
        retry_output_tail = _limited_text(retry.output or "")
        if retry_output_tail:
            (bundle_dir / "retry-output-tail.txt").write_text(retry_output_tail, encoding="utf-8")
        retry_progress_tail = _tail_text_file(retry.progress_path)
        if retry_progress_tail:
            (bundle_dir / "retry-progress-tail.ndjson").write_text(retry_progress_tail, encoding="utf-8")
        retry_payload = {
            "success": retry.returncode == 0 and retry.summary.get("success") is True,
            "returncode": retry.returncode,
            "duration_seconds": retry.duration_seconds,
            "summary_path": str(retry.summary_path),
            "progress_path": str(retry.progress_path),
            "trace_dir": str(retry.trace_dir) if retry.trace_dir is not None else "",
            "har_dir": str(retry.har_dir) if retry.har_dir is not None else "",
            "video_dir": str(retry.video_dir) if retry.video_dir is not None else "",
            "command": retry.argv,
        }
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
    if retry_payload is not None:
        manifest["failure_artifact_retry"] = retry_payload
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return bundle_dir


def _repo_relative_or_absolute(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_signature(path_name: Path | str) -> dict[str, object]:
    path = Path(path_name)
    target = path if path.is_absolute() else REPO_ROOT / path
    label = _repo_relative_or_absolute(target) if target.is_absolute() else path.as_posix()
    try:
        stat = target.stat()
    except OSError as exc:
        return {"path": label, "state": "missing", "error": exc.__class__.__name__}
    signature: dict[str, object] = {
        "path": label,
        "state": "directory" if target.is_dir() else "file",
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }
    if target.is_file() and stat.st_size <= RESULT_CACHE_HASH_LIMIT_BYTES:
        try:
            signature["sha256"] = _file_sha256(target)
        except OSError as exc:
            signature["sha256_error"] = exc.__class__.__name__
    return signature


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _git_text(argv: Sequence[str]) -> str:
    completed = subprocess.run(
        list(argv),
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        return f"git-error:{completed.returncode}:{completed.stderr.strip()}"
    return completed.stdout


def _git_output_sha256(argv: Sequence[str]) -> str:
    completed = subprocess.run(
        list(argv),
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        return f"git-error:{completed.returncode}"
    return hashlib.sha256(completed.stdout).hexdigest()


def _status_paths(status_text: str) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for line in status_text.splitlines():
        if len(line) < 4:
            continue
        path_name = line[3:]
        if " -> " in path_name:
            path_name = path_name.split(" -> ", 1)[1]
        path_name = path_name.strip().strip('"')
        if path_name and path_name not in seen:
            paths.append(path_name)
            seen.add(path_name)
    return paths


def _git_watched_state() -> dict[str, object]:
    paths = list(RESULT_CACHE_WATCHED_PATHS)
    status_text = _git_text(["git", "status", "--porcelain=v1", "--untracked-files=all", "--", *paths])
    return {
        "head": _git_head(),
        "status": status_text.splitlines(),
        "diff_sha256": _git_output_sha256(["git", "diff", "--", *paths]),
        "cached_diff_sha256": _git_output_sha256(["git", "diff", "--cached", "--", *paths]),
        "dirty_inputs": [_file_signature(path) for path in _status_paths(status_text)],
    }


def _result_cache_run_fingerprint() -> dict[str, object]:
    return {
        "python": {"executable": sys.executable, "version": sys.version},
        "inputs": [
            _file_signature(ROBOT_PATH),
            _file_signature(Path(__file__).resolve()),
        ],
        "source_state": _git_watched_state(),
    }


def _scenario_cache_options(options: MatrixOptions) -> dict[str, object]:
    return {
        "apps": options.apps,
        "timeout_seconds": options.timeout_seconds,
        "widget_timeout_seconds": options.widget_timeout_seconds,
        "quiet_progress": options.quiet_progress,
        "no_seed_demo_artifacts": options.no_seed_demo_artifacts,
        "browser": options.browser,
        "active_app": options.active_app,
        "remote_app_root": options.remote_app_root,
    }


def _scenario_result_cache_key(
    scenario: RobotScenario,
    *,
    options: MatrixOptions,
    run_fingerprint: dict[str, object],
) -> str:
    payload = {
        "schema": RESULT_CACHE_SCHEMA,
        "scenario": asdict(scenario),
        "options": _scenario_cache_options(options),
        "run_fingerprint": run_fingerprint,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _empty_result_cache() -> dict[str, object]:
    return {"schema": RESULT_CACHE_SCHEMA, "entries": {}}


def _load_result_cache(cache_path: Path) -> dict[str, object]:
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _empty_result_cache()
    if not isinstance(payload, dict) or payload.get("schema") != RESULT_CACHE_SCHEMA:
        return _empty_result_cache()
    if not isinstance(payload.get("entries"), dict):
        return _empty_result_cache()
    return payload


def _prune_result_cache(entries: dict[str, object]) -> None:
    if len(entries) <= RESULT_CACHE_MAX_ENTRIES:
        return

    def _stored_at(item: tuple[str, object]) -> float:
        value = item[1]
        if not isinstance(value, dict):
            return 0.0
        stored_at = value.get("stored_at", 0.0)
        return float(stored_at) if isinstance(stored_at, (int, float)) else 0.0

    keep = {
        key
        for key, _value in sorted(entries.items(), key=_stored_at, reverse=True)[:RESULT_CACHE_MAX_ENTRIES]
    }
    for key in list(entries):
        if key not in keep:
            entries.pop(key, None)


def _write_result_cache(cache_path: Path, cache_state: dict[str, object]) -> None:
    entries = cache_state.get("entries")
    if not isinstance(entries, dict):
        return
    _prune_result_cache(entries)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = cache_path.with_name(f"{cache_path.name}.tmp")
    temp_path.write_text(json.dumps(cache_state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(cache_path)


def _scenario_cache_supported(scenario: RobotScenario, options: MatrixOptions) -> bool:
    if options.result_cache_path is None:
        return False
    if options.url or options.headful:
        return False
    if options.trace_dir is not None or options.har_dir is not None or options.video_dir is not None:
        return False
    if scenario.success_screenshot:
        return False
    return True


def _scenario_result_from_cache(
    payload: object,
    scenario: RobotScenario,
    *,
    options: MatrixOptions,
) -> ScenarioResult | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("scenario") != scenario.name or payload.get("returncode") != 0:
        return None
    summary = payload.get("summary")
    if not isinstance(summary, dict) or summary.get("success") is not True:
        return None
    argv, summary_path, progress_path = build_robot_command(scenario, options=options)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    progress_log = payload.get("progress_log")
    if isinstance(progress_log, str) and progress_log.strip():
        progress_path.write_text(progress_log, encoding="utf-8")
    else:
        progress_path.write_text(
            json.dumps(
                {
                    "event": "cached_result",
                    "scenario": scenario.name,
                    "stored_at": payload.get("stored_at"),
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return ScenarioResult(
        scenario=scenario,
        argv=argv,
        returncode=0,
        duration_seconds=0.0,
        summary_path=summary_path,
        progress_path=progress_path,
        summary=dict(summary),
        output="ui-robot-matrix: reused cached successful scenario result\n",
        cached=True,
    )


def _cacheable_progress_log(path: Path) -> str | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    if stat.st_size > RESULT_CACHE_PROGRESS_LOG_LIMIT_BYTES:
        return None
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return content if content.strip() else None


def _store_scenario_result_cache(
    cache_state: dict[str, object],
    key: str,
    result: ScenarioResult,
) -> bool:
    progress_log = _cacheable_progress_log(result.progress_path)
    if progress_log is None:
        return False
    entries = cache_state.get("entries")
    if not isinstance(entries, dict):
        entries = {}
        cache_state["entries"] = entries
    entries[key] = {
        "scenario": result.scenario.name,
        "stored_at": time.time(),
        "returncode": result.returncode,
        "summary": result.summary,
        "progress_log": progress_log,
    }
    return True


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
    if options.retry_failed_with_artifacts and _scenario_failed(result):
        result = replace(
            result,
            artifact_retry=run_failure_artifact_retry(scenario, options=options, runner=runner),
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
    cache_path = options.result_cache_path
    cache_state = _load_result_cache(cache_path) if cache_path is not None else None
    run_fingerprint = _result_cache_run_fingerprint() if cache_state is not None else {}
    cache_changed = False
    for scenario in scenarios:
        cache_key = ""
        result: ScenarioResult | None = None
        if cache_state is not None and _scenario_cache_supported(scenario, options):
            cache_key = _scenario_result_cache_key(
                scenario,
                options=options,
                run_fingerprint=run_fingerprint,
            )
            entries = cache_state.get("entries")
            if isinstance(entries, dict):
                result = _scenario_result_from_cache(entries.get(cache_key), scenario, options=options)
        if result is None:
            result = run_scenario(scenario, options=options, runner=runner)
            if (
                cache_state is not None
                and cache_key
                and result.returncode == 0
                and result.summary.get("success") is True
            ):
                cache_changed = _store_scenario_result_cache(cache_state, cache_key, result) or cache_changed
        results.append(result)
        if result.returncode != 0 and not keep_going:
            break
    if cache_path is not None and cache_state is not None and cache_changed:
        _write_result_cache(cache_path, cache_state)
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
        "cached_count": sum(1 for result in results if result.cached),
        "failure_artifact_retry_count": sum(1 for result in results if result.artifact_retry is not None),
        "failure_artifact_retry_passed_count": sum(
            1
            for result in results
            if result.artifact_retry is not None
            and result.artifact_retry.returncode == 0
            and result.artifact_retry.summary.get("success") is True
        ),
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
                "cached": result.cached,
                "summary_path": str(result.summary_path),
                "progress_path": str(result.progress_path),
                "page_count": int(result.summary.get("page_count") or 0),
                "widget_count": int(result.summary.get("widget_count") or 0),
                "interacted_count": int(result.summary.get("interacted_count") or 0),
                "probed_count": int(result.summary.get("probed_count") or 0),
                "skipped_count": int(result.summary.get("skipped_count") or 0),
                "failed_count": int(result.summary.get("failed_count") or 0),
                "failure_artifact_retry": _failure_artifact_retry_summary(result.artifact_retry),
            }
            for result in results
        ],
    }


def _failure_artifact_retry_summary(retry: FailureArtifactRetry | None) -> dict[str, object] | None:
    if retry is None:
        return None
    return {
        "success": retry.returncode == 0 and retry.summary.get("success") is True,
        "returncode": retry.returncode,
        "duration_seconds": retry.duration_seconds,
        "summary_path": str(retry.summary_path),
        "progress_path": str(retry.progress_path),
        "trace_dir": str(retry.trace_dir) if retry.trace_dir is not None else "",
        "har_dir": str(retry.har_dir) if retry.har_dir is not None else "",
        "video_dir": str(retry.video_dir) if retry.video_dir is not None else "",
        "command": retry.argv,
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
            f"skipped={summary['skipped_count']} failed={summary['failed_count']} "
            f"cached={summary['cached_count']} "
            f"artifact_retries={summary['failure_artifact_retry_count']}"
        )
    ]
    for scenario in summary["scenarios"]:
        scenario_status = "PASS" if scenario["success"] else "FAIL"
        cached = " cached" if scenario.get("cached") else ""
        retry = scenario.get("failure_artifact_retry") or {}
        retry_status = ""
        if retry:
            retry_status = " artifact-retry=PASS" if retry.get("success") is True else " artifact-retry=FAIL"
        lines.append(
            (
                f"- [{scenario_status}] {scenario['name']}{cached}{retry_status}: pages={scenario['page_count']} "
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
