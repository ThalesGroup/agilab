from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path("src/agilab/first_proof_wizard.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("first_proof_wizard_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_first_proof_content_exposes_one_actionable_validated_route() -> None:
    module = _load_module()

    content = module.newcomer_first_proof_content()

    assert content["recommended_path_id"] == "source-checkout-first-proof"
    assert content["recommended_path_label"] == "Source checkout first proof"
    assert content["actionable_route_ids"] == ["source-checkout-first-proof"]
    assert content["documented_route_ids"] == ["notebook-quickstart", "published-package-route"]
    assert content["compatibility_status"] == "validated"
    assert content["compatibility_report_status"] == "pass"
    assert content["proof_command_labels"] == ["preinit smoke", "source ui smoke"]
    assert [label for label, _ in content["steps"]] == ["PROJECT", "ORCHESTRATE", "ANALYSIS"]
    assert "tools/newcomer_first_proof.py --json" in content["cli_command"]


def test_first_proof_tool_contract_uses_newcomer_smoke_defaults() -> None:
    module = _load_module()

    contract = module.first_proof_tool_contract()

    assert contract.active_app.name == "flight_project"
    assert contract.command_labels == ("preinit smoke", "source ui smoke")
    assert contract.target_seconds == 600.0
    assert contract.source == "tools/newcomer_first_proof.py"


def test_first_proof_state_routes_only_to_flight_project(tmp_path: Path) -> None:
    module = _load_module()
    apps_path = tmp_path / "apps"
    flight_project = apps_path / "builtin" / "flight_project"
    flight_project.mkdir(parents=True)

    env = SimpleNamespace(
        apps_path=apps_path,
        app="notebook-quickstart",
        AGILAB_LOG_ABS=tmp_path / "log",
    )

    state = module.newcomer_first_proof_state(env)

    assert state["project_path"] == flight_project.resolve()
    assert state["current_app_matches"] is False
    assert state["recommended_path_id"] == "source-checkout-first-proof"
    assert state["actionable_route_ids"] == ["source-checkout-first-proof"]
    assert state["documented_route_ids"] == ["notebook-quickstart", "published-package-route"]
    assert state["next_step"] == "Go to `PROJECT`. Choose `flight_project`."


def test_first_proof_state_detects_completion_outputs(tmp_path: Path) -> None:
    module = _load_module()
    apps_path = tmp_path / "apps"
    flight_project = apps_path / "flight_project"
    flight_project.mkdir(parents=True)
    output_dir = tmp_path / "log" / "execute" / "flight"
    output_dir.mkdir(parents=True)
    (output_dir / "AGI_install_flight.py").write_text("# helper", encoding="utf-8")
    (output_dir / "AGI_run_flight.py").write_text("# helper", encoding="utf-8")
    (output_dir / "trajectory_summary.json").write_text("{}", encoding="utf-8")

    env = SimpleNamespace(
        apps_path=apps_path,
        app=str(flight_project),
        AGILAB_LOG_ABS=tmp_path / "log",
    )

    state = module.newcomer_first_proof_state(env)

    assert state["current_app_matches"] is True
    assert state["helper_scripts_present"] is True
    assert state["run_output_detected"] is True
    assert [path.name for path in state["visible_outputs"]] == ["trajectory_summary.json"]
    assert state["next_step"] == "First proof done. Now you can try another demo."
