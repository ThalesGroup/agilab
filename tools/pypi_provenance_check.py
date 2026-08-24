#!/usr/bin/env python3
"""Validate PyPI Integrity API provenance identity for AGILAB packages.

PyPI is the trusted authority for cryptographic attestation verification. This
tool fail-closes on malformed Integrity API data and binds the publisher and
decoded in-toto subject to PyPI's distribution filename and SHA-256 metadata.
"""

from __future__ import annotations

import argparse
import base64
import binascii
from dataclasses import dataclass
import json
from pathlib import Path
import time
import tomllib
from typing import Any, Callable, Iterable, Sequence
import urllib.error
import urllib.request
import re

try:
    from package_split_contract import (
        PACKAGE_CONTRACTS,
        PACKAGE_NAMES,
        PROMOTED_APP_PROJECT_PACKAGE_NAMES,
    )
    from release_plan import PYPI_PUBLISH_ROLES
except ModuleNotFoundError:  # pragma: no cover - used when imported as tools.*
    from tools.package_split_contract import (
        PACKAGE_CONTRACTS,
        PACKAGE_NAMES,
        PROMOTED_APP_PROJECT_PACKAGE_NAMES,
    )
    from tools.release_plan import PYPI_PUBLISH_ROLES


SCHEMA = "agilab.pypi_provenance_check.v1"
PYPI_JSON_URL = "https://pypi.org/pypi/{name}/json"
PYPI_PROVENANCE_URL = "https://pypi.org/integrity/{name}/{version}/{filename}/provenance"
EXPECTED_PUBLISHER_KIND = "GitHub"
EXPECTED_PUBLISHER_REPOSITORY = "ThalesGroup/agilab"
EXPECTED_PUBLISHER_WORKFLOW = "pypi-publish.yaml"
IN_TOTO_STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PYPI_PUBLISH_PREDICATE_TYPE = "https://docs.pypi.org/attestations/publish/v1"


@dataclass(frozen=True)
class ReleaseTarget:
    name: str
    version: str
    project: str


@dataclass(frozen=True)
class ReleaseFile:
    filename: str
    sha256: str


def _normalize_version(value: str) -> str:
    parts = []
    for part in str(value).strip().split("."):
        parts.append(str(int(part)) if part.isdigit() else part.lower())
    return ".".join(parts)


def _read_project_version(repo_root: Path, project: str) -> str:
    pyproject = repo_root / project / "pyproject.toml" if project != "." else repo_root / "pyproject.toml"
    with pyproject.open("rb") as stream:
        payload = tomllib.load(stream)
    return str(payload["project"]["version"])


def release_targets(
    *,
    repo_root: Path,
    package_names: Iterable[str] | None = None,
) -> list[ReleaseTarget]:
    selected = set(package_names or PACKAGE_NAMES)
    unknown = selected.difference(PACKAGE_NAMES)
    if unknown:
        raise ValueError(f"Unknown public package(s): {', '.join(sorted(unknown))}")

    targets: list[ReleaseTarget] = []
    for package in PACKAGE_CONTRACTS:
        publish_to_pypi = (
            package.role in PYPI_PUBLISH_ROLES
            or package.name in PROMOTED_APP_PROJECT_PACKAGE_NAMES
        )
        if package.name not in selected or not publish_to_pypi:
            continue
        targets.append(
            ReleaseTarget(
                name=package.name,
                version=_read_project_version(repo_root, package.project),
                project=package.project,
            )
        )
    return targets


