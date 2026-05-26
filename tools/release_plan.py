#!/usr/bin/env python3
"""Render the AGILAB release package plan from the package split contract."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Sequence

try:
    from package_split_contract import (
        LIBRARY_PACKAGE_CONTRACTS,
        PACKAGE_CONTRACTS,
        PACKAGE_NAMES,
        PROMOTED_APP_PROJECT_PACKAGE_NAMES,
        UMBRELLA_PACKAGE_CONTRACT,
    )
except ModuleNotFoundError:  # pragma: no cover - used when imported as tools.*
    from tools.package_split_contract import (
        LIBRARY_PACKAGE_CONTRACTS,
        PACKAGE_CONTRACTS,
        PACKAGE_NAMES,
        PROMOTED_APP_PROJECT_PACKAGE_NAMES,
        UMBRELLA_PACKAGE_CONTRACT,
    )


SCHEMA_VERSION = "agilab.release_plan.v1"
PYPI_PUBLISH_ROLES = {
    "runtime-component",
    "ui-component",
    "page-bundle",
    "page-umbrella",
    "runtime-bundle",
    "app-umbrella",
    "top-level-bundle",
}


PACKAGE_ROLES = tuple(sorted({package.role for package in PACKAGE_CONTRACTS}))


def _package_entry(package: Any) -> dict[str, str]:
    publish_to_pypi = package.role in PYPI_PUBLISH_ROLES or package.name in PROMOTED_APP_PROJECT_PACKAGE_NAMES
    return {
        "package": package.name,
        "project": package.project,
        "dist": package.dist,
        "pypi_project": package.name,
        "pypi_environment": package.pypi_environment,
        "artifact_policy": package.artifact_policy,
        "publish_to_pypi": "true" if publish_to_pypi else "false",
    }


def _split_filter_values(values: Sequence[str] | None) -> tuple[str, ...]:
    tokens: list[str] = []
    for value in values or ():
        tokens.extend(token for token in re.split(r"[\s,]+", value.strip()) if token)
    return tuple(dict.fromkeys(tokens))


def _validate_filters(package_names: Sequence[str] | None, roles: Sequence[str] | None) -> None:
    unknown_packages = sorted(set(package_names or ()).difference(PACKAGE_NAMES))
    if unknown_packages:
        raise ValueError(f"Unknown package(s): {', '.join(unknown_packages)}")
    unknown_roles = sorted(set(roles or ()).difference(PACKAGE_ROLES))
    if unknown_roles:
        raise ValueError(f"Unknown package role(s): {', '.join(unknown_roles)}")


def _selected(package: Any, package_names: set[str], roles: set[str]) -> bool:
    if package_names and package.name not in package_names:
        return False
    if roles and package.role not in roles:
        return False
    return True


def _publish_packages(payload: dict[str, Any]) -> list[str]:
    packages = [
        package["package"]
        for package in payload["library_matrix"]
        if package["publish_to_pypi"] == "true"
    ]
    umbrella = payload["umbrella_package"]
    if payload["umbrella_selected"] == "true" and umbrella["publish_to_pypi"] == "true":
        packages.append(umbrella["package"])
    return packages


def library_matrix(
    *,
    package_names: Sequence[str] | None = None,
    roles: Sequence[str] | None = None,
) -> list[dict[str, str]]:
    """Return the GitHub matrix entries for publishable library packages."""

    package_filter = set(package_names or ())
    role_filter = set(roles or ())
    _validate_filters(package_names, roles)
    return [
        _package_entry(package)
        for package in LIBRARY_PACKAGE_CONTRACTS
        if _selected(package, package_filter, role_filter)
    ]


def umbrella_package() -> dict[str, str]:
    """Return the umbrella package entry."""

    return _package_entry(UMBRELLA_PACKAGE_CONTRACT)


def release_plan(
    *,
    package_names: Sequence[str] | None = None,
    roles: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Return the complete release package plan."""

    package_filter = set(package_names or ())
    role_filter = set(roles or ())
    _validate_filters(package_names, roles)
    matrix = library_matrix(package_names=package_names, roles=roles)
    umbrella_selected = _selected(UMBRELLA_PACKAGE_CONTRACT, package_filter, role_filter)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "library_matrix": matrix,
        "umbrella_package": umbrella_package(),
        "library_selected": "true" if matrix else "false",
        "umbrella_selected": "true" if umbrella_selected else "false",
    }
    publish_packages = _publish_packages(payload)
    payload["pypi_publish_selected"] = "true" if publish_packages else "false"
    payload["provenance_packages"] = publish_packages
    return payload


def format_json(payload: Any, *, compact: bool = False) -> str:
    if compact:
        return json.dumps(payload, separators=(",", ":")) + "\n"
    return json.dumps(payload, indent=2) + "\n"


