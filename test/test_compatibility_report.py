from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/compatibility_report.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("compatibility_report_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_manifest(
    path: Path,
    *,
    status: str = "pass",
    path_id: str = "source-checkout-first-proof",
    validation_status: str = "pass",
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "agilab.run_manifest",
                "run_id": "compatibility-test",
                "path_id": path_id,
                "label": "Source checkout first proof",
                "status": status,
                "command": {
                    "label": "newcomer first proof",
                    "argv": ["tools/newcomer_first_proof.py", "--json"],
                    "cwd": str(path.parent),
                    "env_overrides": {},
                },
                "environment": {
                    "python_version": "3.13.0",
                    "python_executable": sys.executable,
                    "platform": "test",
                    "repo_root": str(path.parent),
                    "active_app": str(path.parent / "flight_telemetry_project"),
                    "app_name": "flight_telemetry_project",
                },
                "timing": {
                    "started_at": "2026-04-25T00:00:00Z",
                    "finished_at": "2026-04-25T00:00:05Z",
                    "duration_seconds": 5.0,
                    "target_seconds": 600.0,
                },
                "artifacts": [],
                "validations": [
                    {
                        "label": label,
                        "status": validation_status,
                        "summary": f"{label} {validation_status}",
                        "details": {},
                    }
                    for label in ("proof_steps", "target_seconds", "recommended_project")
                ],
                "created_at": "2026-04-25T00:00:05Z",
            }
        ),
        encoding="utf-8",
    )
    return path


def test_build_report_passes_public_compatibility_contracts() -> None:
    module = _load_module()

    report = module.build_report(include_default_manifests=False)

    assert report["report"] == "Compatibility report"
    assert report["status"] == "pass"
    assert report["summary"]["status_counts"] == {
        "documented": 1,
        "validated": 5,
    }
    assert report["summary"]["workflow_backed_validated_paths"] == 5
    assert report["summary"]["manifest_evidence"] == {
        "loaded": 0,
        "path_ids": [],
        "failed_path_ids": [],
        "load_failures": 0,
    }
    check_ids = {check["id"] for check in report["checks"]}
    assert check_ids == {
        "compatibility_matrix_schema",
        "run_manifest_evidence_ingestion",
        "artifact_index_evidence_ingestion",
        "required_public_statuses",
        "workflow_evidence_commands",
        "documented_route_boundaries",
        "compatibility_docs_report_reference",
    }


def test_required_public_statuses_include_hf_demo_and_documented_routes() -> None:
    module = _load_module()

    check = module._check_required_public_statuses(Path.cwd(), {"path_statuses": {}})

    assert check["status"] == "pass"
    statuses = check["details"]["actual_statuses"]
    assert statuses["agilab-hf-demo"] == "validated"
    assert statuses["notebook-quickstart"] == "documented"
    assert statuses["published-package-route"] == "validated"
    assert check["details"]["mismatched"] == {}


