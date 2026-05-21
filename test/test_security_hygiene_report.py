from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/security_hygiene_report.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "security_hygiene_report_test_module",
        MODULE_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_security_hygiene_report_passes_static_contract(tmp_path: Path) -> None:
    module = _load_module()

    report = module.build_report(repo_root=Path.cwd())

    assert report["schema"] == "agilab.security_hygiene.v1"
    assert report["status"] == "pass"
    assert report["summary"]["pip_audit_artifact_provided"] is False
    assert report["summary"]["sbom_artifact_provided"] is False
    assert "pip-audit --format json" in report["summary"]["pip_audit_command"]
    assert "cyclonedx-py environment" in report["summary"]["sbom_command"]
    checks = {check["id"]: check for check in report["checks"]}
    assert checks["security_policy_present"]["status"] == "pass"
    assert checks["locked_dependencies_present"]["status"] == "pass"
    assert checks["optional_ai_dependency_boundary"]["status"] == "pass"
    assert checks["service_queue_json_payload_contract"]["status"] == "pass"
    assert checks["service_queue_json_payload_contract"]["details"]["task_suffix"] == ".task.json"
    assert checks["operator_shell_install_boundary_documented"]["status"] == "pass"
    shell_files = checks["operator_shell_install_boundary_documented"]["details"][
        "shell_or_pipe_shell_files"
    ]
    assert shell_files == []
    assert "src/agilab/core/agi-node/src/agi_node/agi_dispatcher/base_worker.py" not in shell_files
    assert (
        "src/agilab/core/agi-node/src/agi_node/agi_dispatcher/base_worker_runtime_support.py"
        not in shell_files
    )
    assert (
        "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/deployment_local_support.py"
        not in shell_files
    )
    assert "src/agilab/core/agi-env/src/agi_env/pagelib_runtime_support.py" not in shell_files
    assert "src/agilab/pipeline_runtime_execution_support.py" not in shell_files
    assert "src/agilab/notebook_export_support.py" not in shell_files
    assert "src/agilab/pages/3_WORKFLOW.py" not in shell_files
    assert "install.sh" not in shell_files
    assert checks["pypi_trusted_publishing_only"]["status"] == "pass"
    assert checks["codecov_uploads_are_blocking_gates"]["status"] == "pass"
    assert checks["local_secret_storage_is_developer_only"]["status"] == "pass"
    assert checks["release_evidence_scope_is_bounded"]["status"] == "pass"
    assert checks["adoption_profile_go_no_go_documented"]["status"] == "pass"
    assert checks["security_disclosure_channel_consistency"]["status"] == "pass"
    assert checks["security_disclosure_channel_consistency"]["details"][
        "stale_public_issue_tokens"
    ] == []
    assert checks["external_apps_repository_trust_boundary"]["status"] == "pass"
    assert checks["supply_chain_profile_evidence_documented"]["status"] == "pass"
    assert checks["release_proof_freshness_policy_documented"]["status"] == "pass"
    assert checks["release_proof_freshness_policy_documented"]["details"]["version_aligned"] is True
    assert checks["release_proof_freshness_policy_documented"]["details"]["tag_aligned"] is True
    assert checks["release_proof_freshness_policy_documented"]["details"]["rendered_page_aligned"] is True
    assert checks["remote_installers_are_staged_before_execution"]["status"] == "pass"
    assert checks["installers_expose_dry_run_profiles"]["status"] == "pass"
    assert checks["central_command_runner_shell_fallback_is_syntax_gated"]["status"] == "pass"
    assert checks["github_actions_are_pinned_to_commit_sha"]["status"] == "pass"

    output = tmp_path / "security-hygiene.json"
    assert module.main(["--output", str(output), "--compact"]) == 0
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["status"] == "pass"


def test_release_tag_alignment_accepts_same_version_retry_tags() -> None:
    module = _load_module()

    assert not module._release_tag_matches_version("", "2026.05.11")
    assert not module._release_tag_matches_version("v2026.05.11", "")
    assert module._release_tag_matches_version("v2026.05.11", "2026.05.11")
    assert module._release_tag_matches_version("v2026.05.11-2", "2026.05.11")
    assert module._release_tag_matches_version("v2026.05.12.post1", "2026.05.12.post1")
    assert module._release_tag_matches_version("v2026.05.12.post1-2", "2026.05.12.post1")
    assert module._release_tag_matches_version("v2026.05.12-5", "2026.05.12.post1")
    assert not module._release_tag_matches_version("v2026.05.12", "2026.05.11")
    assert not module._release_tag_matches_version("v2026.05.13", "2026.05.12.post1")
    assert not module._release_tag_matches_version("v2026.05.11-beta", "2026.05.11")


def test_security_hygiene_version_comparison_accepts_public_release_lag() -> None:
    module = _load_module()

    assert module._version_key("2026.05.11-2") == (2026, 5, 11, 2)
    assert module._version_key("draft") is None
    assert module._version_not_newer("2026.05.11", "2026.05.11")
    assert module._version_not_newer("2026.05.11", "2026.05.12")
    assert not module._version_not_newer("2026.05.12", "2026.05.11")
    assert module._version_not_newer("draft", "draft")
    assert not module._version_not_newer("draft", "release")


