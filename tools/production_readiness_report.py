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
from typing import Any, Sequence
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
        docs_command = docs_commands[0] if docs_commands else None
        argv = list(getattr(docs_command, "argv", [])) if docs_command else []
        required_tokens = [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "sphinx",
            "docs/source",
            "docs/html",
        ]
        ok = bool(docs_command) and all(token in argv for token in required_tokens)
        summary = (
            "docs workflow parity profile matches the expected Sphinx build command"
            if ok
            else "docs workflow parity profile is missing or no longer matches the expected command"
        )
        details = {"argv": argv, "label": getattr(docs_command, "label", "")}
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
                "manifest_index.json",
                "attachment_sha256",
                "signature_status",
                "artifact_gates",
                "metric_gates",
            ],
            str(readme_path.relative_to(repo_root)): [
                "apply explicit artifact and KPI gates",
                "gate promotion on first-proof `run_manifest.json`",
                "import external run-manifest evidence",
                "provenance-tagged with SHA-256",
                "manifest_index.json",
                "cross-release manifest comparison",
                "cross-run evidence bundle comparison",
                "export `promotion_decision.json`",
            ],
            str(test_path.relative_to(repo_root)): [
                "test_view_release_decision_renders_promotable_candidate_and_exports_json",
                "test_view_release_decision_imports_external_manifest_for_gate",
                "run_manifest_gates",
                "run_manifest_summary",
                "run_manifest_import_summary",
                "manifest_index_summary",
                "manifest_index_comparison_summary",
                "evidence_bundle_comparison_summary",
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
        "with provenance-tagged cross-run manifest/artifact/KPI/reduce gates"
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


def build_report(*, repo_root: Path = REPO_ROOT, run_docs_profile: bool = False) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    checks = [
        _check_docs_mirror_stamp(repo_root),
        _check_docs_workflow_profile(repo_root),
        _check_compatibility_matrix(repo_root),
        _check_service_health_contract(repo_root),
        _check_release_decision_contract(repo_root),
        _check_security_policy(repo_root),
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = build_report(run_docs_profile=args.run_docs_profile)
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
