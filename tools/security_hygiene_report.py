#!/usr/bin/env python3
"""Emit AGILAB dependency and security hygiene evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "agilab.security_hygiene.v1"
PIP_AUDIT_COMMAND = "pip-audit --format json --output pip-audit.json"
SBOM_COMMAND = "cyclonedx-py environment --output-format JSON --output-file sbom-cyclonedx.json"
SERVICE_QUEUE_FILES = (
    "src/agilab/core/agi-node/src/agi_node/agi_dispatcher/base_worker_service_support.py",
    "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/service_lifecycle_support.py",
    "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/service_state_support.py",
)
SCAN_EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "site-packages",
    "test",
}


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


def _optional_check_result(
    check_id: str,
    label: str,
    provided: bool,
    valid: bool,
    summary: str,
    *,
    evidence: Sequence[str] = (),
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = "pass" if (not provided or valid) else "fail"
    return {
        "id": check_id,
        "label": label,
        "status": status,
        "summary": summary,
        "evidence": list(evidence),
        "details": {"provided": provided, **(details or {})},
    }


def _read_json_artifact(path: Path | None) -> tuple[bool, dict[str, Any] | list[Any] | None, str | None]:
    if path is None:
        return False, None, None
    try:
        return True, json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:
        return True, None, str(exc)


def _pip_audit_vulnerability_count(payload: dict[str, Any] | list[Any] | None) -> int | None:
    if payload is None:
        return None
    if isinstance(payload, dict) and isinstance(payload.get("vulnerabilities"), list):
        return len(payload["vulnerabilities"])
    if isinstance(payload, dict) and isinstance(payload.get("dependencies"), list):
        total = 0
        for dependency in payload["dependencies"]:
            if isinstance(dependency, dict) and isinstance(dependency.get("vulns"), list):
                total += len(dependency["vulns"])
        return total
    if isinstance(payload, list):
        total = 0
        for dependency in payload:
            if isinstance(dependency, dict) and isinstance(dependency.get("vulns"), list):
                total += len(dependency["vulns"])
        return total
    return None


def _component_count(payload: dict[str, Any] | list[Any] | None) -> int | None:
    if isinstance(payload, dict) and isinstance(payload.get("components"), list):
        return len(payload["components"])
    return None


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore") if path.is_file() else ""


def _service_queue_payload_check(repo_root: Path) -> dict[str, Any]:
    texts = {
        relative_path: _read_text(repo_root / relative_path)
        for relative_path in SERVICE_QUEUE_FILES
    }
    combined = "\n".join(texts.values())
    passed = (
        "pickle.load" not in combined
        and "pickle.dump" not in combined
        and ".task.json" in combined
        and "LEGACY_SERVICE_TASK_SUFFIX" in combined
        and "rejecting legacy pickle service task" in combined
        and "json.dump" in texts[SERVICE_QUEUE_FILES[1]]
    )
    return _check_result(
        "service_queue_json_payload_contract",
        "Service queue uses non-executable JSON payloads",
        passed,
        "Service tasks are JSON files; legacy pickle task files are quarantined without deserialization",
        evidence=list(SERVICE_QUEUE_FILES),
        details={
            "forbidden_tokens": ["pickle.load", "pickle.dump"],
            "task_suffix": ".task.json",
            "legacy_suffix": ".task.pkl",
        },
    )


def _shell_execution_boundary_check(repo_root: Path, security_text: str) -> dict[str, Any]:
    shell_true_hits: list[str] = []
    for base in ("src/agilab", "tools", "install.sh"):
        path = repo_root / base
        if path.is_file():
            candidates = [path]
        elif path.is_dir():
            candidates = sorted(
                candidate
                for candidate in path.rglob("*")
                if candidate.is_file()
                and SCAN_EXCLUDED_PARTS.isdisjoint(candidate.relative_to(repo_root).parts)
            )
        else:
            candidates = []
        for candidate in candidates:
            if candidate == Path(__file__).resolve():
                continue
            if candidate.suffix not in {".py", ".sh"} and candidate.name != "install.sh":
                continue
            text = _read_text(candidate)
            if "shell=True" in text or "| sh" in text:
                shell_true_hits.append(str(candidate.relative_to(repo_root)))

    documented = (
        "trusted-operator boundary" in security_text
        and "shell execution" in security_text
        and "install profiles" in security_text
    )
    return _check_result(
        "operator_shell_install_boundary_documented",
        "Shell and installer boundary is documented",
        documented,
        "Shell execution and powerful installer profiles are documented as trusted-operator surfaces",
        evidence=["SECURITY.md"],
        details={"shell_or_pipe_shell_files": sorted(set(shell_true_hits))},
    )


def _pypi_trusted_publishing_check(repo_root: Path) -> dict[str, Any]:
    workflow = repo_root / ".github" / "workflows" / "pypi-publish.yaml"
    text = _read_text(workflow)
    passed = (
        "id-token: write" in text
        and "PYPI_TRUSTED_PUBLISHING" in text
        and "PyPI publication requires Trusted Publishing/OIDC" in text
        and "PYPI_API_TOKEN" not in text
        and "PYPI_SECRET" not in text
        and "PYPI_TOKEN" not in text
        and "password:" not in text
    )
    return _check_result(
        "pypi_trusted_publishing_only",
        "PyPI publishing requires OIDC Trusted Publishing",
        passed,
        "The PyPI workflow refuses long-lived token publishing and requires Trusted Publishing/OIDC",
        evidence=[".github/workflows/pypi-publish.yaml"],
    )


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    pip_audit_json: Path | None = None,
    sbom_json: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    security_path = repo_root / "SECURITY.md"
    pyproject_path = repo_root / "pyproject.toml"
    lock_path = repo_root / "uv.lock"
    supply_chain_tool = repo_root / "tools" / "supply_chain_attestation_report.py"
    public_proof_tool = repo_root / "tools" / "public_proof_scenarios.py"

    security_text = security_path.read_text(encoding="utf-8") if security_path.is_file() else ""
    pyproject_text = pyproject_path.read_text(encoding="utf-8") if pyproject_path.is_file() else ""
    checks = [
        _check_result(
            "security_policy_present",
            "Security policy is present",
            security_path.is_file()
            and "GitHub private vulnerability reporting" in security_text,
            "SECURITY.md exposes the private vulnerability reporting channel",
            evidence=["SECURITY.md"],
        ),
        _check_result(
            "locked_dependencies_present",
            "Dependency lockfile is present",
            pyproject_path.is_file() and lock_path.is_file(),
            "pyproject.toml and uv.lock are both present",
            evidence=["pyproject.toml", "uv.lock"],
        ),
        _check_result(
            "optional_ai_dependency_boundary",
            "Optional AI dependency boundary is explicit",
            "[project.optional-dependencies]" in pyproject_text
            and "ai =" in pyproject_text
            and "openai" in pyproject_text,
            "OpenAI client dependency is kept behind the optional ai extra",
            evidence=["pyproject.toml"],
        ),
        _check_result(
            "supply_chain_static_evidence_present",
            "Supply-chain static evidence is present",
            supply_chain_tool.is_file() and public_proof_tool.is_file(),
            "supply-chain and public-proof evidence tools are available",
            evidence=[
                "tools/supply_chain_attestation_report.py",
                "tools/public_proof_scenarios.py",
            ],
        ),
        _check_result(
            "security_scan_commands_documented",
            "Security scan commands are documented",
            True,
            "SBOM and pip-audit commands are part of the security hygiene contract",
            details={
                "pip_audit_command": PIP_AUDIT_COMMAND,
                "sbom_command": SBOM_COMMAND,
            },
        ),
        _service_queue_payload_check(repo_root),
        _shell_execution_boundary_check(repo_root, security_text),
        _pypi_trusted_publishing_check(repo_root),
    ]

    pip_audit_provided, pip_audit_payload, pip_audit_error = _read_json_artifact(pip_audit_json)
    vulnerability_count = _pip_audit_vulnerability_count(pip_audit_payload)
    checks.append(
        _optional_check_result(
            "pip_audit_artifact_valid",
            "pip-audit artifact is valid when provided",
            pip_audit_provided,
            pip_audit_error is None and vulnerability_count is not None,
            "pip-audit artifact is valid"
            if pip_audit_provided and pip_audit_error is None
            else "pip-audit artifact not provided; command contract is documented"
            if not pip_audit_provided
            else "pip-audit artifact is invalid",
            evidence=[str(pip_audit_json)] if pip_audit_json is not None else [],
            details={
                "error": pip_audit_error,
                "vulnerability_count": vulnerability_count,
            },
        )
    )

    sbom_provided, sbom_payload, sbom_error = _read_json_artifact(sbom_json)
    component_count = _component_count(sbom_payload)
    sbom_valid = (
        sbom_error is None
        and isinstance(sbom_payload, dict)
        and (
            sbom_payload.get("bomFormat") == "CycloneDX"
            or component_count is not None
        )
    )
    checks.append(
        _optional_check_result(
            "sbom_artifact_valid",
            "SBOM artifact is valid when provided",
            sbom_provided,
            sbom_valid,
            "CycloneDX SBOM artifact is valid"
            if sbom_provided and sbom_valid
            else "SBOM artifact not provided; command contract is documented"
            if not sbom_provided
            else "SBOM artifact is invalid",
            evidence=[str(sbom_json)] if sbom_json is not None else [],
            details={
                "error": sbom_error,
                "component_count": component_count,
            },
        )
    )

    failed = [check for check in checks if check["status"] != "pass"]
    return {
        "report": "AGILAB security hygiene report",
        "schema": SCHEMA,
        "status": "pass" if not failed else "fail",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "python": platform.python_version(),
        },
        "summary": {
            "check_count": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
            "pip_audit_artifact_provided": pip_audit_provided,
            "sbom_artifact_provided": sbom_provided,
            "pip_audit_command": PIP_AUDIT_COMMAND,
            "sbom_command": SBOM_COMMAND,
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit dependency and security hygiene evidence for AGILAB."
    )
    parser.add_argument("--pip-audit-json", type=Path, default=None)
    parser.add_argument("--sbom-json", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report(
        pip_audit_json=args.pip_audit_json,
        sbom_json=args.sbom_json,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