def test_security_hygiene_artifact_parsers_cover_supported_shapes(tmp_path: Path) -> None:
    module = _load_module()
    invalid_toml = tmp_path / "bad.toml"
    invalid_toml.write_text("not = [", encoding="utf-8")

    assert module._read_toml_artifact(invalid_toml)[0] is None
    assert module._pip_audit_vulnerability_count(None) is None
    assert module._pip_audit_vulnerability_count({"vulnerabilities": [{}, {}]}) == 2
    assert module._pip_audit_vulnerability_count([{"name": "a", "vulns": [{}]}]) == 1
    assert module._pip_audit_vulnerability_count({"unexpected": []}) is None
    assert module._component_count({"components": [{}, {}]}) == 2
    assert module._component_count([]) is None


def test_security_hygiene_release_package_spec_sorts_optional_extras() -> None:
    module = _load_module()

    assert (
        module._release_package_spec(
            "agilab",
            "2026.05.11",
            {"package_extras": ["ui", "ai", ""]},
        )
        == "agilab[ai,ui]==2026.05.11"
    )
    assert (
        module._release_package_spec(
            "agilab",
            "2026.05.11",
            {"package_extras": "ui"},
        )
        == "agilab==2026.05.11"
    )


def test_security_hygiene_static_checks_report_missing_or_unsafe_files(tmp_path: Path) -> None:
    module = _load_module()
    install_script = tmp_path / "install.sh"
    install_script.write_text("python - <<'PY'\nsubprocess.run('x', shell=True)\nPY\n", encoding="utf-8")
    workflow_root = tmp_path / ".github" / "workflows"
    workflow_root.mkdir(parents=True)
    (workflow_root / "coverage.yml").write_text("jobs: {}\n", encoding="utf-8")
    (workflow_root / "unpinned.yml").write_text(
        "steps:\n  - uses: actions/checkout@v4\n",
        encoding="utf-8",
    )

    shell_check = module._shell_execution_boundary_check(
        tmp_path,
        "trusted-operator boundary shell execution install profiles",
    )
    assert shell_check["status"] == "pass"
    assert shell_check["details"]["shell_or_pipe_shell_files"] == ["install.sh"]

    coverage_check = module._coverage_upload_gate_check(tmp_path)
    assert coverage_check["status"] == "fail"
    assert "Upload agi-env coverage to Codecov" in coverage_check["details"]["failing_steps"]

    dry_run_check = module._installer_dry_run_profile_check(tmp_path)
    assert dry_run_check["status"] == "fail"
    assert set(dry_run_check["details"]["missing_tokens"]) == {"install.sh", "tools/install_enduser.sh"}

    pin_check = module._github_actions_sha_pin_check(tmp_path)
    assert pin_check["status"] == "fail"
    assert pin_check["details"]["unpinned_actions"] == [
        ".github/workflows/unpinned.yml:2:actions/checkout@v4"
    ]

    disclosure_check = module._security_disclosure_channel_check(
        tmp_path,
        "Open a GitHub issue with the title [SECURITY]",
    )
    assert disclosure_check["status"] == "fail"
    assert disclosure_check["details"]["stale_public_issue_tokens"]


def test_security_hygiene_report_accepts_scan_artifacts(tmp_path: Path) -> None:
    module = _load_module()
    pip_audit = tmp_path / "pip-audit.json"
    pip_audit.write_text(
        json.dumps({"dependencies": [{"name": "agilab", "vulns": []}]}),
        encoding="utf-8",
    )
    sbom = tmp_path / "sbom-cyclonedx.json"
    sbom.write_text(
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "components": [{"name": "agilab", "type": "library"}],
            }
        ),
        encoding="utf-8",
    )

    report = module.build_report(
        repo_root=Path.cwd(),
        pip_audit_json=pip_audit,
        sbom_json=sbom,
    )

    assert report["status"] == "pass"
    checks = {check["id"]: check for check in report["checks"]}
    assert checks["pip_audit_artifact_valid"]["details"]["provided"] is True
    assert checks["pip_audit_artifact_valid"]["details"]["vulnerability_count"] == 0
    assert checks["sbom_artifact_valid"]["details"]["component_count"] == 1


def test_security_hygiene_report_rejects_invalid_scan_artifact(tmp_path: Path) -> None:
    module = _load_module()
    pip_audit = tmp_path / "pip-audit.json"
    pip_audit.write_text("{not json", encoding="utf-8")

    report = module.build_report(repo_root=Path.cwd(), pip_audit_json=pip_audit)

    assert report["status"] == "fail"
    checks = {check["id"]: check for check in report["checks"]}
    assert checks["pip_audit_artifact_valid"]["status"] == "fail"


def test_security_hygiene_main_prints_pretty_json(capsys) -> None:
    module = _load_module()

    assert module.main([]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "agilab.security_hygiene.v1"
    assert payload["status"] == "pass"
