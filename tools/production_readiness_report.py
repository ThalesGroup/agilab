#!/usr/bin/env python3
"""Emit executable evidence for AGILAB's production-readiness KPI."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_SCORE = "3.0 / 5"


def _load_tool_module(name: str) -> Any:
    module_path = REPO_ROOT / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(
        f"{name}_for_production_report", module_path
    )
    if not spec or not spec.loader:
        raise RuntimeError(f"unable to load tool module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tail(text: str, *, max_lines: int = 25) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-max_lines:])


def _check_result(
    check_id: str,
    label: str,
    passed: bool,
    summary: str,
    *,
    evidence: Sequence[str] = (),
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


def _check_docs_mirror_stamp(repo_root: Path) -> dict[str, Any]:
    try:
        sync_docs_source = _load_tool_module("sync_docs_source")
        ok, message = sync_docs_source.verify_mirror_stamp(repo_root / "docs" / "source")
    except Exception as exc:
        ok, message = False, str(exc)
    return _check_result(
        "docs_mirror_stamp",
        "Docs mirror stamp",
        ok,
        message,
        evidence=["docs/.docs_source_mirror_stamp.json", "tools/sync_docs_source.py"],
    )


def _check_docs_workflow_profile(repo_root: Path) -> dict[str, Any]:
    try:
        workflow_parity = _load_tool_module("workflow_parity")
        args = SimpleNamespace(components=None, skills=None, app_path=None, worker_copy=None)
        profiles = workflow_parity._profile_commands(args)
        docs_commands = profiles.get("docs") or []
        command_details = [
            {
                "label": getattr(command, "label", ""),
                "argv": list(getattr(command, "argv", [])),
            }
            for command in docs_commands
        ]
        release_proof_tokens = [
            "tools/release_proof_report.py",
            "--check",
            "--compact",
        ]
        sphinx_tokens = [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "sphinx",
            "docs/source",
            "docs/html",
        ]
        release_proof_command = next(
            (
                command
                for command in docs_commands
                if all(token in list(getattr(command, "argv", [])) for token in release_proof_tokens)
            ),
            None,
        )
        sphinx_command = next(
            (
                command
                for command in docs_commands
                if all(token in list(getattr(command, "argv", [])) for token in sphinx_tokens)
            ),
            None,
        )
        ok = bool(release_proof_command and sphinx_command)
        summary = (
            "docs workflow parity profile checks release-proof generation and builds Sphinx"
            if ok
            else "docs workflow parity profile is missing or no longer matches the expected command"
        )
        details = {
            "commands": command_details,
            "release_proof_argv": (
                list(getattr(release_proof_command, "argv", [])) if release_proof_command else []
            ),
            "sphinx_argv": list(getattr(sphinx_command, "argv", [])) if sphinx_command else [],
        }
    except Exception as exc:
        ok = False
        summary = str(exc)
        details = {}
    return _check_result(
        "docs_workflow_parity_profile",
        "Docs workflow parity profile",
        ok,
        summary,
        evidence=["tools/workflow_parity.py"],
        details=details,
    )


def _check_production_readiness_workflow_profile(repo_root: Path) -> dict[str, Any]:
    try:
        workflow_parity = _load_tool_module("workflow_parity")
        args = SimpleNamespace(components=None, skills=None, app_path=None, worker_copy=None)
        profiles = workflow_parity._profile_commands(args)
        commands = profiles.get("production-readiness") or []
        command_details = [
            {
                "label": getattr(command, "label", ""),
                "argv": list(getattr(command, "argv", [])),
                "ensure_dirs": list(getattr(command, "ensure_dirs", [])),
                "remove_paths": list(getattr(command, "remove_paths", [])),
                "timeout_seconds": getattr(command, "timeout_seconds", None),
            }
            for command in commands
        ]
        command = commands[0] if commands else None
        argv = list(getattr(command, "argv", [])) if command else []
        ok = bool(
            command
            and "tools/production_readiness_report.py" in argv
            and "--run-docs-profile" in argv
            and "--output" in argv
            and "test-results/production-readiness.json" in argv
            and list(getattr(command, "ensure_dirs", [])) == ["test-results"]
            and "test-results/production-readiness.json"
            in list(getattr(command, "remove_paths", []))
        )
        summary = (
            "production-readiness workflow profile runs the full report and persists a JSON artifact"
            if ok
            else "production-readiness workflow profile is missing or incomplete"
        )
        details = {"commands": command_details, "argv": argv}
    except Exception as exc:
        ok = False
        summary = str(exc)
        details = {}
    return _check_result(
        "production_readiness_workflow_profile",
        "Production-readiness workflow profile",
        ok,
        summary,
        evidence=["tools/workflow_parity.py", "tools/production_readiness_report.py"],
        details=details,
    )


def _run_docs_workflow_profile(repo_root: Path) -> dict[str, Any]:
    argv = [
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "python",
        "tools/workflow_parity.py",
        "--profile",
        "docs",
    ]
    completed = subprocess.run(
        argv,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return _check_result(
        "docs_workflow_parity_run",
        "Docs workflow parity run",
        completed.returncode == 0,
        (
            "docs workflow parity profile passed"
            if completed.returncode == 0
            else "docs workflow parity profile failed"
        ),
        evidence=["tools/workflow_parity.py", "docs/source"],
        details={
            "argv": argv,
            "returncode": completed.returncode,
            "stdout_tail": _tail(completed.stdout),
            "stderr_tail": _tail(completed.stderr),
        },
    )


def _check_compatibility_matrix(repo_root: Path) -> dict[str, Any]:
    matrix_path = repo_root / "docs" / "source" / "data" / "compatibility_matrix.toml"
    required_validated_ids = {
        "published-package-route",
        "source-checkout-first-proof",
        "web-ui-local-first-proof",
        "service-mode-operator-surface",
    }
    try:
        with matrix_path.open("rb") as stream:
            payload = tomllib.load(stream)
        entries = payload.get("entries", [])
        validated = {
            entry.get("id")
            for entry in entries
            if isinstance(entry, dict) and entry.get("status") == "validated"
        }
        missing = sorted(required_validated_ids - validated)
        ok = not missing
        details = {
            "required_validated_ids": sorted(required_validated_ids),
            "validated_ids": sorted(str(item) for item in validated if item),
            "missing": missing,
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    summary = (
        "compatibility matrix includes the validated public paths used by the KPI"
        if ok
        else "compatibility matrix is missing validated public paths"
    )
    return _check_result(
        "compatibility_matrix_validated_paths",
        "Compatibility matrix validated paths",
        ok,
        summary,
        evidence=["docs/source/data/compatibility_matrix.toml"],
        details=details,
    )


def _check_service_health_contract(repo_root: Path) -> dict[str, Any]:
    cli_path = repo_root / "tools" / "service_health_check.py"
    test_path = repo_root / "test" / "test_service_health_check.py"
    try:
        cli_text = _read_text(cli_path)
        test_text = _read_text(test_path)
        required_cli = [
            'choices=("json", "prometheus")',
            "json.dumps",
            "agilab_service_health_gate_pass",
        ]
        required_tests = [
            "test_service_health_check_ok",
            "test_service_health_check_prometheus_output",
            "test_service_health_check_reads_sla_from_app_settings",
        ]
        missing_cli = [item for item in required_cli if item not in cli_text]
        missing_tests = [item for item in required_tests if item not in test_text]
        ok = not missing_cli and not missing_tests
        details = {"missing_cli_contract": missing_cli, "missing_tests": missing_tests}
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    summary = (
        "service health CLI exposes JSON/Prometheus health gates with regression coverage"
        if ok
        else "service health CLI contract or coverage is incomplete"
    )
    return _check_result(
        "service_health_json_prometheus",
        "Service health JSON/Prometheus contract",
        ok,
        summary,
        evidence=["tools/service_health_check.py", "test/test_service_health_check.py"],
        details=details,
    )


def _check_release_decision_contract(repo_root: Path) -> dict[str, Any]:
    page_path = (
        repo_root
        / "src"
        / "agilab"
        / "apps-pages"
        / "view_release_decision"
        / "src"
        / "view_release_decision"
        / "view_release_decision.py"
    )
    readme_path = (
        repo_root
        / "src"
        / "agilab"
        / "apps-pages"
        / "view_release_decision"
        / "README.md"
    )
    test_path = repo_root / "test" / "test_view_release_decision.py"
    try:
        page_text = _read_text(page_path)
        readme_text = _read_text(readme_path)
        test_text = _read_text(test_path)
        required = {
            str(page_path.relative_to(repo_root)): [
                "promotion_decision.json",
                "Export promotion decision",
                "run_manifest_gates",
                "run_manifest_summary",
                "run_manifest_import_summary",
                "imported_run_manifest_evidence",
                "manifest_index_path",
                "manifest_index_summary",
                "manifest_index_comparison",
                "manifest_index_comparison_summary",
                "evidence_bundle_comparison",
                "evidence_bundle_comparison_summary",
                "ci_artifact_harvest_summary",
                "ci_artifact_harvest_evidence",
                "CI artifact harvest evidence",
                "manifest_index.json",
                "attachment_sha256",
                "signature_status",
                "connector_registry_paths",
                "build_connector_path_registry",
                "artifact_gates",
                "metric_gates",
            ],
            str(readme_path.relative_to(repo_root)): [
                "apply explicit artifact and KPI gates",
                "gate promotion on first-proof `run_manifest.json`",
                "import external run-manifest evidence",
                "import CI artifact harvest evidence",
                "provenance-tagged with SHA-256",
                "connector path registry",
                "manifest_index.json",
                "cross-release manifest comparison",
                "cross-run evidence bundle comparison",
                "export `promotion_decision.json`",
            ],
            str(test_path.relative_to(repo_root)): [
                "test_view_release_decision_renders_promotable_candidate_and_exports_json",
                "test_view_release_decision_imports_external_manifest_for_gate",
                "test_view_release_decision_imports_ci_artifact_harvest_for_export",
                "run_manifest_gates",
                "run_manifest_summary",
                "run_manifest_import_summary",
                "ci_artifact_harvest_summary",
                "manifest_index_summary",
                "manifest_index_comparison_summary",
                "evidence_bundle_comparison_summary",
                "connector_registry_summary",
                "attachment_status",
                "attachment_sha256",
                "promotion_decision.json",
            ],
        }
        haystacks = {
            str(page_path.relative_to(repo_root)): page_text,
            str(readme_path.relative_to(repo_root)): readme_text,
            str(test_path.relative_to(repo_root)): test_text,
        }
        missing = {
            path: [needle for needle in needles if needle not in haystacks[path]]
            for path, needles in required.items()
        }
        missing = {path: values for path, values in missing.items() if values}
        ok = not missing
        details = {"missing": missing}
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    summary = (
        "release-decision page exports promotion_decision.json and manifest_index.json "
        "with connector-registry, CI artifact harvest, and provenance-tagged cross-run gates"
        if ok
        else "release-decision page export contract is incomplete"
    )
    return _check_result(
        "release_decision_promotion_export",
        "Release-decision promotion export",
        ok,
        summary,
        evidence=[
            "src/agilab/apps-pages/view_release_decision/README.md",
            "src/agilab/apps-pages/view_release_decision/src/view_release_decision/view_release_decision.py",
            "test/test_view_release_decision.py",
        ],
        details=details,
    )


def _check_security_policy(repo_root: Path) -> dict[str, Any]:
    security_path = repo_root / "SECURITY.md"
    try:
        text = _read_text(security_path)
        required = [
            "## Supported Versions",
            "## Reporting a Vulnerability",
            "## Coordinated Disclosure",
            "## Security Updates",
            "## Hardening Checklist",
        ]
        missing = [item for item in required if item not in text]
        ok = not missing
        details = {"missing_sections": missing}
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    summary = (
        "SECURITY.md documents disclosure, update, support, and hardening expectations"
        if ok
        else "SECURITY.md is missing production-readiness security sections"
    )
    return _check_result(
        "security_disclosure_hardening",
        "Security disclosure and hardening",
        ok,
        summary,
        evidence=["SECURITY.md"],
        details=details,
    )


def _check_security_adoption_gate(repo_root: Path) -> dict[str, Any]:
    required = {
        "tools/workflow_parity.py": [
            "security-adoption",
            "_security_adoption_profile",
            "tools/security_adoption_check.py",
            "test-results/security-check.json",
            "AGILAB_SECURITY_CHECK_STRICT=1",
        ],
        "tools/security_adoption_check.py": [
            'STRICT_ENV_VAR = "AGILAB_SECURITY_CHECK_STRICT"',
            "--strict",
            "--profile",
            "security_check.build_report",
        ],
        "test/test_workflow_parity.py": [
            "security_adoption",
            "tools/security_adoption_check.py",
            "test-results/security-check.json",
        ],
        "docs/source/security-adoption.rst": [
            "workflow_parity.py --profile security-adoption",
            "AGILAB_SECURITY_CHECK_STRICT=1",
            "Use strict mode when missing controls must fail the gate",
        ],
    }
    missing = _missing_required_tokens(repo_root, required)
    ok = not missing
    summary = (
        "security-adoption workflow profile persists a reviewable security-check artifact and supports strict gating"
        if ok
        else "security-adoption workflow profile or strict-gate documentation is incomplete"
    )
    return _check_result(
        "security_adoption_strict_gate",
        "Security-adoption strict gate",
        ok,
        summary,
        evidence=list(required),
        details={"missing": missing},
    )


def _check_profile_supply_chain_gate(repo_root: Path) -> dict[str, Any]:
    required = {
        "tools/profile_supply_chain_scan.py": [
            "PROFILE_EXTRAS",
            "DEFAULT_PROFILES",
            "pip-audit",
            "cyclonedx-py",
            "write_pip_audit_requirements",
            "--profile",
            "--run",
        ],
        "test/test_profile_supply_chain_scan.py": [
            "test_cli_prints_all_profile_scan_plan",
            "test_write_pip_audit_requirements_removes_local_editables",
            "pip-audit",
            "cyclonedx-py",
        ],
        "src/agilab/security_check.py": [
            "supply_chain_artifacts",
            "tools/profile_supply_chain_scan.py --profile all --run",
        ],
        "docs/source/security-adoption.rst": [
            "tools/profile_supply_chain_scan.py --profile all --run",
        ],
        "README.md": [
            "tools/profile_supply_chain_scan.py",
        ],
    }
    missing = _missing_required_tokens(repo_root, required)
    ok = not missing
    summary = (
        "profile-specific pip-audit and CycloneDX SBOM evidence is planned, tested, and linked from adoption guidance"
        if ok
        else "profile-specific supply-chain evidence gate is incomplete"
    )
    return _check_result(
        "profile_supply_chain_scan_gate",
        "Profile supply-chain scan gate",
        ok,
        summary,
        evidence=list(required),
        details={"missing": missing},
    )


def _check_public_ui_bind_guard(repo_root: Path) -> dict[str, Any]:
    required = {
        "src/agilab/ui_public_bind_guard.py": [
            "EXPOSED_UI_HOSTS",
            "PUBLIC_BIND_OK_ENV",
            "AGILAB_PUBLIC_BIND_OK",
            "PUBLIC_BIND_CONTROL_ENVS",
            "PublicBindPolicyError",
            "public_bind_has_controls",
            "enforce_public_bind_policy",
        ],
        "test/test_ui_public_bind_guard.py": [
            "test_public_bind_requires_explicit_ok_and_auth_or_tls_indicator",
            "test_direct_streamlit_public_bind_is_refused_without_controls",
            "test_direct_streamlit_public_bind_is_allowed_with_controls",
            "AGILAB_TLS_TERMINATED",
        ],
        "src/agilab/security_check.py": [
            "ui_network_exposure",
            "AGILAB_PUBLIC_BIND_OK",
            "auth/TLS",
        ],
        "docs/source/environment.rst": [
            "AGILAB_PUBLIC_BIND_OK",
            "AGILAB_TLS_TERMINATED",
        ],
    }
    missing = _missing_required_tokens(repo_root, required)
    ok = not missing
    summary = (
        "public Streamlit binds require explicit operator acknowledgement plus an auth/TLS indicator and regression coverage"
        if ok
        else "public UI bind guard contract is incomplete"
    )
    return _check_result(
        "public_ui_bind_guard",
        "Public UI bind guard",
        ok,
        summary,
        evidence=list(required),
        details={"missing": missing},
    )


def _check_cluster_share_fail_fast(repo_root: Path) -> dict[str, Any]:
    required = {
        "src/agilab/security_check.py": [
            "cluster_share_isolation",
            "Cluster share is the same path as the local share.",
            "do not silently degrade to localshare",
        ],
        "src/agilab/orchestrate_cluster.py": [
            "Cluster mode needs `AGI_CLUSTER_SHARE`",
            "Fix the cluster share before enabling cluster mode",
        ],
        "src/agilab/core/agi-env/test/test_agi_env.py": [
            "test_cluster_share_same_as_local_share_raises",
            "must not fall back to localshare",
            "Cluster-enabled apps must fail fast",
        ],
        "test/test_security_check.py": [
            "cluster_share_isolation",
            "same_as_local_share",
        ],
        "docs/source/faq.rst": [
            "requires an explicit usable cluster share",
            "distinct from the local share",
            "instead of silently",
        ],
        "docs/source/distributed-workers.rst": [
            "Keep cluster share and local share conceptually separate",
            "not silently on local-only",
        ],
    }
    missing = _missing_required_tokens(repo_root, required)
    ok = not missing
    summary = (
        "cluster mode is documented and tested to fail fast unless a distinct usable cluster share exists"
        if ok
        else "cluster-share fail-fast contract is incomplete"
    )
    return _check_result(
        "cluster_share_fail_fast",
        "Cluster-share fail-fast contract",
        ok,
        summary,
        evidence=list(required),
        details={"missing": missing},
    )


def _check_production_boundary_docs(repo_root: Path) -> dict[str, Any]:
    required = {
        "README.md": [
            "AGILAB complements MLflow and production MLOps platforms",
            "Not safe as-is",
            "Sole production MLOps control plane",
            "not production MLOps claims",
        ],
        "SECURITY.md": [
            "Not recommended as-is",
            "production ML serving",
            "only production MLOps control plane",
            "Hardening Checklist",
        ],
        "docs/source/security-adoption.rst": [
            "No-go as a standalone production platform",
            "Public Streamlit exposure",
            "sole MLOps control plane",
        ],
        "docs/source/agilab-mlops-positioning.rst": [
            "not as a production MLOps platform",
            "not a production MLOps certification",
        ],
        "docs/source/compatibility-matrix.rst": [
            "tools/production_readiness_report.py --compact",
        ],
    }
    missing = _missing_required_tokens(repo_root, required)
    ok = not missing
    summary = (
        "public docs consistently present AGILAB as a controlled experimentation workbench, not standalone production MLOps"
        if ok
        else "production boundary documentation is incomplete or inconsistent"
    )
    return _check_result(
        "production_boundary_docs",
        "Production boundary documentation",
        ok,
        summary,
        evidence=list(required),
        details={"missing": missing},
    )


def build_report(*, repo_root: Path = REPO_ROOT, run_docs_profile: bool = False) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    checks = [
        _check_docs_mirror_stamp(repo_root),
        _check_docs_workflow_profile(repo_root),
        _check_production_readiness_workflow_profile(repo_root),
        _check_compatibility_matrix(repo_root),
        _check_service_health_contract(repo_root),
        _check_release_decision_contract(repo_root),
        _check_security_policy(repo_root),
        _check_security_adoption_gate(repo_root),
        _check_profile_supply_chain_gate(repo_root),
        _check_public_ui_bind_guard(repo_root),
        _check_cluster_share_fail_fast(repo_root),
        _check_production_boundary_docs(repo_root),
    ]
    if run_docs_profile:
        checks.append(_run_docs_workflow_profile(repo_root))

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "kpi": "Production readiness",
        "supported_score": SUPPORTED_SCORE,
        "status": "pass" if failed == 0 else "fail",
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "docs_profile_executed": run_docs_profile,
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit executable evidence for AGILAB's production-readiness KPI."
    )
    parser.add_argument(
        "--run-docs-profile",
        action="store_true",
        help="Also run the docs workflow parity Sphinx build instead of only checking its command contract.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON without indentation.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON artifact path to write in addition to stdout.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = build_report(run_docs_profile=args.run_docs_profile)
    if args.output is not None:
        output = args.output.expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    stdout_payload = (
        json.dumps(report, sort_keys=True, separators=(",", ":"))
        if args.compact
        else json.dumps(report, indent=2, sort_keys=True)
    )
    print(stdout_payload)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