def _fetch_json(
    url: str,
    *,
    timeout: float,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
    accept: str | None = None,
) -> Any:
    headers = {"Accept": accept} if accept else {}
    request = urllib.request.Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _release_files(
    payload: dict[str, Any], expected_version: str
) -> tuple[str | None, list[ReleaseFile], str | None]:
    releases = payload.get("releases")
    if not isinstance(releases, dict):
        return None, [], None
    expected = _normalize_version(expected_version)
    for version, files in releases.items():
        if _normalize_version(str(version)) != expected:
            continue
        if not isinstance(files, list) or not files:
            return str(version), [], None
        release_files: list[ReleaseFile] = []
        for file_index, file_payload in enumerate(files):
            if not isinstance(file_payload, dict):
                return str(version), [], f"releases[{version}][{file_index}] must be an object"
            filename = file_payload.get("filename")
            digests = file_payload.get("digests")
            sha256 = digests.get("sha256") if isinstance(digests, dict) else None
            if not isinstance(filename, str) or not filename.strip():
                return str(version), [], f"releases[{version}][{file_index}].filename is missing"
            if not isinstance(sha256, str) or re.fullmatch(r"[0-9a-fA-F]{64}", sha256) is None:
                return str(version), [], f"releases[{version}][{file_index}].digests.sha256 is invalid"
            release_files.append(ReleaseFile(filename=filename, sha256=sha256.lower()))
        return str(version), release_files, None
    return None, [], None


def _non_empty_string_fields(payload: Any, fields: tuple[str, ...]) -> bool:
    return isinstance(payload, dict) and all(
        isinstance(payload.get(field), str) and payload[field].strip() for field in fields
    )


def _attestation_validation_error(
    payload: Any,
    *,
    expected_filename: str,
    expected_sha256: str,
) -> str | None:
    if re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256) is None:
        return "expected distribution SHA-256 is invalid"
    if not isinstance(payload, dict):
        return "top-level provenance payload must be an object"
    if payload.get("version") != 1:
        return "top-level provenance version must be 1"
    bundles = payload.get("attestation_bundles")
    if not isinstance(bundles, list) or not bundles:
        return "attestation_bundles must be a non-empty list"
    publisher_found = False
    subject_found = False
    for bundle_index, bundle in enumerate(bundles):
        prefix = f"attestation_bundles[{bundle_index}]"
        if not isinstance(bundle, dict):
            return f"{prefix} must be an object"
        if not _non_empty_string_fields(
            bundle.get("publisher"),
            ("environment", "kind", "repository", "workflow"),
        ):
            return f"{prefix}.publisher is incomplete"
        publisher = bundle["publisher"]
        publisher_matches = (
            publisher["kind"] == EXPECTED_PUBLISHER_KIND
            and publisher["repository"] == EXPECTED_PUBLISHER_REPOSITORY
            and publisher["workflow"] == EXPECTED_PUBLISHER_WORKFLOW
        )
        publisher_found = publisher_found or publisher_matches
        attestations = bundle.get("attestations")
        if not isinstance(attestations, list) or not attestations:
            return f"{prefix}.attestations must be a non-empty list"
        for attestation_index, attestation in enumerate(attestations):
            attestation_prefix = f"{prefix}.attestations[{attestation_index}]"
            if not isinstance(attestation, dict) or attestation.get("version") != 1:
                return f"{attestation_prefix}.version must be 1"
            if not _non_empty_string_fields(
                attestation.get("envelope"),
                ("signature", "statement"),
            ):
                return f"{attestation_prefix}.envelope is incomplete"
            statement_encoded = attestation["envelope"]["statement"]
            try:
                statement_bytes = base64.b64decode(statement_encoded, validate=True)
                statement = json.loads(statement_bytes.decode("utf-8"))
            except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                return f"{attestation_prefix}.envelope.statement is not valid base64 in-toto JSON"
            if not isinstance(statement, dict):
                return f"{attestation_prefix}.envelope.statement must decode to an object"
            if statement.get("_type") != IN_TOTO_STATEMENT_TYPE:
                return f"{attestation_prefix}.envelope.statement._type is invalid"
            if statement.get("predicateType") != PYPI_PUBLISH_PREDICATE_TYPE:
                return f"{attestation_prefix}.envelope.statement.predicateType is invalid"
            subjects = statement.get("subject")
            if not isinstance(subjects, list) or not subjects:
                return f"{attestation_prefix}.envelope.statement.subject must be non-empty"
            attestation_subject_matches = False
            for subject_index, subject in enumerate(subjects):
                subject_prefix = (
                    f"{attestation_prefix}.envelope.statement.subject[{subject_index}]"
                )
                if not isinstance(subject, dict) or not isinstance(subject.get("name"), str):
                    return f"{subject_prefix}.name is invalid"
                digest = subject.get("digest")
                subject_sha256 = digest.get("sha256") if isinstance(digest, dict) else None
                if not isinstance(subject_sha256, str) or re.fullmatch(
                    r"[0-9a-fA-F]{64}", subject_sha256
                ) is None:
                    return f"{subject_prefix}.digest.sha256 is invalid"
                if (
                    subject["name"] == expected_filename
                    and subject_sha256.lower() == expected_sha256.lower()
                ):
                    attestation_subject_matches = True
            if publisher_matches and attestation_subject_matches:
                subject_found = True
            verification = attestation.get("verification_material")
            if not isinstance(verification, dict) or not isinstance(
                verification.get("certificate"), str
            ) or not verification["certificate"].strip():
                return f"{attestation_prefix}.verification_material.certificate is missing"
            transparency_entries = verification.get("transparency_entries")
            if not isinstance(transparency_entries, list) or not transparency_entries or not all(
                isinstance(entry, dict) and entry for entry in transparency_entries
            ):
                return f"{attestation_prefix}.verification_material.transparency_entries is incomplete"
    if not publisher_found:
        return "required GitHub publisher repository/workflow was not found"
    if not subject_found:
        return "required publisher attestation does not bind the PyPI filename and SHA-256"
    return None


