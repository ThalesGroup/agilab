#!/usr/bin/env python3
"""Check public release truth for an AGILAB release tag."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Sequence

from packaging.version import InvalidVersion, Version

try:
    from pypi_project_preflight import fetch_pypi_json, selected_pypi_projects
except ModuleNotFoundError:  # pragma: no cover - used when imported as tools.*
    from tools.pypi_project_preflight import fetch_pypi_json, selected_pypi_projects


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "agilab.release_status.v1"


def package_version_from_tag(tag: str) -> str:
    value = tag.strip()
    if value.startswith("refs/tags/"):
        value = value.removeprefix("refs/tags/")
    value = value.removeprefix("v")
    return re.sub(r"-\d+$", "", value)


def _run_json(command: list[str]) -> tuple[dict[str, Any] | None, str | None]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        return None, completed.stderr.strip() or completed.stdout.strip()
    try:
        return json.loads(completed.stdout), None
    except json.JSONDecodeError as exc:
        return None, str(exc)


def github_release_status(tag: str) -> dict[str, Any]:
    payload, error = _run_json(
        [
            "gh",
            "release",
            "view",
            tag,
            "--repo",
            "ThalesGroup/agilab",
            "--json",
            "tagName,isDraft,isPrerelease,publishedAt,url,assets",
        ]
    )
    if error:
        return {"status": "fail", "error": error, "tag": tag}
    assets = payload.get("assets") or []
    return {
        "status": "pass",
        "tag": payload.get("tagName"),
        "url": payload.get("url"),
        "published_at": payload.get("publishedAt"),
        "is_draft": payload.get("isDraft"),
        "is_prerelease": payload.get("isPrerelease"),
        "asset_count": len(assets),
    }


def _versions(payload: dict[str, Any]) -> set[Version]:
    versions: set[Version] = set()
    for raw_version in payload.get("releases") or {}:
        try:
            versions.add(Version(str(raw_version)))
        except InvalidVersion:
            continue
    return versions


def pypi_version_status(expected_version: str, *, repo_root: Path = ROOT) -> list[dict[str, Any]]:
    expected = Version(expected_version)
    statuses: list[dict[str, Any]] = []
    for project in selected_pypi_projects(repo_root=repo_root):
        payload = fetch_pypi_json(project.pypi_project)
        if payload is None:
            statuses.append(
                {
                    "pypi_project": project.pypi_project,
                    "status": "missing-project",
                    "expected": expected_version,
                    "latest": None,
                }
            )
            continue
        raw_latest = str(payload.get("info", {}).get("version") or "")
        statuses.append(
            {
                "pypi_project": project.pypi_project,
                "status": "pass" if expected in _versions(payload) else "missing-version",
                "expected": expected_version,
                "latest": raw_latest or None,
            }
        )
    return statuses


def build_report(tag: str, *, package_version: str | None = None, repo_root: Path = ROOT) -> dict[str, Any]:
    expected = package_version or package_version_from_tag(tag)
    release = github_release_status(tag)
    pypi = pypi_version_status(expected, repo_root=repo_root)
    pypi_failures = [item for item in pypi if item["status"] != "pass"]
    status = "pass" if release["status"] == "pass" and not pypi_failures else "fail"
    return {
        "schema": SCHEMA_VERSION,
        "tag": tag,
        "expected_package_version": expected,
        "status": status,
        "github_release": release,
        "pypi": pypi,
        "summary": {
            "pypi_checked": len(pypi),
            "pypi_failures": len(pypi_failures),
            "release_asset_count": release.get("asset_count", 0),
        },
    }


def render_text(report: dict[str, Any]) -> str:
    lines = [
        "AGILAB release status",
        f"tag: {report['tag']}",
        f"expected package version: {report['expected_package_version']}",
        f"status: {report['status']}",
        f"github release assets: {report['summary']['release_asset_count']}",
        f"pypi failures: {report['summary']['pypi_failures']}",
    ]
    failures = [item for item in report["pypi"] if item["status"] != "pass"]
    if failures:
        lines.append("")
        lines.append("PyPI failures:")
        for item in failures:
            lines.append(f"- {item['pypi_project']}: {item['status']} latest={item['latest']}")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--package-version")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-failures", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        args.tag,
        package_version=args.package_version,
        repo_root=args.repo_root.resolve(),
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_text(report))
    return 0 if report["status"] == "pass" or args.allow_failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
