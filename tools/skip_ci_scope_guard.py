# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Reject ``[skip ci]`` on commits that change executable code.

GitHub honours ``[skip ci]`` by not scheduling workflows at all, so no CI job
can police it — by the time a workflow could object, it has already been
skipped. The only place left to enforce it is before the push.

This exists because of a concrete outage: #923 carried ``[skip ci]`` on a
branch that changed ``tools/`` and ``test/`` alongside a docs refresh. Only the
secret scan ran, the branch merged on that single check, and a false positive
it introduced took ``main`` red and blocked an unrelated PR until it was
diagnosed and fixed.

``[skip ci]`` is fine for a pure docs or asset refresh. It is not fine when the
same commit range touches code the suite is meant to protect.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]

#: GitHub's documented skip directives, matched case-insensitively.
SKIP_DIRECTIVES = (
    "[skip ci]",
    "[ci skip]",
    "[no ci]",
    "[skip actions]",
    "[actions skip]",
)

#: Paths whose behaviour the suite is meant to protect. A commit touching any
#: of these must not suppress CI.
CODE_PREFIXES = (
    "src/",
    "test/",
    "tools/",
    ".github/workflows/",
    ".githooks/",
)

#: Extensions that are inert even under a code prefix (docs and assets living
#: beside code should not force a full matrix).
INERT_SUFFIXES = (".md", ".rst", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".txt")


@dataclass(frozen=True)
class Offence:
    commit: str
    subject: str
    directive: str
    code_files: tuple[str, ...]


def _run(args: Sequence[str]) -> str:
    completed = subprocess.run(
        args, cwd=REPO_ROOT, text=True, capture_output=True, check=False
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout


def commit_range(base: str, head: str) -> list[str]:
    out = _run(["git", "rev-list", f"{base}..{head}"])
    return [line.strip() for line in out.splitlines() if line.strip()]


def _message(commit: str) -> str:
    return _run(["git", "log", "-1", "--format=%B", commit])


def _subject(commit: str) -> str:
    return _run(["git", "log", "-1", "--format=%s", commit]).strip()


def _changed_files(commit: str) -> list[str]:
    out = _run(["git", "show", "--name-only", "--format=", commit])
    return [line.strip() for line in out.splitlines() if line.strip()]


def skip_directive_in(message: str) -> str | None:
    lowered = message.lower()
    for directive in SKIP_DIRECTIVES:
        if directive in lowered:
            return directive
    return None


def is_code_path(path: str) -> bool:
    if not any(path.startswith(prefix) for prefix in CODE_PREFIXES):
        return False
    return not path.lower().endswith(INERT_SUFFIXES)


def find_offences(commits: Sequence[str]) -> list[Offence]:
    offences: list[Offence] = []
    for commit in commits:
        directive = skip_directive_in(_message(commit))
        if directive is None:
            continue
        code_files = tuple(path for path in _changed_files(commit) if is_code_path(path))
        if code_files:
            offences.append(
                Offence(
                    commit=commit[:12],
                    subject=_subject(commit),
                    directive=directive,
                    code_files=code_files,
                )
            )
    return offences


def render(offences: Sequence[Offence]) -> str:
    lines = [
        "[agilab pre-push] refusing to skip CI on commits that change code.",
        "",
    ]
    for offence in offences:
        lines.append(f"  {offence.commit} {offence.subject}")
        lines.append(f"    carries {offence.directive} and changes:")
        for path in offence.code_files[:6]:
            lines.append(f"      {path}")
        if len(offence.code_files) > 6:
            lines.append(f"      ... and {len(offence.code_files) - 6} more")
    lines += [
        "",
        "  GitHub skips the whole workflow set for these commits, so nothing",
        "  downstream can catch a regression in them.",
        "",
        "  Drop the skip directive, or split the docs-only part into its own commit.",
        "  Override with AGILAB_ALLOW_SKIP_CI=1 and an explicit reason.",
    ]
    return "\n".join(lines)


def _parse_pre_push_spec(text: str) -> list[tuple[str, str]]:
    """Parse git's pre-push stdin: `<local ref> <local sha> <remote ref> <remote sha>`."""

    ranges: list[tuple[str, str]] = []
    zero = re.compile(r"^0+$")
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 4:
            continue
        _local_ref, local_sha, _remote_ref, remote_sha = fields
        if zero.match(local_sha):
            continue  # branch deletion
        base = remote_sha if not zero.match(remote_sha) else "origin/main"
        ranges.append((base, local_sha))
    return ranges


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="Base ref when not reading a pre-push spec.")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument(
        "--pre-push-spec",
        type=Path,
        help="File holding git's pre-push stdin payload.",
    )
    args = parser.parse_args(argv)

    if args.pre_push_spec is not None:
        try:
            spec = args.pre_push_spec.read_text(encoding="utf-8")
        except OSError:
            spec = ""
        ranges = _parse_pre_push_spec(spec)
    elif args.base:
        ranges = [(args.base, args.head)]
    else:
        ranges = [("origin/main", args.head)]

    commits: list[str] = []
    for base, head in ranges:
        for commit in commit_range(base, head):
            if commit not in commits:
                commits.append(commit)

    offences = find_offences(commits)
    if not offences:
        return 0

    print(render(offences), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
