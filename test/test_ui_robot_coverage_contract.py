from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_PATH = Path("tools/ui_robot_coverage_contract.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("ui_robot_coverage_contract_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_ui_robot_coverage_contract_passes_for_current_matrix() -> None:
    module = _load_module()

    payload = module.evaluate_contract()

    assert payload["schema"] == module.SCHEMA
    assert payload["success"] is True
    assert payload["issues"] == []
    for page in module.REQUIRED_CORE_PAGES:
        assert payload["coverage"]["core_pages"][page]
    for action in module.REQUIRED_HIGH_RISK_ACTIONS:
        assert payload["coverage"]["high_risk_actions"][action]
    assert payload["coverage"]["configured_apps_pages_scenarios"] == ["isolated-entry-and-app-pages"]
    assert payload["coverage"]["public_demo_contract"]["ui_apps"] == [
        "flight_telemetry_project",
        "weather_forecast_project",
        "mission_decision_project",
        "execution_pandas_project",
        "execution_polars_project",
        "uav_queue_project",
        "uav_relay_queue_project",
    ]
    assert payload["coverage"]["public_demo_contract"]["ui_apps_covered_by"] == "ui-robot-matrix --apps all"
    assert payload["coverage"]["public_demo_contract"]["apps_pages"] == [
        "view_maps",
        "view_forecast_analysis",
        "view_release_decision",
        "view_data_io_decision",
        "view_scenario_cockpit",
        "view_queue_resilience",
        "view_relay_resilience",
        "view_maps_network",
    ]
    public_proof_scenarios = module._load_module(
        "public_proof_scenarios_current_contract_test",
        module.PUBLIC_PROOF_SCENARIOS_PATH,
    )
    proof_scenario_ids = payload["coverage"]["public_demo_contract"]["proof_scenarios"]
    assert proof_scenario_ids == [str(scenario["id"]) for scenario in public_proof_scenarios.SCENARIOS]
    assert set(module.REQUIRED_DEMO_PROOF_SCENARIOS).issubset(proof_scenario_ids)
    assert payload["coverage"]["hf_first_proof_apps"] == [
        "flight_telemetry_project",
        "pytorch_playground_project",
        "weather_forecast_project",
    ]
    assert payload["coverage"]["hf_install_profile_apps"] == [
        "flight_telemetry_project",
        "pytorch_playground_project",
        "weather_forecast_project",
    ]
    assert payload["coverage"]["hf_install_profile_scenarios"] == ["hf-first-proof-install"]
    assert payload["coverage"]["hf_first_proof_pages"] == [
        "view_forecast_analysis",
        "view_maps",
        "view_release_decision",
    ]
    assert payload["coverage"]["hf_visual_smoke_profile_apps"] == [
        "flight_telemetry_project",
        "pytorch_playground_project",
        "weather_forecast_project",
    ]
    assert payload["coverage"]["hf_install_profile_apps"] == [
        "flight_telemetry_project",
        "pytorch_playground_project",
        "weather_forecast_project",
    ]
    assert payload["coverage"]["hf_install_profile_scenarios"] == ["hf-first-proof-install"]
    assert payload["coverage"]["hf_visual_smoke_profile_scenarios"] == [
        "hf-first-proof-app-pages-visual-smoke",
        "hf-first-proof-visual-smoke",
    ]
    assert "isolated-pytorch-playground-analysis" in payload["coverage"]["ui_robot_matrix_profile_scenarios"]
    assert payload["coverage"]["pytorch_analysis_robot"] == {
        "apps": ["pytorch_playground_project"],
        "flags": ["browser_error_check"],
        "pages": ["ANALYSIS"],
        "required_actions": ["Refresh evidence"],
        "required_text": ["PyTorch Playground", "Refresh evidence", "Settings", "Synced RUN snippet"],
    }
    assert payload["coverage"]["hf_robot_scenarios"]["hf-first-proof-visual-smoke"] == {
        "actions": [],
        "apps_pages": [],
        "flags": ["above_fold_check", "browser_error_check", "success_screenshot"],
        "pages": ["ANALYSIS", "HOME", "ORCHESTRATE", "PROJECT", "WORKFLOW"],
    }
    assert payload["coverage"]["hf_robot_scenarios"]["hf-first-proof-app-pages-visual-smoke"] == {
        "actions": [],
        "apps_pages": ["view_forecast_analysis", "view_maps", "view_release_decision"],
        "flags": ["above_fold_check", "browser_error_check", "success_screenshot"],
        "pages": [],
    }
    assert payload["coverage"]["hf_robot_scenarios"]["hf-first-proof-install"] == {
        "actions": ["install"],
        "apps_pages": [],
        "flags": [],
        "pages": ["ORCHESTRATE"],
    }


def test_ui_robot_coverage_contract_json_cli(capsys) -> None:
    module = _load_module()

    exit_code = module.main(["--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    assert payload["schema"] == module.SCHEMA
    assert payload["coverage"]["hf_robot_scenarios"]


def test_ui_robot_coverage_contract_accepts_explicit_full_app_profile(monkeypatch) -> None:
    module = _load_module()

    def scenario(
        name: str,
        *,
        pages: str = "",
        apps: str = "",
        apps_pages: str = "none",
        click_action_labels: str = "",
        required_text: str = "",
        required_action_labels: str = "",
        success_screenshot: bool = False,
        above_fold_check: bool = False,
        browser_error_check: bool = False,
    ):
        return SimpleNamespace(
            name=name,
            pages=pages,
            apps=apps,
            apps_pages=apps_pages,
            click_action_labels=click_action_labels,
            required_text=required_text,
            required_action_labels=required_action_labels,
            success_screenshot=success_screenshot,
            above_fold_check=above_fold_check,
            browser_error_check=browser_error_check,
        )

    core_scenario = scenario(
        "core-selected-actions",
        pages=",".join(module.REQUIRED_CORE_PAGES),
        apps_pages="configured",
        click_action_labels=",".join(module.REQUIRED_HIGH_RISK_ACTIONS),
    )
    hf_visual = scenario(
        "hf-first-proof-visual-smoke",
        pages="HOME,PROJECT,ORCHESTRATE,WORKFLOW,ANALYSIS",
        success_screenshot=True,
        above_fold_check=True,
        browser_error_check=True,
    )
    hf_app_pages = scenario(
        "hf-first-proof-app-pages-visual-smoke",
        apps_pages=",".join(module.REQUIRED_HF_FIRST_PROOF_PAGES),
        success_screenshot=True,
        above_fold_check=True,
        browser_error_check=True,
    )
    hf_install = scenario(
        "hf-first-proof-install",
        pages="ORCHESTRATE",
        click_action_labels="INSTALL",
    )
    pytorch = scenario(
        "isolated-pytorch-playground-analysis",
        pages="ANALYSIS",
        apps=module.REQUIRED_PYTORCH_ANALYSIS_APP,
        required_text=",".join(module.REQUIRED_PYTORCH_ANALYSIS_TEXT),
        required_action_labels=",".join(module.REQUIRED_PYTORCH_ANALYSIS_ACTIONS),
        browser_error_check=True,
    )
    all_scenarios = {
        item.name: item
        for item in (core_scenario, hf_visual, hf_app_pages, hf_install, pytorch)
    }
    widget_robot = SimpleNamespace(
        page_label=lambda page: str(page),
        resolve_pages=lambda pages: [part.strip() for part in str(pages).split(",") if part.strip()],
        parse_csv=lambda value: [part.strip() for part in str(value).split(",") if part.strip()],
        _normalized_label=lambda value: str(value).strip().lower(),
        public_builtin_apps=lambda: [SimpleNamespace(name=name) for name in module.REQUIRED_DEMO_UI_APPS],
        configured_apps_pages_for_app=lambda _app: [
            SimpleNamespace(name=name) for name in module.REQUIRED_DEMO_UI_PAGES
        ],
    )
    matrix = SimpleNamespace(
        DEFAULT_SCENARIOS={"core-selected-actions": core_scenario},
        ALL_SCENARIOS=all_scenarios,
        OPT_IN_SCENARIOS={"isolated-pytorch-playground-analysis": pytorch},
    )
    hf_smoke = SimpleNamespace(
        profile_builtin_app_entries=lambda _profile: set(module.REQUIRED_HF_FIRST_PROOF_APPS),
        profile_page_entries=lambda _profile: set(module.REQUIRED_HF_FIRST_PROOF_PAGES),
    )
    workflow_parity = SimpleNamespace(
        _profile_commands=lambda _args: {
            "hf-visual-smoke-robot": [
                SimpleNamespace(
                    argv=[
                        "--scenario",
                        "hf-first-proof-visual-smoke",
                        "--scenario",
                        "hf-first-proof-app-pages-visual-smoke",
                        "--apps",
                        ",".join(module.REQUIRED_HF_FIRST_PROOF_APPS),
                    ]
                )
            ],
            "hf-install-robot": [
                SimpleNamespace(
                    argv=[
                        "--scenario",
                        "hf-first-proof-install",
                        "--apps",
                        ",".join(module.REQUIRED_HF_FIRST_PROOF_APPS),
                    ]
                )
            ],
            "ui-robot-matrix": [
                SimpleNamespace(
                    argv=[
                        "--scenario",
                        "isolated-pytorch-playground-analysis",
                        "--apps",
                        ",".join(module.REQUIRED_DEMO_UI_APPS),
                    ]
                )
            ],
        }
    )
    public_proof_scenarios = SimpleNamespace(
        SCENARIOS=tuple({"id": scenario_id} for scenario_id in module.REQUIRED_DEMO_PROOF_SCENARIOS)
    )

    def fake_load_module(_name, path):
        if path == module.WIDGET_ROBOT_PATH:
            return widget_robot
        if path == module.MATRIX_PATH:
            return matrix
        if path == module.HF_SMOKE_PATH:
            return hf_smoke
        if path == module.WORKFLOW_PARITY_PATH:
            return workflow_parity
        if path == module.PUBLIC_PROOF_SCENARIOS_PATH:
            return public_proof_scenarios
        raise AssertionError(f"unexpected module path: {path}")

    monkeypatch.setattr(module, "_load_module", fake_load_module)

    payload = module.evaluate_contract()

    assert payload["success"] is True
    assert payload["issues"] == []
    assert payload["coverage"]["public_demo_contract"]["ui_apps_covered_by"] == "ui-robot-matrix explicit --apps"
    assert payload["coverage"]["ui_robot_matrix_profile_apps"] == sorted(module.REQUIRED_DEMO_UI_APPS)


def test_ui_robot_coverage_contract_load_module_rejects_missing_spec(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module.importlib.util, "spec_from_file_location", lambda _name, _path: None)

    with pytest.raises(RuntimeError, match="Could not load"):
        module._load_module("missing", Path("missing.py"))


def test_ui_robot_coverage_contract_argv_value_handles_missing_values() -> None:
    module = _load_module()

    assert module._argv_value([], "--apps") == ""
    assert module._argv_value(["--apps"], "--apps") == ""


def test_ui_robot_coverage_contract_reports_hf_first_proof_gaps(monkeypatch) -> None:
    module = _load_module()
    core_scenario = SimpleNamespace(
        name="core-selected-actions",
        pages="HOME,PROJECT,ORCHESTRATE,WORKFLOW,ANALYSIS,SETTINGS",
        apps_pages="none",
        click_action_labels="INSTALL,CHECK distribute,Run -> Load -> Export",
    )
    incomplete_hf_visual = SimpleNamespace(
        name="hf-first-proof-visual-smoke",
        pages="HOME",
        apps_pages="none",
        click_action_labels="",
        success_screenshot=False,
        above_fold_check=False,
        browser_error_check=False,
    )
    widget_robot = SimpleNamespace(
        page_label=lambda page: str(page),
        resolve_pages=lambda pages: [page.strip() for page in str(pages).split(",") if page.strip()],
        parse_csv=lambda value: [part.strip() for part in str(value).split(",") if part.strip()],
        _normalized_label=lambda value: str(value).strip().lower(),
        public_builtin_apps=lambda: [SimpleNamespace(name="flight_telemetry_project")],
        configured_apps_pages_for_app=lambda _app: [],
    )
    matrix = SimpleNamespace(
        DEFAULT_SCENARIOS={"core-selected-actions": core_scenario},
        ALL_SCENARIOS={
            "core-selected-actions": core_scenario,
            "hf-first-proof-visual-smoke": incomplete_hf_visual,
        },
        OPT_IN_SCENARIOS={"hf-first-proof-visual-smoke": incomplete_hf_visual},
    )
    hf_smoke = SimpleNamespace(
        profile_builtin_app_entries=lambda _profile: {"flight_project"},
        profile_page_entries=lambda _profile: {"view_maps"},
    )
    workflow_parity = SimpleNamespace(
        _profile_commands=lambda _args: {
            "ui-robot-matrix": [SimpleNamespace(argv=["--scenario", "legacy-ui-matrix"])],
            "hf-install-robot": [SimpleNamespace(argv=["--scenario", "legacy-hf-install"])],
            "hf-visual-smoke-robot": [SimpleNamespace(argv=["--scenario", "legacy-hf-smoke"])],
        }
    )
    public_proof_scenarios = SimpleNamespace(SCENARIOS=({"id": "legacy-proof"},))

    def fake_load_module(_name, path):
        if path == module.WIDGET_ROBOT_PATH:
            return widget_robot
        if path == module.MATRIX_PATH:
            return matrix
        if path == module.HF_SMOKE_PATH:
            return hf_smoke
        if path == module.WORKFLOW_PARITY_PATH:
            return workflow_parity
        if path == module.PUBLIC_PROOF_SCENARIOS_PATH:
            return public_proof_scenarios
        raise AssertionError(f"unexpected module path: {path}")

    monkeypatch.setattr(module, "_load_module", fake_load_module)

    payload = module.evaluate_contract()

    assert payload["success"] is False
    details = [issue["detail"] for issue in payload["issues"]]
    assert (
        "first-proof HF profile is missing public demo apps: "
        "flight_telemetry_project, pytorch_playground_project, weather_forecast_project"
    ) in details
    assert "first-proof HF profile still exposes stale demo apps: flight_project" in details
    assert (
        "first-proof HF profile is missing public demo pages: "
        "view_forecast_analysis, view_release_decision"
    ) in details
    assert "hf-visual-smoke-robot does not run hf-first-proof-visual-smoke" in details
    assert "hf-visual-smoke-robot does not run hf-first-proof-app-pages-visual-smoke" in details
    assert "hf-visual-smoke-robot is missing first-proof apps: flight_project" in details
    assert "hf-install-robot does not run hf-first-proof-install" in details
    assert "hf-install-robot is missing first-proof apps: flight_project" in details
    assert any(
        detail.startswith("hf-first-proof-visual-smoke is missing required pages:")
        and "ANALYSIS" in detail
        and "WORKFLOW" in detail
        for detail in details
    )
    assert any(
        detail.startswith("hf-first-proof-visual-smoke is missing required flags:")
        and "above_fold_check" in detail
        and "browser_error_check" in detail
        and "success_screenshot" in detail
        for detail in details
    )
    assert "hf-first-proof-app-pages-visual-smoke is missing from the robot matrix" in details
    assert "hf-first-proof-install is missing from the robot matrix" in details
    assert "isolated-pytorch-playground-analysis is missing from the robot matrix" in details
    assert "ui-robot-matrix profile does not run isolated-pytorch-playground-analysis" in details
    assert any(
        detail.startswith("ui-robot-matrix profile is missing documented demo apps:")
        and "flight_telemetry_project" in detail
        and "uav_relay_queue_project" in detail
        for detail in details
    )
    assert any(
        detail.startswith("documented demo apps-pages are not configured on any built-in app:")
        and "view_forecast_analysis" in detail
        and "view_maps_network" in detail
        for detail in details
    )
    assert any(
        detail.startswith("public proof scenarios are missing documented demo routes:")
        and "flight-local-first-proof" in detail
        and "train-then-serve-proof" in detail
        for detail in details
    )


def test_ui_robot_coverage_contract_reports_empty_public_app_inventory(monkeypatch) -> None:
    module = _load_module()
    widget_robot = SimpleNamespace(
        page_label=lambda page: str(page),
        resolve_pages=lambda pages: [],
        parse_csv=lambda value: [],
        _normalized_label=lambda value: str(value).strip().lower(),
        public_builtin_apps=lambda: [],
        configured_apps_pages_for_app=lambda _app: [],
    )
    matrix = SimpleNamespace(DEFAULT_SCENARIOS={}, ALL_SCENARIOS={}, OPT_IN_SCENARIOS={})
    hf_smoke = SimpleNamespace(
        profile_builtin_app_entries=lambda _profile: set(module.REQUIRED_HF_FIRST_PROOF_APPS),
        profile_page_entries=lambda _profile: set(module.REQUIRED_HF_FIRST_PROOF_PAGES),
    )
    workflow_parity = SimpleNamespace(_profile_commands=lambda _args: {})
    public_proof_scenarios = SimpleNamespace(
        SCENARIOS=({"id": scenario_id} for scenario_id in module.REQUIRED_DEMO_PROOF_SCENARIOS)
    )

    def fake_load_module(_name, path):
        if path == module.WIDGET_ROBOT_PATH:
            return widget_robot
        if path == module.MATRIX_PATH:
            return matrix
        if path == module.HF_SMOKE_PATH:
            return hf_smoke
        if path == module.WORKFLOW_PARITY_PATH:
            return workflow_parity
        if path == module.PUBLIC_PROOF_SCENARIOS_PATH:
            return public_proof_scenarios
        raise AssertionError(f"unexpected module path: {path}")

    monkeypatch.setattr(module, "_load_module", fake_load_module)

    payload = module.evaluate_contract()

    assert payload["success"] is False
    assert {"kind": "built_in_apps", "detail": "no public built-in apps were discovered"} in payload["issues"]


def test_ui_robot_coverage_contract_reports_missing_public_demo_wording(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    demo_doc = tmp_path / "demos.rst"
    demo_doc.write_text("Public demos\n============\n", encoding="utf-8")
    monkeypatch.setattr(module, "DEMOS_DOC_PATH", demo_doc)

    payload = module.evaluate_contract()

    assert payload["success"] is False
    assert any(
        issue["kind"] == "public_demo_docs"
        and "demos page is missing robot/proof coverage wording" in issue["detail"]
        for issue in payload["issues"]
    )


def test_ui_robot_coverage_contract_reports_matrix_and_pytorch_gaps(monkeypatch, capsys) -> None:
    module = _load_module()
    app = SimpleNamespace(name="demo_project")
    route = SimpleNamespace(name="view_demo")
    broken_hf_visual = SimpleNamespace(
        name="hf-first-proof-visual-smoke",
        pages="HOME,PROJECT,UNKNOWN",
        apps="",
        apps_pages="none",
        click_action_labels="",
        required_text="",
        required_action_labels="",
        success_screenshot=False,
        above_fold_check=False,
        browser_error_check=False,
    )
    broken_hf_app_pages = SimpleNamespace(
        name="hf-first-proof-app-pages-visual-smoke",
        pages="",
        apps="",
        apps_pages="view_maps",
        click_action_labels="",
        required_text="",
        required_action_labels="",
        success_screenshot=False,
        above_fold_check=False,
        browser_error_check=False,
    )
    broken_hf_install = SimpleNamespace(
        name="hf-first-proof-install",
        pages="ORCHESTRATE",
        apps="",
        apps_pages="none",
        click_action_labels="",
        required_text="",
        required_action_labels="",
        success_screenshot=False,
        above_fold_check=False,
        browser_error_check=False,
    )
    broken_pytorch = SimpleNamespace(
        name="isolated-pytorch-playground-analysis",
        pages="HOME",
        apps="other_project",
        apps_pages="none",
        click_action_labels="",
        required_text="PyTorch Playground",
        required_action_labels="",
        success_screenshot=False,
        above_fold_check=False,
        browser_error_check=False,
    )
    widget_robot = SimpleNamespace(
        page_label=lambda page: str(page),
        resolve_pages=lambda pages: [page.strip() for page in str(pages).split(",") if page.strip()],
        parse_csv=lambda value: [part.strip() for part in str(value).split(",") if part.strip()],
        _normalized_label=lambda value: str(value).strip().lower(),
        public_builtin_apps=lambda: [app],
        configured_apps_pages_for_app=lambda _app: [route],
    )
    matrix = SimpleNamespace(
        DEFAULT_SCENARIOS={},
        ALL_SCENARIOS={
            scenario.name: scenario
            for scenario in (broken_hf_visual, broken_hf_app_pages, broken_hf_install, broken_pytorch)
        },
        OPT_IN_SCENARIOS={"isolated-pytorch-playground-analysis": broken_pytorch},
    )
    hf_smoke = SimpleNamespace(
        profile_builtin_app_entries=lambda _profile: set(module.REQUIRED_HF_FIRST_PROOF_APPS),
        profile_page_entries=lambda _profile: set(module.REQUIRED_HF_FIRST_PROOF_PAGES),
    )
    workflow_parity = SimpleNamespace(
        _profile_commands=lambda _args: {
            "hf-visual-smoke-robot": [
                SimpleNamespace(
                    argv=["--scenario", "hf-first-proof-visual-smoke", "--apps", "flight_telemetry_project"]
                )
            ],
            "hf-install-robot": [
                SimpleNamespace(argv=["--scenario", "hf-first-proof-install", "--apps", "flight_telemetry_project"])
            ],
            "ui-robot-matrix": [SimpleNamespace(argv=["--scenario", "other"])],
        }
    )
    public_proof_scenarios = SimpleNamespace(SCENARIOS=({"id": "legacy-proof"},))

    def fake_load_module(_name, path):
        if path == module.WIDGET_ROBOT_PATH:
            return widget_robot
        if path == module.MATRIX_PATH:
            return matrix
        if path == module.HF_SMOKE_PATH:
            return hf_smoke
        if path == module.WORKFLOW_PARITY_PATH:
            return workflow_parity
        if path == module.PUBLIC_PROOF_SCENARIOS_PATH:
            return public_proof_scenarios
        raise AssertionError(f"unexpected module path: {path}")

    monkeypatch.setattr(module, "_load_module", fake_load_module)

    payload = module.evaluate_contract()
    rendered = module.render_human(payload)
    monkeypatch.setattr(module, "evaluate_contract", lambda: payload)
    exit_code = module.main([])

    details = [issue["detail"] for issue in payload["issues"]]
    assert exit_code == 1
    assert "verdict: FAIL" in capsys.readouterr().out
    assert "- core_page:" in rendered
    assert any("apps declare configured apps-pages" in detail for detail in details)
    assert "default robot matrix has no scenarios for --apps all" in details
    assert "'INSTALL' is not covered by a selected-action scenario" in details
    assert "hf-first-proof-install is missing required actions: install" in details
    assert (
        "hf-first-proof-app-pages-visual-smoke is missing required apps-pages: "
        "view_forecast_analysis, view_release_decision"
    ) in details
    assert "isolated-pytorch-playground-analysis does not cover ANALYSIS" in details
    assert "isolated-pytorch-playground-analysis does not target pytorch_playground_project" in details
    assert (
        "isolated-pytorch-playground-analysis is missing required text probes: "
        "Refresh evidence, Settings, Synced RUN snippet"
    ) in details
    assert "isolated-pytorch-playground-analysis is missing required action probes: Refresh evidence" in details
    assert "isolated-pytorch-playground-analysis does not enable browser_error_check" in details
    assert "ui-robot-matrix profile does not run isolated-pytorch-playground-analysis" in details
    assert any(
        detail.startswith("public proof scenarios are missing documented demo routes:")
        and "notebook-migration-proof" in detail
        for detail in details
    )
