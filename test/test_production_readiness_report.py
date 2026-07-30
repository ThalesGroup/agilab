from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_PATH = Path("tools/production_readiness_report.py").resolve()
SYNC_DOCS_MODULE_PATH = Path("tools/sync_docs_source.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "production_readiness_report_test_module", MODULE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_sync_docs_module():
    spec = importlib.util.spec_from_file_location(
        "production_readiness_sync_docs_test_module",
        SYNC_DOCS_MODULE_PATH,
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
        "docs_canonical_alignment",
        "docs_workflow_parity_profile",
        "production_readiness_workflow_profile",
        "architecture_scorecard",
        "runtime_robustness_matrix",
        "compatibility_matrix_validated_paths",
        "service_health_json_prometheus",
        "controlled_pilot_readiness_gate",
        "release_decision_promotion_export",
        "security_disclosure_hardening",
        "security_adoption_strict_gate",
        "profile_supply_chain_scan_gate",
        "shared_team_go_gate",
        "public_ui_bind_guard",
        "cluster_share_fail_fast",
        "production_boundary_docs",
    }


def test_explicit_missing_canonical_docs_fails_without_claiming_comparison(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    configured_source = tmp_path / "missing-canonical"
    calls: list[str] = []

    def verify_target(_target: Path) -> tuple[bool, str]:
        calls.append("target")
        return True, "target integrity verified"

    def verify_canonical(
        _target: Path,
        source: Path,
        *,
        source_required: bool,
    ) -> tuple[str, str]:
        calls.append("canonical")
        assert source == configured_source
        assert source_required is True
        return "fail", f"configured canonical docs source not found: {source}"

    fake_sync_docs = SimpleNamespace(
        verify_target_mirror_integrity=verify_target,
        canonical_source_configuration=lambda _repo_root: SimpleNamespace(
            path=configured_source,
            origin="env:AGILAB_DOCS_SOURCE",
            required=True,
        ),
        verify_canonical_mirror_alignment=verify_canonical,
    )
    monkeypatch.setattr(
        module,
        "_load_tool_module",
        lambda _repo_root, _name: fake_sync_docs,
    )

    target_check = module._check_docs_mirror_stamp(Path.cwd())
    canonical_check = module._check_docs_canonical_alignment(Path.cwd())

    assert target_check["status"] == "pass"
    assert "target integrity" in target_check["summary"]
    assert canonical_check["status"] == "fail"
    assert canonical_check["details"]["canonical_alignment_checked"] is False
    assert canonical_check["details"]["canonical_source_required"] is True
    assert "configured canonical docs source not found" in canonical_check["summary"]
    assert calls == ["target", "target", "canonical"]


def test_docs_target_check_loads_verifier_from_requested_repo_root(
    tmp_path: Path,
) -> None:
    module = _load_module()
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    verifier = tools_dir / "sync_docs_source.py"
    verifier.write_text(
        "def verify_target_mirror_integrity(target):\n"
        "    return True, 'requested-root-verifier:' + __file__\n",
        encoding="utf-8",
    )

    check = module._check_docs_mirror_stamp(tmp_path)

    assert check["status"] == "pass"
    assert f"requested-root-verifier:{verifier}" == check["summary"]


def test_canonical_comparison_exception_does_not_claim_checked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    canonical_source = tmp_path / "canonical"
    canonical_source.mkdir()

    def raise_during_comparison(*_args, **_kwargs):
        raise RuntimeError("comparison exploded")

    fake_sync_docs = SimpleNamespace(
        verify_target_mirror_integrity=lambda _target: (
            True,
            "target integrity verified",
        ),
        canonical_source_configuration=lambda _repo_root: SimpleNamespace(
            path=canonical_source,
            origin="default",
            required=False,
        ),
        verify_canonical_mirror_alignment=raise_during_comparison,
    )
    monkeypatch.setattr(
        module,
        "_load_tool_module",
        lambda _repo_root, _name: fake_sync_docs,
    )

    check = module._check_docs_canonical_alignment(Path.cwd())

    assert check["status"] == "fail"
    assert check["details"]["target_integrity_ok"] is True
    assert check["details"]["canonical_alignment_checked"] is False
    assert "comparison exploded" in check["summary"]


def test_target_integrity_exception_does_not_claim_checked(monkeypatch) -> None:
    module = _load_module()

    def raise_during_target_check(_target: Path):
        raise RuntimeError("target check exploded")

    fake_sync_docs = SimpleNamespace(
        verify_target_mirror_integrity=raise_during_target_check,
    )
    monkeypatch.setattr(
        module,
        "_load_tool_module",
        lambda _repo_root, _name: fake_sync_docs,
    )

    check = module._check_docs_canonical_alignment(Path.cwd())

    assert check["status"] == "fail"
    assert check["details"]["target_integrity_checked"] is False
    assert check["details"]["target_integrity_ok"] is False
    assert check["details"]["canonical_alignment_checked"] is False
    assert "target check exploded" in check["summary"]


def test_default_missing_canonical_source_is_skipped_and_not_checked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    default_source = tmp_path / "missing-default-source"
    fake_sync_docs = SimpleNamespace(
        verify_target_mirror_integrity=lambda _target: (
            True,
            "target integrity verified",
        ),
        canonical_source_configuration=lambda _repo_root: SimpleNamespace(
            path=default_source,
            origin="default",
            required=False,
        ),
        verify_canonical_mirror_alignment=lambda *_args, **_kwargs: (
            "skipped",
            "canonical drift NOT CHECKED",
        ),
    )
    monkeypatch.setattr(
        module,
        "_load_tool_module",
        lambda _repo_root, _name: fake_sync_docs,
    )

    check = module._check_docs_canonical_alignment(Path.cwd())

    assert check["status"] == "skipped"
    assert check["details"]["target_integrity_ok"] is True
    assert check["details"]["canonical_alignment_checked"] is False
    assert "canonical drift NOT CHECKED" in check["summary"]


def test_target_integrity_failure_blocks_canonical_comparison(monkeypatch) -> None:
    module = _load_module()

    def unexpected_configuration(_repo_root: Path):
        raise AssertionError("canonical configuration must not be resolved")

    fake_sync_docs = SimpleNamespace(
        verify_target_mirror_integrity=lambda _target: (
            False,
            "target stamp mismatch",
        ),
        canonical_source_configuration=unexpected_configuration,
    )
    monkeypatch.setattr(
        module,
        "_load_tool_module",
        lambda _repo_root, _name: fake_sync_docs,
    )

    check = module._check_docs_canonical_alignment(Path.cwd())

    assert check["status"] == "fail"
    assert check["details"]["target_integrity_checked"] is True
    assert check["details"]["target_integrity_ok"] is False
    assert check["details"]["canonical_alignment_checked"] is False
    assert "target integrity failed" in check["summary"]


def test_symlink_canonical_root_fails_without_claiming_tree_comparison(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    sync_docs = _load_sync_docs_module()
    repo_root = tmp_path / "public"
    target = repo_root / "docs" / "source"
    canonical = tmp_path / "canonical"
    target.mkdir(parents=True)
    canonical.mkdir()
    (target / "guide.rst").write_text("same\n", encoding="utf-8")
    (canonical / "guide.rst").write_text("same\n", encoding="utf-8")
    sync_docs.write_mirror_stamp(canonical, target)
    configured_link = tmp_path / "configured-canonical"
    try:
        configured_link.symlink_to(canonical, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")
    monkeypatch.setenv(sync_docs.DOCS_SOURCE_ENV, str(configured_link))
    monkeypatch.setattr(module, "_load_tool_module", lambda *_args: sync_docs)

    check = module._check_docs_canonical_alignment(repo_root)

    assert check["status"] == "fail"
    assert check["details"]["target_integrity_checked"] is True
    assert check["details"]["target_integrity_ok"] is True
    assert check["details"]["canonical_alignment_checked"] is False
    assert "symlink or junction" in check["summary"]


def test_build_report_includes_shared_adoption_hardening_controls() -> None:
    module = _load_module()

    report = module.build_report(run_docs_profile=False)
    checks = {check["id"]: check for check in report["checks"]}

    for check_id in {
        "security_adoption_strict_gate",
        "profile_supply_chain_scan_gate",
        "shared_team_go_gate",
        "public_ui_bind_guard",
        "cluster_share_fail_fast",
        "controlled_pilot_readiness_gate",
        "architecture_scorecard",
        "runtime_robustness_matrix",
        "production_boundary_docs",
    }:
        check = checks[check_id]
        assert check["status"] == "pass"
        assert check["evidence"]
        if "missing" in check["details"]:
            assert check["details"]["missing"] == {}


def test_shared_team_go_gate_is_machine_checkable_and_documented() -> None:
    module = _load_module()

    report = module.build_report(run_docs_profile=False)
    check = next(check for check in report["checks"] if check["id"] == "shared_team_go_gate")

    assert check["status"] == "pass"
    assert "machine-checkable go/no-go gate" in check["summary"]
    assert check["details"]["missing"] == {}
    assert set(check["evidence"]) == {
        "tools/shared_go_gate.py",
        "test/test_shared_go_gate.py",
        "tools/workflow_parity.py",
        "docs/source/trusted-shared-deployment.rst",
    }


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
    assert check["details"]["supported_score"] == "4.7 / 5"
    assert "multi-tenant production" in check["details"]["score_scope"]
    assert set(check["details"]["check_ids"]) >= {
        "architecture_plane_boundaries",
        "architecture_runtime_guardrails",
        "architecture_supply_chain_release_proof",
        "architecture_remote_execution_hardening",
        "architecture_capacity_model_trust_boundary",
        "architecture_hardening_gap_register",
        "architecture_claim_boundary",
    }


def test_runtime_robustness_matrix_executes_fail_closed_and_recovery_profiles() -> None:
    module = _load_module()

    report = module.build_report(run_docs_profile=False)
    check = next(
        check for check in report["checks"] if check["id"] == "runtime_robustness_matrix"
    )

    assert check["status"] == "pass"
    assert check["details"]["profile"] == "all"
    assert check["details"]["scenario_count"] >= 16
    assert check["details"]["failed"] == []
    assert check["details"]["missing_recovery_scenarios"] == []
    assert check["details"]["missing_recovery_evidence"] == []
    assert check["details"]["abrupt_child_termination_observed"] is True
    assert check["details"]["crash_termination_method"] in {"SIGKILL", "TerminateProcess"}
    assert check["details"]["crash_child_returncode"] not in (None, 0)
    assert {"runner-state", "agent-trace", "workflow-evidence"} <= set(
        check["details"]["domains"]
    )
    assert set(check["evidence"]) == {
        "tools/robustness_matrix.py",
        "test/test_robustness_matrix.py",
    }


def test_runtime_robustness_matrix_requires_observed_abrupt_child_termination(
    monkeypatch,
) -> None:
    module = _load_module()
    scenario_ids = {
        "stale_runner_state_writer_is_rejected",
        "crash_partial_agent_trace_tail_is_quarantined",
        "interrupted_workflow_evidence_publish_recovers",
        "tampered_workflow_evidence_manifest_is_rejected",
    }
    fake_report = {
        "schema": "agilab.robustness_matrix.v1",
        "profile": "all",
        "status": "pass",
        "available_profiles": ["p0", "p1-recovery", "all"],
        "summary": {
            "scenario_count": len(scenario_ids),
            "domains": ["agent-trace", "runner-state", "workflow-evidence"],
        },
        "scenarios": [
            {
                "id": scenario_id,
                "status": "pass",
                "details": {},
            }
            for scenario_id in sorted(scenario_ids)
        ],
    }
    fake_robustness_matrix = SimpleNamespace(
        SCHEMA="agilab.robustness_matrix.v1",
        build_report=lambda **_kwargs: fake_report,
    )
    monkeypatch.setattr(
        module,
        "_load_tool_module",
        lambda _repo_root, _name: fake_robustness_matrix,
    )

    check = module._check_runtime_robustness_matrix(Path.cwd())

    assert check["status"] == "fail"
    assert check["details"]["abrupt_child_termination_observed"] is False
    assert check["details"]["missing_recovery_evidence"] == [
        "crash_partial_agent_trace_tail_is_quarantined:abrupt_child_termination_observed"
    ]


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
