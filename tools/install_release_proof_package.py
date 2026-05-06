#!/usr/bin/env python3
"""Install the exact PyPI package declared by the release-proof manifest."""

from __future__ import annotations

import argparse
from importlib import metadata
from pathlib import Path
import subprocess
import sys
import time
import tomllib
from typing import Callable, Sequence


DEFAULT_MANIFEST = Path("docs/source/data/release_proof.toml")


def release_package_spec(manifest_path: Path) -> tuple[str, str, str]:
    """Return package name, version, and exact pip spec from release_proof.toml."""
    with manifest_path.open("rb") as stream:
        manifest = tomllib.load(stream)
    release = manifest.get("release", {})
    package_name = str(release.get("package_name", "")).strip()
    package_version = str(release.get("package_version", "")).strip()
    if not package_name or not package_version:
        raise ValueError(
            f"{manifest_path} must contain release.package_name and release.package_version"
        )
    return package_name, package_version, f"{package_name}=={package_version}"


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
Sleeper = Callable[[float], None]


def _run(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, text=True)


def _show_available_versions(package_name: str, runner: Runner) -> None:
    print(f"[install] PyPI versions visible for {package_name}:", file=sys.stderr)
    runner([sys.executable, "-m", "pip", "index", "versions", package_name])


def install_with_retry(
    package_name: str,
    package_spec: str,
    *,
    retries: int,
    delay_seconds: float,
    runner: Runner = _run,
    sleeper: Sleeper = time.sleep,
    diagnose: bool = True,
) -> int:
    """Install a manifest-pinned package, retrying while PyPI propagates a release."""
    if retries < 1:
        raise ValueError("retries must be >= 1")
    last_returncode = 1
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-cache-dir",
        package_spec,
    ]
    for attempt in range(1, retries + 1):
        print(f"[install] attempt {attempt}/{retries}: {package_spec}", flush=True)
        result = runner(cmd)
        last_returncode = int(result.returncode)
        if last_returncode == 0:
            try:
                installed = metadata.version(package_name)
            except metadata.PackageNotFoundError:
                print(
                    f"[install] {package_name} installed but metadata was not found",
                    file=sys.stderr,
                )
                return 1
            print(f"[install] installed {package_name} {installed}", flush=True)
            return 0
        if attempt < retries:
            if diagnose:
                _show_available_versions(package_name, runner)
            print(
                f"[install] {package_spec} is not installable yet; retrying in "
                f"{delay_seconds:g}s",
                file=sys.stderr,
                flush=True,
            )
            sleeper(delay_seconds)
    return last_returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Install the exact package version recorded in docs/source/data/"
            "release_proof.toml."
        )
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--retries", type=int, default=20)
    parser.add_argument("--delay-seconds", type=float, default=15.0)
    args = parser.parse_args(argv)

    package_name, _package_version, package_spec = release_package_spec(args.manifest)
    return install_with_retry(
        package_name,
        package_spec,
        retries=args.retries,
        delay_seconds=args.delay_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
