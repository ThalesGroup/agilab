from __future__ import annotations

import importlib.util
import builtins
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


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

    assert content["title"] == (
        "First proof with flight-telemetry-project: verify AGILAB end-to-end"
    )
    assert "sample data and expected outputs" in content["intro"]
    assert content["recommended_path_id"] == "source-checkout-first-proof"
    assert content["recommended_path_label"] == "Source checkout first proof"
    assert content["actionable_route_ids"] == ["source-checkout-first-proof"]
    assert content["documented_route_ids"] == ["notebook-quickstart"]
    assert content["compatibility_status"] == "validated"
    assert content["compatibility_report_status"] == "pass"
    assert content["proof_command_labels"] == ["preinit smoke", "source ui smoke"]
    assert content["run_manifest_filename"] == "run_manifest.json"
    assert [label for label, _ in content["steps"]] == ["DEMO", "ORCHESTRATE", "ANALYSIS"]
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
    assert (
        state["next_step"]
        == "Select the built-in flight-telemetry demo (`flight_telemetry_project`) from this page."
    )


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


def test_first_proof_loader_error_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module()

    monkeypatch.setattr(module.importlib.util, "spec_from_file_location", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="unable to load tool module"):
        module._load_tool_module(tmp_path, "missing_tool")
    with pytest.raises(RuntimeError, match="unable to load run manifest module"):
        module._load_run_manifest_module()


def test_first_proof_installed_provider_error_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module()
    original_import = builtins.__import__

    def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "agi_env.app_provider_registry":
            raise ImportError("blocked provider registry")
        return original_import(name, globals, locals, fromlist, level)

    with monkeypatch.context() as scoped:
        scoped.setattr(builtins, "__import__", blocked_import)
        assert module._resolve_installed_first_proof_project() is None

    import agi_env.app_provider_registry as registry

    with monkeypatch.context() as scoped:
        scoped.setattr(registry, "resolve_installed_app_project", lambda _name: (_ for _ in ()).throw(RuntimeError("boom")))
        assert module._resolve_installed_first_proof_project() is None

    with monkeypatch.context() as scoped:
        scoped.setattr(registry, "resolve_installed_app_project", lambda _name: None)
        assert module._resolve_installed_first_proof_project() is None

    with monkeypatch.context() as scoped:
        scoped.setattr(registry, "resolve_installed_app_project", lambda _name: object())
        assert module._resolve_installed_first_proof_project() is None

    missing_pyproject = tmp_path / "installed" / "flight_telemetry_project"
    missing_pyproject.mkdir(parents=True)
    with monkeypatch.context() as scoped:
        scoped.setattr(registry, "resolve_installed_app_project", lambda _name: missing_pyproject)
        assert module._resolve_installed_first_proof_project() is None


def test_first_proof_project_path_handles_bad_env_and_duplicates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_resolve_installed_first_proof_project", lambda: None)

    bad_env = SimpleNamespace(apps_path=object())
    assert module.newcomer_first_proof_project_path(bad_env, repo_root=tmp_path / "missing-root").name == (
        "flight_telemetry_project"
    )

    duplicate_root = tmp_path / "duplicate-root"
    duplicate_env = SimpleNamespace(apps_path=duplicate_root / "src" / "agilab" / "apps" / "builtin")
    assert module.newcomer_first_proof_project_path(duplicate_env, repo_root=duplicate_root).name == (
        "flight_telemetry_project"
    )


def test_first_proof_state_without_project_points_to_app_list(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "newcomer_first_proof_project_path", lambda _env, _repo_root=module.REPO_ROOT: None)

    env = SimpleNamespace(app="flight_telemetry_project", AGILAB_LOG_ABS=tmp_path / "log")

    state = module.newcomer_first_proof_state(env)

    assert state["project_available"] is False
    assert state["next_step"].startswith("Fix the app list first.")


def test_first_proof_state_reports_invalid_manifest_and_filtered_outputs(tmp_path: Path) -> None:
    module = _load_module()
    apps_path = tmp_path / "apps"
    flight_telemetry_project = apps_path / "flight_telemetry_project"
    flight_telemetry_project.mkdir(parents=True)
    output_dir = tmp_path / "log" / "execute" / "flight"
    output_dir.mkdir(parents=True)
    (output_dir / "run_manifest.json").write_text("{not-json", encoding="utf-8")
    (output_dir / ".hidden").write_text("hidden", encoding="utf-8")
    (output_dir / "AGI_get_flight_telemetry.py").write_text("# helper", encoding="utf-8")
    (output_dir / "artifact.csv").write_text("x\n", encoding="utf-8")

    env = SimpleNamespace(
        apps_path=apps_path,
        app="flight_telemetry_project",
        AGILAB_LOG_ABS=tmp_path / "log",
    )

    state = module.newcomer_first_proof_state(env)

    assert [path.name for path in state["visible_outputs"]] == ["artifact.csv"]
    assert state["run_manifest_loaded"] is False
    assert state["run_manifest_status"] == "invalid"
    assert state["remediation_status"] == "invalid"
    assert state["run_manifest_error"]


def test_first_proof_failing_remediation_lists_path_and_missing_target(tmp_path: Path) -> None:
    module = _load_module()
    run_manifest = module._load_run_manifest_module()
    manifest = run_manifest.build_run_manifest(
        path_id="wrong-path",
        label="Wrong path",
        status="pass",
        command=run_manifest.RunManifestCommand(
            label="newcomer first proof",
            argv=("tools/newcomer_first_proof.py", "--json"),
            cwd=str(tmp_path),
        ),
        environment=run_manifest.RunManifestEnvironment.from_paths(
            repo_root=tmp_path,
            active_app=tmp_path / "apps" / "flight_telemetry_project",
        ),
        timing=run_manifest.RunManifestTiming(
            started_at="2026-04-25T00:00:00Z",
            finished_at="2026-04-25T00:00:05Z",
            duration_seconds=5.0,
            target_seconds=None,
        ),
        artifacts=[],
        validations=[
            run_manifest.RunManifestValidation(label=label, status="pass", summary=f"{label} passed")
            for label in ("proof_steps", "target_seconds", "recommended_project")
        ],
        run_id="first-proof-wrong-path",
        created_at="2026-04-25T00:00:05Z",
    )

    rows = module._manifest_validation_rows(manifest)
    remediation = module._first_proof_remediation(
        manifest=manifest,
        manifest_error=None,
        manifest_path=tmp_path / "run_manifest.json",
        manifest_passed=False,
        validation_rows=rows,
        visible_outputs=(),
    )

    assert remediation["status"] == "failing"
    assert any("path_id is `wrong-path`" in action for action in remediation["actions"])
    assert any("target_seconds is missing" in action for action in remediation["actions"])
