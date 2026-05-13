#!/usr/bin/env python3
"""Render the PyPI Trusted Publishing contract for AGILAB releases."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

try:
    from package_split_contract import PACKAGE_CONTRACTS, PACKAGE_NAMES
except ModuleNotFoundError:  # pragma: no cover - used when imported as tools.*
    from tools.package_split_contract import PACKAGE_CONTRACTS, PACKAGE_NAMES


DEFAULT_OWNER = "ThalesGroup"
DEFAULT_REPOSITORY = "agilab"
DEFAULT_WORKFLOW = "pypi-publish.yaml"


@dataclass(frozen=True)
class TrustedPublisherClaim:
    """The GitHub claim tuple that must be configured on a PyPI project."""

    project: str
    owner: str
    repository: str
    workflow: str
    environment: str

    @property
    def subject(self) -> str:
        return f"repo:{self.owner}/{self.repository}:environment:{self.environment}"


def trusted_publisher_claims(
    *,
    package_names: Iterable[str] | None = None,
    owner: str = DEFAULT_OWNER,
    repository: str = DEFAULT_REPOSITORY,
    workflow: str = DEFAULT_WORKFLOW,
) -> list[TrustedPublisherClaim]:
    """Return the expected PyPI trusted-publisher claims in release order."""

    selected = set(package_names or PACKAGE_NAMES)
    unknown = selected.difference(PACKAGE_NAMES)
    if unknown:
        raise ValueError(f"Unknown public package(s): {', '.join(sorted(unknown))}")

    claims: list[TrustedPublisherClaim] = []
    for package in PACKAGE_CONTRACTS:
        if package.name not in selected:
            continue
        claims.append(
            TrustedPublisherClaim(
                project=package.name,
                owner=owner,
                repository=repository,
                workflow=workflow,
                environment=package.pypi_environment,
            )
        )
    return claims


def validate_workflow_contract(
    workflow_path: Path,
    claims: Sequence[TrustedPublisherClaim],
) -> list[str]:
    """Return missing workflow contract fragments for the selected claims."""

    text = workflow_path.read_text(encoding="utf-8")
    required_fragments = {
        "id-token: write": "workflow must grant OIDC token permission",
        "uses: pypa/gh-action-pypi-publish@": "workflow must use trusted publishing action",
        "PYPI_TRUSTED_PUBLISHING": "workflow must keep the trusted-publishing gate",
    }
    if any(claim.project != "agilab" for claim in claims):
        required_fragments["tools/release_plan.py"] = "generated library release matrix"
        required_fragments[
            "include: ${{ fromJSON(needs.release-plan.outputs.library_matrix) }}"
        ] = "library release matrix generated from package contract"
        required_fragments["name: ${{ matrix.pypi_environment }}"] = (
            "matrix-specific library GitHub environments"
        )
        required_fragments[
            "url: https://pypi.org/project/${{ matrix.pypi_project }}/"
        ] = "matrix-specific PyPI project URLs"
        required_fragments['--package "${{ matrix.package }}"'] = (
            "matrix-specific trusted publisher claim reporting"
        )
        required_fragments['--artifact-policy "${{ matrix.artifact_policy }}"'] = (
            "matrix-specific artifact policy verification"
        )

    for claim in claims:
        if claim.project == "agilab":
            required_fragments["name: pypi-agilab"] = "agilab GitHub environment"
            required_fragments["Publish agilab to PyPI with trusted publishing"] = (
                "agilab trusted publish step"
            )

    return [
        f"{description}: missing {fragment!r}"
        for fragment, description in required_fragments.items()
        if fragment not in text
    ]


def format_markdown(claims: Sequence[TrustedPublisherClaim]) -> str:
    """Render claims for GitHub step summaries and release runbooks."""

    lines = [
        "## PyPI Trusted Publishing contract",
        "",
        "Configure every PyPI project below with these exact GitHub publisher values.",
        "A PyPI `invalid-publisher` error means the project is missing this entry or one field differs.",
        "",
        "| PyPI project | GitHub owner | GitHub repository | Workflow | Environment | OIDC subject |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for claim in claims:
        lines.append(
            f"| `{claim.project}` | `{claim.owner}` | `{claim.repository}` | "
            f"`{claim.workflow}` | `{claim.environment}` | `{claim.subject}` |"
        )
    lines.extend(
        [
            "",
            "PyPI setup path: project Settings > Publishing > Trusted publishers > Add GitHub publisher.",
        ]
    )
    return "\n".join(lines) + "\n"


def format_text(claims: Sequence[TrustedPublisherClaim]) -> str:
    """Render a compact terminal report."""

    lines = [
        "PyPI Trusted Publishing contract",
        "Configure these GitHub publisher values in each PyPI project:",
        "",
    ]
    for claim in claims:
        lines.extend(
            [
                f"- {claim.project}",
                f"  owner: {claim.owner}",
                f"  repository: {claim.repository}",
                f"  workflow: {claim.workflow}",
                f"  environment: {claim.environment}",
                f"  oidc-subject: {claim.subject}",
            ]
        )
    return "\n".join(lines) + "\n"


def format_json(claims: Sequence[TrustedPublisherClaim]) -> str:
    payload = [asdict(claim) | {"subject": claim.subject} for claim in claims]
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render the PyPI Trusted Publishing setup contract for AGILAB packages."
    )
    parser.add_argument("--owner", default=DEFAULT_OWNER)
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    parser.add_argument(
        "--package",
        action="append",
        choices=PACKAGE_NAMES,
        dest="packages",
        help="Limit output to one package. May be passed more than once.",
    )
    parser.add_argument("--format", choices=("text", "markdown", "json"), default="text")
    parser.add_argument(
        "--github-step-summary",
        nargs="?",
        const=os.environ.get("GITHUB_STEP_SUMMARY"),
        help="Also append markdown output to the given GitHub step-summary path.",
    )
    parser.add_argument(
        "--check-workflow",
        type=Path,
        help="Validate that a workflow file still contains the required publisher matrix.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    claims = trusted_publisher_claims(
        package_names=args.packages,
        owner=args.owner,
        repository=args.repository,
        workflow=args.workflow,
    )

    if args.check_workflow:
        missing = validate_workflow_contract(args.check_workflow, claims)
        if missing:
            for message in missing:
                print(f"ERROR: {message}")
            return 2

    if args.format == "json":
        output = format_json(claims)
    elif args.format == "markdown":
        output = format_markdown(claims)
    else:
        output = format_text(claims)

    print(output, end="")

    if args.github_step_summary:
        summary_path = Path(args.github_step_summary)
        with summary_path.open("a", encoding="utf-8") as handle:
            handle.write(format_markdown(claims))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
