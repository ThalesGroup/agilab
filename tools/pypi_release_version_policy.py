#!/usr/bin/env python3
"""Validate the public PyPI release cadence policy before upload."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path
from typing import Mapping, Sequence

try:
    from release_plan import release_plan
except ModuleNotFoundError:  # pragma: no cover - used when imported as tools.*
    from tools.release_plan import release_plan


POST_RELEASE_RE = re.compile(r"(?:[._-]?post\d+)\Z", re.IGNORECASE)


class ReleaseVersionPolicyError(ValueError):
    """Raised when a selected public release version violates cadence policy."""


def split_filter_values(values: Sequence[str] | None) -> tuple[str, ...]:
    tokens: list[str] = []
    for value in values or ():
        tokens.extend(token for token in re.split(r"[\s,]+", value.strip()) if token)
    return tuple(dict.fromkeys(tokens))


def is_post_release(version: str) -> bool:
    return bool(POST_RELEASE_RE.search(version.strip()))


def post_release_versions(package_versions: Mapping[str, str]) -> dict[str, str]:
    return {
        package: version
        for package, version in sorted(package_versions.items())
        if is_post_release(version)
    }


def validate_public_release_versions(
    package_versions: Mapping[str, str],
    *,
    allow_post_release: bool = False,
    post_release_reason: str = "",
) -> str:
    post_versions = post_release_versions(package_versions)
    if not post_versions:
        return "No selected public PyPI package uses a .postN release version."

    formatted = ", ".join(f"{package}={version}" for package, version in post_versions.items())
    reason = post_release_reason.strip()
    if allow_post_release and reason:
        return f"Allowed documented critical hotfix post-release: {formatted}. Reason: {reason}"

    raise ReleaseVersionPolicyError(
        "Public PyPI .postN releases are reserved for documented critical hotfixes. "
        f"Selected post-release versions: {formatted}. Use a release candidate or TestPyPI "
        "for rehearsal, then publish a deliberate new date-based final release. "
        "To publish a critical hotfix, set allow_post_release=true and provide "
        "post_release_reason in the workflow dispatch inputs."
    )


def public_package_entries(
    *,
    package_names: Sequence[str] | None = None,
    roles: Sequence[str] | None = None,
    repo_root: Path = Path.cwd(),
    skip_existing_pypi: bool = False,
    impact_base_ref: str | None = None,
) -> list[dict[str, str]]:
    payload = release_plan(
        package_names=package_names,
        roles=roles,
        repo_root=repo_root,
        skip_existing_pypi=skip_existing_pypi,
        impact_base_ref=impact_base_ref,
    )
    entries = [
        package
        for package in payload["library_matrix"]
        if package["publish_to_pypi"] == "true"
    ]
    umbrella = payload["umbrella_package"]
    if payload["umbrella_selected"] == "true" and umbrella["publish_to_pypi"] == "true":
        entries.append(umbrella)
    return entries


def read_project_version(repo_root: Path, project: str) -> str:
    pyproject = repo_root / project / "pyproject.toml" if project != "." else repo_root / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    version = str((data.get("project") or {}).get("version") or "").strip()
    if not version:
        raise ReleaseVersionPolicyError(f"{pyproject} does not define [project].version")
    return version


def selected_public_versions(
    repo_root: Path,
    *,
    package_names: Sequence[str] | None = None,
    roles: Sequence[str] | None = None,
    skip_existing_pypi: bool = False,
    impact_base_ref: str | None = None,
) -> dict[str, str]:
    return {
        package["package"]: read_project_version(repo_root, package["project"])
        for package in public_package_entries(
            package_names=package_names,
            roles=roles,
            repo_root=repo_root,
            skip_existing_pypi=skip_existing_pypi,
            impact_base_ref=impact_base_ref,
        )
    }


def write_summary(path: Path | None, *, package_versions: Mapping[str, str], result: str) -> None:
    if path is None:
        return
    lines = [
        "## PyPI release cadence policy",
        "",
        "| Package | Version |",
        "| --- | --- |",
    ]
    for package, version in sorted(package_versions.items()):
        lines.append(f"| `{package}` | `{version}` |")
    lines.extend(["", result, ""])
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--packages",
        action="append",
        default=[],
        help="Limit policy validation to comma- or space-separated package names.",
    )
    parser.add_argument(
        "--roles",
        action="append",
        default=[],
        help="Limit policy validation to comma- or space-separated package roles.",
    )
    parser.add_argument(
        "--allow-post-release",
        action="store_true",
        help="Allow committed .postN public PyPI versions for a documented critical hotfix.",
    )
    parser.add_argument(
        "--post-release-reason",
        default="",
        help="Critical hotfix justification required when --allow-post-release is set.",
    )
    parser.add_argument(
        "--skip-existing-pypi",
        action="store_true",
        help=(
            "Validate only selected PyPI packages whose current project version is not "
            "already complete on PyPI."
        ),
    )
    parser.add_argument(
        "--impact-base-ref",
        default="",
        help=(
            "When no package or role filter is supplied, validate packages changed since "
            "this git ref plus transitive exact-pin dependents."
        ),
    )
    parser.add_argument(
        "--github-step-summary",
        type=Path,
        default=None,
        help="Append a markdown policy summary to the GitHub step summary.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    package_versions: dict[str, str] = {}
    try:
        package_versions = selected_public_versions(
            args.repo_root.resolve(),
            package_names=split_filter_values(args.packages),
            roles=split_filter_values(args.roles),
            skip_existing_pypi=args.skip_existing_pypi,
            impact_base_ref=args.impact_base_ref.strip() or None,
        )
        result = validate_public_release_versions(
            package_versions,
            allow_post_release=args.allow_post_release,
            post_release_reason=args.post_release_reason,
        )
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        if args.github_step_summary:
            write_summary(args.github_step_summary, package_versions=package_versions, result=f"Failed: {exc}")
        return 2

    for package, version in sorted(package_versions.items()):
        print(f"{package}: {version}")
    print(result)
    write_summary(args.github_step_summary, package_versions=package_versions, result=result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
