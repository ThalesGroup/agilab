#!/usr/bin/env python3
"""Emit executable evidence for AGILAB's architecture self-assessment."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import json
from pathlib import Path
import re
import tomllib
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "agilab.architecture_scorecard.v1"
HARDENING_GAPS_SCHEMA = "agilab.architecture_hardening_gaps.v1"
SUPPORTED_SCORE = "4.7 / 5"
SCORE_SCOPE = (
    "Excellent evidence-first workbench architecture; hardened shared/team use is go "
    "when explicit gates pass; multi-tenant production use remains outside the current score."
)


@dataclass(frozen=True, slots=True)
class ArchitectureLayerContract:
    """Allowed first-party dependencies for one independently published layer."""

    distribution: str
    import_root: str
    project: str
    allowed_internal_dependencies: frozenset[str]


ARCHITECTURE_LAYER_CONTRACTS: tuple[ArchitectureLayerContract, ...] = (
    ArchitectureLayerContract("agi-env", "agi_env", "src/agilab/core/agi-env", frozenset()),
    ArchitectureLayerContract(
        "agi-node",
        "agi_node",
        "src/agilab/core/agi-node",
        frozenset({"agi-env"}),
    ),
    ArchitectureLayerContract(
        "agi-cluster",
        "agi_cluster",
        "src/agilab/core/agi-cluster",
        frozenset({"agi-env", "agi-node"}),
    ),
    ArchitectureLayerContract(
        "agi-core",
        "agi_core",
        "src/agilab/core/agi-core",
        frozenset({"agi-env", "agi-node", "agi-cluster"}),
    ),
    ArchitectureLayerContract(
        "agi-gui",
        "agi_gui",
        "src/agilab/lib/agi-gui",
        frozenset({"agi-env"}),
    ),
    ArchitectureLayerContract(
        "agi-pages",
        "agi_pages",
        "src/agilab/lib/agi-pages",
        frozenset({"agi-gui"}),
    ),
)
INTERNAL_IMPORT_DISTRIBUTIONS: dict[str, str] = {
    contract.import_root: contract.distribution for contract in ARCHITECTURE_LAYER_CONTRACTS
}
_REQUIREMENT_NAME_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)")
_DYNAMIC_IMPORT_CALLS = frozenset({"find_spec", "import_module"})


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


def _canonicalize_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _declared_internal_dependencies(pyproject_path: Path) -> set[str]:
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    requirements = data.get("project", {}).get("dependencies", ())
    declared: set[str] = set()
    for requirement in requirements if isinstance(requirements, list) else ():
        if not isinstance(requirement, str):
            continue
        match = _REQUIREMENT_NAME_RE.match(requirement)
        if match:
            name = _canonicalize_distribution_name(match.group(1))
            if name in INTERNAL_IMPORT_DISTRIBUTIONS.values():
                declared.add(name)
    return declared


def _literal_imports(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append((node.module, node.lineno))
        elif (
            isinstance(node, ast.Call)
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            call_name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            if call_name in _DYNAMIC_IMPORT_CALLS:
                imports.append((node.args[0].value, node.lineno))
    return imports


def _architecture_import_boundary_violations(repo_root: Path) -> list[dict[str, Any]]:
    """Return disallowed or undeclared imports across published architecture layers."""

    violations: list[dict[str, Any]] = []
    for contract in ARCHITECTURE_LAYER_CONTRACTS:
        project_root = repo_root / contract.project
        pyproject_path = project_root / "pyproject.toml"
        try:
            declared = _declared_internal_dependencies(pyproject_path)
        except Exception as exc:
            violations.append(
                {
                    "distribution": contract.distribution,
                    "path": str(pyproject_path.relative_to(repo_root)),
                    "reason": "invalid package manifest",
                    "error": str(exc),
                }
            )
            continue

        for dependency in sorted(declared - contract.allowed_internal_dependencies):
            violations.append(
                {
                    "distribution": contract.distribution,
                    "path": str(pyproject_path.relative_to(repo_root)),
                    "imported_distribution": dependency,
                    "reason": "disallowed declared dependency",
                }
            )

        source_root = project_root / "src" / contract.import_root
        if not source_root.is_dir():
            violations.append(
                {
                    "distribution": contract.distribution,
                    "path": str(source_root.relative_to(repo_root)),
                    "reason": "missing package source root",
                }
            )
            continue
        for path in sorted(source_root.rglob("*.py")):
            try:
                imports = _literal_imports(path)
            except (OSError, SyntaxError, UnicodeError) as exc:
                violations.append(
                    {
                        "distribution": contract.distribution,
                        "path": str(path.relative_to(repo_root)),
                        "reason": "unreadable Python import surface",
                        "error": str(exc),
                    }
                )
                continue
            for imported_module, lineno in imports:
                imported_distribution = INTERNAL_IMPORT_DISTRIBUTIONS.get(
                    imported_module.split(".", 1)[0]
                )
                if not imported_distribution or imported_distribution == contract.distribution:
                    continue
                if imported_distribution not in contract.allowed_internal_dependencies:
                    reason = "disallowed layer import"
                elif imported_distribution not in declared:
                    reason = "undeclared internal import"
                else:
                    continue
                violations.append(
                    {
                        "distribution": contract.distribution,
                        "path": str(path.relative_to(repo_root)),
                        "line": lineno,
                        "imported_module": imported_module,
                        "imported_distribution": imported_distribution,
                        "reason": reason,
                    }
                )
    return violations


def _check_plane_boundaries(repo_root: Path) -> dict[str, Any]:
    result = _token_check(
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
    import_violations = _architecture_import_boundary_violations(repo_root)
    result["details"]["import_violations"] = import_violations
    result["evidence"].extend(
        [
            "tools/architecture_scorecard.py",
            *(f"{contract.project}/pyproject.toml" for contract in ARCHITECTURE_LAYER_CONTRACTS),
        ]
    )
    if import_violations:
        result["status"] = "fail"
        result["summary"] = "published package imports violate the executable layer contract"
    elif result["status"] == "pass":
        result["summary"] = (
            "architecture docs describe the control, payload, and evidence planes, and published "
            "package imports respect the executable dependency direction"
        )
    return result


def _check_runtime_guardrails(repo_root: Path) -> dict[str, Any]:
    return _token_check(
        repo_root,
        check_id="architecture_runtime_guardrails",
        label="Runtime fail-closed guardrails",
        pass_summary=(
            "robustness matrix covers public UI bind, cluster share, evidence manifest, "
            "notebook import, service, route, stale-state, owned child-process crash recovery, "
            "trace repair, and evidence-recovery bad states"
        ),
        fail_summary="runtime robustness matrix does not cover the expected architecture guardrails",
        required={
            "tools/robustness_matrix.py": [
                "public_streamlit_bind_without_controls_refused",
                "cluster_share_same_as_local_fails_closed",
                "missing_run_manifest_fails_verification",
                "invalid_notebook_import_fails_preflight",
                "service_unhealthy_workers_block_promotion",
                "RECOVERY_PROFILE = \"p1-recovery\"",
                "stale_runner_state_writer_is_rejected",
                "crash_partial_agent_trace_tail_is_quarantined",
                "abrupt_child_termination_observed",
                "_CHILD_SELF_EXIT_SECONDS",
                "interrupted_workflow_evidence_publish_recovers",
                "tampered_workflow_evidence_manifest_is_rejected",
            ],
            "test/test_robustness_matrix.py": [
                "test_robustness_matrix_p0_passes_against_current_contracts",
                "test_robustness_matrix_p1_recovery_passes_against_current_contracts",
                "test_robustness_matrix_all_profile_combines_fail_closed_and_recovery",
                "abrupt_child_termination_observed",
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
            "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/runtime/runtime_distribution_support.py": [
                "_remote_dask_worker_command",
                "shlex.quote",
                "tcp://{scheduler}",
            ],
            "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/deployment/deployment_remote_support.py": [
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
            "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/runtime/runtime_misc_support.py": [
                "_capacity_model_trust_error",
                "_capacity_model_manifest_error",
                "write_capacity_model_manifest",
                "trusted_root=env.resources_path",
                "is world-writable",
                "is group-writable by a shared group",
                "grants unsafe write/delete access to untrusted Windows",
                "Refusing to load unverified capacity model",
            ],
            "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/runtime/capacity_support.py": [
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
                "hardened shared/team use is go",
                "use remains outside this score",
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
