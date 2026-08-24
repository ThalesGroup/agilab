from __future__ import annotations

import importlib.util
import json
import subprocess
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
    assert report["summary"]["passed"] == report["summary"]["check_count"] - 2
    assert report["summary"]["failed"] == 0
    assert report["summary"]["skipped"] == 2
    assert report["summary"]["scan_artifacts_required"] is False
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
    assert checks["tracked_source_secret_patterns_absent"]["status"] == "pass"
    assert checks["release_evidence_scope_is_bounded"]["status"] == "pass"
    assert checks["adoption_profile_go_no_go_documented"]["status"] == "pass"
    assert checks["security_release_process_documented"]["status"] == "pass"
    assert checks["security_disclosure_channel_consistency"]["status"] == "pass"
    assert checks["security_disclosure_channel_consistency"]["details"][
        "stale_public_issue_tokens"
    ] == []
    assert checks["issue_templates_route_security_reports_privately"]["status"] == "pass"
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
    assert checks["pip_audit_artifact_valid"]["status"] == "skipped"
    assert checks["sbom_artifact_valid"]["status"] == "skipped"

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
    assert module._release_tag_matches_version("v2026.05.11_1", "2026.05.11.1")
    assert module._release_tag_matches_version("v2026.05.11_1-2", "2026.05.11.1")
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
    valid_vulnerability = {
        "id": "GHSA-test-test-test",
        "fix_versions": ["2.0"],
        "aliases": ["CVE-2099-0001"],
        "description": "synthetic vulnerability",
    }
    assert module._pip_audit_vulnerability_count(
        [{"name": "a", "version": "1.0", "vulns": [valid_vulnerability]}]
    ) == 1
    assert module._pip_audit_vulnerability_count({"unexpected": []}) is None
    assert module._pip_audit_vulnerability_count({"dependencies": [{}]}) is None
    assert module._pip_audit_vulnerability_count(
        {"dependencies": [{"name": "a", "version": "1.0", "vulns": "not-a-list"}]}
    ) is None
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

    issue_template_check = module._security_issue_template_intake_check(tmp_path)
    assert issue_template_check["status"] == "fail"
    assert ".github/ISSUE_TEMPLATE/bug_report.md" in issue_template_check["details"][
        "missing_tokens"
    ][0]


def test_tracked_source_secret_scan_rejects_mapbox_tokens_and_allows_marked_synthetic_tests(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "test").mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    synthetic = "sk." + "SYNTHETIC_TEST_TOKEN_1234567890"
    (repo / "test" / "fixture.py").write_text(
        f'TOKEN = "{synthetic}"  # {module.SYNTHETIC_SECRET_ALLOW_MARKER}\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(repo), "add", "test/fixture.py"], check=True)

    allowed = module._tracked_source_secret_pattern_check(repo)

    assert allowed["status"] == "pass"
    assert allowed["details"]["allowed_synthetic_matches"] == [
        "test/fixture.py:1:mapbox_secret_token"
    ]

    token = "sk." + ("A" * 32)
    (repo / "src" / "config.py").write_text(f'TOKEN = "{token}"\n', encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "src/config.py"], check=True)

    rejected = module._tracked_source_secret_pattern_check(repo)

    assert rejected["status"] == "fail"
    assert rejected["details"]["matches"] == ["src/config.py:1:mapbox_secret_token"]
    assert token not in json.dumps(rejected)


