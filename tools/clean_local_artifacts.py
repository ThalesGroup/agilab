#!/usr/bin/env python3
"""Remove ignored local artifacts that commonly pollute AGILAB checkouts."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
STALE_BUILD_LIB_DIRS = (
    Path("src/agilab/core/agi-env/build/lib"),
    Path("src/agilab/core/agi-node/build/lib"),
)


class CleanResult(NamedTuple):
    path: str
    action: str
    exists: bool


def repo_root(repo: str | Path) -> Path:
    """Return the Git repository root for ``repo``."""

    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=Path(repo),
        check=True,
        text=True,
        capture_output=True,
    )
    return Path(completed.stdout.strip()).resolve()


def stale_build_lib_paths(root: Path) -> list[Path]:
    """Return known stale setuptools ``build/lib`` duplicate-source trees."""

    return [root / rel for rel in STALE_BUILD_LIB_DIRS]


def _is_safe_clean_target(root: Path, target: Path) -> bool:
    resolved_root = root.resolve()
    resolved_target = target.resolve(strict=False)
    try:
        resolved_target.relative_to(resolved_root)
    except ValueError:
        return False
    return resolved_target.name == "lib" and resolved_target.parent.name == "build"


def clean_stale_build_libs(root: Path, *, apply: bool = False) -> list[CleanResult]:
    """Dry-run or remove known stale ``build/lib`` duplicate-source trees."""

    results: list[CleanResult] = []
    for target in stale_build_lib_paths(root):
        rel = target.relative_to(root).as_posix()
        exists = target.exists()
        if not exists:
            results.append(CleanResult(path=rel, action="missing", exists=False))
            continue
        if not _is_safe_clean_target(root, target):
            raise RuntimeError(f"Refusing unsafe clean target: {target}")
        if apply:
            shutil.rmtree(target)
            results.append(CleanResult(path=rel, action="removed", exists=True))
        else:
            results.append(CleanResult(path=rel, action="would-remove", exists=True))
    return results


def _print_human(results: Sequence[CleanResult], *, apply: bool) -> None:
    actionable = [result for result in results if result.action != "missing"]
    if not actionable:
        print("No stale local build/lib artifacts found.")
        return

    verb = "Removed" if apply else "Would remove"
    for result in actionable:
        print(f"{verb}: {result.path}")
    if not apply:
        print("Dry run only. Re-run with --apply to remove these ignored local artifacts.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Clean ignored AGILAB local artifacts that duplicate source trees."
    )
    parser.add_argument("--repo", default=str(REPO_ROOT), help="Repository checkout to clean.")
    parser.add_argument("--apply", action="store_true", help="Actually remove stale artifacts.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = repo_root(args.repo)
    results = clean_stale_build_libs(root, apply=bool(args.apply))

    if args.json:
        payload = {
            "schema": "agilab.clean_local_artifacts.v1",
            "repo": str(root),
            "apply": bool(args.apply),
            "results": [result._asdict() for result in results],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_human(results, apply=bool(args.apply))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