def _has_attestation(
    payload: Any,
    *,
    expected_filename: str,
    expected_sha256: str,
) -> bool:
    return (
        _attestation_validation_error(
            payload,
            expected_filename=expected_filename,
            expected_sha256=expected_sha256,
        )
        is None
    )


def check_target(
    target: ReleaseTarget,
    *,
    timeout: float = 20.0,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    try:
        package_payload = _fetch_json(
            PYPI_JSON_URL.format(name=target.name),
            timeout=timeout,
            urlopen=urlopen,
        )
    except urllib.error.HTTPError as exc:
        return {
            "package": target.name,
            "version": target.version,
            "project": target.project,
            "status": "fail",
            "reason": f"pypi_json_http_{exc.code}",
            "files": [],
        }
    actual_version, release_files, release_metadata_error = _release_files(
        package_payload, target.version
    )
    if release_metadata_error is not None:
        return {
            "package": target.name,
            "version": target.version,
            "project": target.project,
            "status": "fail",
            "reason": "release_metadata_invalid",
            "validation_error": release_metadata_error,
            "files": [],
        }
    if not actual_version or not release_files:
        return {
            "package": target.name,
            "version": target.version,
            "project": target.project,
            "status": "fail",
            "reason": "release_missing",
            "files": [],
        }

    file_rows: list[dict[str, Any]] = []
    for release_file in release_files:
        filename = release_file.filename
        url = PYPI_PROVENANCE_URL.format(
            name=target.name,
            version=actual_version,
            filename=filename,
        )
        try:
            provenance_payload = _fetch_json(
                url,
                timeout=timeout,
                urlopen=urlopen,
                accept="application/vnd.pypi.integrity.v1+json",
            )
        except urllib.error.HTTPError as exc:
            file_rows.append(
                {
                    "filename": filename,
                    "sha256": release_file.sha256,
                    "status": "fail",
                    "reason": f"provenance_http_{exc.code}",
                }
            )
            continue
        validation_error = _attestation_validation_error(
            provenance_payload,
            expected_filename=filename,
            expected_sha256=release_file.sha256,
        )
        has_attestation = validation_error is None
        file_rows.append(
            {
                "filename": filename,
                "sha256": release_file.sha256,
                "status": "pass" if has_attestation else "fail",
                "reason": "provenance_bound" if has_attestation else "provenance_invalid",
                **({"validation_error": validation_error} if validation_error else {}),
            }
        )
    status = "pass" if all(row["status"] == "pass" for row in file_rows) else "fail"
    return {
        "package": target.name,
        "version": target.version,
        "pypi_version": actual_version,
        "project": target.project,
        "status": status,
        "reason": "all_files_provenance_bound" if status == "pass" else "provenance_invalid",
        "files": file_rows,
    }


def _is_transient_failure(check: dict[str, Any]) -> bool:
    reason = str(check.get("reason", ""))
    transient_http_reasons = {
        "pypi_json_http_404",
        "pypi_json_http_408",
        "pypi_json_http_409",
        "pypi_json_http_425",
        "pypi_json_http_429",
    }
    if reason == "release_missing" or reason.startswith("pypi_json_http_5"):
        return True
    if reason in transient_http_reasons:
        return True
    for file_row in check.get("files", []):
        if not isinstance(file_row, dict):
            continue
        file_reason = str(file_row.get("reason", ""))
        if file_reason.startswith("provenance_http_5") or file_reason in {
            "provenance_http_404",
            "provenance_http_408",
            "provenance_http_409",
            "provenance_http_425",
            "provenance_http_429",
        }:
            return True
    return False


def check_target_with_retries(
    target: ReleaseTarget,
    *,
    attempts: int = 1,
    retry_delay: float = 0.0,
    timeout: float = 20.0,
    sleep: Callable[[float], Any] = time.sleep,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    max_attempts = max(1, attempts)
    previous_failures: list[dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        check = check_target(target, timeout=timeout, urlopen=urlopen)
        check["attempt"] = attempt
        if (
            check["status"] == "pass"
            or attempt == max_attempts
            or not _is_transient_failure(check)
        ):
            if previous_failures:
                check["previous_failures"] = previous_failures
            return check
        previous_failures.append(
            {
                "attempt": attempt,
                "reason": check.get("reason"),
                "status": check.get("status"),
            }
        )
        if retry_delay > 0:
            sleep(retry_delay)
    raise AssertionError("unreachable")


def build_report(
    *,
    repo_root: Path,
    package_names: Iterable[str] | None = None,
    attempts: int = 1,
    retry_delay: float = 0.0,
    timeout: float = 20.0,
    sleep: Callable[[float], Any] = time.sleep,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    targets = release_targets(repo_root=repo_root, package_names=package_names)
    checks = [
        check_target_with_retries(
            target,
            attempts=attempts,
            retry_delay=retry_delay,
            timeout=timeout,
            sleep=sleep,
            urlopen=urlopen,
        )
        for target in targets
    ]
    failures = sum(1 for check in checks if check["status"] != "pass")
    return {
        "schema": SCHEMA,
        "status": "fail" if failures else "pass",
        "summary": {
            "package_count": len(checks),
            "failures": failures,
            "attempts": max(1, attempts),
        },
        "checks": checks,
    }


def format_markdown(report: dict[str, Any]) -> str:
    lines = [
        "## PyPI provenance check",
        "",
        "| Package | Version | Status | Reason |",
        "| --- | --- | --- | --- |",
    ]
    for check in report["checks"]:
        lines.append(
            f"| `{check['package']}` | `{check['version']}` | "
            f"`{check['status']}` | `{check['reason']}` |"
        )
    return "\n".join(lines) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate PyPI Integrity API publisher and distribution-subject binding "
            "for published AGILAB packages."
        )
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="AGILAB repository root.",
    )
    parser.add_argument(
        "--package",
        action="append",
        choices=PACKAGE_NAMES,
        dest="packages",
        help="Limit the check to one package. May be passed more than once.",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--attempts",
        type=int,
        default=1,
        help=(
            "Maximum attempts per package. Use after a fresh upload to tolerate "
            "PyPI propagation lag."
        ),
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=5.0,
        help="Seconds to wait between transient PyPI provenance checks.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    parser.add_argument(
        "--github-step-summary",
        type=Path,
        help="Append a markdown summary to this GitHub step-summary path.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        repo_root=args.repo_root,
        package_names=args.packages,
        attempts=args.attempts,
        retry_delay=args.retry_delay,
        timeout=args.timeout,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"PyPI provenance check: {report['status'].upper()} "
            f"({report['summary']['failures']} failure(s))"
        )
        for check in report["checks"]:
            print(
                f"- [{check['status'].upper()}] {check['package']}=={check['version']}: "
                f"{check['reason']}"
            )
    if args.github_step_summary:
        with args.github_step_summary.open("a", encoding="utf-8") as handle:
            handle.write(format_markdown(report))
    return 1 if report["status"] != "pass" else 0


if __name__ == "__main__":
    raise SystemExit(main())
