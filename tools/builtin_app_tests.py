#!/usr/bin/env python3
"""Run built-in app tests in their own app project environments."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import shlex
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from collections.abc import Iterator
from email.parser import BytesParser
from pathlib import Path
from typing import Mapping, NamedTuple, Sequence


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
DEFAULT_APP_TEST_ENVS_ROOT = REPO_ROOT / ".venv-builtin-app-tests"
APP_TEST_ENV_ROOT_ENV = "AGILAB_BUILTIN_APP_TEST_ENV_ROOT"
SDK_PROJECTS_ROOT = REPO_ROOT / "src" / "agilab" / "core"
SDK_PACKAGES = ("agi-env", "agi-node", "agi-cluster", "agi-core")
SDK_VERSION_GUARD = """\
import importlib.metadata as metadata
import json, runpy, sys
from packaging.version import Version
expected = json.loads(sys.argv.pop(1))
for name, version in expected.items():
    actual = metadata.version(name)
    if Version(actual) != Version(version):
        raise SystemExit(f"SDK candidate version mismatch: {name}=={actual}, expected {version}")
if sys.argv.pop(1) != "-m":
    raise SystemExit("expected a Python module after SDK validation")
module = sys.argv.pop(1)
sys.argv[0] = module
runpy.run_module(module, run_name="__main__", alter_sys=True)
"""


class BuiltinAppTestTarget(NamedTuple):
    name: str
    path: Path


def _release_parts(version: str | None) -> tuple[int, ...]:
    """Compare numeric release versions after wheel normalization of leading zeros."""
    if not isinstance(version, str):
        raise ValueError("missing SDK release version")
    return tuple(int(part) for part in version.split("."))


def prepare_sdk_wheels(root: Path) -> tuple[Path, dict[str, str]]:
    """Build prepublication SDK candidates in an owned temporary directory."""

    wheels = root / "wheels"
    wheels.mkdir()
    versions: dict[str, str] = {}
    build_env = os.environ.copy()
    for key in ("VIRTUAL_ENV", "UV_RUN_RECURSION_DEPTH", "UV_FIND_LINKS"):
        build_env.pop(key, None)
    for name in SDK_PACKAGES:
        source = SDK_PROJECTS_ROOT / name
        project = tomllib.loads((source / "pyproject.toml").read_text())["project"]
        if project["name"] != name:
            raise ValueError(f"unexpected SDK project name in {source}")
        version = project["version"]
        copied_source = root / "sources" / name
        shutil.copytree(
            source, copied_source,
            ignore=shutil.ignore_patterns(
                ".venv", "build", "dist", "*.egg-info", "__pycache__",
                ".pytest_cache", ".ruff_cache", ".git",
            ),
        )
        before = set(wheels.glob("*.whl"))
        subprocess.run(
            ["uv", "--no-cache", "build", "--wheel", str(copied_source),
             "--out-dir", str(wheels)],
            check=True, env=build_env,
        )
        created = set(wheels.glob("*.whl")) - before
        if len(created) != 1:
            raise ValueError(f"expected one candidate wheel for {name}, got {len(created)}")
        with zipfile.ZipFile(created.pop()) as archive:
            metadata_files = [path for path in archive.namelist() if path.endswith(".dist-info/METADATA")]
            if len(metadata_files) != 1:
                raise ValueError(f"expected one METADATA record for {name}")
            metadata = BytesParser().parsebytes(archive.read(metadata_files[0]))
        if metadata["Name"] != name or _release_parts(metadata["Version"]) != _release_parts(version):
            raise ValueError(f"candidate wheel metadata does not match {name}=={version}")
        versions[name] = version
    return wheels, versions


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


def build_pytest_command(
    pytest_args: Sequence[str] = (), *, coverage_data_file: Path | None = None,
    junit_path: Path | None = None,
    sdk_versions: Mapping[str, str] | None = None,
) -> list[str]:
    """Build the app-local pytest command used for each built-in app."""

    forwarded = list(pytest_args)
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]
    if not forwarded:
        forwarded = list(DEFAULT_PYTEST_ARGS)
    dependencies = ["--with", "coverage"] if coverage_data_file is not None else []
    instrumentation = []
    if coverage_data_file is not None:
        instrumentation = [
            "-m", "coverage", "run",
            f"--rcfile={REPO_ROOT / '.coveragerc.agi-gui'}",
            f"--source={REPO_ROOT / 'src/agilab'}",
            f"--data-file={coverage_data_file.resolve()}", "--parallel-mode",
        ]
    if junit_path is not None:
        forwarded.append(f"--junitxml={junit_path.resolve()}")
    python = ["python"]
    if sdk_versions is not None:
        python.extend(["-c", SDK_VERSION_GUARD, json.dumps(dict(sdk_versions))])
    return [
        "uv",
        "--no-cache",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "--project",
        ".",
        "--with",
        "pytest",
        "--with",
        "pytest-asyncio",
        *dependencies,
        *python,
        *instrumentation,
        "-m",
        "pytest",
        *forwarded,
    ]


def subprocess_env(
    target: BuiltinAppTestTarget, env_root: Path | None = None,
    sdk_wheels: Path | None = None,
) -> dict[str, str]:
    """Return an isolated uv environment for one built-in app test target."""

    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    env.pop("UV_RUN_RECURSION_DEPTH", None)
    if env_root is None:
        env_root = Path(env.get(APP_TEST_ENV_ROOT_ENV, str(DEFAULT_APP_TEST_ENVS_ROOT)))
    env["UV_PROJECT_ENVIRONMENT"] = str(env_root / target.name)
    # Ignored app-local .venv links must not override the repo test interpreter.
    env["UV_PYTHON"] = sys.executable
    if sdk_wheels is not None:
        # Source preflight only; actual registry qualification rejects find-links.
        env["UV_FIND_LINKS"] = str(sdk_wheels)
    return env


@contextlib.contextmanager
def app_test_env_root() -> Iterator[Path]:
    """Return the root directory used for this runner invocation's app envs."""

    configured = os.environ.get(APP_TEST_ENV_ROOT_ENV)
    if configured:
        yield Path(configured)
        return
    with tempfile.TemporaryDirectory(prefix="agilab-builtin-app-tests-") as temp_dir:
        yield Path(temp_dir)


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
    parser.add_argument("--coverage-data-file", type=Path, help="Collect parallel coverage files under this prefix.")
    parser.add_argument("--junit-dir", type=Path, help="Write a JUnit report per app.")
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

    failures: list[str] = []
    if args.coverage_data_file is not None and not args.dry_run:
        args.coverage_data_file.parent.mkdir(parents=True, exist_ok=True)
    with app_test_env_root() as env_root, contextlib.ExitStack() as stack:
        sdk_wheels = None
        sdk_versions = None
        if not args.dry_run and targets:
            sdk_root = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="agilab-builtin-sdk-wheels-")))
            try:
                sdk_wheels, sdk_versions = prepare_sdk_wheels(sdk_root)
            except (OSError, ValueError, zipfile.BadZipFile, subprocess.CalledProcessError) as exc:
                print(f"Could not prepare built-in test SDK candidates: {exc}", file=sys.stderr)
                return 1
        for target in targets:
            command = build_pytest_command(
                args.pytest_args, coverage_data_file=args.coverage_data_file,
                junit_path=(args.junit_dir / f"junit-agi-gui-builtin-{target.name}.xml") if args.junit_dir is not None else None,
                sdk_versions=sdk_versions,
            )
            print(f"\n== {target.path.relative_to(REPO_ROOT)} ==", flush=True)
            if args.dry_run:
                print(shlex.join(command))
                continue
            result = subprocess.run(
                command,
                cwd=target.path,
                check=False,
                env=subprocess_env(target, env_root, sdk_wheels),
            )
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