def format_text(payload: dict[str, Any]) -> str:
    lines = [
        "AGILAB release package plan",
        f"schema: {payload['schema_version']}",
        f"library selected: {payload['library_selected']}",
        f"umbrella selected: {payload['umbrella_selected']}",
        f"PyPI publish selected: {payload['pypi_publish_selected']}",
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
            "  - {package}: {project} -> {pypi_environment} ({artifact_policy}, publish={publish_to_pypi}, selected={selected})".format(
                selected=payload["umbrella_selected"],
                **umbrella
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def format_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "## AGILAB release package plan",
        "",
        f"- Library selected: `{payload['library_selected']}`",
        f"- Umbrella selected: `{payload['umbrella_selected']}`",
        f"- PyPI publication selected: `{payload['pypi_publish_selected']}`",
        f"- Provenance packages: `{', '.join(payload['provenance_packages']) or '(none)'}`",
        "",
        "| Selected | Package | Project | PyPI environment | Artifact policy | Publish to PyPI |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for package in payload["library_matrix"]:
        lines.append(
            f"| `true` | `{package['package']}` | `{package['project']}` | "
            f"`{package['pypi_environment']}` | `{package['artifact_policy']}` | "
            f"`{package['publish_to_pypi']}` |"
        )
    umbrella = payload["umbrella_package"]
    lines.append(
        f"| `{payload['umbrella_selected']}` | `{umbrella['package']}` | `{umbrella['project']}` | "
        f"`{umbrella['pypi_environment']}` | `{umbrella['artifact_policy']}` | "
        f"`{umbrella['publish_to_pypi']}` |"
    )
    return "\n".join(lines) + "\n"


def write_github_output(path: Path, payload: dict[str, Any]) -> None:
    """Write compact release-plan values for GitHub Actions outputs."""

    lines = [
        f"library_matrix={format_json(payload['library_matrix'], compact=True).strip()}",
        f"umbrella_package={format_json(payload['umbrella_package'], compact=True).strip()}",
        f"library_selected={payload['library_selected']}",
        f"umbrella_selected={payload['umbrella_selected']}",
        f"pypi_publish_selected={payload['pypi_publish_selected']}",
        "provenance_packages=" + " ".join(payload["provenance_packages"]),
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
        "python -m playwright install --with-deps chromium": (
            "release preflight must install a browser before the frontend smoke"
        ),
        "--profile ui-frontend-smoke": (
            "release preflight must verify the Streamlit frontend hydrates in a real browser"
        ),
        "library_matrix: ${{ steps.release-plan.outputs.library_matrix }}": (
            "release-plan job must expose the library matrix output"
        ),
        "library_selected: ${{ steps.release-plan.outputs.library_selected }}": (
            "release-plan job must expose whether the library matrix is selected"
        ),
        "umbrella_selected: ${{ steps.release-plan.outputs.umbrella_selected }}": (
            "release-plan job must expose whether the umbrella package is selected"
        ),
        "pypi_publish_selected: ${{ steps.release-plan.outputs.pypi_publish_selected }}": (
            "release-plan job must expose whether any PyPI publication is selected"
        ),
        "provenance_packages: ${{ steps.release-plan.outputs.provenance_packages }}": (
            "release-plan job must expose the selected provenance package list"
        ),
        "include: ${{ fromJSON(needs.release-plan.outputs.library_matrix) }}": (
            "library publish matrix must be generated from the release plan"
        ),
        "needs.release-plan.outputs.library_selected == 'true'": (
            "library publish job must be skippable for umbrella-only releases"
        ),
        "needs.release-plan.outputs.umbrella_selected == 'true'": (
            "umbrella publish job must be skippable for package-only releases"
        ),
        "needs.release-plan.outputs.pypi_publish_selected == 'true'": (
            "release asset jobs must be skippable when no PyPI package is selected"
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
        "Check whether ${{ matrix.package }} can reuse PyPI artifacts": (
            "library packages must check for reusable PyPI artifacts before building"
        ),
        "--project \"${{ matrix.project }}\"": (
            "library PyPI reuse checks must read package metadata from the generated project path"
        ),
        "steps.library-pypi-reuse.outputs.all-exist != 'true'": (
            "library build and upload steps must skip packages that already exist on PyPI"
        ),
        "Check whether agilab can reuse PyPI artifacts": (
            "umbrella package must check for reusable PyPI artifacts before building"
        ),
        "steps.agilab-pypi-reuse.outputs.all-exist != 'true'": (
            "umbrella build and upload steps must skip when artifacts already exist on PyPI"
        ),
        "--download-dir \"${{ matrix.dist }}\"": (
            "library reuse checks must materialize existing PyPI artifacts for release assets"
        ),
        "--download-dir dist": (
            "umbrella reuse checks must materialize existing PyPI artifacts for release assets"
        ),
        "matrix.publish_to_pypi == 'true'": (
            "PyPI upload steps must be gated by the generated publish flag"
        ),
        "pypi-provenance-evidence:": "workflow must verify PyPI provenance after upload",
        "tools/pypi_provenance_check.py": "workflow must run the PyPI provenance verifier",
        "pypi-provenance-evidence.tar.gz": (
            "workflow must attach PyPI provenance evidence to GitHub release assets"
        ),
        "release-dist-*": "workflow must download release distribution evidence artifacts",
        "-name '*.whl' -o": "GitHub release assets must include wheels",
        "-name '*.tar.gz' -o": "GitHub release assets must include source distributions",
        "-name '*-artifact-hashes.json' -o": (
            "GitHub release assets must include release artifact hash manifests"
        ),
        "-name '*-SHA256SUMS.txt'": (
            "GitHub release assets must include per-package SHA256SUMS files"
        ),
        "release-distribution-evidence.tar.gz": (
            "workflow must attach the complete release distribution evidence archive"
        ),
        "allow_post_release:": "workflow must require an explicit public .postN hotfix override",
        "post_release_reason:": "workflow must capture the public .postN hotfix justification",
        "tools/pypi_release_version_policy.py": (
            "workflow must validate public release cadence before publishing"
        ),
        "--allow-post-release": "workflow must pass the explicit .postN override to the policy gate",
        "POST_RELEASE_REASON": "workflow must pass the .postN hotfix justification to the policy gate",
        "pypi-release-retention:": "workflow must prune old PyPI releases after provenance passes",
        "tools/pypi_release_retention.py": "workflow must use the PyPI release retention tool",
        "--protect-versions-from-projects": (
            "PyPI release retention must protect each selected package's own project version"
        ),
        "--repo-root .": (
            "PyPI release retention must read selected project versions from the checked-out repo"
        ),
        "PYPI_RELEASE_PRUNE_PASSWORD": (
            "workflow must keep PyPI release pruning credentials separate from OIDC upload"
        ),
        "PYPI_RELEASE_PRUNE_TOTP_SECRET": (
            "workflow must support non-interactive PyPI 2FA for release pruning"
        ),
        "PYPI_CONFIRM_READER_TOKEN": (
            "workflow must support PyPI unrecognized-login confirmation polling"
        ),
        "--confirm-delete": "workflow must make destructive PyPI retention explicit",
        "--github-confirm-login-variable": (
            "PyPI release retention must poll for temporary login confirmation"
        ),
        "--github-confirm-login-timeout": (
            "PyPI release retention must leave a long bounded confirmation window"
        ),
        "needs.pypi-release-retention.result == 'success'": (
            "release assets must wait for successful PyPI release retention"
        ),
        "workflow-dist-${{ matrix.package }}": (
            "non-published package artifacts must stay workflow-only"
        ),
        "sync-hf-space:": "workflow must sync the public Hugging Face Space after release assets",
        "sync-hf-space:\n    if: ${{ always() && needs.release-plan.outputs.umbrella_selected == 'true'": (
            "HF Space sync and release-proof refresh must run only for the umbrella AGILAB release"
        ),
        "ref: ${{ github.sha }}": (
            "HF Space sync must deploy from the workflow SHA, not a stale manual release_tag checkout"
        ),
        "huggingface_hub click": (
            "HF Space sync must install the current HF CLI dependency set explicitly"
        ),
        "tools/hf_space_release_sync.py": "workflow must use the release HF Space sync tool",
        "HF_TOKEN secret is required": "workflow must fail closed when HF_TOKEN is not configured",
        "update_public_release_references_for_guard(": (
            "workflow must refresh public release metadata before release-proof checks"
        ),
        "badges/pypi-version-agilab.svg": (
            "workflow must commit the static PyPI badge when release metadata changes"
        ),
        "--hf-space-commit \"$hf_commit\"": (
            "workflow must refresh release proof with the deployed HF Space commit"
        ),
    }
    missing = [
        f"{description}: missing {fragment!r}"
        for fragment, description in required_fragments.items()
        if fragment not in text
    ]
    if "\n          - package: " in text:
        missing.append("library package matrix must not be hard-coded in the workflow")
    if "--allow-delete-failure-warning" in text:
        missing.append(
            "PyPI release retention must fail closed while stale releases remain: "
            "remove '--allow-delete-failure-warning'"
        )
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
    parser.add_argument(
        "--packages",
        action="append",
        default=[],
        help="Limit the release plan to comma- or space-separated package names.",
    )
    parser.add_argument(
        "--roles",
        action="append",
        default=[],
        help="Limit the release plan to comma- or space-separated package roles.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = release_plan(
            package_names=_split_filter_values(args.packages),
            roles=_split_filter_values(args.roles),
        )
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2

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
