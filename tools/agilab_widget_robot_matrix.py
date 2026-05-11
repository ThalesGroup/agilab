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
    missing_selected_action_policy: str = "fail"
    action_timeout_seconds: float = 90.0
    page_timeout_seconds: float = 420.0
    target_seconds: float = 1800.0
    assert_orchestrate_artifacts: bool = False
    assert_workflow_artifacts: bool = False


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
        choices=["all", *DEFAULT_SCENARIOS.keys()],
        help="Scenario to run. May be passed multiple times. Defaults to all.",
    )
    parser.add_argument("--apps", default="all", help="Built-in apps or app paths to pass to the widget robot.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--screenshot-dir", type=Path, help="Directory for failure screenshots and manifest files.")
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
            resolved.append(DEFAULT_SCENARIOS[scenario_name])
            seen.add(scenario_name)
    return resolved


def options_from_args(args: argparse.Namespace) -> MatrixOptions:
    return MatrixOptions(
        apps=args.apps,
        output_dir=args.output_dir,
        screenshot_dir=args.screenshot_dir,
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
    if scenario.assert_orchestrate_artifacts:
        argv.append("--assert-orchestrate-artifacts")
    if scenario.assert_workflow_artifacts:
        argv.append("--assert-workflow-artifacts")
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
    return ScenarioResult(
        scenario=scenario,
        argv=argv,
        returncode=completed.returncode,
        duration_seconds=time.perf_counter() - started,
        summary_path=summary_path,
        progress_path=progress_path,
        summary=_load_summary(summary_path, output),
        output=output,
    )


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
