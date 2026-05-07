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
    assert "src/agilab/pages/3_PIPELINE.py" not in shell_files
    assert "install.sh" not in shell_files
    assert checks["pypi_trusted_publishing_only"]["status"] == "pass"
    assert checks["codecov_uploads_are_blocking_gates"]["status"] == "pass"
    assert checks["local_secret_storage_is_developer_only"]["status"] == "pass"
    assert checks["release_evidence_scope_is_bounded"]["status"] == "pass"
    assert checks["remote_installers_are_staged_before_execution"]["status"] == "pass"
    assert checks["installers_expose_dry_run_profiles"]["status"] == "pass"
    assert checks["central_command_runner_shell_fallback_is_syntax_gated"]["status"] == "pass"
    assert checks["github_actions_are_pinned_to_commit_sha"]["status"] == "pass"

    output = tmp_path / "security-hygiene.json"
    assert module.main(["--output", str(output), "--compact"]) == 0
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["status"] == "pass"


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
