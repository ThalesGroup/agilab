#!/usr/bin/env python3
"""Remove ignored local artifacts that commonly pollute AGILAB checkouts."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
STALE_BUILD_LIB_DIRS = (
    Path("src/agilab/core/agi-env/build/lib"),
    Path("src/agilab/core/agi-node/build/lib"),
)
LOCAL_ARTIFACT_DIR_NAMES = frozenset(
    {
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
    }
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


def _is_safe_build_lib_target(root: Path, target: Path) -> bool:
    resolved_root = root.resolve()
    resolved_target = _resolve_clean_target_path(target)
    try:
        resolved_target.relative_to(resolved_root)
    except ValueError:
        return False
    return resolved_target.name == "lib" and resolved_target.parent.name == "build"


def _is_safe_local_artifact_target(root: Path, target: Path) -> bool:
    resolved_root = root.resolve()
    resolved_target = _resolve_clean_target_path(target)
    try:
        relative = resolved_target.relative_to(resolved_root)
    except ValueError:
        return False
    return len(relative.parts) >= 3 and relative.parts[:2] == ("src", "agilab") and target.name in LOCAL_ARTIFACT_DIR_NAMES


def _resolve_clean_target_path(target: Path) -> Path:
    """Resolve parent directories without following the final artifact symlink."""

    if target.is_symlink():
        return target.parent.resolve(strict=False) / target.name
    return target.resolve(strict=False)


def _remove_clean_target(target: Path) -> None:
    """Remove an ignored artifact path without following final symlinks."""

    if target.is_symlink() or target.is_file():
        target.unlink()
        return
    shutil.rmtree(target)


def _is_git_ignored(root: Path, target: Path) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "-q", "--", str(target)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return completed.returncode == 0


def ignored_local_artifact_paths(root: Path, *, ignored_fn=_is_git_ignored) -> list[Path]:
    """Return ignored local artifact directories below ``src/agilab``."""

    source_root = root / "src" / "agilab"
    if not source_root.is_dir():
        return []

    targets: list[Path] = []
    for current, dirnames, _filenames in os.walk(source_root):
        current_path = Path(current)
        for dirname in list(dirnames):
            candidate = current_path / dirname
            if dirname not in LOCAL_ARTIFACT_DIR_NAMES:
                continue
            dirnames.remove(dirname)
            if _is_safe_local_artifact_target(root, candidate) and ignored_fn(root, candidate):
                targets.append(candidate)
    return sorted(targets)


def clean_stale_build_libs(root: Path, *, apply: bool = False) -> list[CleanResult]:
    """Dry-run or remove known stale ``build/lib`` duplicate-source trees."""

    results: list[CleanResult] = []
    for target in stale_build_lib_paths(root):
        rel = target.relative_to(root).as_posix()
        exists = target.exists()
        if not exists:
            results.append(CleanResult(path=rel, action="missing", exists=False))
            continue
        if not _is_safe_build_lib_target(root, target):
            raise RuntimeError(f"Refusing unsafe clean target: {target}")
        if apply:
            _remove_clean_target(target)
            results.append(CleanResult(path=rel, action="removed", exists=True))
        else:
            results.append(CleanResult(path=rel, action="would-remove", exists=True))
    return results


def clean_ignored_local_artifacts(root: Path, *, apply: bool = False, ignored_fn=_is_git_ignored) -> list[CleanResult]:
    """Dry-run or remove ignored local artifact directories below ``src/agilab``."""

    results: list[CleanResult] = []
    for target in ignored_local_artifact_paths(root, ignored_fn=ignored_fn):
        rel = target.relative_to(root).as_posix()
        if not _is_safe_local_artifact_target(root, target):
            raise RuntimeError(f"Refusing unsafe clean target: {target}")
        if apply:
            _remove_clean_target(target)
            results.append(CleanResult(path=rel, action="removed", exists=True))
        else:
            results.append(CleanResult(path=rel, action="would-remove", exists=True))
    return results


def clean_local_artifacts(root: Path, *, apply: bool = False) -> list[CleanResult]:
    """Dry-run or remove known ignored local artifacts."""

    by_path: dict[str, CleanResult] = {}
    for result in [*clean_stale_build_libs(root, apply=apply), *clean_ignored_local_artifacts(root, apply=apply)]:
        if result.action == "missing":
            by_path.setdefault(result.path, result)
            continue
        by_path[result.path] = result
    return [by_path[path] for path in sorted(by_path)]


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
    results = clean_local_artifacts(root, apply=bool(args.apply))

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