def test_security_hygiene_report_accepts_scan_artifacts(tmp_path: Path) -> None:
    module = _load_module()
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "Agilab==1.0\n"
        "-e .\n"
        'ignored-package==9.0 ; python_version < "1"\n'
        '-e ./inactive ; python_version < "1"\n',
        encoding="utf-8",
    )
    pip_audit = tmp_path / "pip-audit.json"
    pip_audit.write_text(
        json.dumps({"dependencies": [{"name": "agilab", "version": "1.0", "vulns": []}]}),
        encoding="utf-8",
    )
    sbom = tmp_path / "sbom-cyclonedx.json"
    sbom.write_text(
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "components": [
                    {
                        "name": "agilab",
                        "version": "1.0",
                        "type": "library",
                        "purl": "pkg:pypi/agilab@1.0",
                    },
                    {
                        "name": "ignored-package",
                        "version": "9.0",
                        "type": "library",
                        "purl": "pkg:pypi/ignored-package@9.0",
                    },
                    {
                        "bom-ref": "requirements-L2",
                        "description": "requirements line 2: -e .",
                        "name": "unknown",
                        "type": "library",
                        "externalReferences": [
                            {
                                "type": "other",
                                "url": ".",
                                "comment": "explicit local path",
                            }
                        ],
                    },
                    {
                        "bom-ref": "requirements-L4",
                        "description": (
                            'requirements line 4: -e ./inactive ; python_version < "1"'
                        ),
                        "name": "unknown",
                        "type": "library",
                        "externalReferences": [
                            {
                                "type": "other",
                                "url": "./inactive",
                                "comment": "explicit local path",
                            }
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    report = module.build_report(
        repo_root=Path.cwd(),
        pip_audit_json=pip_audit,
        sbom_json=sbom,
        scan_requirements=requirements,
        require_scan_artifacts=True,
    )

    assert report["status"] == "pass"
    assert report["summary"]["passed"] == report["summary"]["check_count"]
    assert report["summary"]["failed"] == 0
    assert report["summary"]["skipped"] == 0
    assert report["summary"]["scan_artifacts_required"] is True
    checks = {check["id"]: check for check in report["checks"]}
    assert checks["pip_audit_artifact_valid"]["status"] == "pass"
    assert checks["pip_audit_artifact_valid"]["details"]["provided"] is True
    assert checks["pip_audit_artifact_valid"]["details"]["required"] is True
    assert checks["pip_audit_artifact_valid"]["details"]["vulnerability_count"] == 0
    assert checks["pip_audit_artifact_valid"]["details"]["expected_dependency_count"] == 1
    assert checks["sbom_artifact_valid"]["status"] == "pass"
    assert checks["sbom_artifact_valid"]["details"]["component_count"] == 4
    assert checks["sbom_artifact_valid"]["details"]["expected_dependency_count"] == 2


def test_security_hygiene_report_rejects_missing_required_scan_artifacts() -> None:
    module = _load_module()

    report = module.build_report(repo_root=Path.cwd(), require_scan_artifacts=True)

    assert report["status"] == "fail"
    assert report["summary"]["failed"] == 2
    assert report["summary"]["skipped"] == 0
    checks = {check["id"]: check for check in report["checks"]}
    assert checks["pip_audit_artifact_valid"]["status"] == "fail"
    assert checks["sbom_artifact_valid"]["status"] == "fail"
    assert module.main(["--require-scan-artifacts", "--compact"]) == 1


def test_security_hygiene_report_rejects_empty_required_scan_inventories(
    tmp_path: Path,
) -> None:
    module = _load_module()
    requirements = tmp_path / "requirements-audit.txt"
    requirements.write_text("agilab==1.0\n", encoding="utf-8")
    pip_audit = tmp_path / "pip-audit.json"
    pip_audit.write_text(json.dumps({"dependencies": []}), encoding="utf-8")
    sbom = tmp_path / "sbom.json"
    sbom.write_text(
        json.dumps({"bomFormat": "CycloneDX", "components": []}),
        encoding="utf-8",
    )

    report = module.build_report(
        repo_root=Path.cwd(),
        pip_audit_json=pip_audit,
        sbom_json=sbom,
        scan_requirements=requirements,
        require_scan_artifacts=True,
    )

    checks = {check["id"]: check for check in report["checks"]}
    assert report["status"] == "fail"
    assert checks["pip_audit_artifact_valid"]["status"] == "fail"
    assert "at least one scanned dependency" in checks["pip_audit_artifact_valid"][
        "details"
    ]["error"]
    assert checks["sbom_artifact_valid"]["status"] == "fail"
    assert "at least one scanned component" in checks["sbom_artifact_valid"]["details"][
        "error"
    ]


def test_security_hygiene_report_rejects_dummy_artifacts_not_bound_to_scan_input(
    tmp_path: Path,
) -> None:
    module = _load_module()
    requirements = tmp_path / "requirements-audit.txt"
    requirements.write_text("real-package==2.0\n", encoding="utf-8")
    pip_audit = tmp_path / "pip-audit.json"
    pip_audit.write_text(
        json.dumps(
            {"dependencies": [{"name": "dummy", "version": "1.0", "vulns": []}]}
        ),
        encoding="utf-8",
    )
    sbom = tmp_path / "sbom.json"
    sbom.write_text(
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "components": [
                    {
                        "name": "dummy",
                        "version": "1.0",
                        "type": "library",
                        "purl": "pkg:pypi/dummy@1.0",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = module.build_report(
        repo_root=Path.cwd(),
        pip_audit_json=pip_audit,
        sbom_json=sbom,
        scan_requirements=requirements,
        require_scan_artifacts=True,
    )

    checks = {check["id"]: check for check in report["checks"]}
    assert checks["pip_audit_artifact_valid"]["status"] == "fail"
    assert "does not match scan requirements" in checks["pip_audit_artifact_valid"][
        "details"
    ]["error"]
    assert checks["sbom_artifact_valid"]["status"] == "fail"
    assert "does not match scan requirements" in checks["sbom_artifact_valid"][
        "details"
    ]["error"]


def test_security_hygiene_report_rejects_sbom_component_without_identity(
    tmp_path: Path,
) -> None:
    module = _load_module()
    requirements = tmp_path / "requirements-audit.txt"
    requirements.write_text("agilab==1.0\n", encoding="utf-8")
    pip_audit = tmp_path / "pip-audit.json"
    pip_audit.write_text(
        json.dumps(
            {"dependencies": [{"name": "agilab", "version": "1.0", "vulns": []}]}
        ),
        encoding="utf-8",
    )
    sbom = tmp_path / "sbom.json"
    sbom.write_text(
        json.dumps(
            {"bomFormat": "CycloneDX", "components": [{"name": "agilab", "type": "library"}]}
        ),
        encoding="utf-8",
    )

    report = module.build_report(
        repo_root=Path.cwd(),
        pip_audit_json=pip_audit,
        sbom_json=sbom,
        scan_requirements=requirements,
        require_scan_artifacts=True,
    )
    check = next(item for item in report["checks"] if item["id"] == "sbom_artifact_valid")

    assert report["status"] == "fail"
    assert check["status"] == "fail"
    assert "version must be a non-empty string" in check["details"]["error"]


def test_security_hygiene_report_rejects_vulnerable_audit_artifact(tmp_path: Path) -> None:
    module = _load_module()
    pip_audit = tmp_path / "pip-audit.json"
    pip_audit.write_text(
        json.dumps(
            {
                "dependencies": [
                    {
                        "name": "agilab",
                        "version": "1.0",
                        "vulns": [
                            {
                                "id": "GHSA-test",
                                "fix_versions": ["2.0"],
                                "aliases": [],
                                "description": "synthetic vulnerability",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = module.build_report(repo_root=Path.cwd(), pip_audit_json=pip_audit)

    checks = {check["id"]: check for check in report["checks"]}
    assert report["status"] == "fail"
    assert checks["pip_audit_artifact_valid"]["status"] == "fail"
    assert checks["pip_audit_artifact_valid"]["details"]["vulnerability_count"] == 1


def test_security_hygiene_report_rejects_incomplete_audit_entries(tmp_path: Path) -> None:
    module = _load_module()
    pip_audit = tmp_path / "pip-audit.json"
    pip_audit.write_text(
        json.dumps({"dependencies": [{"name": "agilab", "vulns": []}]}),
        encoding="utf-8",
    )

    report = module.build_report(repo_root=Path.cwd(), pip_audit_json=pip_audit)
    check = next(item for item in report["checks"] if item["id"] == "pip_audit_artifact_valid")

    assert report["status"] == "fail"
    assert check["status"] == "fail"
    assert "version must be a non-empty string" in check["details"]["error"]


def test_security_hygiene_report_rejects_non_cyclonedx_sbom(tmp_path: Path) -> None:
    module = _load_module()
    sbom = tmp_path / "sbom.json"
    sbom.write_text(json.dumps({"components": []}), encoding="utf-8")

    report = module.build_report(repo_root=Path.cwd(), sbom_json=sbom)

    checks = {check["id"]: check for check in report["checks"]}
    assert report["status"] == "fail"
    assert checks["sbom_artifact_valid"]["status"] == "fail"


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
    assert payload["summary"]["skipped"] == 2
