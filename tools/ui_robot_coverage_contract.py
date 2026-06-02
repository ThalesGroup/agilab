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
PUBLIC_PROOF_SCENARIOS_PATH = REPO_ROOT / "tools" / "public_proof_scenarios.py"
DEMOS_DOC_PATH = REPO_ROOT / "docs" / "source" / "demos.rst"
SCHEMA = "agilab.ui_robot_coverage_contract.v1"
REQUIRED_CORE_PAGES = ("HOME", "PROJECT", "ORCHESTRATE", "WORKFLOW", "ANALYSIS", "SETTINGS")
REQUIRED_EDITOR_ROUTES = ("PROJECT_EDITOR",)
REQUIRED_EDITOR_ROUTE_TEXT = {"PROJECT_EDITOR": ("Edit project files",)}
REQUIRED_EDITOR_ROUTE_FORBIDDEN_TEXT = {"PROJECT_EDITOR": ("Environment Health", "Source LOC", "Worker class")}
REQUIRED_EDITOR_ROUTE_PROFILE_SCENARIOS = ("isolated-project-editor-page",)
REQUIRED_HIGH_RISK_ACTIONS = ("INSTALL", "CHECK distribute", "Run -> Load -> Export")
REQUIRED_HF_FIRST_PROOF_APPS = (
    "flight_telemetry_project",
    "pytorch_playground_project",
    "weather_forecast_project",
)
REQUIRED_HF_FIRST_PROOF_PAGES = ("view_forecast_analysis", "view_maps", "view_release_decision")
FORBIDDEN_HF_FIRST_PROOF_APPS = ("flight_project", "weather_forecast_legacy_project")
REQUIRED_PYTORCH_ANALYSIS_SCENARIO = "isolated-pytorch-playground-analysis"
REQUIRED_PYTORCH_ANALYSIS_APP = "pytorch_playground_project"
REQUIRED_PYTORCH_ANALYSIS_TEXT = ("PyTorch Playground", "Refresh evidence", "Synced RUN snippet", "Settings")
REQUIRED_PYTORCH_ANALYSIS_FORBIDDEN_SIDEBAR_TEXT = ("Project:",)
REQUIRED_PYTORCH_ANALYSIS_LINKS = ("PyTorch Playground=>current_page=view_app_ui",)
REQUIRED_PYTORCH_ANALYSIS_ACTIONS = ("Refresh evidence",)
REQUIRED_HF_ROBOT_SCENARIOS = {
    "hf-first-proof-visual-smoke": {
        "pages": ("HOME", "PROJECT", "ORCHESTRATE", "WORKFLOW", "ANALYSIS"),
        "flags": ("success_screenshot", "above_fold_check", "browser_error_check"),
    },
    "hf-first-proof-app-pages-visual-smoke": {
        "apps_pages": REQUIRED_HF_FIRST_PROOF_PAGES,
        "flags": ("success_screenshot", "above_fold_check", "browser_error_check"),
    },
    "hf-first-proof-install": {
        "pages": ("ORCHESTRATE",),
        "actions": ("INSTALL",),
    },
}
REQUIRED_DEMO_DOC_SNIPPETS = (
    "Robot/proof coverage",
    "UI robot",
    "Static/CLI proof",
    "tools/ui_robot_coverage_contract.py --json",
    "tools/public_proof_scenarios.py --compact",
)
REQUIRED_DEMO_UI_APPS = (
    "flight_telemetry_project",
    "weather_forecast_project",
    "mission_decision_project",
    "execution_pandas_project",
    "execution_polars_project",
    "uav_queue_project",
    "uav_relay_queue_project",
)
REQUIRED_DEMO_UI_PAGES = (
    "view_maps",
    "view_forecast_analysis",
    "view_release_decision",
    "view_data_io_decision",
    "view_scenario_cockpit",
    "view_queue_resilience",
    "view_relay_resilience",
    "view_maps_network",
)
REQUIRED_DEMO_PROOF_SCENARIOS = (
    "flight-local-first-proof",
    "weather-forecast-hosted-proof",
    "mlflow-tracking-proof",
    "distributed-worker-health-proof",
    "notebook-migration-proof",
    "resilience-failure-injection-proof",
    "train-then-serve-proof",
    "service-mode-preview-proof",
)


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


