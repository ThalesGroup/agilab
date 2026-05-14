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

    assert content["title"] == "Start here: run flight_telemetry_project first"
    assert "built-in flight demo locally" in content["intro"]
    assert content["recommended_path_id"] == "source-checkout-first-proof"
    assert content["recommended_path_label"] == "Source checkout first proof"
    assert content["actionable_route_ids"] == ["source-checkout-first-proof"]
    assert content["documented_route_ids"] == ["notebook-quickstart"]
    assert content["compatibility_status"] == "validated"
    assert content["compatibility_report_status"] == "pass"
    assert content["proof_command_labels"] == ["preinit smoke", "source ui smoke"]
    assert content["run_manifest_filename"] == "run_manifest.json"
    assert [label for label, _ in content["steps"]] == ["PROJECT", "ORCHESTRATE", "ANALYSIS"]
    assert any("cluster, benchmark, and service options off" in detail for _, detail in content["steps"])
    assert "tools/newcomer_first_proof.py --json" in content["cli_command"]
    assert any("run_manifest.json" in item for item in content["success_criteria"])


def test_first_proof_tool_contract_uses_newcomer_smoke_defaults() -> None:
    module = _load_module()

    contract = module.first_proof_tool_contract()

    assert contract.active_app.name == "flight_telemetry_project"
    assert contract.command_labels == ("preinit smoke", "source ui smoke")
    assert contract.target_seconds == 600.0
    assert contract.source == "tools/newcomer_first_proof.py"


def test_first_proof_state_routes_only_to_flight_telemetry_project(tmp_path: Path) -> None:
    module = _load_module()
    apps_path = tmp_path / "apps"
    flight_telemetry_project = apps_path / "builtin" / "flight_telemetry_project"
    flight_telemetry_project.mkdir(parents=True)

    env = SimpleNamespace(
        apps_path=apps_path,
        app="notebook-quickstart",
        AGILAB_LOG_ABS=tmp_path / "log",
    )

    state = module.newcomer_first_proof_state(env)

    assert state["project_path"] == flight_telemetry_project.resolve()
    assert state["current_app_matches"] is False
    assert state["recommended_path_id"] == "source-checkout-first-proof"
    assert state["actionable_route_ids"] == ["source-checkout-first-proof"]
    assert state["documented_route_ids"] == ["notebook-quickstart"]
    assert state["run_manifest_path"] == tmp_path / "log" / "execute" / "flight" / "run_manifest.json"
    assert state["run_manifest_loaded"] is False
    assert state["run_manifest_status"] == "missing"
    assert state["remediation_status"] == "missing"
    assert "tools/newcomer_first_proof.py --json" in state["evidence_commands"][0]
    assert "tools/compatibility_report.py --manifest" in state["evidence_commands"][1]
    assert state["next_step"] == "Go to `PROJECT`. Choose `flight_telemetry_project`."


