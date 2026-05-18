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
SCHEMA = "agilab.ui_robot_coverage_contract.v1"
REQUIRED_CORE_PAGES = ("HOME", "PROJECT", "ORCHESTRATE", "WORKFLOW", "ANALYSIS", "SETTINGS")
REQUIRED_HIGH_RISK_ACTIONS = ("INSTALL", "CHECK distribute", "Run -> Load -> Export")


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


def evaluate_contract() -> dict[str, Any]:
    widget_robot = _load_module("agilab_widget_robot_contract", WIDGET_ROBOT_PATH)
    matrix = _load_module("agilab_widget_robot_matrix_contract", MATRIX_PATH)
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
