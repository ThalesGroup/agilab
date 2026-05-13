#!/usr/bin/env python3
"""Check whether built distributions already exist on PyPI.

The release workflow uses this before authenticating to PyPI. If every built
package version already exists, the publish step can be skipped safely. If a
built version is older than the current PyPI latest, the workflow fails before a
misleading release can pass.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from packaging.utils import (
    InvalidSdistFilename,
    InvalidWheelFilename,
    canonicalize_name,
    parse_sdist_filename,
    parse_wheel_filename,
)
from packaging.version import InvalidVersion, Version


PYPI_JSON_URL = "https://pypi.org/pypi/{name}/json"


class DistributionStateError(RuntimeError):
    """Raised when distribution state cannot be safely evaluated."""


@dataclass(frozen=True)
class DistributionState:
    path: Path
    name: str
    version: Version
    filename: str
    exists: bool
    latest: Version | None


def _parse_distribution_name(path: Path) -> tuple[str, Version]:
    filename = path.name
    try:
        if filename.endswith(".whl"):
            name, version, _build, _tags = parse_wheel_filename(filename)
        elif filename.endswith((".tar.gz", ".zip")):
            name, version = parse_sdist_filename(filename)
        else:
            raise DistributionStateError(f"unsupported distribution file: {path}")
    except (InvalidWheelFilename, InvalidSdistFilename, InvalidVersion) as exc:
        raise DistributionStateError(f"invalid distribution filename: {path}") from exc
    return str(canonicalize_name(name)), version


def _is_distribution_file(path: Path) -> bool:
    return path.name.endswith((".whl", ".tar.gz", ".zip"))


def fetch_pypi_releases(name: str) -> set[Version]:
    return set(fetch_pypi_distribution_files(name))


def fetch_pypi_distribution_files(name: str) -> dict[Version, set[str]]:
    url = PYPI_JSON_URL.format(name=urllib.parse.quote(name))
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {}
        raise DistributionStateError(f"could not fetch PyPI metadata for {name}: HTTP {exc.code}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise DistributionStateError(f"could not fetch PyPI metadata for {name}: {exc}") from exc

    releases: dict[Version, set[str]] = {}
    for raw_version, files in (payload.get("releases") or {}).items():
        try:
            version = Version(str(raw_version))
        except InvalidVersion:
            continue
        filenames = {
            str(file_payload.get("filename"))
            for file_payload in files or []
            if isinstance(file_payload, dict) and file_payload.get("filename")
        }
        releases[version] = filenames
    return releases


def analyze_distribution_dir(
    dist_dir: Path,
    *,
    fetch_releases: Callable[[str], set[Version]] | None = None,
    fetch_distributions: Callable[[str], dict[Version, set[str]]] | None = None,
) -> list[DistributionState]:
    files = sorted(path for path in dist_dir.iterdir() if path.is_file() and _is_distribution_file(path))
    if not files:
        raise DistributionStateError(f"no distribution files found in {dist_dir}")

    release_cache: dict[str, set[Version]] = {}
    distribution_cache: dict[str, dict[Version, set[str]]] = {}
    states: list[DistributionState] = []
    for path in files:
        name, version = _parse_distribution_name(path)
        exact_filenames_known = fetch_releases is None
        if fetch_distributions is not None:
            distributions = distribution_cache.setdefault(name, fetch_distributions(name))
            releases = set(distributions)
            exact_filenames_known = True
        elif fetch_releases is not None:
            releases = release_cache.setdefault(name, fetch_releases(name))
            distributions = {release: set() for release in releases}
        else:
            distributions = distribution_cache.setdefault(name, fetch_pypi_distribution_files(name))
            releases = set(distributions)
        latest = max(releases) if releases else None
        if latest is not None and version < latest:
            raise DistributionStateError(
                f"{path.name} is version {version}, but PyPI latest for {name} is {latest}"
            )
        exists = path.name in distributions.get(version, set()) if exact_filenames_known else version in releases
        states.append(
            DistributionState(
                path=path,
                name=name,
                version=version,
                filename=path.name,
                exists=exists,
                latest=latest,
            )
        )
    return states


def all_distributions_exist(states: Iterable[DistributionState]) -> bool:
    return all(state.exists for state in states)


def write_github_output(path: Path, states: list[DistributionState]) -> None:
    existing = sum(1 for state in states if state.exists)
    missing = len(states) - existing
    all_exist = "true" if missing == 0 else "false"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"all-exist={all_exist}\n")
        handle.write(f"existing-count={existing}\n")
        handle.write(f"missing-count={missing}\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        states = analyze_distribution_dir(args.dist_dir)
    except DistributionStateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    for state in states:
        remote = "exists" if state.exists else "missing"
        latest = state.latest if state.latest is not None else "none"
        print(f"{state.path.name}: {state.name} {state.version} -> {remote} (latest={latest})")

    if args.github_output is not None:
        write_github_output(args.github_output, states)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