def test_first_proof_state_detects_installed_payload_provider(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    installed_project = tmp_path / "site-packages" / "agi_app_flight_telemetry" / "project" / "flight_telemetry_project"
    installed_project.mkdir(parents=True)
    (installed_project / "pyproject.toml").write_text("[project]\nname='flight-telemetry'\n", encoding="utf-8")
    monkeypatch.setattr(module, "_resolve_installed_first_proof_project", lambda: installed_project.resolve())

    env = SimpleNamespace(
        apps_path=tmp_path / "missing-apps",
        app="flight_telemetry_project",
        AGILAB_LOG_ABS=tmp_path / "log",
    )

    state = module.newcomer_first_proof_state(env, repo_root=tmp_path / "not-a-source-checkout")

    assert state["project_path"] == installed_project.resolve()
    assert state["project_available"] is True
    assert state["current_app_matches"] is True


def test_first_proof_state_detects_completion_outputs(tmp_path: Path) -> None:
    module = _load_module()
    apps_path = tmp_path / "apps"
    flight_telemetry_project = apps_path / "flight_telemetry_project"
    flight_telemetry_project.mkdir(parents=True)
    output_dir = tmp_path / "log" / "execute" / "flight"
    output_dir.mkdir(parents=True)
    (output_dir / "AGI_install_flight_telemetry.py").write_text("# helper", encoding="utf-8")
    (output_dir / "AGI_run_flight_telemetry.py").write_text("# helper", encoding="utf-8")
    (output_dir / "trajectory_summary.json").write_text("{}", encoding="utf-8")

    env = SimpleNamespace(
        apps_path=apps_path,
        app=str(flight_telemetry_project),
        AGILAB_LOG_ABS=tmp_path / "log",
    )

    state = module.newcomer_first_proof_state(env)

    assert state["current_app_matches"] is True
    assert state["helper_scripts_present"] is True
    assert state["run_output_detected"] is True
    assert [path.name for path in state["visible_outputs"]] == ["trajectory_summary.json"]
    assert state["remediation_status"] == "missing_manifest_with_outputs"
    assert state["next_step"] == "Generate `run_manifest.json` with the first-proof JSON command."


def test_first_proof_state_prefers_passing_run_manifest(tmp_path: Path) -> None:
    module = _load_module()
    run_manifest = module._load_run_manifest_module()
    apps_path = tmp_path / "apps"
    flight_telemetry_project = apps_path / "flight_telemetry_project"
    flight_telemetry_project.mkdir(parents=True)
    output_dir = tmp_path / "log" / "execute" / "flight"
    output_dir.mkdir(parents=True)
    manifest = run_manifest.build_run_manifest(
        path_id="source-checkout-first-proof",
        label="Source checkout first proof",
        status="pass",
        command=run_manifest.RunManifestCommand(
            label="newcomer first proof",
            argv=("tools/newcomer_first_proof.py", "--json"),
            cwd=str(tmp_path),
        ),
        environment=run_manifest.RunManifestEnvironment.from_paths(
            repo_root=tmp_path,
            active_app=flight_telemetry_project,
        ),
        timing=run_manifest.RunManifestTiming(
            started_at="2026-04-25T00:00:00Z",
            finished_at="2026-04-25T00:00:05Z",
            duration_seconds=5.0,
            target_seconds=600.0,
        ),
        artifacts=[],
        validations=[
            run_manifest.RunManifestValidation(
                label=label,
                status="pass",
                summary=f"{label} passed",
            )
            for label in ("proof_steps", "target_seconds", "recommended_project")
        ],
        run_id="first-proof-demo",
        created_at="2026-04-25T00:00:05Z",
    )
    run_manifest.write_run_manifest(manifest, output_dir / "run_manifest.json")

    env = SimpleNamespace(
        apps_path=apps_path,
        app=str(flight_telemetry_project),
        AGILAB_LOG_ABS=tmp_path / "log",
    )

    state = module.newcomer_first_proof_state(env)

    assert state["run_manifest_loaded"] is True
    assert state["run_manifest_status"] == "pass"
    assert state["run_manifest_passed"] is True
    assert state["run_manifest_summary"]["run_id"] == "first-proof-demo"
    assert {row["label"]: row["status"] for row in state["run_manifest_validation_rows"]} == {
        "proof_steps": "pass",
        "target_seconds": "pass",
        "recommended_project": "pass",
    }
    assert state["remediation_status"] == "passed"
    assert state["run_output_detected"] is True
    assert state["visible_outputs"] == []
    assert state["next_step"] == "First proof done. Now you can try another demo."


def test_first_proof_state_explains_failing_run_manifest(tmp_path: Path) -> None:
    module = _load_module()
    run_manifest = module._load_run_manifest_module()
    apps_path = tmp_path / "apps"
    flight_telemetry_project = apps_path / "flight_telemetry_project"
    flight_telemetry_project.mkdir(parents=True)
    output_dir = tmp_path / "log" / "execute" / "flight"
    output_dir.mkdir(parents=True)
    manifest = run_manifest.build_run_manifest(
        path_id="source-checkout-first-proof",
        label="Source checkout first proof",
        status="fail",
        command=run_manifest.RunManifestCommand(
            label="newcomer first proof",
            argv=("tools/newcomer_first_proof.py", "--json"),
            cwd=str(tmp_path),
        ),
        environment=run_manifest.RunManifestEnvironment.from_paths(
            repo_root=tmp_path,
            active_app=flight_telemetry_project,
        ),
        timing=run_manifest.RunManifestTiming(
            started_at="2026-04-25T00:00:00Z",
            finished_at="2026-04-25T00:10:05Z",
            duration_seconds=605.0,
            target_seconds=600.0,
        ),
        artifacts=[],
        validations=[
            run_manifest.RunManifestValidation(
                label="proof_steps",
                status="pass",
                summary="proof steps passed",
            ),
            run_manifest.RunManifestValidation(
                label="target_seconds",
                status="fail",
                summary="proof exceeded target",
            ),
        ],
        run_id="first-proof-fail",
        created_at="2026-04-25T00:10:05Z",
    )
    run_manifest.write_run_manifest(manifest, output_dir / "run_manifest.json")

    env = SimpleNamespace(
        apps_path=apps_path,
        app=str(flight_telemetry_project),
        AGILAB_LOG_ABS=tmp_path / "log",
    )

    state = module.newcomer_first_proof_state(env)

    assert state["run_manifest_loaded"] is True
    assert state["run_manifest_passed"] is False
    assert state["remediation_status"] == "failing"
    assert state["next_step"] == "Run manifest found but not passing. Follow the remediation checklist."
    assert any("target_seconds=fail" in action for action in state["remediation_actions"])
    assert any("recommended_project=missing" in action for action in state["remediation_actions"])
    assert "tools/compatibility_report.py --manifest" in state["evidence_commands"][1]
