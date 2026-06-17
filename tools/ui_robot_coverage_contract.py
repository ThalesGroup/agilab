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
REQUIRED_HIGH_RISK_ACTIONS = ("Deploy workers", "CHECK distribute", "Run -> Load -> Export")
REQUIRED_HF_FIRST_PROOF_APPS = (
    "flight_telemetry_project",
    "pytorch_playground_project",
    "weather_forecast_project",
)
REQUIRED_HF_FIRST_PROOF_PAGES = ("view_forecast_analysis", "view_maps", "view_release_decision")
FORBIDDEN_HF_FIRST_PROOF_APPS = ("flight_project", "weather_forecast_legacy_project")
REQUIRED_PYTORCH_ANALYSIS_SCENARIO = "isolated-pytorch-playground-analysis"
REQUIRED_RELEASE_EVIDENCE_SCENARIO = "isolated-release-evidence"
REQUIRED_ORCHESTRATE_POOL_SCENARIO = "isolated-orchestrate-pool-parameters"
REQUIRED_ORCHESTRATE_POOL_TEXT = ("Pool parameters", "Max workers", "Item timeout seconds", "Pool executor")
REQUIRED_EXECUTION_PANDAS_POOL_SCENARIO = "isolated-execution-pandas-orchestrate-pool-executor"
REQUIRED_EXECUTION_PANDAS_POOL_APP = "execution_pandas_project"
REQUIRED_EXECUTION_PANDAS_POOL_TEXT = ("Pool executor", "Auto (ORCHESTRATE setting)")
REQUIRED_PYTORCH_ANALYSIS_APP = "pytorch_playground_project"
REQUIRED_PYTORCH_ANALYSIS_TEXT = ("PyTorch Playground", "Refresh evidence", "Synced RUN snippet", "Settings")
REQUIRED_PYTORCH_ANALYSIS_FORBIDDEN_SIDEBAR_TEXT = ("Project:",)
REQUIRED_PYTORCH_ANALYSIS_LINKS = ("PyTorch Playground=>current_page=app_ui",)
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
    "hf-first-proof-view-maps-visual-smoke": {
        "apps_pages": ("view_maps",),
        "flags": ("success_screenshot", "above_fold_check", "browser_error_check"),
    },
    "hf-first-proof-install": {
        "pages": ("ORCHESTRATE",),
        "actions": ("Deploy workers",),
    },
}
REQUIRED_HF_VISUAL_SMOKE_ROBOT_SCENARIOS = (
    "hf-first-proof-visual-smoke",
    "hf-first-proof-app-pages-visual-smoke",
    "hf-first-proof-view-maps-visual-smoke",
)
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

# Apps-pages whose content is asserted in the browser by a robot scenario. ``app_ui`` is
# reached through the PyTorch analysis required-links contract; the rest are the HF first-proof
# pages swept with seeded demo artifacts.
BROWSER_ASSERTED_APPS_PAGES = REQUIRED_HF_FIRST_PROOF_PAGES + ("app_ui",)

