#!/usr/bin/env python3
"""Emit AGILAB dependency and security hygiene evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import tomllib
from typing import Any, Mapping, Sequence


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


def _read_toml_artifact(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:
        return None, str(exc)


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
    pipe_to_shell_pattern = re.compile(
        r"\|\s*(?:sudo\s+)?(?:/usr/bin/env\s+)?(?:/bin/)?(?:ba)?sh(?:\s|$)"
    )
    report_path = Path(__file__).resolve()
    for base in ("src/agilab", "tools", "install.sh"):
        path = repo_root / base
        if path.is_file():
            candidates = [path]
        elif path.is_dir():
            candidates = []
            for dirpath, dirnames, filenames in os.walk(path):
                dirnames[:] = sorted(
                    dirname
                    for dirname in dirnames
                    if dirname not in SCAN_EXCLUDED_PARTS
                )
                root = Path(dirpath)
                for filename in sorted(filenames):
                    candidates.append(root / filename)
        else:
            candidates = []
        for candidate in candidates:
            if candidate == report_path:
                continue
            if candidate.suffix not in {".py", ".sh"} and candidate.name != "install.sh":
                continue
            text = _read_text(candidate)
            if "shell=True" in text or pipe_to_shell_pattern.search(text):
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


def _coverage_upload_gate_check(repo_root: Path) -> dict[str, Any]:
    workflow = repo_root / ".github" / "workflows" / "coverage.yml"
    text = _read_text(workflow)
    upload_steps = [
        "Upload agi-env coverage to Codecov",
        "Upload agi-node coverage to Codecov",
        "Upload agi-cluster coverage to Codecov",
        "Upload agi-gui coverage to Codecov",
        "Upload repo-wide agilab coverage to Codecov",
    ]
    failing_steps: list[str] = []
    for step_name in upload_steps:
        marker = f"      - name: {step_name}"
        start = text.find(marker)
        if start == -1:
            failing_steps.append(step_name)
            continue
        next_step = text.find("\n      - name:", start + len(marker))
        block = text[start : next_step if next_step != -1 else len(text)]
        if (
            "uses: codecov/codecov-action@" not in block
            or "# v6" not in block
            or "continue-on-error: true" in block
            or "fail_ci_if_error: true" not in block
        ):
            failing_steps.append(step_name)

    return _check_result(
        "codecov_uploads_are_blocking_gates",
        "Coverage uploads are blocking CI gates",
        not failing_steps,
        "Codecov upload failures fail the coverage workflow instead of being treated as advisory",
        evidence=[".github/workflows/coverage.yml"],
        details={"checked_steps": upload_steps, "failing_steps": failing_steps},
    )


def _local_secret_storage_policy_check(repo_root: Path, security_text: str) -> dict[str, Any]:
    environment_doc = _read_text(repo_root / "docs" / "source" / "environment.rst")
    required_tokens = [
        "~/.agilab/.env",
        "developer convenience",
        "OS keyrings",
        "enterprise vaults",
        "short-lived environment variables",
        "plaintext",
    ]
    combined = f"{security_text}\n{environment_doc}"
    missing = [token for token in required_tokens if token not in combined]
    return _check_result(
        "local_secret_storage_is_developer_only",
        "Local plaintext secret storage is scoped to developer use",
        not missing,
        "Local .env persistence is documented as plaintext developer convenience, with keyring/vault/short-lived alternatives for sensitive use",
        evidence=["SECURITY.md", "docs/source/environment.rst"],
        details={"missing_tokens": missing},
    )


def _release_evidence_scope_check(repo_root: Path, security_text: str) -> dict[str, Any]:
    release_proof = _read_text(repo_root / "docs" / "source" / "release-proof.rst")
    required_tokens = [
        "bounded evidence",
        "not production certification",
        "does not certify",
        "long-running production operations",
    ]
    combined = f"{security_text}\n{release_proof}"
    missing = [token for token in required_tokens if token not in combined]
    return _check_result(
        "release_evidence_scope_is_bounded",
        "Release evidence does not claim production certification",
        not missing,
        "Public release proof is documented as bounded evidence, not certification for production operations",
        evidence=["SECURITY.md", "docs/source/release-proof.rst"],
        details={"missing_tokens": missing},
    )


def _adoption_profile_check(security_text: str) -> dict[str, Any]:
    required_tokens = [
        "trusted-operator experimentation workbench",
        "Recommended use without additional platform hardening",
        "Conditional use only after hardening",
        "Not recommended as-is",
        "public exposure without authentication, TLS, and sandboxing",
        "Multi-tenant service use",
        "production ML serving",
    ]
    missing = [token for token in required_tokens if token not in security_text]
    return _check_result(
        "adoption_profile_go_no_go_documented",
        "Security adoption profile is documented",
        not missing,
        "SECURITY.md separates recommended sandbox use, conditional shared use, and no-go production/multi-tenant use",
        evidence=["SECURITY.md"],
        details={"missing_tokens": missing},
    )


def _security_disclosure_channel_check(repo_root: Path, security_text: str) -> dict[str, Any]:
    documents = {
        "SECURITY.md": security_text,
        "README.md": _read_text(repo_root / "README.md"),
        "README.pypi.md": _read_text(repo_root / "README.pypi.md"),
        "ADOPTION.md": _read_text(repo_root / "ADOPTION.md"),
        "docs/source/security-adoption.rst": _read_text(
            repo_root / "docs" / "source" / "security-adoption.rst"
        ),
    }
    forbidden_tokens = [
        "Open a GitHub issue with the title",
        "open a GitHub issue with the title",
        "[SECURITY]",
    ]
    stale_hits = [
        f"{path}: {token}"
        for path, text in documents.items()
        for token in forbidden_tokens
        if token in text
    ]
    required = {
        "SECURITY.md": [
            "Do **not** open a public GitHub issue",
            "GitHub Private Vulnerability Reporting",
        ],
        "README.md": ["Do not use public GitHub issues", "SECURITY.md"],
        "README.pypi.md": ["Do not use public GitHub issues", "SECURITY.md"],
        "ADOPTION.md": ["Do not use public GitHub issues", "SECURITY.md"],
        "docs/source/security-adoption.rst": [
            "Do not use public GitHub issues",
            "GitHub Private Vulnerability Reporting",
            "Public GitHub issues are for non-sensitive product bugs",
        ],
    }
    missing = [
        f"{path}: {token}"
        for path, tokens in required.items()
        for token in tokens
        if token not in documents.get(path, "")
    ]
    return _check_result(
        "security_disclosure_channel_consistency",
        "Security disclosure channel is private and consistent",
        not stale_hits and not missing,
        "Public docs and package READMEs route suspected vulnerabilities to private reporting, not public issues",
        evidence=list(documents),
        details={"stale_public_issue_tokens": stale_hits, "missing_tokens": missing},
    )


def _external_apps_repository_policy_check(repo_root: Path, security_text: str) -> dict[str, Any]:
    service_paths = _read_text(repo_root / "docs" / "source" / "service_mode_and_paths.md")
    quick_start = _read_text(repo_root / "docs" / "source" / "quick-start.rst")
    combined = f"{security_text}\n{service_paths}\n{quick_start}"
    required_tokens = [
        "APPS_REPOSITORY",
        "executable-code trust boundary",
        "explicit allowlist",
        "commit SHA",
        "immutable tag",
        "reject floating branches",
        "scan the repository",
    ]
    missing = [token for token in required_tokens if token not in combined]
    return _check_result(
        "external_apps_repository_trust_boundary",
        "External apps repository trust boundary is documented",
        not missing,
        "External apps repositories are documented as executable code that must be allowlisted, pinned, reviewed, and scanned for shared use",
        evidence=[
            "SECURITY.md",
            "docs/source/service_mode_and_paths.md",
            "docs/source/quick-start.rst",
        ],
        details={"missing_tokens": missing},
    )


def _supply_chain_profile_evidence_check(security_text: str) -> dict[str, Any]:
    required_tokens = [
        "CycloneDX SBOM",
        "pip-audit",
        "actual install profile",
        "base CLI",
        "agilab[ui]",
        "MLflow/tracking",
        "offline/local-LLM",
        "worker/cluster extras",
    ]
    missing = [token for token in required_tokens if token not in security_text]
    return _check_result(
        "supply_chain_profile_evidence_documented",
        "Per-profile supply-chain evidence is documented",
        not missing,
        "SECURITY.md requires SBOM and pip-audit evidence for the actual enabled install profiles",
        evidence=["SECURITY.md"],
        details={
            "missing_tokens": missing,
            "pip_audit_command": PIP_AUDIT_COMMAND,
            "sbom_command": SBOM_COMMAND,
        },
    )


def _release_tag_matches_version(manifest_tag: str, project_version: str) -> bool:
    if not manifest_tag or not project_version:
        return False
    accepted_bases = [project_version]
    post_base = re.sub(r"\.post\d+\Z", "", project_version)
    if post_base != project_version:
        accepted_bases.append(post_base)
    return any(
        re.fullmatch(rf"{re.escape(f'v{base}')}(?:-\d+)?", manifest_tag) is not None
        for base in accepted_bases
    )


def _accepted_release_tag_pattern(project_version: str) -> str:
    if not project_version:
        return ""
    patterns = [f"v{project_version}[-N]"]
    post_base = re.sub(r"\.post\d+\Z", "", project_version)
    if post_base != project_version:
        patterns.append(f"v{post_base}[-N]")
    return " or ".join(patterns)


def _version_key(version: str) -> tuple[int, ...] | None:
    parts = re.findall(r"\d+", version)
    if not parts:
        return None
    return tuple(int(part) for part in parts)


def _version_not_newer(left: str, right: str) -> bool:
    left_key = _version_key(left)
    right_key = _version_key(right)
    if left_key is None or right_key is None:
        return left == right
    max_len = max(len(left_key), len(right_key))
    padded_left = left_key + (0,) * (max_len - len(left_key))
    padded_right = right_key + (0,) * (max_len - len(right_key))
    return padded_left <= padded_right


def _release_package_spec(package_name: str, package_version: str, release: Mapping[str, Any]) -> str:
    package_extras = release.get("package_extras", []) or []
    extras = []
    if isinstance(package_extras, list):
        extras = [str(extra).strip() for extra in package_extras if str(extra).strip()]
    package_spec_name = f"{package_name}[{','.join(sorted(extras))}]" if extras else package_name
    return f"{package_spec_name}=={package_version}"


def _release_proof_freshness_check(repo_root: Path, security_text: str) -> dict[str, Any]:
    pyproject, pyproject_error = _read_toml_artifact(repo_root / "pyproject.toml")
    manifest, manifest_error = _read_toml_artifact(
        repo_root / "docs" / "source" / "data" / "release_proof.toml"
    )
    release_proof = _read_text(repo_root / "docs" / "source" / "release-proof.rst")
    release_manifest = _read_text(
        repo_root / "docs" / "source" / "data" / "release_proof.toml"
    )
    combined = f"{security_text}\n{release_proof}\n{release_manifest}"
    required_tokens = [
        "GitHub tag",
        "PyPI version",
        "release-proof",
        "republish the documentation",
        "docs-source guard",
        "github_release_tag",
        "package_version",
    ]
    missing = [token for token in required_tokens if token not in combined]
    project_version = str(((pyproject or {}).get("project") or {}).get("version") or "")
    release = (manifest or {}).get("release") or {}
    package_name = str(release.get("package_name") or "")
    manifest_version = str(release.get("package_version") or "")
    manifest_tag = str(release.get("github_release_tag") or "")
    package_spec = _release_package_spec(package_name, manifest_version, release)
    expected_tag = f"v{manifest_version}" if manifest_version else ""
    version_aligned = (
        bool(project_version)
        and bool(manifest_version)
        and _version_not_newer(manifest_version, project_version)
    )
    tag_aligned = _release_tag_matches_version(manifest_tag, manifest_version)
    rendered_page_aligned = (
        bool(package_name)
        and bool(manifest_version)
        and package_spec in release_proof
        and bool(manifest_tag)
        and manifest_tag in release_proof
    )
    return _check_result(
        "release_proof_freshness_policy_documented",
        "Release-proof freshness policy is documented",
        not missing
        and pyproject_error is None
        and manifest_error is None
        and version_aligned
        and tag_aligned
        and rendered_page_aligned,
        "SECURITY.md and release-proof data preserve the requirement that public proof stays aligned with GitHub tag and PyPI version",
        evidence=[
            "SECURITY.md",
            "docs/source/release-proof.rst",
            "docs/source/data/release_proof.toml",
        ],
        details={
            "missing_tokens": missing,
            "pyproject_error": pyproject_error,
            "manifest_error": manifest_error,
            "pyproject_version": project_version,
            "manifest_package_version": manifest_version,
            "manifest_package_spec": package_spec,
            "expected_github_release_tag": expected_tag,
            "manifest_github_release_tag": manifest_tag,
            "accepted_github_release_tag_pattern": _accepted_release_tag_pattern(
                manifest_version
            ),
            "version_aligned": version_aligned,
            "exact_source_version_match": project_version == manifest_version,
            "tag_aligned": tag_aligned,
            "rendered_page_aligned": rendered_page_aligned,
        },
    )


def _remote_installer_staging_check(repo_root: Path) -> dict[str, Any]:
    files = [
        "install.sh",
        "tools/install_enduser.sh",
        "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/deployment_prepare_support.py",
    ]
    texts = {relative_path: _read_text(repo_root / relative_path) for relative_path in files}
    forbidden_tokens = [
        "curl -fsSL https://ollama.com/install.sh | sh",
        "curl -LsSf https://astral.sh/uv/install.sh | sh",
        "irm https://astral.sh/uv/install.ps1 | iex",
        '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"',
    ]
    combined = "\n".join(texts.values())
    found_forbidden = [token for token in forbidden_tokens if token in combined]
    required_tokens = [
        "run_remote_shell_installer()",
        'run_remote_shell_installer "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh" "Homebrew" "/bin/bash"',
        "_staged_uv_install_command",
        "_staged_uv_powershell_install_command",
        "curl --proto '=https' --tlsv1.2",
    ]
    missing_required = [token for token in required_tokens if token not in combined]
    return _check_result(
        "remote_installers_are_staged_before_execution",
        "Remote installer scripts are staged before execution",
        not found_forbidden and not missing_required,
        "Installer bootstrap downloads remote scripts to temporary files before executing them instead of piping network responses directly to shells",
        evidence=files,
        details={
            "found_forbidden_tokens": found_forbidden,
            "missing_required_tokens": missing_required,
        },
    )


def _installer_dry_run_profile_check(repo_root: Path) -> dict[str, Any]:
    files = ["install.sh", "tools/install_enduser.sh"]
    texts = {relative_path: _read_text(repo_root / relative_path) for relative_path in files}
    missing: dict[str, list[str]] = {}
    for relative_path, text in texts.items():
        required_tokens = [
            "--dry-run",
            "dry-run plan",
            "steps_would_run:",
            "print_dry_run_plan",
        ]
        missing_tokens = [token for token in required_tokens if token not in text]
        if missing_tokens:
            missing[relative_path] = missing_tokens

    return _check_result(
        "installers_expose_dry_run_profiles",
        "Installers expose dry-run planning profiles",
        not missing,
        "Root and end-user installers can print an installation plan before installing dependencies or mutating environments",
        evidence=files,
        details={"missing_tokens": missing},
    )


def _central_command_runner_shell_gate_check(repo_root: Path) -> dict[str, Any]:
    relative_path = "src/agilab/core/agi-env/src/agi_env/execution_support.py"
    text = _read_text(repo_root / relative_path)
    required_tokens = [
        "def _command_requires_shell",
        "allow_shell: bool = True",
        "Shell syntax is not allowed for this command",
        "asyncio.create_subprocess_exec",
        "asyncio.create_subprocess_shell",
    ]
    forbidden_tokens = [
        "except SUBPROCESS_FALLBACK_EXCEPTIONS",
    ]
    missing = [token for token in required_tokens if token not in text]
    found_forbidden = [token for token in forbidden_tokens if token in text]
    return _check_result(
        "central_command_runner_shell_fallback_is_syntax_gated",
        "Central command runner gates shell execution",
        not missing and not found_forbidden,
        "Plain commands run through argv execution; shell execution is reserved for explicit shell syntax and can be disabled",
        evidence=[relative_path],
        details={
            "missing_tokens": missing,
            "found_forbidden_tokens": found_forbidden,
        },
    )


def _github_actions_sha_pin_check(repo_root: Path) -> dict[str, Any]:
    workflow_root = repo_root / ".github" / "workflows"
    uses_pattern = re.compile(r"uses:\s+([^\s#]+)@([^\s#]+)(?:\s+#\s*(\S+))?")
    sha_pattern = re.compile(r"^[0-9a-f]{40}$")
    unpinned: list[str] = []
    checked: list[str] = []
    for path in sorted(workflow_root.glob("*.*ml")):
        text = _read_text(path)
        for line_number, line in enumerate(text.splitlines(), start=1):
            match = uses_pattern.search(line)
            if not match:
                continue
            action, ref, comment_ref = match.groups()
            rel = path.relative_to(repo_root)
            checked.append(f"{rel}:{line_number}:{action}@{ref}")
            if not sha_pattern.match(ref) or not comment_ref:
                unpinned.append(f"{rel}:{line_number}:{action}@{ref}")

    return _check_result(
        "github_actions_are_pinned_to_commit_sha",
        "GitHub Actions are pinned to immutable SHAs",
        not unpinned,
        "Workflow third-party actions use full commit SHAs with the human-readable source tag/branch retained as a comment",
        evidence=[str(path.relative_to(repo_root)) for path in sorted(workflow_root.glob("*.*ml"))],
        details={
            "checked_actions": checked,
            "unpinned_actions": unpinned,
        },
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
    security_text_lower = security_text.lower()

    checks = [
        _check_result(
            "security_policy_present",
            "Security policy is present",
            security_path.is_file()
            and "github private vulnerability reporting" in security_text_lower,
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
        _coverage_upload_gate_check(repo_root),
        _local_secret_storage_policy_check(repo_root, security_text),
        _release_evidence_scope_check(repo_root, security_text),
        _adoption_profile_check(security_text),
        _security_disclosure_channel_check(repo_root, security_text),
        _external_apps_repository_policy_check(repo_root, security_text),
        _supply_chain_profile_evidence_check(security_text),
        _release_proof_freshness_check(repo_root, security_text),
        _remote_installer_staging_check(repo_root),
        _installer_dry_run_profile_check(repo_root),
        _central_command_runner_shell_gate_check(repo_root),
        _github_actions_sha_pin_check(repo_root),
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
