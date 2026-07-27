"""Run root tests in existing coverage-contract process boundaries.

Many root tests intentionally replace imported modules while exercising optional
dependencies and dynamic app loading. Running every file in one interpreter lets
that state leak into later files. The coverage workflow already maintains stable
GUI-oriented chunks, so the local canonical gate reuses those boundaries and
runs the remaining root files in a separate process.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from tools.coverage_shard_plan import static_chunk_args

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_TEST_DIR = REPO_ROOT / "test"
PYTEST_OPTIONS_WITH_VALUES = frozenset({"-k", "-m", "-o"})


@dataclass(frozen=True)
class RootTestGroup:
    name: str
    pytest_args: tuple[str, ...]
    test_files: tuple[str, ...]


def _repo_relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def _expand_test_target(target: str) -> tuple[str, ...]:
    if any(token in target for token in "*?["):
        matches = sorted(REPO_ROOT.glob(target))
    else:
        path = REPO_ROOT / target
        if path.is_dir():
            matches = sorted(path.rglob("test*.py"))
        elif path.is_file():
            matches = [path]
        else:
            matches = []
    return tuple(
        _repo_relative(path)
        for path in matches
        if path.is_file() and _repo_relative(path).startswith("test/")
    )


def _expand_chunk_args(
    args: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    expanded: list[str] = []
    test_files: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in PYTEST_OPTIONS_WITH_VALUES:
            if index + 1 >= len(args):
                raise ValueError(f"pytest option {arg} is missing its value")
            expanded.extend((arg, args[index + 1]))
            index += 2
            continue
        if arg.startswith("-"):
            expanded.append(arg)
            index += 1
            continue
        paths = _expand_test_target(arg)
        expanded.extend(paths)
        test_files.extend(paths)
        index += 1
    return tuple(expanded), tuple(dict.fromkeys(test_files))


def build_root_test_groups() -> tuple[RootTestGroup, ...]:
    """Return deterministic root-test groups with complete file coverage."""

    chunk_groups: list[RootTestGroup] = []
    classified: set[str] = set()
    for name, args in static_chunk_args().items():
        expanded_args, test_files = _expand_chunk_args(args)
        if not test_files:
            continue
        classified.update(test_files)
        chunk_groups.append(RootTestGroup(name, expanded_args, test_files))

    discovered = tuple(
        _repo_relative(path) for path in sorted(ROOT_TEST_DIR.glob("test_*.py"))
    )
    general = tuple(path for path in discovered if path not in classified)
    # The unclassified root tests contain several dynamic-import and Streamlit
    # harnesses that intentionally replace process-global modules. Give each
    # file its own interpreter so one test module cannot corrupt a later one.
    groups = [
        RootTestGroup(f"general:{Path(path).stem}", (path,), (path,))
        for path in general
    ]
    groups.extend(chunk_groups)

    planned = {path for group in groups for path in group.test_files}
    missing = sorted(set(discovered) - planned)
    if missing:
        raise RuntimeError(
            "root test plan omitted files: " + ", ".join(missing)
        )
    return tuple(groups)


def _pytest_command(group: RootTestGroup) -> tuple[str, ...]:
    return (
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-o",
        "addopts=",
        "--import-mode=importlib",
        *group.pytest_args,
    )


def _pytest_environment() -> dict[str, str]:
    """Keep nested uv operations from mutating the runner's environment."""

    env = dict(os.environ)
    for name in ("UV_PROJECT_ENVIRONMENT", "UV_RUN_RECURSION_DEPTH", "VIRTUAL_ENV"):
        env.pop(name, None)
    return env


def run_root_test_groups(
    groups: Sequence[RootTestGroup],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> int:
    """Run every group in a fresh interpreter and aggregate failures."""

    aggregate_returncode = 0
    for group in groups:
        print(
            f"[root-test] {group.name}: {len(group.test_files)} file(s)",
            file=sys.stderr,
            flush=True,
        )
        completed = runner(
            _pytest_command(group),
            cwd=REPO_ROOT,
            check=False,
            env=_pytest_environment(),
        )
        if completed.returncode:
            aggregate_returncode = aggregate_returncode or completed.returncode
            print(
                f"[root-test] {group.name}: failed exit={completed.returncode}",
                file=sys.stderr,
                flush=True,
            )
        else:
            print(
                f"[root-test] {group.name}: passed",
                file=sys.stderr,
                flush=True,
            )
    return aggregate_returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run root tests in isolated coverage-contract groups."
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the group names and test-file counts without running pytest.",
    )
    args = parser.parse_args(argv)
    groups = build_root_test_groups()
    if args.list:
        for group in groups:
            print(f"{group.name}\t{len(group.test_files)}")
        return 0
    return run_root_test_groups(groups)


if __name__ == "__main__":
    raise SystemExit(main())
