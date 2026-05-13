#!/usr/bin/env python3
"""Render the AGILAB release package plan from the package split contract."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Sequence

try:
    from package_split_contract import LIBRARY_PACKAGE_CONTRACTS, UMBRELLA_PACKAGE_CONTRACT
except ModuleNotFoundError:  # pragma: no cover - used when imported as tools.*
    from tools.package_split_contract import LIBRARY_PACKAGE_CONTRACTS, UMBRELLA_PACKAGE_CONTRACT


SCHEMA_VERSION = "agilab.release_plan.v1"
PYPI_PUBLISH_ROLES = {
    "runtime-component",
    "ui-component",
    "page-umbrella",
    "runtime-bundle",
    "app-umbrella",
    "top-level-bundle",
}


def _package_entry(package: Any) -> dict[str, str]:
    return {
        "package": package.name,
        "project": package.project,
        "dist": package.dist,
        "pypi_project": package.name,
        "pypi_environment": package.pypi_environment,
        "artifact_policy": package.artifact_policy,
        "publish_to_pypi": "true" if package.role in PYPI_PUBLISH_ROLES else "false",
    }


def library_matrix() -> list[dict[str, str]]:
    """Return the GitHub matrix entries for publishable library packages."""

    return [_package_entry(package) for package in LIBRARY_PACKAGE_CONTRACTS]


def umbrella_package() -> dict[str, str]:
    """Return the umbrella package entry."""

    return _package_entry(UMBRELLA_PACKAGE_CONTRACT)


def release_plan() -> dict[str, Any]:
    """Return the complete release package plan."""

    return {
        "schema_version": SCHEMA_VERSION,
        "library_matrix": library_matrix(),
        "umbrella_package": umbrella_package(),
    }


def format_json(payload: Any, *, compact: bool = False) -> str:
    if compact:
        return json.dumps(payload, separators=(",", ":")) + "\n"
    return json.dumps(payload, indent=2) + "\n"


def format_text(payload: dict[str, Any]) -> str:
    lines = [
        "AGILAB release package plan",
        f"schema: {payload['schema_version']}",
        "",
        "Library packages:",
    ]
    for package in payload["library_matrix"]:
        lines.append(
            (
                "  - {package}: {project} -> {pypi_environment} "
                "({artifact_policy}, publish={publish_to_pypi})"
            ).format(**package)
        )
    umbrella = payload["umbrella_package"]
    lines.extend(
        [
            "",
            "Umbrella package:",
            "  - {package}: {project} -> {pypi_environment} ({artifact_policy}, publish={publish_to_pypi})".format(
                **umbrella
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def format_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "## AGILAB release package plan",
        "",
        "| Package | Project | PyPI environment | Artifact policy | Publish to PyPI |",
        "| --- | --- | --- | --- | --- |",
    ]
    for package in [*payload["library_matrix"], payload["umbrella_package"]]:
        lines.append(
            f"| `{package['package']}` | `{package['project']}` | "
            f"`{package['pypi_environment']}` | `{package['artifact_policy']}` | "
            f"`{package['publish_to_pypi']}` |"
        )
    return "\n".join(lines) + "\n"


def write_github_output(path: Path, payload: dict[str, Any]) -> None:
    """Write compact release-plan values for GitHub Actions outputs."""

    lines = [
        f"library_matrix={format_json(payload['library_matrix'], compact=True).strip()}",
        f"umbrella_package={format_json(payload['umbrella_package'], compact=True).strip()}",
    ]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def validate_workflow_contract(workflow_path: Path) -> list[str]:
    """Return missing workflow fragments for the generated release-plan contract."""

    text = workflow_path.read_text(encoding="utf-8")
    required_fragments = {
        "release-plan:": "workflow must render the package plan before publishing",
        "id: release-plan": "release-plan step must expose GitHub outputs",
        "tools/release_plan.py": "workflow must call the release-plan generator",
        "library_matrix: ${{ steps.release-plan.outputs.library_matrix }}": (
            "release-plan job must expose the library matrix output"
        ),
        "include: ${{ fromJSON(needs.release-plan.outputs.library_matrix) }}": (
            "library publish matrix must be generated from the release plan"
        ),
        "- release-plan": "library publishing must depend on the generated release plan",
        "name: ${{ matrix.pypi_environment }}": (
            "library packages must use matrix-specific PyPI environments"
        ),
        "url: https://pypi.org/project/${{ matrix.pypi_project }}/": (
            "library package environment URL must come from the generated matrix"
        ),
        "--artifact-policy \"${{ matrix.artifact_policy }}\"": (
            "artifact verification must use the generated artifact policy"
        ),
        "matrix.publish_to_pypi == 'true'": (
            "PyPI upload steps must be gated by the generated publish flag"
        ),
    }
    missing = [
        f"{description}: missing {fragment!r}"
        for fragment, description in required_fragments.items()
        if fragment not in text
    ]
    if "\n          - package: " in text:
        missing.append("library package matrix must not be hard-coded in the workflow")
    return missing


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render the AGILAB PyPI release package plan from the package split contract."
    )
    parser.add_argument("--format", choices=("text", "json", "markdown"), default="text")
    parser.add_argument("--compact", action="store_true", help="Compact JSON output.")
    parser.add_argument(
        "--github-output",
        nargs="?",
        const=os.environ.get("GITHUB_OUTPUT"),
        help="Append GitHub Actions output keys to this path.",
    )
    parser.add_argument(
        "--github-step-summary",
        nargs="?",
        const=os.environ.get("GITHUB_STEP_SUMMARY"),
        help="Append markdown output to this GitHub step-summary path.",
    )
    parser.add_argument(
        "--check-workflow",
        type=Path,
        help="Validate that a workflow consumes the generated release package matrix.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = release_plan()

    if args.check_workflow:
        missing = validate_workflow_contract(args.check_workflow)
        if missing:
            for message in missing:
                print(f"ERROR: {message}")
            return 2

    if args.github_output:
        write_github_output(Path(args.github_output), payload)

    if args.github_step_summary:
        summary_path = Path(args.github_step_summary)
        with summary_path.open("a", encoding="utf-8") as handle:
            handle.write(format_markdown(payload))

    if args.format == "json":
        output = format_json(payload, compact=args.compact)
    elif args.format == "markdown":
        output = format_markdown(payload)
    else:
        output = format_text(payload)
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
