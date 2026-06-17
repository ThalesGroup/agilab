#!/usr/bin/env python3
"""Run built-in app tests in their own app project environments."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILTIN_APPS_ROOT = REPO_ROOT / "src" / "agilab" / "apps" / "builtin"
DEFAULT_PYTEST_ARGS = (
    "-q",
    "--disable-warnings",
    "-o",
    "addopts=",
    "--import-mode=importlib",
    "test",
)


class BuiltinAppTestTarget(NamedTuple):
    name: str
    path: Path


def discover_builtin_app_tests(root: Path = BUILTIN_APPS_ROOT) -> list[BuiltinAppTestTarget]:
    """Return built-in app projects that own pytest tests."""

    if not root.exists():
        return []
    targets: list[BuiltinAppTestTarget] = []
    for app_dir in sorted(root.glob("*_project")):
        test_dir = app_dir / "test"
        if test_dir.is_dir() and any(test_dir.glob("test_*.py")):
            targets.append(BuiltinAppTestTarget(name=app_dir.name, path=app_dir))
    return targets


def build_pytest_command(pytest_args: Sequence[str] = ()) -> list[str]:
    """Build the app-local pytest command used for each built-in app."""

    forwarded = list(pytest_args)
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]
    if not forwarded:
        forwarded = list(DEFAULT_PYTEST_ARGS)
    return [
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "--project",
        ".",
        "--with",
        "pytest",
        "--with",
        "pytest-asyncio",
        "python",
        "-m",
        "pytest",
        *forwarded,
    ]


def subprocess_env() -> dict[str, str]:
    """Return an environment that lets uv select each app's project environment."""

    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    return env


def _selected_targets(
    targets: Sequence[BuiltinAppTestTarget], app_names: Sequence[str]
) -> list[BuiltinAppTestTarget]:
    if not app_names:
        return list(targets)
    requested = set(app_names)
    selected = [target for target in targets if target.name in requested]
    missing = sorted(requested.difference(target.name for target in selected))
    if missing:
        raise SystemExit(f"unknown built-in app test target(s): {', '.join(missing)}")
    return selected


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--app",
        action="append",
        default=[],
        help="Built-in app project name to test. May be passed more than once.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List built-in app projects with tests and exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print app-local pytest commands without executing them.",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Continue testing remaining apps after a failure.",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Optional pytest arguments after '--'. Defaults to the app test directory.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    targets = _selected_targets(discover_builtin_app_tests(), args.app)
    if args.list:
        for target in targets:
            print(target.name)
        return 0
    if not targets:
        print("No built-in app test targets found.", file=sys.stderr)
        return 1

    command = build_pytest_command(args.pytest_args)
    failures: list[str] = []
    for target in targets:
        print(f"\n== {target.path.relative_to(REPO_ROOT)} ==", flush=True)
        if args.dry_run:
            print(shlex.join(command))
            continue
        result = subprocess.run(command, cwd=target.path, check=False, env=subprocess_env())
        if result.returncode:
            failures.append(target.name)
            if not args.keep_going:
                return result.returncode

    if failures:
        print(f"Failed built-in app test target(s): {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
