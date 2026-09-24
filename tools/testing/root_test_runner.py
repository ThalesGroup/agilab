"""Run root tests in existing coverage-contract process boundaries.

Many root tests intentionally replace imported modules while exercising optional
dependencies and dynamic app loading. Running every file in one interpreter lets
that state leak into later files. The coverage workflow already maintains stable
GUI-oriented chunks, so the local canonical gate reuses those boundaries and
runs the remaining root files in a separate process.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from tools.coverage_shard_plan import static_chunk_args
from tools.testing.pytest_entrypoint import cleaned_test_environment

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_TEST_DIR = REPO_ROOT / "test"
PYTEST_OPTIONS_WITH_VALUES = frozenset({"-k", "-m", "-o"})


@dataclass(frozen=True)
class RootTestGroup:
    name: str
    pytest_args: tuple[str, ...]
    test_files: tuple[str, ...]
    working_directory: Path | None = None


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


def build_demo_test_groups() -> tuple[RootTestGroup, ...]:
    """Discover the test entrypoints shipped with standalone demo bundles."""
    resources = REPO_ROOT / "src/agilab/demos/resources"
    return tuple(
        RootTestGroup(
            f"demos:{path.parent.name}",
            ("-c", "/dev/null", "-o", "pythonpath=.", "-p", "no:cacheprovider", "tests.py"),
            (_repo_relative(path),),
            path.parent,
        )
        for path in sorted(resources.glob("*/tests.py"))
    )


def _pytest_command(
    group: RootTestGroup,
    coverage_data_file: Path | None = None,
    junit_dir: Path | None = None,
    coverage_config: Path | None = None,
) -> tuple[str, ...]:
    prefix = (sys.executable,)
    if coverage_data_file is not None:
        prefix += (
            "-m", "coverage", "run",
            f"--rcfile={(coverage_config or REPO_ROOT / '.coveragerc.agi-gui').resolve()}",
            f"--source={REPO_ROOT / 'src/agilab'}",
            f"--data-file={coverage_data_file.resolve()}", "--parallel-mode",
        )
    reports = ()
    if junit_dir is not None:
        name = group.name.replace(":", "-")
        reports = (f"--junitxml={junit_dir.resolve() / f'junit-agi-gui-{name}.xml'}",)
    selection = ("-m", "not integration") if coverage_data_file is not None else ()
    return (
        *prefix,
        "-m",
        "pytest" if group.working_directory is not None else "tools.testing.pytest_entrypoint",
        "-q",
        "-o",
        "addopts=",
        *reports,
        *selection,
        *group.pytest_args,
    )


def _pytest_environment() -> dict[str, str]:
    """Keep nested uv operations from mutating the runner's environment."""

    return cleaned_test_environment()


def run_root_test_groups(
    groups: Sequence[RootTestGroup],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    coverage_data_file: Path | None = None,
    junit_dir: Path | None = None,
    coverage_config: Path | None = None,
) -> int:
    """Run every group in a fresh interpreter and aggregate failures."""

    if coverage_data_file is not None:
        coverage_data_file.parent.mkdir(parents=True, exist_ok=True)
    if junit_dir is not None:
        junit_dir.mkdir(parents=True, exist_ok=True)
    aggregate_returncode = 0
    for group in groups:
        print(
            f"[root-test] {group.name}: {len(group.test_files)} file(s)",
            file=sys.stderr,
            flush=True,
        )
        completed = runner(
            _pytest_command(group, coverage_data_file, junit_dir, coverage_config),
            cwd=group.working_directory or REPO_ROOT,
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
    parser.add_argument("--demos", action="store_true", help="Run standalone demo bundles in their own working directories.")
    parser.add_argument("--coverage-config", type=Path, help="Coverage configuration for this suite.")
    parser.add_argument("--unclassified", action="store_true", help="Run root tests outside the named coverage chunks.")
    parser.add_argument("--coverage-data-file", type=Path, help="Collect isolated parallel coverage files under this prefix.")
    parser.add_argument("--junit-dir", type=Path, help="Write one JUnit report per isolated group.")
    args = parser.parse_args(argv)
    if args.demos and args.unclassified:
        parser.error("--demos and --unclassified are mutually exclusive")
    groups = build_demo_test_groups() if args.demos else build_root_test_groups()
    if args.unclassified:
        groups = tuple(group for group in groups if group.name.startswith("general:"))
    if args.list:
        for group in groups:
            print(f"{group.name}\t{len(group.test_files)}")
        return 0
    return run_root_test_groups(groups, coverage_data_file=args.coverage_data_file, junit_dir=args.junit_dir, coverage_config=args.coverage_config)


if __name__ == "__main__":
    raise SystemExit(main())