# The remaining public apps-pages render their meaningful content only after data-dependent
# ``st.stop()`` guards pass, so the generic widget robot (which does not seed every view's
# artifacts) deliberately performs render + Streamlit-exception checks only. Each entry names the
# focused test that asserts the view's content against seeded fixtures. ``evaluate_contract``
# enforces that every public view is either browser-asserted or listed here with a test that
# exists, so a new view cannot ship with zero coverage and a dropped focused test is caught.
APPS_PAGE_RENDER_ONLY_DISPOSITIONS: dict[str, tuple[str, str]] = {
    "autoencoder_latentspace": (
        "latent-space plots render only with a trained autoencoder artifact",
        "test/test_autoencoder_latentspace.py",
    ),
    "view_barycentric": (
        "barycentric projection renders only with seeded routing artifacts",
        "test/test_view_barycentric.py",
    ),
    "view_data_io_decision": (
        "decision panels render only after the artifact directory and pipeline exist",
        "test/test_view_data_io_decision.py",
    ),
    "view_inference_analysis": (
        "diagnostics render only when an active project and inference runs are passed in",
        "test/test_view_inference_analysis.py",
    ),
    "view_live_artifacts": (
        "manifest candidates render only when live artifacts are present",
        "test/test_view_live_artifacts.py",
    ),
    "view_maps_3d": (
        "3D map renders only with seeded geospatial artifacts",
        "test/test_view_maps_3d.py",
    ),
    "view_maps_network": (
        "network topology renders only after seeded relay artifacts pass the data guards",
        "test/test_view_maps_network.py",
    ),
    "view_queue_resilience": (
        "queue occupancy plots render only after the artifact directory guards pass",
        "test/test_view_queue_resilience.py",
    ),
    "view_relay_resilience": (
        "run comparison renders only after seeded relay artifacts pass the data guards",
        "test/test_view_relay_resilience.py",
    ),
    "view_routing_model_comparison": (
        "model summary renders only with seeded routing comparison artifacts",
        "test/test_view_routing_model_comparison.py",
    ),
    "view_scenario_cockpit": (
        "scenario comparison renders only after the artifact directory guards pass",
        "test/test_view_scenario_cockpit.py",
    ),
    "view_shap_explanation": (
        "feature attributions render only with a seeded SHAP explanation artifact",
        "test/test_view_shap_explanation.py",
    ),
    "view_training_analysis": (
        "scalar/training plots render only with seeded training-run artifacts",
        "test/test_view_training_analysis.py",
    ),
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


def apps_page_coverage_issues(public_views: Sequence[str]) -> list[CoverageIssue]:
    """Every public apps-page must be browser-asserted or carry a render-only disposition whose
    focused test exists; stale dispositions for removed views are also flagged."""
    issues: list[CoverageIssue] = []
    classified = set(BROWSER_ASSERTED_APPS_PAGES) | set(APPS_PAGE_RENDER_ONLY_DISPOSITIONS)
    for view in sorted(set(public_views)):
        if view in BROWSER_ASSERTED_APPS_PAGES:
            continue
        disposition = APPS_PAGE_RENDER_ONLY_DISPOSITIONS.get(view)
        if disposition is None:
            issues.append(
                CoverageIssue(
                    "apps_page_coverage",
                    f"{view} is neither browser-asserted nor given a render-only disposition with a focused test",
                )
            )
            continue
        reason, focused_test = disposition
        if not reason.strip():
            issues.append(
                CoverageIssue("apps_page_coverage", f"{view} render-only disposition needs a non-empty reason")
            )
        focused_path = Path(focused_test)
        if not focused_path.is_absolute():
            focused_path = REPO_ROOT / focused_path
        if not focused_path.is_file():
            issues.append(
                CoverageIssue(
                    "apps_page_coverage",
                    f"{view} render-only disposition references a focused test that does not exist: {focused_test}",
                )
            )
    stale = sorted(classified - set(public_views))
    if stale:
        issues.append(
            CoverageIssue(
                "apps_page_coverage",
                "apps-page dispositions reference views that no longer exist: " + ", ".join(stale),
            )
        )
    return issues


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

    public_apps_pages = sorted({route.name for route in widget_robot.public_apps_pages()})
    issues.extend(apps_page_coverage_issues(public_apps_pages))

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
    hf_visual_smoke_required_scenarios = set(REQUIRED_HF_VISUAL_SMOKE_ROBOT_SCENARIOS)
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
    for scenario_name in REQUIRED_HF_VISUAL_SMOKE_ROBOT_SCENARIOS:
        if scenario_name not in hf_visual_smoke_profile_scenarios:
            issues.append(
                CoverageIssue(
                    "hf_robot_profile",
                    f"hf-visual-smoke-robot does not run {scenario_name}",
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
    if REQUIRED_RELEASE_EVIDENCE_SCENARIO not in ui_robot_matrix_profile_scenarios:
        issues.append(
            CoverageIssue(
                "release_evidence_robot",
                f"ui-robot-matrix profile does not run {REQUIRED_RELEASE_EVIDENCE_SCENARIO}",
            )
        )
    if REQUIRED_EXECUTION_PANDAS_POOL_SCENARIO not in ui_robot_matrix_profile_scenarios:
        issues.append(
            CoverageIssue(
                "execution_pandas_pool_robot",
                f"ui-robot-matrix profile does not run {REQUIRED_EXECUTION_PANDAS_POOL_SCENARIO}",
            )
        )

    orchestrate_pool: dict[str, list[str]] = {}
    orchestrate_pool_scenario = scenario_by_name.get(REQUIRED_ORCHESTRATE_POOL_SCENARIO)
    if orchestrate_pool_scenario is None:
        issues.append(
            CoverageIssue(
                "orchestrate_pool_robot",
                f"{REQUIRED_ORCHESTRATE_POOL_SCENARIO} is missing from the robot matrix",
            )
        )
    else:
        pages = sorted(_scenario_pages(widget_robot, orchestrate_pool_scenario))
        required_text = sorted(_scenario_required_text(widget_robot, orchestrate_pool_scenario))
        flags = sorted(_scenario_flags(orchestrate_pool_scenario))
        orchestrate_pool = {
            "pages": pages,
            "required_text": required_text,
            "flags": flags,
        }
        if "ORCHESTRATE" not in pages:
            issues.append(
                CoverageIssue(
                    "orchestrate_pool_robot",
                    f"{REQUIRED_ORCHESTRATE_POOL_SCENARIO} does not cover ORCHESTRATE",
                )
            )
        missing_text = sorted(set(REQUIRED_ORCHESTRATE_POOL_TEXT) - set(required_text))
        if missing_text:
            issues.append(
                CoverageIssue(
                    "orchestrate_pool_robot",
                    f"{REQUIRED_ORCHESTRATE_POOL_SCENARIO} is missing required text probes: "
                    + ", ".join(missing_text),
                )
            )

    execution_pandas_pool: dict[str, list[str]] = {}
    execution_pandas_pool_scenario = scenario_by_name.get(REQUIRED_EXECUTION_PANDAS_POOL_SCENARIO)
    if execution_pandas_pool_scenario is None:
        issues.append(
            CoverageIssue(
                "execution_pandas_pool_robot",
                f"{REQUIRED_EXECUTION_PANDAS_POOL_SCENARIO} is missing from the robot matrix",
            )
        )
    else:
        pages = sorted(_scenario_pages(widget_robot, execution_pandas_pool_scenario))
        apps = sorted(_scenario_apps(widget_robot, execution_pandas_pool_scenario))
        required_text = sorted(_scenario_required_text(widget_robot, execution_pandas_pool_scenario))
        flags = sorted(_scenario_flags(execution_pandas_pool_scenario))
        execution_pandas_pool = {
            "apps": apps,
            "pages": pages,
            "required_text": required_text,
            "flags": flags,
        }
        if REQUIRED_EXECUTION_PANDAS_POOL_APP not in apps:
            issues.append(
                CoverageIssue(
                    "execution_pandas_pool_robot",
                    f"{REQUIRED_EXECUTION_PANDAS_POOL_SCENARIO} does not target "
                    f"{REQUIRED_EXECUTION_PANDAS_POOL_APP}",
                )
            )
        if "ORCHESTRATE" not in pages:
            issues.append(
                CoverageIssue(
                    "execution_pandas_pool_robot",
                    f"{REQUIRED_EXECUTION_PANDAS_POOL_SCENARIO} does not cover ORCHESTRATE",
                )
            )
        missing_text = sorted(set(REQUIRED_EXECUTION_PANDAS_POOL_TEXT) - set(required_text))
        if missing_text:
            issues.append(
                CoverageIssue(
                    "execution_pandas_pool_robot",
                    f"{REQUIRED_EXECUTION_PANDAS_POOL_SCENARIO} is missing required text probes: "
                    + ", ".join(missing_text),
                )
            )
        if "browser_error_check" not in flags:
            issues.append(
                CoverageIssue(
                    "execution_pandas_pool_robot",
                    f"{REQUIRED_EXECUTION_PANDAS_POOL_SCENARIO} does not enable browser_error_check",
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
            "orchestrate_pool_robot": orchestrate_pool,
            "execution_pandas_pool_robot": execution_pandas_pool,
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