def _scenario_apps_pages(widget_robot: Any, scenario: Any) -> set[str]:
    return {
        name
        for name in widget_robot.parse_csv(str(getattr(scenario, "apps_pages", "")))
        if name and name != "none"
    }


def _scenario_apps(widget_robot: Any, scenario: Any) -> set[str]:
    return {
        name
        for name in widget_robot.parse_csv(str(getattr(scenario, "apps", "")))
        if name and name != "all"
    }


def _scenario_required_text(widget_robot: Any, scenario: Any) -> set[str]:
    return set(widget_robot.parse_csv(str(getattr(scenario, "required_text", ""))))


def _scenario_forbidden_text(widget_robot: Any, scenario: Any) -> set[str]:
    return set(widget_robot.parse_csv(str(getattr(scenario, "forbidden_text", ""))))


def _scenario_forbidden_sidebar_text(widget_robot: Any, scenario: Any) -> set[str]:
    return set(widget_robot.parse_csv(str(getattr(scenario, "forbidden_sidebar_text", ""))))


def _scenario_required_links(widget_robot: Any, scenario: Any) -> set[str]:
    return set(widget_robot.parse_csv(str(getattr(scenario, "required_links", ""))))


def _scenario_required_actions(widget_robot: Any, scenario: Any) -> set[str]:
    return set(widget_robot.parse_csv(str(getattr(scenario, "required_action_labels", ""))))


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


def _argv_values(argv: Sequence[str], option: str) -> list[str]:
    return [argv[index + 1] for index, value in enumerate(argv[:-1]) if value == option]


