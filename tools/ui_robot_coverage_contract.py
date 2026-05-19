#!/usr/bin/env python3
"""Validate that AGILAB UI robot scenarios cover the expected UI surface."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
WIDGET_ROBOT_PATH = REPO_ROOT / "tools" / "agilab_widget_robot.py"
MATRIX_PATH = REPO_ROOT / "tools" / "agilab_widget_robot_matrix.py"
HF_SMOKE_PATH = REPO_ROOT / "tools" / "hf_space_smoke.py"
WORKFLOW_PARITY_PATH = REPO_ROOT / "tools" / "workflow_parity.py"
SCHEMA = "agilab.ui_robot_coverage_contract.v1"
REQUIRED_CORE_PAGES = ("HOME", "PROJECT", "ORCHESTRATE", "WORKFLOW", "ANALYSIS", "SETTINGS")
REQUIRED_HIGH_RISK_ACTIONS = ("INSTALL", "CHECK distribute", "Run -> Load -> Export")
REQUIRED_HF_FIRST_PROOF_APPS = ("flight_telemetry_project", "weather_forecast_project")
FORBIDDEN_HF_FIRST_PROOF_APPS = ("flight_project", "meteo_forecast_project")
REQUIRED_HF_ROBOT_SCENARIOS = {
    "hf-first-proof-visual-smoke": {
        "pages": ("HOME", "ORCHESTRATE", "WORKFLOW", "ANALYSIS"),
        "flags": ("success_screenshot", "above_fold_check", "browser_error_check"),
    },
    "hf-flight-telemetry-install": {
        "pages": ("ORCHESTRATE",),
        "actions": ("INSTALL",),
    },
}


@dataclass(frozen=True)
class CoverageIssue:
    kind: str
    detail: str


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _scenario_pages(widget_robot: Any, scenario: Any) -> set[str]:
    return {widget_robot.page_label(page) for page in widget_robot.resolve_pages(str(scenario.pages))}


def _scenario_action_labels(widget_robot: Any, scenario: Any) -> set[str]:
    return {
        widget_robot._normalized_label(label)
        for label in widget_robot.parse_csv(str(getattr(scenario, "click_action_labels", "")))
        if widget_robot._normalized_label(label)
    }


def _scenario_flags(scenario: Any) -> set[str]:
    return {
        flag
        for flag in ("success_screenshot", "above_fold_check", "browser_error_check")
        if bool(getattr(scenario, flag, False))
    }


def _argv_value(argv: Sequence[str], option: str) -> str:
    try:
        return argv[argv.index(option) + 1]
    except (ValueError, IndexError):
        return ""


def evaluate_contract() -> dict[str, Any]:
    widget_robot = _load_module("agilab_widget_robot_contract", WIDGET_ROBOT_PATH)
    matrix = _load_module("agilab_widget_robot_matrix_contract", MATRIX_PATH)
    hf_smoke = _load_module("hf_space_smoke_contract", HF_SMOKE_PATH)
    workflow_parity = _load_module("workflow_parity_contract", WORKFLOW_PARITY_PATH)
    issues: list[CoverageIssue] = []
    default_scenarios = list(matrix.DEFAULT_SCENARIOS.values())
    all_scenarios = list(matrix.ALL_SCENARIOS.values())
    built_in_apps = [path.name for path in widget_robot.public_builtin_apps()]
    if not built_in_apps:
        issues.append(CoverageIssue("built_in_apps", "no public built-in apps were discovered"))

    page_to_scenarios: dict[str, list[str]] = {page: [] for page in REQUIRED_CORE_PAGES}
    for scenario in all_scenarios:
        for page in _scenario_pages(widget_robot, scenario):
            if page in page_to_scenarios:
                page_to_scenarios[page].append(scenario.name)
    for page, scenarios in page_to_scenarios.items():
        if not scenarios:
            issues.append(CoverageIssue("core_page", f"{page} is not covered by any robot scenario"))

    configured_apps_pages: dict[str, list[str]] = {}
    for app in widget_robot.public_builtin_apps():
        routes = widget_robot.configured_apps_pages_for_app(app)
        if routes:
            configured_apps_pages[app.name] = [route.name for route in routes]
    configured_scenarios = [
        scenario.name
        for scenario in default_scenarios
        if str(scenario.apps_pages) == "configured"
    ]
    if configured_apps_pages and not configured_scenarios:
        issues.append(
            CoverageIssue(
                "configured_apps_pages",
                "apps declare configured apps-pages but no default scenario sweeps apps_pages=configured",
            )
        )

    action_to_scenarios: dict[str, list[str]] = {label: [] for label in REQUIRED_HIGH_RISK_ACTIONS}
    for scenario in all_scenarios:
        labels = _scenario_action_labels(widget_robot, scenario)
        for required in REQUIRED_HIGH_RISK_ACTIONS:
            normalized = widget_robot._normalized_label(required)
            if any(normalized == label or normalized in label or label in normalized for label in labels):
                action_to_scenarios[required].append(scenario.name)
    for label, scenarios in action_to_scenarios.items():
        if not scenarios:
            issues.append(CoverageIssue("high_risk_action", f"{label!r} is not covered by a selected-action scenario"))

    default_apps_all = bool(default_scenarios)
    if built_in_apps and not default_apps_all:
        issues.append(CoverageIssue("built_in_app_matrix", "default robot matrix has no scenarios for --apps all"))

    hf_first_proof_apps = sorted(hf_smoke.profile_builtin_app_entries("first-proof"))
    missing_hf_apps = sorted(set(REQUIRED_HF_FIRST_PROOF_APPS) - set(hf_first_proof_apps))
    forbidden_hf_apps = sorted(set(FORBIDDEN_HF_FIRST_PROOF_APPS) & set(hf_first_proof_apps))
    if missing_hf_apps:
        issues.append(
            CoverageIssue(
                "hf_public_demo_app",
                "first-proof HF profile is missing public demo apps: " + ", ".join(missing_hf_apps),
            )
        )
    if forbidden_hf_apps:
        issues.append(
            CoverageIssue(
                "hf_public_demo_app",
                "first-proof HF profile still exposes stale demo apps: " + ", ".join(forbidden_hf_apps),
            )
        )

    scenario_by_name = {scenario.name: scenario for scenario in all_scenarios}
    hf_robot_scenarios: dict[str, dict[str, list[str]]] = {}
    for scenario_name, requirements in REQUIRED_HF_ROBOT_SCENARIOS.items():
        scenario = scenario_by_name.get(scenario_name)
        if scenario is None:
            issues.append(CoverageIssue("hf_robot_scenario", f"{scenario_name} is missing from the robot matrix"))
            continue
        pages = sorted(_scenario_pages(widget_robot, scenario))
        actions = sorted(_scenario_action_labels(widget_robot, scenario))
        flags = sorted(_scenario_flags(scenario))
        hf_robot_scenarios[scenario_name] = {
            "pages": pages,
            "actions": actions,
            "flags": flags,
        }
        missing_pages = sorted(set(requirements.get("pages", ())) - set(pages))
        if missing_pages:
            issues.append(
                CoverageIssue(
                    "hf_robot_scenario",
                    f"{scenario_name} is missing required pages: " + ", ".join(missing_pages),
                )
            )
        missing_actions = sorted(
            {
                widget_robot._normalized_label(action)
                for action in requirements.get("actions", ())
                if widget_robot._normalized_label(action) not in actions
            }
        )
        if missing_actions:
            issues.append(
                CoverageIssue(
                    "hf_robot_scenario",
                    f"{scenario_name} is missing required actions: " + ", ".join(missing_actions),
                )
            )
        missing_flags = sorted(set(requirements.get("flags", ())) - set(flags))
        if missing_flags:
            issues.append(
                CoverageIssue(
                    "hf_robot_scenario",
                    f"{scenario_name} is missing required flags: " + ", ".join(missing_flags),
                )
            )

    parity_profiles = workflow_parity._profile_commands(
        argparse.Namespace(components=(), skills=(), app_path=None, worker_copy=None)
    )
    hf_visual_smoke_profile_apps: list[str] = []
    hf_visual_smoke_profile_scenarios: list[str] = []
    for command in parity_profiles.get("hf-visual-smoke-robot", []):
        scenario = _argv_value(command.argv, "--scenario")
        if scenario:
            hf_visual_smoke_profile_scenarios.append(scenario)
        if scenario == "hf-first-proof-visual-smoke":
            hf_visual_smoke_profile_apps.extend(widget_robot.parse_csv(_argv_value(command.argv, "--apps")))
    hf_visual_smoke_profile_apps = sorted(set(hf_visual_smoke_profile_apps))
    hf_visual_smoke_profile_scenarios = sorted(set(hf_visual_smoke_profile_scenarios))
    missing_profile_apps = sorted(set(hf_first_proof_apps) - set(hf_visual_smoke_profile_apps))
    if "hf-first-proof-visual-smoke" not in hf_visual_smoke_profile_scenarios:
        issues.append(
            CoverageIssue(
                "hf_robot_profile",
                "hf-visual-smoke-robot does not run hf-first-proof-visual-smoke",
            )
        )
    if missing_profile_apps:
        issues.append(
            CoverageIssue(
                "hf_robot_profile",
                "hf-visual-smoke-robot is missing first-proof apps: " + ", ".join(missing_profile_apps),
            )
        )

    return {
        "schema": SCHEMA,
        "success": not issues,
        "issues": [asdict(issue) for issue in issues],
        "coverage": {
            "built_in_apps": built_in_apps,
            "built_in_apps_covered_by": "ui-robot-matrix --apps all" if default_apps_all else "",
            "core_pages": page_to_scenarios,
            "configured_apps_pages": configured_apps_pages,
            "configured_apps_pages_scenarios": configured_scenarios,
            "high_risk_actions": action_to_scenarios,
            "hf_first_proof_apps": hf_first_proof_apps,
            "hf_visual_smoke_profile_apps": hf_visual_smoke_profile_apps,
            "hf_visual_smoke_profile_scenarios": hf_visual_smoke_profile_scenarios,
            "hf_robot_scenarios": hf_robot_scenarios,
            "default_scenarios": [scenario.name for scenario in default_scenarios],
            "opt_in_scenarios": sorted(set(matrix.OPT_IN_SCENARIOS)),
        },
    }


def render_human(payload: dict[str, Any]) -> str:
    lines = [
        "AGILAB UI robot coverage contract",
        f"verdict: {'PASS' if payload.get('success') else 'FAIL'}",
    ]
    for issue in payload.get("issues", []):
        lines.append(f"- {issue.get('kind')}: {issue.get('detail')}")
    coverage = payload.get("coverage", {})
    lines.append(f"built_in_apps={len(coverage.get('built_in_apps', []))}")
    lines.append(f"default_scenarios={len(coverage.get('default_scenarios', []))}")
    lines.append(f"opt_in_scenarios={len(coverage.get('opt_in_scenarios', []))}")
    lines.append(f"hf_robot_scenarios={len(coverage.get('hf_robot_scenarios', []))}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(list(argv) if argv is not None else None)
    payload = evaluate_contract()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_human(payload))
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
