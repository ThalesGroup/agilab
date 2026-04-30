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

    if command in {"impact", "iv", "i"}:
        forwarded = args or ["--staged"]
        return [_uv_python("tools/impact_validate.py", *forwarded)]

    if command in {"test", "pt", "t"}:
        return [[*UV_RUN, "pytest", "-q", *args]]

    if command in {"profile", "wp", "w"}:
        profiles, extras = _split_leading_values(args, command_name=command)
        profile_args: list[str] = []
        for profile in profiles:
            profile_args.extend(["--profile", profile])
        return [_uv_python("tools/workflow_parity.py", *profile_args, *extras)]

    if command in {"guard", "bg", "b"}:
        defaults = ["--changed-only", "--require-fresh-xml"]
        return [_uv_python("tools/coverage_badge_guard.py", *defaults, *args)]

    if command in {"docs", "ds", "d"}:
        return [
            _uv_python("tools/sync_docs_source.py", "--apply", "--delete"),
            _uv_python("tools/sync_docs_source.py", "--verify-stamp"),
        ]

    if command in {"skills", "sk"}:
        skills, extras = _split_leading_values(args, command_name=command)
        return [
            ["python3", "tools/sync_agent_skills.py", "--skills", *skills, *extras],
            ["python3", "tools/codex_skills.py", "--root", ".codex/skills", "validate", "--strict"],
            ["python3", "tools/codex_skills.py", "--root", ".codex/skills", "generate"],
        ]

    raise SystemExit(f"unknown shortcut: {command}")


def _usage() -> str:
    return """Usage:
  ./dev [--print-only] impact|iv|i [impact_validate args]
  ./dev [--print-only] test|pt|t [pytest args]
  ./dev [--print-only] profile|wp|w <profile> [profile...] [workflow args]
  ./dev [--print-only] guard|bg|b [coverage_badge_guard args]
  ./dev [--print-only] docs|ds|d
  ./dev [--print-only] skills|sk <skill> [skill...]

High-frequency mappings:
  i         -> impact_validate.py, defaulting to --staged
  t         -> pytest -q
  w         -> workflow_parity.py with repeated --profile flags
  b         -> coverage_badge_guard.py --changed-only --require-fresh-xml
  d         -> sync_docs_source.py --apply --delete, then --verify-stamp
  sk        -> sync_agent_skills.py, then Codex skill validate/generate
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
        print(shlex.join(command))
        if print_only:
            continue
        completed = subprocess.run(command, cwd=ROOT)
        if completed.returncode:
            return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
