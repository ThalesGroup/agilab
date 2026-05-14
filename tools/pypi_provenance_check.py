#!/usr/bin/env python3
"""Verify PyPI Trusted Publishing attestations for AGILAB packages."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
import tomllib
from typing import Any, Callable, Iterable, Sequence
import urllib.error
import urllib.request

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


@dataclass(frozen=True)
class ReleaseTarget:
    name: str
    version: str
    project: str


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


def _release_files(payload: dict[str, Any], expected_version: str) -> tuple[str | None, list[str]]:
    releases = payload.get("releases")
    if not isinstance(releases, dict):
        return None, []
    expected = _normalize_version(expected_version)
    for version, files in releases.items():
        if _normalize_version(str(version)) != expected:
            continue
        filenames = [
            str(file.get("filename"))
            for file in files
            if isinstance(file, dict) and file.get("filename")
        ]
        return str(version), filenames
    return None, []


def _has_attestation(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    bundles = payload.get("attestation_bundles")
    if isinstance(bundles, list) and bundles:
        return True
    legacy = payload.get("provenance")
    return isinstance(legacy, list) and bool(legacy)


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
    actual_version, filenames = _release_files(package_payload, target.version)
    if not actual_version or not filenames:
        return {
            "package": target.name,
            "version": target.version,
            "project": target.project,
            "status": "fail",
            "reason": "release_missing",
            "files": [],
        }

    file_rows: list[dict[str, Any]] = []
    for filename in filenames:
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
                    "status": "fail",
                    "reason": f"provenance_http_{exc.code}",
                }
            )
            continue
        has_attestation = _has_attestation(provenance_payload)
        file_rows.append(
            {
                "filename": filename,
                "status": "pass" if has_attestation else "fail",
                "reason": "attestation_present" if has_attestation else "attestation_missing",
            }
        )
    status = "pass" if all(row["status"] == "pass" for row in file_rows) else "fail"
    return {
        "package": target.name,
        "version": target.version,
        "pypi_version": actual_version,
        "project": target.project,
        "status": status,
        "reason": "all_files_attested" if status == "pass" else "missing_attestation",
        "files": file_rows,
    }


def build_report(
    *,
    repo_root: Path,
    package_names: Iterable[str] | None = None,
    timeout: float = 20.0,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    targets = release_targets(repo_root=repo_root, package_names=package_names)
    checks = [check_target(target, timeout=timeout, urlopen=urlopen) for target in targets]
    failures = sum(1 for check in checks if check["status"] != "pass")
    return {
        "schema": SCHEMA,
        "status": "fail" if failures else "pass",
        "summary": {
            "package_count": len(checks),
            "failures": failures,
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
        description="Verify PyPI Trusted Publishing attestations for published AGILAB packages."
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
