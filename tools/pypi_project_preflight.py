#!/usr/bin/env python3
"""Preflight selected AGILAB PyPI projects before release dispatch."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Callable, Sequence
import urllib.error
import urllib.parse
import urllib.request

from packaging.version import InvalidVersion, Version

try:
    from pypi_distribution_state import DistributionStateError, read_project_metadata
    from release_plan import release_plan
except ModuleNotFoundError:  # pragma: no cover - used when imported as tools.*
    from tools.pypi_distribution_state import DistributionStateError, read_project_metadata
    from tools.release_plan import release_plan


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "agilab.pypi_project_preflight.v1"


@dataclass(frozen=True)
class PlannedPyPIProject:
    package: str
    project: str
    pypi_project: str
    pypi_environment: str
    artifact_policy: str
    version: str


@dataclass(frozen=True)
class PyPIProjectStatus:
    package: str
    project: str
    pypi_project: str
    pypi_environment: str
    artifact_policy: str
    version: str
    status: str
    latest: str | None = None
    release_count: int = 0
    pending_publisher_command: str | None = None
    error: str | None = None


def fetch_pypi_json(project_name: str) -> dict[str, Any] | None:
    url = f"https://pypi.org/pypi/{urllib.parse.quote(project_name)}/json"
    request = urllib.request.Request(
        url,
        headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise RuntimeError(f"could not fetch PyPI metadata for {project_name}: HTTP {exc.code}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not fetch PyPI metadata for {project_name}: {exc}") from exc


def _project_version(repo_root: Path, project: str) -> str:
    try:
        _name, version = read_project_metadata(repo_root / project)
    except DistributionStateError as exc:
        raise RuntimeError(str(exc)) from exc
    return str(version)


def _split_values(values: Sequence[str] | None) -> list[str]:
    tokens: list[str] = []
    for value in values or ():
        tokens.extend(token for token in value.replace(",", " ").split() if token)
    return tokens


def selected_pypi_projects(
    *,
    repo_root: Path = ROOT,
    package_names: Sequence[str] | None = None,
    roles: Sequence[str] | None = None,
) -> list[PlannedPyPIProject]:
    plan = release_plan(package_names=package_names, roles=roles, repo_root=repo_root)
    entries = [
        entry
        for entry in plan["library_matrix"]
        if entry.get("publish_to_pypi") == "true"
    ]
    umbrella = plan["umbrella_package"]
    if plan.get("umbrella_selected") == "true" and umbrella.get("publish_to_pypi") == "true":
        entries.append(umbrella)
    projects: list[PlannedPyPIProject] = []
    for entry in entries:
        projects.append(
            PlannedPyPIProject(
                package=entry["package"],
                project=entry["project"],
                pypi_project=entry["pypi_project"],
                pypi_environment=entry["pypi_environment"],
                artifact_policy=entry["artifact_policy"],
                version=_project_version(repo_root, entry["project"]),
            )
        )
    return projects


def pending_publisher_command(project: PlannedPyPIProject) -> str:
    return (
        "gh workflow run pypi-pending-trusted-publisher.yaml "
        "-R ThalesGroup/agilab --ref main "
        f"-f project_name={project.pypi_project} "
        f"-f pypi_environment={project.pypi_environment}"
    )


def _release_versions(payload: dict[str, Any]) -> list[Version]:
    versions: list[Version] = []
    for raw_version in payload.get("releases") or {}:
        try:
            versions.append(Version(str(raw_version)))
        except InvalidVersion:
            continue
    return versions


def classify_project(
    project: PlannedPyPIProject,
    *,
    fetch_json: Callable[[str], dict[str, Any] | None] = fetch_pypi_json,
) -> PyPIProjectStatus:
    try:
        payload = fetch_json(project.pypi_project)
    except RuntimeError as exc:
        return PyPIProjectStatus(
            package=project.package,
            project=project.project,
            pypi_project=project.pypi_project,
            pypi_environment=project.pypi_environment,
            artifact_policy=project.artifact_policy,
            version=project.version,
            status="error",
            error=str(exc),
        )
    if payload is None:
        return PyPIProjectStatus(
            package=project.package,
            project=project.project,
            pypi_project=project.pypi_project,
            pypi_environment=project.pypi_environment,
            artifact_policy=project.artifact_policy,
            version=project.version,
            status="missing-project",
            pending_publisher_command=pending_publisher_command(project),
        )

    releases = _release_versions(payload)
    expected = Version(project.version)
    latest = max(releases) if releases else None
    if expected in set(releases):
        status = "current"
    elif latest is not None and latest > expected:
        status = "newer-on-pypi"
    elif latest is None:
        status = "empty-project"
    else:
        status = "missing-version"
    return PyPIProjectStatus(
        package=project.package,
        project=project.project,
        pypi_project=project.pypi_project,
        pypi_environment=project.pypi_environment,
        artifact_policy=project.artifact_policy,
        version=project.version,
        status=status,
        latest=str(latest) if latest is not None else None,
        release_count=len(releases),
        pending_publisher_command=(
            pending_publisher_command(project)
            if status in {"missing-project", "empty-project"}
            else None
        ),
    )


def build_report(
    *,
    repo_root: Path = ROOT,
    package_names: Sequence[str] | None = None,
    roles: Sequence[str] | None = None,
    fetch_json: Callable[[str], dict[str, Any] | None] = fetch_pypi_json,
) -> dict[str, Any]:
    statuses = [
        classify_project(project, fetch_json=fetch_json)
        for project in selected_pypi_projects(
            repo_root=repo_root,
            package_names=package_names,
            roles=roles,
        )
    ]
    blockers = [
        status
        for status in statuses
        if status.status in {"missing-project", "empty-project", "newer-on-pypi", "error"}
    ]
    return {
        "schema": SCHEMA_VERSION,
        "repo_root": str(repo_root),
        "status": "pass" if not blockers else "fail",
        "summary": {
            "checked": len(statuses),
            "current": sum(1 for status in statuses if status.status == "current"),
            "to_publish": sum(1 for status in statuses if status.status == "missing-version"),
            "blockers": len(blockers),
        },
        "projects": [asdict(status) for status in statuses],
        "blockers": [asdict(status) for status in blockers],
    }


def render_text(report: dict[str, Any]) -> str:
    lines = [
        "AGILAB PyPI project preflight",
        f"status: {report['status']}",
        f"checked: {report['summary']['checked']}",
        f"current: {report['summary']['current']}",
        f"to publish: {report['summary']['to_publish']}",
        f"blockers: {report['summary']['blockers']}",
        "",
    ]
    if report["blockers"]:
        lines.append("Blockers:")
        for blocker in report["blockers"]:
            lines.append(
                f"- {blocker['pypi_project']}: {blocker['status']} "
                f"(expected {blocker['version']}, latest {blocker['latest'] or 'n/a'})"
            )
            if blocker.get("pending_publisher_command"):
                lines.append(f"  pending publisher: {blocker['pending_publisher_command']}")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--package", dest="packages", action="append")
    parser.add_argument("--role", dest="roles", action="append")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-blockers", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        repo_root=args.repo_root.resolve(),
        package_names=_split_values(args.packages),
        roles=_split_values(args.roles),
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_text(report))
    return 0 if report["status"] == "pass" or args.allow_blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
