#!/usr/bin/env python3
"""Classify changed files for fast local pre-push guardrails."""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence


ZERO_SHA = "0" * 40
REPO_ROOT = Path(__file__).resolve().parents[1]

DOCS_GUARD_PREFIXES = (
    "docs/source/",
)
DOCS_GUARD_FILES = {
    "docs/.docs_source_mirror_stamp.json",
    "tools/sync_docs_source.py",
    "test/test_sync_docs_source.py",
}
RELEASE_PROOF_GUARD_PREFIXES = (
    "docs/source/data/release_proof",
)
RELEASE_PROOF_GUARD_FILES = {
    "README.md",
    "badges/pypi-version-agilab.svg",
    "docs/source/release-proof.rst",
    "pyproject.toml",
    "test/test_release_proof_report.py",
    "tools/release_proof_report.py",
}


GitRunner = Callable[[Sequence[str]], str]


@dataclass(frozen=True)
class GuardState:
    changed_files: tuple[str, ...]
    docs_changed: bool
    release_proof_changed: bool
    detection_failed: bool = False
    error: str = ""


def _run_git(args: Sequence[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def _split_lines(value: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in value.splitlines() if line.strip())


def _remote_default_base(git: GitRunner) -> str:
    try:
        return git(["rev-parse", "--verify", "@{u}"])
    except subprocess.CalledProcessError:
        return git(["rev-parse", "--verify", "origin/main"])


def _new_branch_base(local_sha: str, git: GitRunner) -> str:
    candidates = ("origin/main", "main")
    for candidate in candidates:
        try:
            base = git(["merge-base", local_sha, candidate])
        except subprocess.CalledProcessError:
            continue
        if base:
            return base
    return f"{local_sha}^"


def parse_pre_push_records(stdin_text: str) -> tuple[tuple[str, str, str, str], ...]:
    records: list[tuple[str, str, str, str]] = []
    for raw_line in stdin_text.splitlines():
        parts = raw_line.split()
        if len(parts) != 4:
            continue
        records.append((parts[0], parts[1], parts[2], parts[3]))
    return tuple(records)


def changed_files_from_pre_push(stdin_text: str, *, git: GitRunner = _run_git) -> tuple[str, ...]:
    records = parse_pre_push_records(stdin_text)
    changed: set[str] = set()

    if not records:
        base = _remote_default_base(git)
        return tuple(sorted(_split_lines(git(["diff", "--name-only", "--diff-filter=ACMR", f"{base}...HEAD"]))))

    for _local_ref, local_sha, _remote_ref, remote_sha in records:
        if local_sha == ZERO_SHA:
            continue
        base = _new_branch_base(local_sha, git) if remote_sha == ZERO_SHA else remote_sha
        changed.update(_split_lines(git(["diff", "--name-only", "--diff-filter=ACMR", base, local_sha])))
    return tuple(sorted(changed))


def _matches(path: str, *, prefixes: Iterable[str], files: set[str]) -> bool:
    return path in files or any(path.startswith(prefix) for prefix in prefixes)


def classify_changed_files(changed_files: Sequence[str]) -> GuardState:
    docs_changed = any(
        _matches(path, prefixes=DOCS_GUARD_PREFIXES, files=DOCS_GUARD_FILES)
        for path in changed_files
    )
    release_proof_changed = any(
        _matches(path, prefixes=RELEASE_PROOF_GUARD_PREFIXES, files=RELEASE_PROOF_GUARD_FILES)
        for path in changed_files
    )
    return GuardState(
        changed_files=tuple(sorted(set(changed_files))),
        docs_changed=docs_changed,
        release_proof_changed=release_proof_changed,
    )


def failed_detection_state(error: Exception) -> GuardState:
    return GuardState(
        changed_files=(),
        docs_changed=True,
        release_proof_changed=True,
        detection_failed=True,
        error=str(error),
    )


def _shell_bool(value: bool) -> str:
    return "1" if value else "0"


def render_shell(state: GuardState) -> str:
    lines = [
        f"DOCS_CHANGED={_shell_bool(state.docs_changed)}",
        f"RELEASE_PROOF_CHANGED={_shell_bool(state.release_proof_changed)}",
        f"DETECTION_FAILED={_shell_bool(state.detection_failed)}",
        f"CHANGED_COUNT={len(state.changed_files)}",
    ]
    if state.error:
        lines.append(f"DETECTION_ERROR={state.error.replace(chr(10), ' ')}")
    else:
        lines.append("DETECTION_ERROR=")
    return "\n".join(lines)


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--format",
        choices=("shell", "files"),
        default="shell",
        help="Output shell variables for the hook, or the changed file list.",
    )
    parser.add_argument(
        "--changed-file",
        action="append",
        default=None,
        help="Bypass git detection and classify this file. Useful for tests/debugging.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    try:
        changed_files = (
            tuple(args.changed_file)
            if args.changed_file is not None
            else changed_files_from_pre_push(sys.stdin.read())
        )
        state = classify_changed_files(changed_files)
    except Exception as exc:  # pragma: no cover - defensive hook fail-safe
        state = failed_detection_state(exc)

    if args.format == "files":
        print("\n".join(state.changed_files))
        return 0

    print(render_shell(state))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