def evaluate_contract() -> dict[str, Any]:
    widget_robot = _load_module("agilab_widget_robot_contract", WIDGET_ROBOT_PATH)
    matrix = _load_module("agilab_widget_robot_matrix_contract", MATRIX_PATH)
    hf_smoke = _load_module("hf_space_smoke_contract", HF_SMOKE_PATH)
    workflow_parity = _load_module("workflow_parity_contract", WORKFLOW_PARITY_PATH)
    public_proof_scenarios = _load_module("public_proof_scenarios_contract", PUBLIC_PROOF_SCENARIOS_PATH)
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

    editor_route_to_scenarios: dict[str, list[str]] = {route: [] for route in REQUIRED_EDITOR_ROUTES}
    editor_route_contract: dict[str, dict[str, list[str]]] = {}
    for route in REQUIRED_EDITOR_ROUTES:
        required_text: set[str] = set()
        forbidden_text: set[str] = set()
        for scenario in default_scenarios:
            if route not in _scenario_pages(widget_robot, scenario):
                continue
            editor_route_to_scenarios[route].append(scenario.name)
            required_text.update(_scenario_required_text(widget_robot, scenario))
            forbidden_text.update(_scenario_forbidden_text(widget_robot, scenario))
        editor_route_contract[route] = {
            "scenarios": editor_route_to_scenarios[route],
            "required_text": sorted(required_text),
            "forbidden_text": sorted(forbidden_text),
        }
        if not editor_route_to_scenarios[route]:
            issues.append(
                CoverageIssue(
                    "editor_route",
                    f"{route} is not covered by any default robot scenario",
                )
            )
        missing_required_text = sorted(set(REQUIRED_EDITOR_ROUTE_TEXT.get(route, ())) - required_text)
        if missing_required_text:
            issues.append(
                CoverageIssue(
                    "editor_route",
                    f"{route} is missing required text probes: " + ", ".join(missing_required_text),
                )
            )
        missing_forbidden_text = sorted(set(REQUIRED_EDITOR_ROUTE_FORBIDDEN_TEXT.get(route, ())) - forbidden_text)
        if missing_forbidden_text:
            issues.append(
                CoverageIssue(
                    "editor_route",
                    f"{route} is missing forbidden dashboard text probes: " + ", ".join(missing_forbidden_text),
                )
            )

    configured_apps_pages: dict[str, list[str]] = {}
    for app in widget_robot.public_builtin_apps():
        routes = widget_robot.configured_apps_pages_for_app(app)
        if routes:
            configured_apps_pages[app.name] = [route.name for route in routes]
    configured_apps_page_names = sorted({name for routes in configured_apps_pages.values() for name in routes})
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
    hf_first_proof_pages = sorted(hf_smoke.profile_page_entries("first-proof"))
    missing_hf_pages = sorted(set(REQUIRED_HF_FIRST_PROOF_PAGES) - set(hf_first_proof_pages))
    if missing_hf_pages:
        issues.append(
            CoverageIssue(
                "hf_public_demo_page",
                "first-proof HF profile is missing public demo pages: " + ", ".join(missing_hf_pages),
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
        apps_pages = sorted(_scenario_apps_pages(widget_robot, scenario))
        hf_robot_scenarios[scenario_name] = {
            "pages": pages,
            "apps_pages": apps_pages,
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
        missing_apps_pages = sorted(set(requirements.get("apps_pages", ())) - set(apps_pages))
        if missing_apps_pages:
            issues.append(
                CoverageIssue(
                    "hf_robot_scenario",
                    f"{scenario_name} is missing required apps-pages: " + ", ".join(missing_apps_pages),
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
    hf_install_profile_apps: list[str] = []
    hf_install_profile_scenarios: list[str] = []
    ui_robot_matrix_profile_apps: list[str] = []
    ui_robot_matrix_profile_scenarios: list[str] = []
    hf_visual_smoke_required_scenarios = {
        "hf-first-proof-visual-smoke",
        "hf-first-proof-app-pages-visual-smoke",
    }
    hf_install_required_scenarios = {"hf-first-proof-install"}
    for command in parity_profiles.get("hf-visual-smoke-robot", []):
        scenarios = _argv_values(command.argv, "--scenario")
        hf_visual_smoke_profile_scenarios.extend(scenarios)
        if hf_visual_smoke_required_scenarios.intersection(scenarios):
            hf_visual_smoke_profile_apps.extend(widget_robot.parse_csv(_argv_value(command.argv, "--apps")))
    for command in parity_profiles.get("hf-install-robot", []):
        scenarios = _argv_values(command.argv, "--scenario")
        hf_install_profile_scenarios.extend(scenarios)
        if hf_install_required_scenarios.intersection(scenarios):
            hf_install_profile_apps.extend(widget_robot.parse_csv(_argv_value(command.argv, "--apps")))
    for command in parity_profiles.get("ui-robot-matrix", []):
        ui_robot_matrix_profile_apps.extend(widget_robot.parse_csv(_argv_value(command.argv, "--apps")))
        ui_robot_matrix_profile_scenarios.extend(_argv_values(command.argv, "--scenario"))
    hf_visual_smoke_profile_apps = sorted(set(hf_visual_smoke_profile_apps))
    hf_visual_smoke_profile_scenarios = sorted(set(hf_visual_smoke_profile_scenarios))
    hf_install_profile_apps = sorted(set(hf_install_profile_apps))
    hf_install_profile_scenarios = sorted(set(hf_install_profile_scenarios))
    ui_robot_matrix_profile_apps = sorted(set(ui_robot_matrix_profile_apps))
    ui_robot_matrix_profile_scenarios = sorted(set(ui_robot_matrix_profile_scenarios))
    missing_profile_apps = sorted(set(hf_first_proof_apps) - set(hf_visual_smoke_profile_apps))
    missing_install_profile_apps = sorted(set(hf_first_proof_apps) - set(hf_install_profile_apps))
    if "hf-first-proof-visual-smoke" not in hf_visual_smoke_profile_scenarios:
        issues.append(
            CoverageIssue(
                "hf_robot_profile",
                "hf-visual-smoke-robot does not run hf-first-proof-visual-smoke",
            )
        )
    if "hf-first-proof-app-pages-visual-smoke" not in hf_visual_smoke_profile_scenarios:
        issues.append(
            CoverageIssue(
                "hf_robot_profile",
                "hf-visual-smoke-robot does not run hf-first-proof-app-pages-visual-smoke",
            )
        )
    if missing_profile_apps:
        issues.append(
            CoverageIssue(
                "hf_robot_profile",
                "hf-visual-smoke-robot is missing first-proof apps: " + ", ".join(missing_profile_apps),
            )
        )
    if "hf-first-proof-install" not in hf_install_profile_scenarios:
        issues.append(
            CoverageIssue(
                "hf_robot_profile",
                "hf-install-robot does not run hf-first-proof-install",
            )
        )
    if missing_install_profile_apps:
        issues.append(
            CoverageIssue(
                "hf_robot_profile",
                "hf-install-robot is missing first-proof apps: " + ", ".join(missing_install_profile_apps),
            )
        )

    pytorch_analysis: dict[str, list[str]] = {}
    pytorch_scenario = scenario_by_name.get(REQUIRED_PYTORCH_ANALYSIS_SCENARIO)
    if pytorch_scenario is None:
        issues.append(
            CoverageIssue(
                "pytorch_analysis_robot",
                f"{REQUIRED_PYTORCH_ANALYSIS_SCENARIO} is missing from the robot matrix",
            )
        )
    else:
        pages = sorted(_scenario_pages(widget_robot, pytorch_scenario))
        apps = sorted(_scenario_apps(widget_robot, pytorch_scenario))
        required_text = sorted(_scenario_required_text(widget_robot, pytorch_scenario))
        forbidden_sidebar_text = sorted(_scenario_forbidden_sidebar_text(widget_robot, pytorch_scenario))
        required_links = sorted(_scenario_required_links(widget_robot, pytorch_scenario))
        required_actions = sorted(_scenario_required_actions(widget_robot, pytorch_scenario))
        flags = sorted(_scenario_flags(pytorch_scenario))
        pytorch_analysis = {
            "pages": pages,
            "apps": apps,
            "required_text": required_text,
            "forbidden_sidebar_text": forbidden_sidebar_text,
            "required_links": required_links,
            "required_actions": required_actions,
            "flags": flags,
        }
        if "ANALYSIS" not in pages:
            issues.append(
                CoverageIssue(
                    "pytorch_analysis_robot",
                    f"{REQUIRED_PYTORCH_ANALYSIS_SCENARIO} does not cover ANALYSIS",
                )
            )
        if REQUIRED_PYTORCH_ANALYSIS_APP not in apps:
            issues.append(
                CoverageIssue(
                    "pytorch_analysis_robot",
                    f"{REQUIRED_PYTORCH_ANALYSIS_SCENARIO} does not target {REQUIRED_PYTORCH_ANALYSIS_APP}",
                )
            )
        missing_text = sorted(set(REQUIRED_PYTORCH_ANALYSIS_TEXT) - set(required_text))
        if missing_text:
            issues.append(
                CoverageIssue(
                    "pytorch_analysis_robot",
                    f"{REQUIRED_PYTORCH_ANALYSIS_SCENARIO} is missing required text probes: "
                    + ", ".join(missing_text),
                )
            )
        missing_forbidden_sidebar_text = sorted(
            set(REQUIRED_PYTORCH_ANALYSIS_FORBIDDEN_SIDEBAR_TEXT) - set(forbidden_sidebar_text)
        )
        if missing_forbidden_sidebar_text:
            issues.append(
                CoverageIssue(
                    "pytorch_analysis_robot",
                    f"{REQUIRED_PYTORCH_ANALYSIS_SCENARIO} is missing forbidden sidebar text probes: "
                    + ", ".join(missing_forbidden_sidebar_text),
                )
            )
        missing_links = sorted(set(REQUIRED_PYTORCH_ANALYSIS_LINKS) - set(required_links))
        if missing_links:
            issues.append(
                CoverageIssue(
                    "pytorch_analysis_robot",
                    f"{REQUIRED_PYTORCH_ANALYSIS_SCENARIO} is missing required link probes: "
                    + ", ".join(missing_links),
                )
            )
        missing_actions = sorted(set(REQUIRED_PYTORCH_ANALYSIS_ACTIONS) - set(required_actions))
        if missing_actions:
            issues.append(
                CoverageIssue(
                    "pytorch_analysis_robot",
                    f"{REQUIRED_PYTORCH_ANALYSIS_SCENARIO} is missing required action probes: "
                    + ", ".join(missing_actions),
                )
            )
        if "browser_error_check" not in flags:
            issues.append(
                CoverageIssue(
                    "pytorch_analysis_robot",
                    f"{REQUIRED_PYTORCH_ANALYSIS_SCENARIO} does not enable browser_error_check",
                )
            )
    for editor_profile_scenario in REQUIRED_EDITOR_ROUTE_PROFILE_SCENARIOS:
        if editor_profile_scenario not in ui_robot_matrix_profile_scenarios:
            issues.append(
                CoverageIssue(
                    "editor_route",
                    f"ui-robot-matrix profile does not run {editor_profile_scenario}",
                )
            )

    if REQUIRED_PYTORCH_ANALYSIS_SCENARIO not in ui_robot_matrix_profile_scenarios:
        issues.append(
            CoverageIssue(
                "pytorch_analysis_robot",
                f"ui-robot-matrix profile does not run {REQUIRED_PYTORCH_ANALYSIS_SCENARIO}",
            )
        )

    demo_doc_text = DEMOS_DOC_PATH.read_text(encoding="utf-8") if DEMOS_DOC_PATH.is_file() else ""
    missing_demo_doc_snippets = [snippet for snippet in REQUIRED_DEMO_DOC_SNIPPETS if snippet not in demo_doc_text]
    if missing_demo_doc_snippets:
        issues.append(
            CoverageIssue(
                "public_demo_docs",
                "demos page is missing robot/proof coverage wording: "
                + ", ".join(missing_demo_doc_snippets),
            )
        )
    missing_demo_ui_apps = sorted(set(REQUIRED_DEMO_UI_APPS) - set(built_in_apps))
    if missing_demo_ui_apps:
        issues.append(
            CoverageIssue(
                "public_demo_ui_app",
                "documented UI demo apps are missing from built-in app discovery: "
                + ", ".join(missing_demo_ui_apps),
            )
        )
    ui_robot_matrix_covers_all_apps = "all" in ui_robot_matrix_profile_apps
    if not ui_robot_matrix_covers_all_apps:
        missing_robot_profile_apps = sorted(set(REQUIRED_DEMO_UI_APPS) - set(ui_robot_matrix_profile_apps))
        if missing_robot_profile_apps:
            issues.append(
                CoverageIssue(
                    "public_demo_ui_app",
                    "ui-robot-matrix profile is missing documented demo apps: "
                    + ", ".join(missing_robot_profile_apps),
                )
            )
    missing_demo_pages = sorted(set(REQUIRED_DEMO_UI_PAGES) - set(configured_apps_page_names))
    if missing_demo_pages:
        issues.append(
            CoverageIssue(
                "public_demo_apps_page",
                "documented demo apps-pages are not configured on any built-in app: "
                + ", ".join(missing_demo_pages),
            )
        )
    proof_scenario_ids = [str(scenario["id"]) for scenario in public_proof_scenarios.SCENARIOS]
    missing_proof_scenarios = sorted(set(REQUIRED_DEMO_PROOF_SCENARIOS) - set(proof_scenario_ids))
    if missing_proof_scenarios:
        issues.append(
            CoverageIssue(
                "public_demo_proof",
                "public proof scenarios are missing documented demo routes: "
                + ", ".join(missing_proof_scenarios),
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
            "editor_routes": editor_route_contract,
            "configured_apps_page_names": configured_apps_page_names,
            "configured_apps_pages_scenarios": configured_scenarios,
            "high_risk_actions": action_to_scenarios,
            "hf_first_proof_apps": hf_first_proof_apps,
            "hf_first_proof_pages": hf_first_proof_pages,
            "hf_install_profile_apps": hf_install_profile_apps,
            "hf_install_profile_scenarios": hf_install_profile_scenarios,
            "ui_robot_matrix_profile_apps": ui_robot_matrix_profile_apps,
            "hf_visual_smoke_profile_apps": hf_visual_smoke_profile_apps,
            "hf_visual_smoke_profile_scenarios": hf_visual_smoke_profile_scenarios,
            "ui_robot_matrix_profile_scenarios": ui_robot_matrix_profile_scenarios,
            "hf_robot_scenarios": hf_robot_scenarios,
            "pytorch_analysis_robot": pytorch_analysis,
            "public_demo_contract": {
                "doc_snippets": list(REQUIRED_DEMO_DOC_SNIPPETS),
                "ui_apps": list(REQUIRED_DEMO_UI_APPS),
                "ui_apps_covered_by": (
                    "ui-robot-matrix --apps all"
                    if ui_robot_matrix_covers_all_apps
                    else "ui-robot-matrix explicit --apps"
                ),
                "apps_pages": list(REQUIRED_DEMO_UI_PAGES),
                "proof_scenarios": proof_scenario_ids,
            },
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
