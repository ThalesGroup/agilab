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
import subprocess
import tomllib
from typing import Any, Mapping, Sequence

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "agilab.security_hygiene.v1"
PIP_AUDIT_COMMAND = "pip-audit --format json --output pip-audit.json"
SBOM_COMMAND = "cyclonedx-py environment --output-format JSON --output-file sbom-cyclonedx.json"
SERVICE_QUEUE_FILES = (
    "src/agilab/core/agi-node/src/agi_node/agi_dispatcher/base_worker_service_support.py",
    "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/service/service_lifecycle_support.py",
    "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/service/service_state_support.py",
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
MAPBOX_SECRET_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_-])sk\.[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])")
SYNTHETIC_SECRET_ALLOW_MARKER = "agilab-secret-scan: allow-synthetic-mapbox-token"


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


def _artifact_check_result(
    check_id: str,
    label: str,
    provided: bool,
    valid: bool,
    summary: str,
    *,
    required: bool,
    evidence: Sequence[str] = (),
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not provided:
        status = "fail" if required else "skipped"
    else:
        status = "pass" if valid else "fail"
    return {
        "id": check_id,
        "label": label,
        "status": status,
        "summary": summary,
        "evidence": list(evidence),
        "details": {
            "provided": provided,
            "required": required,
            **(details or {}),
        },
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


def _validate_pip_audit_payload(
    payload: dict[str, Any] | list[Any] | None,
    *,
    require_inventory: bool = False,
    expected_inventory: Mapping[str, str] | None = None,
) -> tuple[int | None, str | None]:
    if payload is None:
        return None, "payload is missing"
    if isinstance(payload, dict):
        dependencies = payload.get("dependencies")
        if not isinstance(dependencies, list):
            return None, "top-level dependencies must be a list"
    elif isinstance(payload, list):
        dependencies = payload
    else:
        return None, "top-level payload must be an object or dependency list"

    if require_inventory and not dependencies:
        return None, "dependencies must contain at least one scanned dependency"

    total = 0
    inventory: dict[str, str] = {}
    for dependency_index, dependency in enumerate(dependencies):
        if not isinstance(dependency, dict):
            return None, f"dependencies[{dependency_index}] must be an object"
        for field in ("name", "version"):
            if not isinstance(dependency.get(field), str) or not dependency[field].strip():
                return None, f"dependencies[{dependency_index}].{field} must be a non-empty string"
        identity, identity_error = _canonical_package_identity(
            dependency["name"],
            dependency["version"],
            label=f"dependencies[{dependency_index}]",
        )
        if identity_error is not None or identity is None:
            return None, identity_error
        name, version = identity
        if name in inventory:
            return None, f"pip-audit inventory contains duplicate package {name}"
        inventory[name] = version
        vulnerabilities = dependency.get("vulns")
        if not isinstance(vulnerabilities, list):
            return None, f"dependencies[{dependency_index}].vulns must be a list"
        for vulnerability_index, vulnerability in enumerate(vulnerabilities):
            prefix = f"dependencies[{dependency_index}].vulns[{vulnerability_index}]"
            if not isinstance(vulnerability, dict):
                return None, f"{prefix} must be an object"
            if not isinstance(vulnerability.get("id"), str) or not vulnerability["id"].strip():
                return None, f"{prefix}.id must be a non-empty string"
            for list_field in ("fix_versions", "aliases"):
                values = vulnerability.get(list_field)
                if not isinstance(values, list) or not all(
                    isinstance(value, str) and value.strip() for value in values
                ):
                    return None, f"{prefix}.{list_field} must be a string list"
            if not isinstance(vulnerability.get("description"), str):
                return None, f"{prefix}.description must be a string"
        total += len(vulnerabilities)
    if expected_inventory is not None:
        inventory_error = _inventory_binding_error(
            expected_inventory,
            inventory,
            label="pip-audit",
        )
        if inventory_error is not None:
            return None, inventory_error
    return total, None


def _pip_audit_vulnerability_count(payload: dict[str, Any] | list[Any] | None) -> int | None:
    count, _error = _validate_pip_audit_payload(payload)
    return count


def _component_count(payload: dict[str, Any] | list[Any] | None) -> int | None:
    if isinstance(payload, dict) and isinstance(payload.get("components"), list):
        return len(payload["components"])
    return None


def _canonical_package_identity(
    name: Any,
    version: Any,
    *,
    label: str,
) -> tuple[tuple[str, str] | None, str | None]:
    if not isinstance(name, str) or not name.strip():
        return None, f"{label}.name must be a non-empty string"
    if not isinstance(version, str) or not version.strip():
        return None, f"{label}.version must be a non-empty string"
    try:
        normalized_version = str(Version(version.strip()))
    except InvalidVersion:
        return None, f"{label}.version is invalid"
    return (str(canonicalize_name(name.strip())), normalized_version), None


def _inventory_binding_error(
    expected: Mapping[str, str],
    actual: Mapping[str, str],
    *,
    label: str,
) -> str | None:
    if dict(expected) == dict(actual):
        return None
    missing = sorted(set(expected) - set(actual))
    unexpected = sorted(set(actual) - set(expected))
    mismatched = sorted(
        name
        for name in set(expected) & set(actual)
        if expected[name] != actual[name]
    )
    details: list[str] = []
    if missing:
        details.append("missing=" + ",".join(missing))
    if unexpected:
        details.append("unexpected=" + ",".join(unexpected))
    if mismatched:
        details.append("version_mismatch=" + ",".join(mismatched))
    return f"{label} inventory does not match scan requirements ({'; '.join(details)})"


EditableRequirement = tuple[int, str, str]
ScanRequirementsInventory = tuple[
    dict[str, str],
    dict[str, str],
    tuple[EditableRequirement, ...],
]


def _scan_requirements_inventory(
    path: Path,
) -> tuple[ScanRequirementsInventory | None, str | None]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return None, str(exc)

    environment = default_environment()
    inventory: dict[str, str] = {}
    complete_inventory: dict[str, str] = {}
    editables: list[EditableRequirement] = []
    for line_number, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("--hash"):
            continue
        if raw_line[:1].isspace():
            return None, f"requirements line {line_number} has an unsupported continuation"
        requirement_text = stripped.removesuffix("\\").strip()
        editable_prefix = next(
            (
                prefix
                for prefix in ("-e ", "--editable ")
                if requirement_text.startswith(prefix)
            ),
            None,
        )
        if editable_prefix is not None:
            editable_value = requirement_text[len(editable_prefix) :].strip()
            editable_path, separator, marker_text = editable_value.partition(";")
            editable_path = editable_path.strip()
            if not editable_path or not (
                editable_path == "." or editable_path.startswith("./")
            ):
                return None, (
                    f"requirements line {line_number} must use a relative local "
                    "editable path"
                )
            if separator:
                try:
                    marker_requirement = Requirement(
                        f"editable-placeholder==0; {marker_text.strip()}"
                    )
                except InvalidRequirement as exc:
                    return None, f"requirements line {line_number} is invalid: {exc}"
                if marker_requirement.marker is None:
                    return None, f"requirements line {line_number} has an empty marker"
                marker_requirement.marker.evaluate(environment)
            rendered_requirement = requirement_text
            editables.append((line_number, editable_path, rendered_requirement))
            continue
        if requirement_text.startswith("-"):
            return None, f"requirements line {line_number} uses an unsupported directive"
        try:
            requirement = Requirement(requirement_text)
        except InvalidRequirement as exc:
            return None, f"requirements line {line_number} is invalid: {exc}"
        if requirement.url is not None:
            return None, f"requirements line {line_number} must identify a pinned package"
        specifiers = list(requirement.specifier)
        if (
            len(specifiers) != 1
            or specifiers[0].operator not in {"==", "==="}
            or "*" in specifiers[0].version
        ):
            return None, f"requirements line {line_number} must use one exact version pin"
        identity, identity_error = _canonical_package_identity(
            requirement.name,
            specifiers[0].version,
            label=f"requirements line {line_number}",
        )
        if identity_error is not None or identity is None:
            return None, identity_error
        name, version = identity
        if name in complete_inventory:
            return None, f"requirements inventory contains duplicate package {name}"
        complete_inventory[name] = version
        if requirement.marker is None or requirement.marker.evaluate(environment):
            inventory[name] = version
    if not complete_inventory:
        return None, "scan requirements must contain at least one pinned package"
    return (inventory, complete_inventory, tuple(editables)), None


def _matched_local_editable_line(
    component: Mapping[str, Any],
    expected_editables: Sequence[EditableRequirement],
) -> int | None:
    references = component.get("externalReferences")
    if not (
        set(component)
        == {"bom-ref", "description", "externalReferences", "name", "type"}
        and component.get("type") == "library"
        and component.get("name") == "unknown"
        and isinstance(references, list)
        and len(references) == 1
        and isinstance(references[0], dict)
        and set(references[0]) == {"comment", "type", "url"}
        and references[0].get("type") == "other"
        and references[0].get("comment") == "explicit local path"
    ):
        return None
    for line_number, editable_path, rendered_requirement in expected_editables:
        if (
            component.get("bom-ref") == f"requirements-L{line_number}"
            and component.get("description")
            == f"requirements line {line_number}: {rendered_requirement}"
            and references[0].get("url") == editable_path
        ):
            return line_number
    return None


def _validate_sbom_payload(
    payload: dict[str, Any] | list[Any] | None,
    *,
    require_inventory: bool = False,
    expected_inventory: Mapping[str, str] | None = None,
    expected_editables: Sequence[EditableRequirement] = (),
) -> tuple[int | None, str | None]:
    if not isinstance(payload, dict) or payload.get("bomFormat") != "CycloneDX":
        return None, "top-level payload must be a CycloneDX object"
    components = payload.get("components")
    if not isinstance(components, list):
        return None, "top-level components must be a list"
    if require_inventory and not components:
        return None, "components must contain at least one scanned component"

    inventory: dict[str, str] = {}
    matched_editable_lines: set[int] = set()
    for component_index, component in enumerate(components):
        label = f"components[{component_index}]"
        if not isinstance(component, dict):
            return None, f"{label} must be an object"
        if component.get("name") == "unknown":
            editable_line = _matched_local_editable_line(component, expected_editables)
            if editable_line is None:
                return None, f"{label} is not bound to an active editable requirement"
            if editable_line in matched_editable_lines:
                return None, f"{label} duplicates editable requirements line {editable_line}"
            matched_editable_lines.add(editable_line)
            continue
        identity, identity_error = _canonical_package_identity(
            component.get("name"),
            component.get("version"),
            label=label,
        )
        if identity_error is not None or identity is None:
            return None, identity_error
        name, version = identity
        purl = component.get("purl")
        purl_match = re.fullmatch(r"pkg:pypi/([^@?#]+)@([^?#]+)(?:\?[^#]*)?(?:#.*)?", str(purl or ""))
        if purl_match is None:
            return None, f"{label}.purl must identify a versioned PyPI package"
        purl_identity, purl_error = _canonical_package_identity(
            purl_match.group(1),
            purl_match.group(2),
            label=f"{label}.purl",
        )
        if purl_error is not None or purl_identity != identity:
            return None, purl_error or f"{label}.purl does not match component identity"
        if name in inventory:
            return None, f"SBOM inventory contains duplicate package {name}"
        inventory[name] = version
    if expected_inventory is not None:
        inventory_error = _inventory_binding_error(
            expected_inventory,
            inventory,
            label="SBOM",
        )
        if inventory_error is not None:
            return None, inventory_error
    expected_editable_lines = {line_number for line_number, _, _ in expected_editables}
    if matched_editable_lines != expected_editable_lines:
        missing = sorted(expected_editable_lines - matched_editable_lines)
        unexpected = sorted(matched_editable_lines - expected_editable_lines)
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(str(line) for line in missing))
        if unexpected:
            details.append("unexpected=" + ",".join(str(line) for line in unexpected))
        return None, (
            "SBOM editable inventory does not match scan requirements "
            f"({'; '.join(details)})"
        )
    return len(components), None


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
        and "build-library-packages:" in text
        and "build-agilab:" in text
        and "Download immutable ${{ matrix.package }} distribution artifact" in text
        and "Download immutable agilab distribution artifact" in text
        and "uses: pypa/gh-action-pypi-publish@" in text
        and "PYPI_API_TOKEN" not in text
        and "PYPI_SECRET" not in text
        and "PYPI_TOKEN" not in text
        and "password:" not in text
    )
    return _check_result(
        "pypi_trusted_publishing_only",
        "PyPI publishing requires OIDC Trusted Publishing",
        passed,
        "The PyPI workflow builds without credentials and publishes immutable artifacts with OIDC",
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


def _tracked_source_secret_pattern_check(repo_root: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        return _check_result(
            "tracked_source_secret_patterns_absent",
            "Tracked source is free of recognized secret-token patterns",
            False,
            "Tracked-source secret scan could not enumerate git-controlled files",
            evidence=["git ls-files"],
            details={"error": str(exc), "matches": []},
        )

    matches: list[str] = []
    allowed_synthetic: list[str] = []
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        relative_path = Path(os.fsdecode(raw_path))
        source_path = repo_root / relative_path
        if not source_path.is_file():
            continue
        text = source_path.read_text(encoding="utf-8", errors="ignore")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in MAPBOX_SECRET_TOKEN_RE.finditer(line):
                is_synthetic_test = (
                    relative_path.parts
                    and relative_path.parts[0] in {"test", "tests"}
                    and SYNTHETIC_SECRET_ALLOW_MARKER in line
                    and "SYNTHETIC" in match.group(0).upper()
                )
                location = f"{relative_path.as_posix()}:{line_number}:mapbox_secret_token"
                if is_synthetic_test:
                    allowed_synthetic.append(location)
                else:
                    matches.append(location)
    return _check_result(
        "tracked_source_secret_patterns_absent",
        "Tracked source is free of recognized secret-token patterns",
        not matches,
        "Tracked files contain no Mapbox secret-token pattern outside explicitly marked synthetic tests",
        evidence=["git ls-files"],
        details={
            "matches": matches,
            "allowed_synthetic_matches": allowed_synthetic,
            "allow_marker": SYNTHETIC_SECRET_ALLOW_MARKER,
        },
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
        "Go for controlled local use without additional platform hardening",
        "Go for hardened shared/team use when the hardening gate passes",
        "clean strict ``agilab security-check`` report",
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
        "SECURITY.md separates controlled local use, hardened shared/team go gates, and no-go production/multi-tenant use",
        evidence=["SECURITY.md"],
        details={"missing_tokens": missing},
    )


def _security_release_process_check(security_text: str) -> dict[str, Any]:
    required_tokens = [
        "Security Release Process",
        "GitHub Security Advisories",
        "CVE",
        "GHSA",
        "affected versions",
        "fixed versions",
        "mitigation guidance",
    ]
    missing = [token for token in required_tokens if token not in security_text]
    return _check_result(
        "security_release_process_documented",
        "Security release process is documented",
        not missing,
        "SECURITY.md explains advisory, CVE/GHSA, mitigation, and release-note handling",
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


def _security_issue_template_intake_check(repo_root: Path) -> dict[str, Any]:
    issue_template_root = repo_root / ".github" / "ISSUE_TEMPLATE"
    documents = {
        ".github/ISSUE_TEMPLATE/bug_report.md": _read_text(
            issue_template_root / "bug_report.md"
        ),
        ".github/ISSUE_TEMPLATE/feature_request.md": _read_text(
            issue_template_root / "feature_request.md"
        ),
        ".github/ISSUE_TEMPLATE/config.yml": _read_text(issue_template_root / "config.yml"),
    }
    required = {
        ".github/ISSUE_TEMPLATE/bug_report.md": [
            "Do not report suspected vulnerabilities here",
            "GitHub Private Vulnerability Reporting",
            "sharing exploit details publicly",
        ],
        ".github/ISSUE_TEMPLATE/feature_request.md": [
            "Do not report suspected vulnerabilities here",
            "GitHub Private Vulnerability Reporting",
            "sharing exploit details publicly",
        ],
        ".github/ISSUE_TEMPLATE/config.yml": [
            "Security vulnerability",
            "security/advisories/new",
            "Do not share exploit details in public issues",
        ],
    }
    missing = [
        f"{path}: {token}"
        for path, tokens in required.items()
        for token in tokens
        if token not in documents.get(path, "")
    ]
    return _check_result(
        "issue_templates_route_security_reports_privately",
        "Issue templates route security reports privately",
        not missing,
        "Issue templates warn against public vulnerability disclosure and expose a private report link",
        evidence=list(documents),
        details={"missing_tokens": missing},
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
    hotfix_tag = re.sub(r"^(\d{4}\.\d{1,2}\.\d{1,2})\.(\d+)$", r"\1_\2", project_version)
    if hotfix_tag != project_version:
        accepted_bases.append(hotfix_tag)
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
    hotfix_tag = re.sub(r"^(\d{4}\.\d{1,2}\.\d{1,2})\.(\d+)$", r"\1_\2", project_version)
    if hotfix_tag != project_version:
        patterns.insert(0, f"v{hotfix_tag}[-N]")
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
        "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/deployment/deployment_prepare_support.py",
    ]
    texts = {relative_path: _read_text(repo_root / relative_path) for relative_path in files}
    forbidden_tokens = [
        "curl -fsSL https://ollama.com/install.sh | sh",
        "curl -LsSf https://astral.sh/uv/install.sh | sh",
        "irm https://astral.sh/uv/install.ps1 | iex",
        "https://astral.sh/uv/install.sh",
        "https://astral.sh/uv/install.ps1",
        "https://ollama.com/install.sh",
        "Homebrew/install/HEAD/install.sh",
        '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"',
    ]
    combined = "\n".join(texts.values())
    found_forbidden = [token for token in forbidden_tokens if token in combined]
    required_tokens = [
        "run_remote_shell_installer()",
        "expected_sha256",
        "UV_INSTALLER_SHA256",
        "OLLAMA_INSTALLER_SHA256",
        "HOMEBREW_INSTALLER_SHA256",
        "_staged_uv_install_command",
        "_staged_uv_powershell_install_command",
        "curl --proto '=https' --tlsv1.2",
        "Get-FileHash -Algorithm SHA256",
        "sha256sum",
    ]
    missing_required = [token for token in required_tokens if token not in combined]
    return _check_result(
        "remote_installers_are_staged_before_execution",
        "Remote installer scripts are pinned and verified before execution",
        not found_forbidden and not missing_required,
        "Installer bootstrap uses immutable upstream assets and verifies pinned SHA-256 digests before execution",
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
    relative_path = "src/agilab/core/agi-env/src/agi_env/runtime/execution_support.py"
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
    scan_requirements: Path | None = None,
    require_scan_artifacts: bool = False,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    security_path = repo_root / "SECURITY.md"
    pyproject_path = repo_root / "pyproject.toml"
    lock_path = repo_root / "uv.lock"
    supply_chain_tool = repo_root / "tools" / "supply_chain_integrity_report.py"
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
                "tools/supply_chain_integrity_report.py",
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
        _tracked_source_secret_pattern_check(repo_root),
        _release_evidence_scope_check(repo_root, security_text),
        _adoption_profile_check(security_text),
        _security_release_process_check(security_text),
        _security_disclosure_channel_check(repo_root, security_text),
        _security_issue_template_intake_check(repo_root),
        _external_apps_repository_policy_check(repo_root, security_text),
        _supply_chain_profile_evidence_check(security_text),
        _release_proof_freshness_check(repo_root, security_text),
        _remote_installer_staging_check(repo_root),
        _installer_dry_run_profile_check(repo_root),
        _central_command_runner_shell_gate_check(repo_root),
        _github_actions_sha_pin_check(repo_root),
    ]

    requirements_inventory: dict[str, str] | None = None
    requirements_sbom_inventory: dict[str, str] | None = None
    requirements_editables: tuple[EditableRequirement, ...] = ()
    requirements_error: str | None = None
    if scan_requirements is not None:
        parsed_requirements, requirements_error = _scan_requirements_inventory(
            scan_requirements
        )
        if parsed_requirements is not None:
            (
                requirements_inventory,
                requirements_sbom_inventory,
                requirements_editables,
            ) = parsed_requirements
    elif require_scan_artifacts:
        requirements_error = "required scan requirements manifest was not provided"

    pip_audit_provided, pip_audit_payload, pip_audit_error = _read_json_artifact(pip_audit_json)
    vulnerability_count, pip_audit_schema_error = _validate_pip_audit_payload(
        pip_audit_payload,
        require_inventory=require_scan_artifacts,
        expected_inventory=requirements_inventory,
    )
    pip_audit_error = pip_audit_error or requirements_error or pip_audit_schema_error
    pip_audit_valid = pip_audit_provided and pip_audit_error is None and vulnerability_count == 0
    if not pip_audit_provided:
        pip_audit_summary = (
            "required pip-audit artifact was not provided"
            if require_scan_artifacts
            else "pip-audit artifact not provided; check skipped"
        )
    elif pip_audit_error is not None or vulnerability_count is None:
        pip_audit_summary = "pip-audit artifact is invalid"
    elif vulnerability_count:
        pip_audit_summary = (
            f"pip-audit artifact reports {vulnerability_count} known vulnerabilities"
        )
    else:
        pip_audit_summary = "pip-audit artifact is valid"
    checks.append(
        _artifact_check_result(
            "pip_audit_artifact_valid",
            "pip-audit artifact is present and vulnerability-free",
            pip_audit_provided,
            pip_audit_valid,
            pip_audit_summary,
            required=require_scan_artifacts,
            evidence=[str(pip_audit_json)] if pip_audit_json is not None else [],
            details={
                "error": pip_audit_error,
                "vulnerability_count": vulnerability_count,
                "expected_dependency_count": (
                    len(requirements_inventory)
                    if requirements_inventory is not None
                    else None
                ),
                "scan_requirements": (
                    str(scan_requirements) if scan_requirements is not None else None
                ),
            },
        )
    )

    sbom_provided, sbom_payload, sbom_error = _read_json_artifact(sbom_json)
    component_count, sbom_schema_error = _validate_sbom_payload(
        sbom_payload,
        require_inventory=require_scan_artifacts,
        expected_inventory=requirements_sbom_inventory,
        expected_editables=requirements_editables,
    )
    sbom_error = sbom_error or requirements_error or sbom_schema_error
    sbom_valid = sbom_error is None and component_count is not None
    if not sbom_provided:
        sbom_summary = (
            "required SBOM artifact was not provided"
            if require_scan_artifacts
            else "SBOM artifact not provided; check skipped"
        )
    elif sbom_valid:
        sbom_summary = "CycloneDX SBOM artifact is valid"
    else:
        sbom_summary = "SBOM artifact is invalid"
    checks.append(
        _artifact_check_result(
            "sbom_artifact_valid",
            "CycloneDX SBOM artifact is present and valid",
            sbom_provided,
            sbom_valid,
            sbom_summary,
            required=require_scan_artifacts,
            evidence=[str(sbom_json)] if sbom_json is not None else [],
            details={
                "error": sbom_error,
                "component_count": component_count,
                "expected_dependency_count": (
                    len(requirements_sbom_inventory)
                    if requirements_sbom_inventory is not None
                    else None
                ),
                "scan_requirements": (
                    str(scan_requirements) if scan_requirements is not None else None
                ),
            },
        )
    )

    passed = [check for check in checks if check["status"] == "pass"]
    failed = [check for check in checks if check["status"] == "fail"]
    skipped = [check for check in checks if check["status"] == "skipped"]
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
            "passed": len(passed),
            "failed": len(failed),
            "skipped": len(skipped),
            "scan_artifacts_required": require_scan_artifacts,
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
    parser.add_argument(
        "--scan-requirements",
        type=Path,
        default=None,
        help=(
            "Independent marker-aware pinned requirements inventory used to bind "
            "pip-audit and CycloneDX evidence."
        ),
    )
    parser.add_argument(
        "--require-scan-artifacts",
        action="store_true",
        help="Fail when pip-audit or CycloneDX SBOM evidence is missing.",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report(
        pip_audit_json=args.pip_audit_json,
        sbom_json=args.sbom_json,
        scan_requirements=args.scan_requirements,
        require_scan_artifacts=args.require_scan_artifacts,
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
