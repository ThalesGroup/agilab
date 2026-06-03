#!/usr/bin/env python3
"""Create a clean AGILAB task worktree for one isolated change."""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKTREE_ROOT = REPO_ROOT.parent / "agilab-worktrees"


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


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._/-]+", "-", value.strip()).strip("-/")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        raise ValueError("branch name cannot be empty")
    return slug


def default_path(branch: str, *, root: Path = DEFAULT_WORKTREE_ROOT) -> Path:
    return root / _slug(branch).replace("/", "-")


def default_start_point() -> str:
    try:
        _run_git(["rev-parse", "--verify", "@{u}"])
    except subprocess.CalledProcessError:
        return "HEAD"
    return "@{u}"


def planned_command(branch: str, *, path: Path | None = None, start_point: str | None = None, force: bool = False) -> list[str]:
    branch_name = _slug(branch)
    target_path = path or default_path(branch_name)
    command = ["git", "worktree", "add"]
    if force:
        command.append("--force")
    command.extend(["-B", branch_name, str(target_path), start_point or default_start_point()])
    return command


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("branch", help="Task branch name, for example fix/pytorch-playground-coach.")
    parser.add_argument("--path", type=Path, default=None, help="Override the worktree path.")
    parser.add_argument("--start-point", default=None, help="Default: upstream branch when available, else HEAD.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--print-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    command = planned_command(
        args.branch,
        path=args.path,
        start_point=args.start_point,
        force=args.force,
    )
    print(shlex.join(command))
    if args.print_only:
        return 0
    completed = subprocess.run(command, cwd=REPO_ROOT)
    if completed.returncode == 0:
        print(f"cd {shlex.quote(command[-2])}")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
