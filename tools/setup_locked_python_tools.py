"""Install repository hash-locked tools in a fresh environment before credentials."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
UV_VERSION = "0.10.7"
REQUIREMENTS_PATTERN = r"\.github/requirements/ci-[a-z0-9-]+\.txt"


class LockedToolsError(ValueError):
    """Invalid installer inputs or an unsupported uv version."""


def validate_requirements(requirements: str, root: Path) -> Path:
    if re.fullmatch(REQUIREMENTS_PATTERN, requirements) is None:
        raise LockedToolsError(f"Unsupported CI requirements path: {requirements}")
    path = root.resolve() / requirements
    if path.resolve() != path or not path.is_file():
        raise LockedToolsError(f"Missing or redirected CI requirements file: {requirements}")
    return path


def isolated_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for key in (
        "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "UV_PROJECT", "UV_ENV_FILE",
        "UV_PYTHON", "PYTHONPATH", "AGILAB_DEV_UV_PROJECT_ENVIRONMENT",
    ):
        environment.pop(key, None)
    environment.update(
        UV_NO_CONFIG="1", UV_NO_CACHE="1", UV_PYTHON_DOWNLOADS="never",
        PYTHONNOUSERSITE="1",
    )
    return environment


def install_tools(
    requirements: str,
    *,
    root: Path = REPO_ROOT,
    github_env: bool = False,
) -> Path:
    # Validate every external input before invoking uv or creating an environment.
    path = validate_requirements(requirements, root)
    exports: dict[str, Path] = {}
    if github_env:
        for key in ("GITHUB_PATH", "GITHUB_ENV"):
            value = os.environ.get(key)
            if not value or not Path(value).is_file():
                raise LockedToolsError(f"{key} must name an existing workflow command file")
            exports[key] = Path(value)
    environment = isolated_environment()
    version = subprocess.run(
        ["uv", "--version"], check=True, capture_output=True, text=True,
        env=environment,
    ).stdout.split()
    if version[:2] != ["uv", UV_VERSION]:
        raise LockedToolsError(f"Expected uv {UV_VERSION}; set up that pinned version first")

    target = Path(tempfile.mkdtemp(prefix=f"agilab-{path.stem}-"))
    python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    try:
        subprocess.run(
            ["uv", "venv", "--python", sys.executable, str(target)],
            check=True, env=environment,
        )
        subprocess.run(
            [
                "uv", "pip", "install", "--python", str(python),
                "--require-hashes", "--no-build", "--no-cache",
                "--requirements", str(path),
            ],
            check=True, env=environment,
        )
        # Failed installations never become a subsequent workflow step's PATH.
        if github_env:
            with exports["GITHUB_PATH"].open("a", encoding="utf-8") as output:
                output.write(str(python.parent) + "\n")
            with exports["GITHUB_ENV"].open("a", encoding="utf-8") as output:
                output.write(f"AGILAB_DEV_UV_PROJECT_ENVIRONMENT={target}\n")
    except BaseException:
        shutil.rmtree(target)
        raise
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", required=True)
    parser.add_argument(
        "--github-env", action="store_true",
        help="Export the installed environment to GITHUB_PATH and GITHUB_ENV.",
    )
    parser.add_argument(
        "--run", nargs=argparse.REMAINDER, metavar="COMMAND",
        help="Run a command in the locked environment, then remove that environment.",
    )
    args = parser.parse_args(argv)
    if args.run == []:
        parser.error("--run requires a command")
    if args.github_env and args.run is not None:
        parser.error("--github-env and --run cannot be combined")
    try:
        target = install_tools(args.requirements, github_env=args.github_env)
    except (LockedToolsError, OSError, subprocess.CalledProcessError) as error:
        print(f"Locked tools setup failed: {error}", file=sys.stderr)
        return 2
    if args.run is None:
        print(f"Locked tools environment: {target}")
        return 0
    try:
        environment = isolated_environment()
        bin_dir = target / ("Scripts" if os.name == "nt" else "bin")
        environment["PATH"] = str(bin_dir) + os.pathsep + environment.get("PATH", "")
        environment["VIRTUAL_ENV"] = str(target)
        environment["AGILAB_DEV_UV_PROJECT_ENVIRONMENT"] = str(target)
        return subprocess.run(args.run, env=environment, check=False).returncode
    finally:
        shutil.rmtree(target)


if __name__ == "__main__":
    raise SystemExit(main())
