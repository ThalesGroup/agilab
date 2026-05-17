#!/usr/bin/env python3
"""Enforce PyPI release retention after a successful trusted publish."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from packaging.version import InvalidVersion, Version


PYPI_JSON_URLS = {
    "pypi": "https://pypi.org/pypi/{package}/json",
    "testpypi": "https://test.pypi.org/pypi/{package}/json",
}
PYPI_HOSTS = {
    "pypi": "https://pypi.org/",
    "testpypi": "https://test.pypi.org/",
}
SCHEMA_VERSION = "agilab.pypi_release_retention.v1"


@dataclass(frozen=True)
class ReleasePlan:
    package: str
    protect_version: str
    published_versions: list[str]
    delete_versions: list[str]
    missing_protected_version: bool


def normalize_version(version: str) -> str:
    try:
        return str(Version(version.strip().lstrip("v")))
    except InvalidVersion as exc:
        raise SystemExit(f"ERROR: invalid version {version!r}") from exc


def exact_release_regex(version: str) -> str:
    return f"^{re.escape(normalize_version(version))}$"


def split_packages(values: Sequence[str] | None) -> list[str]:
    packages: list[str] = []
    for value in values or ():
        packages.extend(token for token in re.split(r"[\s,]+", value.strip()) if token)
    return list(dict.fromkeys(packages))


def fetch_releases(package: str, repo: str, *, timeout: int = 15) -> list[str]:
    url = PYPI_JSON_URLS[repo].format(package=package)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []
        raise RuntimeError(f"{url}: HTTP {exc.code}") from exc
    releases = data.get("releases") or {}
    if not isinstance(releases, dict):
        raise RuntimeError(f"{url}: expected JSON object with a releases mapping")
    return sorted(releases, key=lambda value: Version(value))


def build_plan(package: str, repo: str, protect_version: str) -> ReleasePlan:
    protected = Version(normalize_version(protect_version))
    releases = fetch_releases(package, repo)
    delete_versions = [
        version
        for version in releases
        if Version(normalize_version(version)) != protected
    ]
    missing_protected = all(
        Version(normalize_version(version)) != protected for version in releases
    )
    return ReleasePlan(
        package=package,
        protect_version=str(protected),
        published_versions=releases,
        delete_versions=delete_versions,
        missing_protected_version=missing_protected,
    )


def wait_for_protected_releases(
    *,
    packages: Sequence[str],
    repo: str,
    protect_version: str,
    attempts: int,
    retry_delay: float,
) -> list[ReleasePlan]:
    latest: list[ReleasePlan] = []
    for attempt in range(1, max(1, attempts) + 1):
        latest = [build_plan(package, repo, protect_version) for package in packages]
        if all(not plan.missing_protected_version for plan in latest):
            return latest
        if attempt < attempts:
            time.sleep(max(0.0, retry_delay))
    return latest


def require_credentials(username: str | None, password: str | None) -> tuple[str, str]:
    user = (username or os.environ.get("PYPI_RELEASE_PRUNE_USERNAME") or "").strip()
    secret = (password or os.environ.get("PYPI_RELEASE_PRUNE_PASSWORD") or "").strip()
    if not user or not secret:
        raise SystemExit(
            "ERROR: PyPI release pruning needs PYPI_RELEASE_PRUNE_USERNAME and "
            "PYPI_RELEASE_PRUNE_PASSWORD secrets because Trusted Publishing/OIDC "
            "only covers upload, not release deletion."
        )
    if user == "__token__" or secret.startswith("pypi-"):
        raise SystemExit(
            "ERROR: PyPI release pruning uses the PyPI web cleanup flow; an API token "
            "or __token__ username is not accepted."
        )
    return user, secret


def delete_release(
    *,
    package: str,
    version: str,
    repo: str,
    username: str,
    password: str,
    verbose: bool = False,
) -> None:
    cmd = [
        "pypi-cleanup",
        "--version-regex",
        exact_release_regex(version),
        "--do-it",
        "-y",
        "--host",
        PYPI_HOSTS[repo],
        "--package",
        package,
        "--username",
        username,
    ]
    if verbose:
        cmd.append("-v")
    env = os.environ.copy()
    env.update(
        {
            "PYPI_USERNAME": username,
            "PYPI_PASSWORD": password,
            "PYPI_CLEANUP_PASSWORD": password,
        }
    )
    subprocess.run(cmd, check=True, text=True, env=env)


def verify_retention(
    *,
    packages: Sequence[str],
    repo: str,
    protect_version: str,
    attempts: int,
    retry_delay: float,
) -> list[ReleasePlan]:
    latest: list[ReleasePlan] = []
    for attempt in range(1, max(1, attempts) + 1):
        latest = [build_plan(package, repo, protect_version) for package in packages]
        failures = [
            plan
            for plan in latest
            if plan.missing_protected_version or plan.delete_versions
        ]
        if not failures:
            return latest
        if attempt < attempts:
            time.sleep(max(0.0, retry_delay))
    return latest


def render_summary(plans: Sequence[ReleasePlan], *, dry_run: bool) -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "success": all(
            not plan.missing_protected_version and not plan.delete_versions
            for plan in plans
        ),
        "dry_run": dry_run,
        "packages": [
            {
                "package": plan.package,
                "protect_version": plan.protect_version,
                "published_versions": plan.published_versions,
                "delete_versions": plan.delete_versions,
                "missing_protected_version": plan.missing_protected_version,
            }
            for plan in plans
        ],
    }


def append_step_summary(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "## PyPI release retention",
        "",
        f"- Status: `{'PASS' if summary['success'] else 'FAIL'}`",
        f"- Dry run: `{summary['dry_run']}`",
        "",
        "| Package | Keep | Published before cleanup | Deleted/remaining old versions |",
        "| --- | ---: | ---: | --- |",
    ]
    for package in summary["packages"]:
        deleted = ", ".join(package["delete_versions"]) or "(none)"
        lines.append(
            "| `{package}` | `{protect}` | `{published}` | {deleted} |".format(
                package=package["package"],
                protect=package["protect_version"],
                published=len(package["published_versions"]),
                deleted=deleted,
            )
        )
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Delete old PyPI releases for selected projects while keeping the "
            "current release version."
        )
    )
    parser.add_argument("--repo", choices=tuple(PYPI_JSON_URLS), default="pypi")
    parser.add_argument("--package", action="append", default=[])
    parser.add_argument(
        "--packages",
        action="append",
        default=[],
        help="Comma- or space-separated package names.",
    )
    parser.add_argument("--protect-version", required=True)
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--confirm-delete", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--verify-attempts", type=int, default=6)
    parser.add_argument("--retry-delay", type=float, default=10.0)
    parser.add_argument(
        "--github-step-summary",
        nargs="?",
        const=os.environ.get("GITHUB_STEP_SUMMARY"),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    packages = split_packages([*args.package, *args.packages])
    if not packages:
        raise SystemExit("ERROR: at least one --package or --packages value is required")
    protect_version = normalize_version(args.protect_version)

    plans = wait_for_protected_releases(
        packages=packages,
        repo=args.repo,
        protect_version=protect_version,
        attempts=args.verify_attempts,
        retry_delay=args.retry_delay,
    )
    missing = [plan.package for plan in plans if plan.missing_protected_version]
    if missing:
        raise SystemExit(
            "ERROR: protected version "
            f"{protect_version} is not visible on {args.repo} for: {', '.join(missing)}"
        )

    pending_deletes = [
        (plan.package, version)
        for plan in plans
        for version in plan.delete_versions
    ]
    if pending_deletes and not args.dry_run:
        if not args.confirm_delete:
            raise SystemExit("ERROR: destructive PyPI retention requires --confirm-delete")
        username, password = require_credentials(args.username, args.password)
        for package, version in pending_deletes:
            print(f"[pypi-retention] deleting {package} {version}", file=sys.stderr)
            delete_release(
                package=package,
                version=version,
                repo=args.repo,
                username=username,
                password=password,
                verbose=args.verbose,
            )
        plans = verify_retention(
            packages=packages,
            repo=args.repo,
            protect_version=protect_version,
            attempts=args.verify_attempts,
            retry_delay=args.retry_delay,
        )

    summary = render_summary(plans, dry_run=args.dry_run)
    if args.github_step_summary:
        append_step_summary(Path(args.github_step_summary), summary)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        for package in summary["packages"]:
            deleted = ", ".join(package["delete_versions"]) or "(none)"
            print(
                f"{package['package']}: keep={package['protect_version']} "
                f"published={len(package['published_versions'])} old={deleted}"
            )
    return 0 if summary["success"] or args.dry_run else 1


if __name__ == "__main__":
    raise SystemExit(main())
