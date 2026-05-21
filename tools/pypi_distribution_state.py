#!/usr/bin/env python3
"""Check whether expected or built distributions already exist on PyPI.

The release workflow uses this before building and before authenticating to
PyPI. If every package artifact already exists, the build/upload path can be
skipped safely while preserving hash evidence. If a local or expected version is
older than the current PyPI latest, the workflow fails before a misleading
release can pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

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
    kind: str = ""
    size: int = 0
    sha256: str = ""
    url: str = ""
    source: str = "local"


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


def fetch_pypi_distribution_payloads(name: str) -> dict[Version, dict[str, dict[str, Any]]]:
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

    releases: dict[Version, dict[str, dict[str, Any]]] = {}
    for raw_version, files in (payload.get("releases") or {}).items():
        try:
            version = Version(str(raw_version))
        except InvalidVersion:
            continue
        file_payloads: dict[str, dict[str, Any]] = {}
        for file_payload in files or []:
            if not isinstance(file_payload, dict):
                continue
            filename = file_payload.get("filename")
            if not filename:
                continue
            file_payloads[str(filename)] = dict(file_payload)
        releases[version] = file_payloads
    return releases


def fetch_pypi_distribution_files(name: str) -> dict[Version, set[str]]:
    return {
        version: set(file_payloads)
        for version, file_payloads in fetch_pypi_distribution_payloads(name).items()
    }


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


def _filename_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "_", str(canonicalize_name(name))).lower()


def _artifact_kind(filename: str) -> str:
    if filename.endswith(".whl"):
        return "wheel"
    if filename.endswith((".tar.gz", ".zip")):
        return "sdist"
    raise DistributionStateError(f"unsupported distribution file: {filename}")


def expected_distribution_filenames(
    name: str,
    version: Version,
    *,
    artifact_policy: str,
) -> list[str]:
    distribution_name = _filename_distribution_name(name)
    normalized_version = str(version)
    expected = [f"{distribution_name}-{normalized_version}-py3-none-any.whl"]
    if artifact_policy == "wheel-only":
        return expected
    if artifact_policy == "wheel+sdist":
        expected.append(f"{distribution_name}-{normalized_version}.tar.gz")
        return expected
    raise DistributionStateError(f"unknown artifact policy: {artifact_policy}")


def read_project_metadata(project: Path) -> tuple[str, Version]:
    pyproject_path = project if project.name == "pyproject.toml" else project / "pyproject.toml"
    try:
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DistributionStateError(f"could not read project metadata from {pyproject_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise DistributionStateError(f"invalid project metadata in {pyproject_path}") from exc

    project_table = payload.get("project")
    if not isinstance(project_table, dict):
        raise DistributionStateError(f"{pyproject_path} has no [project] table")
    raw_name = project_table.get("name")
    raw_version = project_table.get("version")
    if not raw_name or not raw_version:
        raise DistributionStateError(f"{pyproject_path} must define project.name and project.version")
    try:
        version = Version(str(raw_version))
    except InvalidVersion as exc:
        raise DistributionStateError(f"invalid project.version in {pyproject_path}: {raw_version}") from exc
    return str(canonicalize_name(str(raw_name))), version


def _remote_artifact_details(payload: dict[str, Any]) -> tuple[int, str, str]:
    raw_size = payload.get("size", 0)
    size = int(raw_size) if isinstance(raw_size, (int, str)) and str(raw_size).isdigit() else 0
    digests = payload.get("digests")
    sha256 = ""
    if isinstance(digests, dict):
        raw_sha256 = digests.get("sha256")
        if raw_sha256:
            sha256 = str(raw_sha256)
    raw_url = payload.get("url")
    return size, sha256, str(raw_url) if raw_url else ""


def analyze_expected_project_distributions(
    *,
    package: str,
    project: Path,
    artifact_policy: str,
    fetch_distributions: Callable[[str], dict[Version, dict[str, dict[str, Any]]]] | None = None,
) -> list[DistributionState]:
    project_name, version = read_project_metadata(project)
    package_name = str(canonicalize_name(package))
    if project_name != package_name:
        raise DistributionStateError(
            f"{project} declares package {project_name}, expected {package_name}"
        )

    expected_filenames = expected_distribution_filenames(
        package_name,
        version,
        artifact_policy=artifact_policy,
    )
    distributions = (
        fetch_distributions(package_name)
        if fetch_distributions is not None
        else fetch_pypi_distribution_payloads(package_name)
    )
    releases = set(distributions)
    latest = max(releases) if releases else None
    if latest is not None and version < latest:
        raise DistributionStateError(
            f"{package_name} is version {version}, but PyPI latest is {latest}"
        )

    version_payloads = distributions.get(version, {})
    states: list[DistributionState] = []
    for filename in expected_filenames:
        payload = version_payloads.get(filename)
        size = 0
        sha256 = ""
        url = ""
        if payload is not None:
            size, sha256, url = _remote_artifact_details(payload)
        states.append(
            DistributionState(
                path=Path(filename),
                name=package_name,
                version=version,
                filename=filename,
                exists=payload is not None,
                latest=latest,
                kind=_artifact_kind(filename),
                size=size,
                sha256=sha256,
                url=url,
                source="pypi",
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
        handle.write(f"release-action={'reuse' if all_exist == 'true' else 'build'}\n")


def write_reused_artifact_manifests(
    states: Iterable[DistributionState],
    *,
    output_dir: Path,
    output_prefix: str,
) -> tuple[Path, Path]:
    artifacts = list(states)
    if not artifacts:
        raise DistributionStateError("no expected distributions were evaluated")
    if not all_distributions_exist(artifacts):
        raise DistributionStateError("cannot write reused artifact manifests while distributions are missing")
    missing_hashes = [artifact.filename for artifact in artifacts if not artifact.sha256]
    if missing_hashes:
        raise DistributionStateError(
            "PyPI metadata is missing SHA256 hashes for " + ", ".join(missing_hashes)
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{output_prefix}-artifact-hashes.json"
    sums_path = output_dir / f"{output_prefix}-SHA256SUMS.txt"
    payload = {
        "schema": "agilab.release_artifact_manifest.v1",
        "source": "pypi",
        "reused": True,
        "artifacts": [
            {
                "filename": artifact.filename,
                "name": artifact.name,
                "version": str(artifact.version),
                "kind": artifact.kind,
                "size": artifact.size,
                "sha256": artifact.sha256,
            }
            for artifact in artifacts
        ],
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sums_path.write_text(
        "".join(f"{artifact.sha256}  {artifact.filename}\n" for artifact in artifacts),
        encoding="utf-8",
    )
    return json_path, sums_path


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_reused_artifacts(
    states: Iterable[DistributionState],
    *,
    download_dir: Path,
) -> list[Path]:
    artifacts = list(states)
    if not artifacts:
        raise DistributionStateError("no expected distributions were evaluated")
    if not all_distributions_exist(artifacts):
        raise DistributionStateError("cannot download reused artifacts while distributions are missing")
    download_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []
    for artifact in artifacts:
        if not artifact.url:
            raise DistributionStateError(f"PyPI metadata is missing a download URL for {artifact.filename}")
        target = download_dir / artifact.filename
        try:
            with urllib.request.urlopen(artifact.url, timeout=60) as response:
                target.write_bytes(response.read())
        except OSError as exc:
            raise DistributionStateError(f"could not download {artifact.filename}: {exc}") from exc
        if artifact.sha256 and _hash_file(target) != artifact.sha256:
            raise DistributionStateError(f"downloaded {artifact.filename} does not match PyPI SHA256")
        downloaded.append(target)
    return downloaded


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path)
    parser.add_argument("--package")
    parser.add_argument("--project", type=Path)
    parser.add_argument(
        "--artifact-policy",
        choices=["wheel-only", "wheel+sdist"],
        default="wheel+sdist",
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--output-prefix", default=None)
    parser.add_argument("--download-dir", type=Path, default=None)
    parser.add_argument("--github-output", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.dist_dir is not None:
            states = analyze_distribution_dir(args.dist_dir)
        elif args.package and args.project is not None:
            states = analyze_expected_project_distributions(
                package=args.package,
                project=args.project,
                artifact_policy=args.artifact_policy,
            )
            if all_distributions_exist(states):
                prefix = args.output_prefix or _filename_distribution_name(args.package)
                if args.output_dir is not None:
                    json_path, sums_path = write_reused_artifact_manifests(
                        states,
                        output_dir=args.output_dir,
                        output_prefix=prefix,
                    )
                    print(f"Wrote reused artifact manifest {json_path}")
                    print(f"Wrote reused artifact sums {sums_path}")
                if args.download_dir is not None:
                    for path in download_reused_artifacts(states, download_dir=args.download_dir):
                        print(f"Downloaded reused artifact {path}")
        else:
            parser.error("provide either --dist-dir or --package with --project")
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
