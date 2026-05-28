from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/production_readiness_report.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "production_readiness_report_test_module", MODULE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_report_passes_static_production_readiness_contracts() -> None:
    module = _load_module()

    report = module.build_report(run_docs_profile=False)

    assert report["kpi"] == "Production readiness"
    assert report["supported_score"] == module.SUPPORTED_SCORE
    assert report["status"] == "pass"
    assert report["summary"]["docs_profile_executed"] is False
    check_ids = {check["id"] for check in report["checks"]}
    assert check_ids == {
        "docs_mirror_stamp",
        "docs_workflow_parity_profile",
        "production_readiness_workflow_profile",
        "architecture_scorecard",
        "compatibility_matrix_validated_paths",
        "service_health_json_prometheus",
        "controlled_pilot_readiness_gate",
        "release_decision_promotion_export",
        "security_disclosure_hardening",
        "security_adoption_strict_gate",
        "profile_supply_chain_scan_gate",
        "public_ui_bind_guard",
        "cluster_share_fail_fast",
        "production_boundary_docs",
    }


def test_build_report_includes_shared_adoption_hardening_controls() -> None:
    module = _load_module()

    report = module.build_report(run_docs_profile=False)
    checks = {check["id"]: check for check in report["checks"]}

    for check_id in {
        "security_adoption_strict_gate",
        "profile_supply_chain_scan_gate",
        "public_ui_bind_guard",
        "cluster_share_fail_fast",
        "controlled_pilot_readiness_gate",
        "architecture_scorecard",
        "production_boundary_docs",
    }:
        check = checks[check_id]
        assert check["status"] == "pass"
        assert check["evidence"]
        if "missing" in check["details"]:
            assert check["details"]["missing"] == {}


def test_controlled_pilot_readiness_gate_supports_score_movement() -> None:
    module = _load_module()

    report = module.build_report(run_docs_profile=False)
    check = next(
        check for check in report["checks"] if check["id"] == "controlled_pilot_readiness_gate"
    )

    assert report["supported_score"] == "3.2 / 5"
    assert check["status"] == "pass"
    assert check["details"]["supported_score"] == "3.2 / 5"
    assert set(check["details"]["check_ids"]) >= {
        "service_health_execution",
        "service_failure_modes",
        "persisted_artifact_contract",
        "public_bind_and_secret_boundary",
        "compatibility_matrix_entry",
    }


def test_architecture_scorecard_is_scoped_and_evidence_backed() -> None:
    module = _load_module()

    report = module.build_report(run_docs_profile=False)
    check = next(check for check in report["checks"] if check["id"] == "architecture_scorecard")

    assert check["status"] == "pass"
    assert check["details"]["supported_score"] == "4.5 / 5"
    assert "multi-tenant production" in check["details"]["score_scope"]
    assert set(check["details"]["check_ids"]) >= {
        "architecture_plane_boundaries",
        "architecture_runtime_guardrails",
        "architecture_supply_chain_release_proof",
        "architecture_remote_execution_hardening",
        "architecture_capacity_model_trust_boundary",
        "architecture_claim_boundary",
    }


def test_docs_workflow_profile_check_reports_expected_sphinx_command() -> None:
    module = _load_module()

    report = module.build_report(run_docs_profile=False)
    check = next(
        check for check in report["checks"] if check["id"] == "docs_workflow_parity_profile"
    )

    assert check["status"] == "pass"
    release_proof_argv = check["details"]["release_proof_argv"]
    sphinx_argv = check["details"]["sphinx_argv"]
    assert release_proof_argv[-2:] == ["--check", "--compact"]
    assert "tools/release_proof_report.py" in release_proof_argv
    assert sphinx_argv[-2:] == ["docs/source", "docs/html"]
    assert "sphinx" in sphinx_argv
    assert "myst-parser" in sphinx_argv


def test_production_readiness_workflow_profile_writes_artifact_contract() -> None:
    module = _load_module()

    report = module.build_report(run_docs_profile=False)
    check = next(
        check
        for check in report["checks"]
        if check["id"] == "production_readiness_workflow_profile"
    )

    assert check["status"] == "pass"
    assert check["details"]["argv"][-4:] == [
        "--run-docs-profile",
        "--output",
        "test-results/production-readiness.json",
        "--compact",
    ]
    assert check["details"]["commands"][0]["ensure_dirs"] == ["test-results"]
    assert check["details"]["commands"][0]["remove_paths"] == [
        "test-results/production-readiness.json"
    ]


def test_main_emits_json_and_returns_success(capsys) -> None:
    module = _load_module()

    exit_code = module.main(["--compact"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kpi"] == "Production readiness"
    assert payload["status"] == "pass"
    assert payload["summary"]["failed"] == 0


def test_main_writes_output_artifact(tmp_path: Path, capsys) -> None:
    module = _load_module()
    output = tmp_path / "production-readiness.json"

    exit_code = module.main(["--compact", "--output", str(output)])

    assert exit_code == 0
    stdout_payload = json.loads(capsys.readouterr().out)
    file_payload = json.loads(output.read_text(encoding="utf-8"))
    assert stdout_payload["status"] == "pass"
    assert file_payload["status"] == "pass"
    assert file_payload["summary"]["failed"] == 0
