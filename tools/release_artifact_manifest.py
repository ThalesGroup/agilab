#!/usr/bin/env python3
"""Write release distribution hash manifests and enforce artifact policy."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from packaging.utils import (
    InvalidSdistFilename,
    InvalidWheelFilename,
    canonicalize_name,
    parse_sdist_filename,
    parse_wheel_filename,
)
from packaging.version import Version


class ReleaseArtifactManifestError(RuntimeError):
    """Raised when release artifacts do not satisfy the package policy."""


@dataclass(frozen=True)
class ReleaseArtifact:
    filename: str
    name: str
    version: str
    kind: str
    size: int
    sha256: str


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_artifact(path: Path) -> tuple[str, Version, str]:
    try:
        if path.name.endswith(".whl"):
            name, version, _build, _tags = parse_wheel_filename(path.name)
            return str(canonicalize_name(name)), version, "wheel"
        if path.name.endswith((".tar.gz", ".zip")):
            name, version = parse_sdist_filename(path.name)
            return str(canonicalize_name(name)), version, "sdist"
    except (InvalidWheelFilename, InvalidSdistFilename) as exc:
        raise ReleaseArtifactManifestError(f"invalid distribution filename: {path.name}") from exc
    raise ReleaseArtifactManifestError(f"unsupported release artifact: {path.name}")


def _dist_files(dist_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in dist_dir.iterdir()
        if path.is_file() and path.name.endswith((".whl", ".tar.gz", ".zip"))
    )


def build_manifest(
    dist_dir: Path,
    *,
    package: str | None = None,
    artifact_policy: str = "wheel+sdist",
) -> list[ReleaseArtifact]:
    files = _dist_files(dist_dir)
    if not files:
        raise ReleaseArtifactManifestError(f"no distribution files found in {dist_dir}")

    expected_name = str(canonicalize_name(package)) if package else None
    artifacts: list[ReleaseArtifact] = []
    for path in files:
        name, version, kind = _parse_artifact(path)
        if expected_name is not None and name != expected_name:
            raise ReleaseArtifactManifestError(
                f"{path.name} belongs to {name}, expected {expected_name}"
            )
        artifacts.append(
            ReleaseArtifact(
                filename=path.name,
                name=name,
                version=str(version),
                kind=kind,
                size=path.stat().st_size,
                sha256=_hash_file(path),
            )
        )

    required_kinds = {
        "wheel-only": {"wheel"},
        "wheel+sdist": {"wheel", "sdist"},
    }.get(artifact_policy)
    if required_kinds is None:
        raise ReleaseArtifactManifestError(f"unknown artifact policy: {artifact_policy}")

    kinds_by_release: dict[tuple[str, str], set[str]] = {}
    for artifact in artifacts:
        kinds_by_release.setdefault((artifact.name, artifact.version), set()).add(artifact.kind)

    missing: list[str] = []
    for (name, version), kinds in sorted(kinds_by_release.items()):
        missing_kinds = sorted(required_kinds - kinds)
        if missing_kinds:
            missing.append(f"{name} {version}: missing {', '.join(missing_kinds)}")
    if missing:
        raise ReleaseArtifactManifestError("; ".join(missing))

    return artifacts


def write_manifests(
    artifacts: Iterable[ReleaseArtifact],
    *,
    output_dir: Path,
    output_prefix: str,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = list(artifacts)
    json_path = output_dir / f"{output_prefix}-artifact-hashes.json"
    sums_path = output_dir / f"{output_prefix}-SHA256SUMS.txt"
    payload = {
        "schema": "agilab.release_artifact_manifest.v1",
        "artifacts": [asdict(artifact) for artifact in artifacts],
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sums_path.write_text(
        "".join(f"{artifact.sha256}  {artifact.filename}\n" for artifact in artifacts),
        encoding="utf-8",
    )
    return json_path, sums_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument(
        "--artifact-policy",
        choices=["wheel-only", "wheel+sdist"],
        default="wheel+sdist",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output-prefix", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    artifacts = build_manifest(
        args.dist_dir,
        package=args.package,
        artifact_policy=args.artifact_policy,
    )
    prefix = args.output_prefix or str(canonicalize_name(args.package)).replace("-", "_")
    json_path, sums_path = write_manifests(
        artifacts,
        output_dir=args.output_dir,
        output_prefix=prefix,
    )
    print(f"Wrote {json_path}")
    print(f"Wrote {sums_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
