#!/usr/bin/env python3
"""Install the exact PyPI package declared by the release-proof manifest."""

from __future__ import annotations

import argparse
import json
from importlib import metadata
from pathlib import Path
import subprocess
import sys
import time
import tomllib
from typing import Callable, Sequence
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_MANIFEST = Path("docs/source/data/release_proof.toml")
DEFAULT_PROJECT = Path("pyproject.toml")


def _release_package_spec(package_name: str, package_version: str, extras: Sequence[str]) -> str:
    normalized_extras = [str(extra).strip() for extra in extras if str(extra).strip()]
    if normalized_extras:
        extras_text = ",".join(sorted(normalized_extras))
        return f"{package_name}[{extras_text}]=={package_version}"
    return f"{package_name}=={package_version}"


def release_package_spec(manifest_path: Path) -> tuple[str, str, str]:
    """Return package name, version, and exact pip spec from release_proof.toml."""
    with manifest_path.open("rb") as stream:
        manifest = tomllib.load(stream)
    release = manifest.get("release", {})
    package_name = str(release.get("package_name", "")).strip()
    package_version = str(release.get("package_version", "")).strip()
    package_extras = release.get("package_extras", []) or []
    if not isinstance(package_extras, list):
        raise ValueError(f"{manifest_path} release.package_extras must be a list when provided")
    if not package_name or not package_version:
        raise ValueError(
            f"{manifest_path} must contain release.package_name and release.package_version"
        )
    return package_name, package_version, _release_package_spec(
        package_name,
        package_version,
        package_extras,
    )


def _normalized_version_token(version: str) -> str:
    parts: list[str] = []
    for part in str(version).strip().lower().split("."):
        if part.isdigit():
            parts.append(str(int(part)))
        elif part.startswith("post") and part[4:].isdigit():
            parts.append(f"post{int(part[4:])}")
        else:
            parts.append(part)
    return ".".join(parts)


def _version_sort_key(version: str) -> tuple[tuple[int, int | str], ...]:
    key: list[tuple[int, int | str]] = []
    for part in _normalized_version_token(version).replace("-", ".").split("."):
        if part.isdigit():
            key.append((0, int(part)))
        elif part.startswith("post") and part[4:].isdigit():
            key.append((1, int(part[4:])))
        else:
            key.append((2, part))
    return tuple(key)


def project_version(project_path: Path) -> str:
    """Return the root project version declared by ``pyproject.toml``."""
    with project_path.open("rb") as stream:
        pyproject = tomllib.load(stream)
    version = str(pyproject.get("project", {}).get("version", "")).strip()
    if not version:
        raise ValueError(f"{project_path} must contain project.version")
    return version


def project_version_newer_than_manifest(project_path: Path, manifest_path: Path) -> bool:
    """Return whether the checkout version is ahead of public release proof."""
    _package_name, package_version, _package_spec = release_package_spec(manifest_path)
    return _version_sort_key(project_version(project_path)) > _version_sort_key(package_version)


def pypi_release_visible(
    package_name: str,
    package_version: str,
    *,
    timeout: float = 20.0,
    opener=urllib.request.urlopen,
) -> bool:
    """Return whether PyPI JSON exposes the manifest-pinned release version."""
    quoted_name = urllib.parse.quote(package_name, safe="")
    url = f"https://pypi.org/pypi/{quoted_name}/json"
    expected = _normalized_version_token(package_version)
    try:
        with opener(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        OSError,
        TimeoutError,
        urllib.error.URLError,
        json.JSONDecodeError,
    ):
        return False
    releases = payload.get("releases", {})
    if not isinstance(releases, dict):
        return False
    return expected in {_normalized_version_token(version) for version in releases}


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
Sleeper = Callable[[float], None]


def _run(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, text=True)


def _show_available_versions(package_name: str, runner: Runner) -> None:
    print(f"[install] PyPI versions visible for {package_name}:", file=sys.stderr)
    runner([sys.executable, "-m", "pip", "index", "versions", package_name])


def pypi_release_installable(
    package_spec: str,
    *,
    runner: Runner = _run,
) -> bool:
    """Return whether pip can resolve the manifest-pinned release spec."""
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--dry-run",
        "--ignore-installed",
        "--no-cache-dir",
        package_spec,
    ]
    return int(runner(cmd).returncode) == 0


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
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--retries", type=int, default=20)
    parser.add_argument("--delay-seconds", type=float, default=15.0)
    parser.add_argument(
        "--check-available-only",
        action="store_true",
        help=(
            "Exit 0 only when the release-proof package version is visible on "
            "PyPI. This supports CI guards that avoid racing a just-pushed "
            "release tag."
        ),
    )
    parser.add_argument(
        "--check-installable-only",
        action="store_true",
        help=(
            "Exit 0 only when pip can resolve the exact release-proof package "
            "spec from PyPI. This is stricter than visibility and catches stale "
            "split-package dependencies."
        ),
    )
    parser.add_argument(
        "--check-project-newer-than-manifest",
        action="store_true",
        help=(
            "Exit 0 when pyproject.toml declares a version newer than the "
            "release-proof manifest. CI uses this to skip stale public-package "
            "checks during non-strict pre-release branches."
        ),
    )
    args = parser.parse_args(argv)

    package_name, package_version, package_spec = release_package_spec(args.manifest)
    check_modes = [
        args.check_available_only,
        args.check_installable_only,
        args.check_project_newer_than_manifest,
    ]
    if sum(bool(mode) for mode in check_modes) > 1:
        parser.error(
            "--check-available-only, --check-installable-only, and "
            "--check-project-newer-than-manifest are mutually exclusive"
        )
    if args.check_project_newer_than_manifest:
        if project_version_newer_than_manifest(args.project, args.manifest):
            print(
                f"[install] {args.project} version is newer than {args.manifest} release proof"
            )
            return 0
        print(
            f"[install] {args.project} version is not newer than {args.manifest} release proof",
            file=sys.stderr,
        )
        return 1
    if args.check_available_only:
        if pypi_release_visible(package_name, package_version):
            print(f"[install] {package_name} {package_version} is visible on PyPI")
            return 0
        print(
            f"[install] {package_name} {package_version} is not visible on PyPI",
            file=sys.stderr,
        )
        _show_available_versions(package_name, _run)
        return 1
    if args.check_installable_only:
        if pypi_release_installable(package_spec):
            print(f"[install] {package_spec} is installable from PyPI")
            return 0
        print(
            f"[install] {package_spec} is not installable from PyPI",
            file=sys.stderr,
        )
        _show_available_versions(package_name, _run)
        return 1
    return install_with_retry(
        package_name,
        package_spec,
        retries=args.retries,
        delay_seconds=args.delay_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
