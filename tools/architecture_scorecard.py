#!/usr/bin/env python3
"""Emit executable evidence for AGILAB's architecture self-assessment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "agilab.architecture_scorecard.v1"
HARDENING_GAPS_SCHEMA = "agilab.architecture_hardening_gaps.v1"
SUPPORTED_SCORE = "4.7 / 5"
SCORE_SCOPE = (
    "Excellent evidence-first workbench architecture; conditional for shared "
    "or multi-tenant production use."
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _missing_required_tokens(
    repo_root: Path,
    required: Mapping[str, Sequence[str]],
) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    for relative_path, tokens in required.items():
        path = repo_root / relative_path
        try:
            text = _read_text(path)
        except Exception as exc:
            missing[relative_path] = [f"<unable to read: {exc}>"]
            continue
        missing_tokens = [token for token in tokens if token not in text]
        if missing_tokens:
            missing[relative_path] = missing_tokens
    return missing


def _check_result(
    check_id: str,
    label: str,
    passed: bool,
    summary: str,
    *,
    evidence: Sequence[str],
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "pass" if passed else "fail",
        "summary": summary,
        "evidence": list(evidence),
        "details": details or {},
    }


def _token_check(
    repo_root: Path,
    *,
    check_id: str,
    label: str,
    pass_summary: str,
    fail_summary: str,
    required: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    missing = _missing_required_tokens(repo_root, required)
    return _check_result(
        check_id,
        label,
        not missing,
        pass_summary if not missing else fail_summary,
        evidence=list(required),
        details={"missing": missing},
    )


def _check_plane_boundaries(repo_root: Path) -> dict[str, Any]:
    return _token_check(
        repo_root,
        check_id="architecture_plane_boundaries",
        label="Control/payload/evidence plane boundaries",
        pass_summary=(
            "architecture docs describe the visible control path, manager/worker split, "
            "and evidence handoff"
        ),
        fail_summary="architecture boundary documentation is incomplete",
        required={
            "docs/source/architecture-five-minutes.rst": [
                "one public control path stays visible",
                "manager prepares and dispatches work; workers",
                "Artifacts, run manifests",
            ],
            "docs/source/architecture.rst": [
                "Execution back-plane boundary",
                "Global AGILAB architecture",
            ],
        },
    )


def _check_runtime_guardrails(repo_root: Path) -> dict[str, Any]:
    return _token_check(
        repo_root,
        check_id="architecture_runtime_guardrails",
        label="Runtime fail-closed guardrails",
        pass_summary=(
            "robustness matrix covers public UI bind, cluster share, evidence manifest, "
            "notebook import, service, and route bad states"
        ),
        fail_summary="runtime robustness matrix does not cover the expected architecture guardrails",
        required={
            "tools/robustness_matrix.py": [
                "public_streamlit_bind_without_controls_refused",
                "cluster_share_same_as_local_fails_closed",
                "missing_run_manifest_fails_verification",
                "invalid_notebook_import_fails_preflight",
                "service_unhealthy_workers_block_promotion",
            ],
            "test/test_robustness_matrix.py": [
                "test_robustness_matrix_p0_passes_against_current_contracts",
            ],
        },
    )


def _check_supply_chain_and_release(repo_root: Path) -> dict[str, Any]:
    return _token_check(
        repo_root,
        check_id="architecture_supply_chain_release_proof",
        label="Supply-chain and release-proof architecture",
        pass_summary=(
            "release architecture is backed by package contracts, SBOM/audit planning, "
            "provenance, and release-proof checks"
        ),
        fail_summary="release and supply-chain architecture evidence is incomplete",
        required={
            "tools/profile_supply_chain_scan.py": [
                "pip-audit",
                "cyclonedx-py",
                "write_pip_audit_requirements",
            ],
            "tools/release_proof_report.py": [
                "--check-github-runs",
                "release_proof.toml",
            ],
            ".github/workflows/pypi-publish.yaml": [
                "pypi-provenance-evidence",
                "publish-release-assets",
                "trusted publishing",
            ],
        },
    )


def _check_remote_execution_hardening(repo_root: Path) -> dict[str, Any]:
    return _token_check(
        repo_root,
        check_id="architecture_remote_execution_hardening",
        label="Remote execution command hardening",
        pass_summary=(
            "remote worker command construction quotes dynamic scheduler, environment, "
            "and worker-path fragments"
        ),
        fail_summary="remote execution command construction is not fully evidenced as quoted",
        required={
            "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/runtime_distribution_support.py": [
                "_remote_dask_worker_command",
                "shlex.quote",
                "tcp://{scheduler}",
            ],
            "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/deployment_remote_support.py": [
                "_remote_arg",
                "_remote_command",
                "_remote_share_mount_command",
            ],
            "test/test_architecture_scorecard.py": [
                "test_remote_dask_worker_command_quotes_dynamic_fragments",
            ],
        },
    )


def _check_capacity_model_trust_boundary(repo_root: Path) -> dict[str, Any]:
    return _token_check(
        repo_root,
        check_id="architecture_capacity_model_trust_boundary",
        label="Capacity model trust boundary",
        pass_summary=(
            "capacity predictor pickle loading is constrained to a trusted resource root, "
            "rejects world-writable files, and verifies a SHA-256 sidecar manifest"
        ),
        fail_summary="capacity predictor pickle trust boundary is incomplete",
        required={
            "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/runtime_misc_support.py": [
                "_capacity_model_trust_error",
                "_capacity_model_manifest_error",
                "write_capacity_model_manifest",
                "trusted_root=env.resources_path",
                "model file is world-writable",
                "Refusing to load unverified capacity model",
            ],
            "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/capacity_support.py": [
                "write_capacity_model_manifest",
            ],
            "src/agilab/core/agi-env/src/agi_env/resources/.agilab/balancer_model.pkl.sha256.json": [
                "agilab.capacity_model_manifest.v1",
                "digest_sha256",
                "sha256",
            ],
            "test/test_architecture_scorecard.py": [
                "test_capacity_predictor_refuses_untrusted_pickle_path",
                "test_capacity_predictor_refuses_signature_mismatch",
            ],
            "src/agilab/core/test/test_agi_distributor_runtime_misc_support.py": [
                "test_load_capacity_predictor_rejects_signature_mismatch",
            ],
            "src/agilab/core/test/test_agi_distributor_capacity_support.py": [
                "test_train_capacity_missing_and_success",
                "CAPACITY_MODEL_MANIFEST_SCHEMA",
            ],
        },
    )


def _check_claim_boundary(repo_root: Path) -> dict[str, Any]:
    return _token_check(
        repo_root,
        check_id="architecture_claim_boundary",
        label="Architecture claim boundary",
        pass_summary=(
            "public docs keep the score scoped to an evidence-first workbench and avoid "
            "multi-tenant production overclaiming"
        ),
        fail_summary="architecture score docs overclaim or omit the production boundary",
        required={
            "docs/source/architecture-scorecard.rst": [
                "self-assessment",
                "not a production MLOps certification",
                "not a multi-tenant production platform score",
                "conditional for shared or",
                "multi-tenant production use",
            ],
            "docs/source/agilab-mlops-positioning.rst": [
                "not as a production MLOps platform",
            ],
        },
    )


def _check_hardening_gap_register(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "docs" / "source" / "data" / "architecture_hardening_gaps.json"
    required_gap_ids = {
        "tenant-isolation",
        "enterprise-auth-rbac",
        "production-rollback",
        "regulated-serving",
        "capacity-model-signature",
    }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        gaps = payload.get("gaps", [])
        gap_ids = {gap.get("id") for gap in gaps if isinstance(gap, dict)}
        missing_ids = sorted(required_gap_ids - gap_ids)
        invalid_gaps = [
            gap.get("id", "<missing-id>")
            for gap in gaps
            if not isinstance(gap, dict)
            or not gap.get("severity")
            or not gap.get("status")
            or not gap.get("surface")
            or not gap.get("production_boundary")
            or not gap.get("evidence_required")
        ]
        ok = (
            payload.get("schema") == HARDENING_GAPS_SCHEMA
            and payload.get("supported_score") == SUPPORTED_SCORE
            and isinstance(gaps, list)
            and not missing_ids
            and not invalid_gaps
        )
        details = {
            "schema": payload.get("schema"),
            "supported_score": payload.get("supported_score"),
            "gap_ids": sorted(gap_ids),
            "gap_statuses": {
                str(gap.get("id")): gap.get("status")
                for gap in gaps
                if isinstance(gap, dict) and gap.get("id")
            },
            "missing_ids": missing_ids,
            "invalid_gaps": invalid_gaps,
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc), "gap_ids": [], "missing_ids": sorted(required_gap_ids)}

    return _check_result(
        "architecture_hardening_gap_register",
        "Architecture hardening gap register",
        ok,
        (
            "remaining production-hardening gaps are machine-readable, scoped, and tied to evidence requirements"
            if ok
            else "architecture hardening gap register is missing or incomplete"
        ),
        evidence=["docs/source/data/architecture_hardening_gaps.json"],
        details=details,
    )


def build_report(*, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    checks = [
        _check_plane_boundaries(repo_root),
        _check_runtime_guardrails(repo_root),
        _check_supply_chain_and_release(repo_root),
        _check_remote_execution_hardening(repo_root),
        _check_capacity_model_trust_boundary(repo_root),
        _check_hardening_gap_register(repo_root),
        _check_claim_boundary(repo_root),
    ]
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "schema": SCHEMA,
        "kpi": "Architecture scorecard",
        "supported_score": SUPPORTED_SCORE,
        "score_scope": SCORE_SCOPE,
        "status": "pass" if failed == 0 else "fail",
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "score_boundary": (
                "self-assessment from repository evidence; not external certification"
            ),
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON.")
    parser.add_argument("--output", type=Path, help="Optional JSON output path.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = build_report()
    text = json.dumps(report, separators=(",", ":") if args.compact else None, indent=None if args.compact else 2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
