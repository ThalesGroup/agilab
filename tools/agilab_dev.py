#!/usr/bin/env python3
"""Shortcuts for the most common AGILAB developer commands."""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
UV_RUN = ("uv", "--preview-features", "extra-build-dependencies", "run")


def _uv_python(*args: str) -> list[str]:
    return [*UV_RUN, "python", *args]


def _split_leading_values(args: Sequence[str], *, command_name: str) -> tuple[list[str], list[str]]:
    values: list[str] = []
    rest: list[str] = []
    for index, item in enumerate(args):
        if item.startswith("-"):
            rest = list(args[index:])
            break
        values.append(item)
    else:
        rest = []
    if not values:
        raise SystemExit(f"{command_name}: at least one value is required")
    return values, rest


def planned_commands(argv: Sequence[str]) -> list[list[str]]:
    if not argv or argv[0] in {"help", "-h", "--help"}:
        return [["./dev", "help"]]

    command = argv[0]
    args = list(argv[1:])

    if command == "impact":
        forwarded = args or ["--staged"]
        return [_uv_python("tools/impact_validate.py", *forwarded)]

    if command in {"bugfix", "fix"}:
        forwarded = args or ["--staged"]
        selector_args = list(forwarded)
        if "--run" not in selector_args:
            selector_args.append("--run")
        impact_args = [item for item in forwarded if item != "--run"]
        return [
            _uv_python("tools/impact_validate.py", *impact_args),
            _uv_python("tools/ga_regression_selector.py", *selector_args),
        ]

    if command == "test":
        return [[*UV_RUN, "pytest", "-q", *args]]

    if command in {"regress", "ga-regress"}:
        forwarded = args or ["--staged", "--run"]
        return [_uv_python("tools/ga_regression_selector.py", *forwarded)]

    if command in {"flow", "profile"}:
        profiles, extras = _split_leading_values(args, command_name=command)
        profile_args: list[str] = []
        for profile in profiles:
            profile_args.extend(["--profile", profile])
        return [_uv_python("tools/workflow_parity.py", *profile_args, *extras)]

    if command in {"release", "pre-release"}:
        forwarded = args or ["--staged"]
        return [
            _uv_python("tools/impact_validate.py", *forwarded),
            _uv_python(
                "tools/release_plan.py",
                "--check-workflow",
                ".github/workflows/pypi-publish.yaml",
            ),
            _uv_python(
                "tools/pypi_trusted_publisher_contract.py",
                "--check-workflow",
                ".github/workflows/pypi-publish.yaml",
            ),
            _uv_python(
                "tools/workflow_parity.py",
                "--profile",
                "dependency-policy",
                "--profile",
                "shared-core-typing",
                "--profile",
                "docs",
                "--profile",
                "badges",
            ),
        ]

    if command in {"badge", "guard"}:
        defaults = ["--changed-only", "--require-fresh-xml"]
        return [_uv_python("tools/coverage_badge_guard.py", *defaults, *args)]

    if command == "docs":
        return [
            _uv_python("tools/sync_docs_source.py", "--apply", "--delete"),
            _uv_python("tools/sync_docs_source.py", "--verify-stamp"),
        ]

    if command == "skills":
        skills, extras = _split_leading_values(args, command_name=command)
        return [
            ["python3", "tools/sync_agent_skills.py", "--skills", *skills, *extras],
            ["python3", "tools/codex_skills.py", "--root", ".codex/skills", "validate", "--strict"],
            ["python3", "tools/codex_skills.py", "--root", ".codex/skills", "generate"],
        ]

    raise SystemExit(f"unknown shortcut: {command}")


def _usage() -> str:
    return """Usage:
  ./dev [--print-only] impact [impact_validate args]
  ./dev [--print-only] bugfix [changed-file args]
  ./dev [--print-only] test [pytest args]
  ./dev [--print-only] regress [ga_regression_selector args]
  ./dev [--print-only] flow|profile <profile> [profile...] [workflow args]
  ./dev [--print-only] release [impact_validate args]
  ./dev [--print-only] badge|guard [coverage_badge_guard args]
  ./dev [--print-only] docs
  ./dev [--print-only] skills <skill> [skill...]

High-frequency mappings:
  impact    -> Analyze changed files and list the required local validations; defaults to --staged.
  bugfix    -> Run impact triage, then run the GA-selected fast regression subset; defaults to --staged.
  test      -> Run targeted pytest with -q while keeping all extra pytest arguments.
  regress   -> Use the GA regression selector on staged files and run the selected pytest subset.
  flow      -> Run one or more workflow_parity profiles with repeated --profile flags.
  release   -> Run local release guards: impact, generated PyPI plan, trusted publisher contract, docs, dependency policy, typing, and badge freshness.
  badge     -> Run the explicit release/pre-release coverage badge freshness guard.
  docs      -> Sync docs from the canonical docs checkout and verify the mirror stamp.
  skills    -> Sync repo skills from Claude to Codex, then validate and regenerate indexes.
"""


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    print_only = False
    if "--print-only" in args:
        print_only = True
        args = [item for item in args if item != "--print-only"]

    if not args or args[0] in {"help", "-h", "--help"}:
        print(_usage())
        return 0

    commands = planned_commands(args)
    for command in commands:
        output = sys.stdout if print_only else sys.stderr
        print(shlex.join(command), file=output, flush=True)
        if print_only:
            continue
        completed = subprocess.run(command, cwd=ROOT)
        if completed.returncode:
            return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