def test_workflow_evidence_commands_resolve_public_proof_tools() -> None:
    module = _load_module()

    check = module._check_workflow_evidence_commands(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["missing_snippets"] == {}
    assert check["details"]["missing_files"] == {}
    assert check["details"]["required_evidence"]["source-checkout-first-proof"] == (
        "tools/newcomer_first_proof.py",
        "--json",
        "run_manifest.json",
    )
    assert check["details"]["required_evidence"]["published-package-route"] == (
        'pip install "agilab[examples]"',
        "python -m agilab.lab_run first-proof --json",
    )


def test_run_manifest_evidence_derives_compatibility_status(tmp_path: Path) -> None:
    module = _load_module()
    manifest_path = _write_manifest(tmp_path / "external" / "run_manifest.json")

    report = module.build_report(
        manifest_paths=[manifest_path],
        include_default_manifests=False,
    )

    assert report["status"] == "pass"
    assert report["summary"]["manifest_evidence"]["loaded"] == 1
    assert report["summary"]["manifest_evidence"]["path_ids"] == ["source-checkout-first-proof"]
    manifest_check = next(
        check
        for check in report["checks"]
        if check["id"] == "run_manifest_evidence_ingestion"
    )
    assert manifest_check["status"] == "pass"
    assert manifest_check["details"]["path_statuses"] == {
        "source-checkout-first-proof": "validated",
    }
    status_check = next(
        check
        for check in report["checks"]
        if check["id"] == "required_public_statuses"
    )
    assert status_check["details"]["actual_statuses"]["source-checkout-first-proof"] == "validated"
    assert status_check["details"]["manifest_evidence_statuses"] == {
        "source-checkout-first-proof": "validated",
    }


def test_artifact_index_evidence_derives_compatibility_status(tmp_path: Path) -> None:
    module = _load_module()
    manifest_path = _write_manifest(tmp_path / "external" / "run_manifest.json")
    artifact_index_path = tmp_path / "artifact_index.json"
    artifact_index_path.write_text(
        json.dumps(
            {
                "schema": "agilab.ci_provider_artifact_index.v1",
                "release_id": "release-20260425",
                "provider": "github_actions",
                "artifacts": [
                    {
                        "kind": "run_manifest",
                        "path": "github-actions://ThalesGroup/agilab/runs/123/artifacts/public/run_manifest.json",
                        "payload": json.loads(manifest_path.read_text(encoding="utf-8")),
                        "provider": "github_actions",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = module.build_report(
        artifact_index_paths=[artifact_index_path],
        include_default_manifests=False,
    )

    assert report["status"] == "pass"
    assert report["summary"]["manifest_evidence"]["loaded"] == 1
    assert report["summary"]["artifact_index_evidence"] == {
        "loaded_indexes": 1,
        "loaded_manifests": 1,
        "release_ids": ["release-20260425"],
        "load_failures": 0,
    }
    artifact_check = next(
        check
        for check in report["checks"]
        if check["id"] == "artifact_index_evidence_ingestion"
    )
    assert artifact_check["status"] == "pass"
    assert artifact_check["details"]["path_statuses"] == {
        "source-checkout-first-proof": "validated",
    }
    assert artifact_check["details"]["artifact_index_release_ids"] == [
        "release-20260425",
    ]


def test_harvest_artifact_summary_derives_compatibility_status(tmp_path: Path) -> None:
    module = _load_module()
    harvest_path = tmp_path / "ci_artifact_harvest.json"
    harvest_path.write_text(
        json.dumps(
            {
                "schema": "agilab.ci_artifact_harvest.v1",
                "release": {"release_id": "release-20260425"},
                "artifacts": [
                    {
                        "kind": "run_manifest",
                        "path": "github-actions://ThalesGroup/agilab/runs/123/artifacts/public/run_manifest.json",
                        "payload_status": "validated",
                        "payload_summary": {
                            "path_id": "source-checkout-first-proof",
                            "status": "pass",
                            "artifact_count": 1,
                        },
                        "run_id": "ci-run-123",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = module.build_report(
        artifact_index_paths=[harvest_path],
        include_default_manifests=False,
    )

    assert report["status"] == "pass"
    assert report["summary"]["artifact_index_evidence"]["loaded_manifests"] == 1
    status_check = next(
        check
        for check in report["checks"]
        if check["id"] == "required_public_statuses"
    )
    assert status_check["details"]["manifest_evidence_statuses"] == {
        "source-checkout-first-proof": "validated",
    }


def test_failing_run_manifest_blocks_evidence_backed_status(tmp_path: Path) -> None:
    module = _load_module()
    manifest_path = _write_manifest(
        tmp_path / "external" / "run_manifest.json",
        status="fail",
        validation_status="fail",
    )

    report = module.build_report(
        manifest_paths=[manifest_path],
        include_default_manifests=False,
    )

    assert report["status"] == "fail"
    assert report["summary"]["manifest_evidence"]["failed_path_ids"] == [
        "source-checkout-first-proof",
    ]
    manifest_check = next(
        check
        for check in report["checks"]
        if check["id"] == "run_manifest_evidence_ingestion"
    )
    assert manifest_check["status"] == "fail"
    status_check = next(
        check
        for check in report["checks"]
        if check["id"] == "required_public_statuses"
    )
    assert status_check["details"]["actual_statuses"]["source-checkout-first-proof"] == "failed"
    assert status_check["details"]["mismatched"]["source-checkout-first-proof"] == {
        "expected": "validated",
        "actual": "failed",
    }


def test_main_emits_json_and_returns_success(capsys) -> None:
    module = _load_module()

    exit_code = module.main(["--compact", "--no-default-manifests"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["report"] == "Compatibility report"
    assert payload["status"] == "pass"
    assert payload["summary"]["failed"] == 0
