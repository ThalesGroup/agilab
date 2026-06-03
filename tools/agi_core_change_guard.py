#!/usr/bin/env python3
"""Fail closed when protected agi-core paths are changed by other actors."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
ZERO_SHA = "0" * 40
EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
DEFAULT_ALLOWED_ACTORS = ("jpmorard",)
PROTECTED_PREFIXES = ("src/agilab/core/agi-core/",)
PROTECTED_FILES = ("src/agilab/core/agi-core",)


@dataclass(frozen=True)
class GuardResult:
    actor: str
    allowed_actors: tuple[str, ...]
    protected_files: tuple[str, ...]

    @property
    def actor_allowed(self) -> bool:
        normalized_actor = normalize_actor(self.actor)
        return bool(normalized_actor) and normalized_actor in {
            normalize_actor(actor) for actor in self.allowed_actors
        }

    @property
    def passed(self) -> bool:
        return not self.protected_files or self.actor_allowed


def normalize_actor(actor: str | None) -> str:
    return (actor or "").strip().lower()


def is_protected_path(path: str) -> bool:
    normalized = path.strip().replace("\\", "/")
    return normalized in PROTECTED_FILES or any(
        normalized.startswith(prefix) for prefix in PROTECTED_PREFIXES
    )


def protected_changed_files(paths: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({path for path in paths if is_protected_path(path)}))


def _run_git(args: Sequence[str], *, repo_root: Path = REPO_ROOT) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def changed_files_between(base_ref: str, head_ref: str, *, repo_root: Path = REPO_ROOT) -> tuple[str, ...]:
    base = EMPTY_TREE_SHA if normalize_actor(base_ref) == ZERO_SHA else base_ref
    output = _run_git(
        ["diff", "--name-only", "--diff-filter=ACMR", base, head_ref],
        repo_root=repo_root,
    )
    return tuple(line.strip() for line in output.splitlines() if line.strip())


def read_changed_files(path: Path) -> tuple[str, ...]:
    return tuple(line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def evaluate(
    changed_files: Sequence[str],
    *,
    actor: str,
    allowed_actors: Sequence[str] = DEFAULT_ALLOWED_ACTORS,
) -> GuardResult:
    return GuardResult(
        actor=actor,
        allowed_actors=tuple(allowed_actors),
        protected_files=protected_changed_files(changed_files),
    )


def render_result(result: GuardResult) -> str:
    if result.passed:
        if result.protected_files:
            return f"agi-core owner guard: allowed actor {result.actor!r}"
        return "agi-core owner guard: no protected agi-core changes"

    actor = result.actor or "(missing)"
    lines = [
        "agi-core owner guard: blocked protected agi-core change",
        f"actor: {actor}",
        "allowed actors: " + ", ".join(result.allowed_actors),
        "protected files:",
    ]
    lines.extend(f"- {path}" for path in result.protected_files)
    return "\n".join(lines)


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--actor",
        default=os.environ.get("AGILAB_CORE_CHANGE_ACTOR") or os.environ.get("GITHUB_ACTOR") or "",
        help="Actor attempting the change. Defaults to AGILAB_CORE_CHANGE_ACTOR or GITHUB_ACTOR.",
    )
    parser.add_argument(
        "--allowed-actor",
        action="append",
        default=None,
        help="Actor allowed to change agi-core. May be repeated. Defaults to jpmorard.",
    )
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--changed-files", type=Path)
    parser.add_argument("--base-ref", help="Base ref for git diff detection.")
    parser.add_argument("--head-ref", help="Head ref for git diff detection.")
    parser.add_argument(
        "--protected-changed",
        action="store_true",
        help="Evaluate as if at least one protected agi-core path changed.",
    )
    return parser.parse_args(argv)


def _changed_files_from_args(args: argparse.Namespace) -> tuple[str, ...]:
    paths: list[str] = list(args.changed_file or [])
    if args.changed_files:
        paths.extend(read_changed_files(args.changed_files))
    if args.base_ref or args.head_ref:
        if not args.base_ref or not args.head_ref:
            raise SystemExit("--base-ref and --head-ref must be provided together")
        paths.extend(changed_files_between(args.base_ref, args.head_ref))
    if args.protected_changed:
        paths.append(PROTECTED_PREFIXES[0] + "__guard_probe__")
    return tuple(paths)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    allowed_actors = tuple(args.allowed_actor or DEFAULT_ALLOWED_ACTORS)
    result = evaluate(
        _changed_files_from_args(args),
        actor=args.actor,
        allowed_actors=allowed_actors,
    )
    output = render_result(result)
    stream = sys.stdout if result.passed else sys.stderr
    print(output, file=stream)
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
