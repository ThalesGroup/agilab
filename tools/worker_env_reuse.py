#!/usr/bin/env python3
"""Report manifest compatibility; this helper never creates or reuses a venv."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
from typing import Sequence

from performance_cache import manifest_digest


SCHEMA_VERSION = "agilab.worker-env-reuse.v1"
DEFAULT_MARKER_NAME = ".agilab-worker-env-fingerprint.json"


def _marker_path(worker_copy: Path, marker_name: str = DEFAULT_MARKER_NAME) -> Path:
    if marker_name in ("", ".", "..") or "/" in marker_name or "\\" in marker_name:
        raise ValueError("marker-name must be a single filename inside worker-copy")
    return worker_copy.expanduser().resolve() / marker_name


def _read_marker(path: Path) -> dict[str, object] | None:
    if path.is_symlink():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA_VERSION:
        return None
    manifest = payload.get("manifest")
    if (
        not isinstance(manifest, dict)
        or not isinstance(manifest.get("files"), list)
        or not manifest["files"]
        or not isinstance(payload.get("digest"), str)
        or manifest.get("digest") != payload["digest"]
    ):
        return None
    return payload


def _fingerprint(paths: Sequence[Path]) -> dict[str, object]:
    # Acceptance uses current bytes, never the performance cache's stat shortcut.
    return manifest_digest(paths, namespace="worker-env", use_cache=False)


def worker_env_reuse_report(
    *,
    worker_pyproject: Path,
    worker_copy: Path,
    manifest_files: Sequence[Path] = (),
    marker_name: str = DEFAULT_MARKER_NAME,
) -> dict[str, object]:
    manifest_paths = sorted(
        {
            path.expanduser().resolve()
            for path in (
                worker_pyproject,
                worker_pyproject.with_name("uv.lock"),
                *manifest_files,
            )
        },
        key=lambda path: path.as_posix(),
    )
    fingerprint = _fingerprint(manifest_paths)
    complete = all(
        path.expanduser().is_file() for path in (worker_pyproject, *manifest_files)
    )
    marker = _marker_path(worker_copy, marker_name)
    existing = _read_marker(marker)
    digest = str(fingerprint["digest"])
    if not complete:
        status, reason = "rebuild", "manifest-missing"
    elif existing is None:
        reason = (
            "marker-invalid"
            if marker.exists() or marker.is_symlink()
            else "marker-missing"
        )
        status = "rebuild"
    elif existing.get("digest") != digest:
        status, reason = "rebuild", "manifest-changed"
    elif existing.get("manifest") != fingerprint:
        status, reason = "rebuild", "marker-invalid"
    else:
        status, reason = "reuse", "manifest-unchanged"
    return {
        "schema": SCHEMA_VERSION,
        "scope": "manifest-only",
        "status": status,
        "reason": reason,
        "digest": digest,
        "marker": marker.as_posix(),
        "marker_destination": {
            "worker_copy": marker.parent.as_posix(),
            "marker_name": marker_name,
        },
        "manifest": fingerprint,
        "manifest_complete": complete,
    }


def _validated_marker_destination(
    report: dict[str, object], paths: Sequence[Path]
) -> Path:
    destination = report.get("marker_destination")
    if (
        not isinstance(destination, dict)
        or not isinstance(destination.get("worker_copy"), str)
        or not isinstance(destination.get("marker_name"), str)
        or not isinstance(report.get("marker"), str)
    ):
        raise ValueError(
            "Marker destination is missing or invalid; regenerate the report"
        )
    worker_copy = Path(destination["worker_copy"])
    marker = _marker_path(worker_copy, destination["marker_name"])
    if worker_copy != worker_copy.resolve() or Path(report["marker"]) != marker:
        raise ValueError(
            "Marker destination differs from the intended worker-copy and marker-name"
        )
    if marker.is_symlink():
        raise ValueError(f"Refusing to replace a symlink marker: {marker}")
    for path in paths:
        if marker.resolve() == path.resolve() or (
            marker.exists() and path.exists() and marker.samefile(path)
        ):
            raise ValueError("Marker destination aliases a fingerprint input")
    return marker


def write_marker(report: dict[str, object]) -> Path:
    """Explicitly record a fresh manifest report, without changing an environment."""
    manifest = report.get("manifest")
    if (
        report.get("schema") != SCHEMA_VERSION
        or report.get("manifest_complete") is not True
        or not isinstance(manifest, dict)
        or not isinstance(manifest.get("files"), list)
        or not manifest["files"]
        or report.get("digest") != manifest.get("digest")
    ):
        raise ValueError("Cannot write an incomplete or invalid manifest report")
    entries = manifest["files"]
    if not all(
        isinstance(entry, dict) and isinstance(entry.get("path"), str)
        for entry in entries
    ):
        raise ValueError("Invalid manifest file entries")
    paths = [Path(entry["path"]) for entry in entries]
    marker = _validated_marker_destination(report, paths)
    if _fingerprint(paths) != manifest:
        raise ValueError(
            "Manifest changed since report; regenerate before writing marker"
        )
    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=marker.parent,
            prefix=f".{marker.name}.",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if _fingerprint(paths) != manifest:
            raise ValueError("Manifest changed during marker write; regenerate report")
        _validated_marker_destination(report, paths)
        temporary.replace(marker)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return marker


def _render_text(report: dict[str, object]) -> str:
    return "\n".join(
        [
            "AGILAB worker env reuse (manifest compatibility only)",
            f"status: {report['status']}",
            f"reason: {report['reason']}",
            f"digest: {report['digest']}",
            f"marker: {report['marker']}",
        ]
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-pyproject", required=True, type=Path)
    parser.add_argument("--worker-copy", required=True, type=Path)
    parser.add_argument("--manifest-file", action="append", default=[], type=Path)
    parser.add_argument("--marker-name", default=DEFAULT_MARKER_NAME)
    parser.add_argument("--write-marker", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = worker_env_reuse_report(
        worker_pyproject=args.worker_pyproject,
        worker_copy=args.worker_copy,
        manifest_files=args.manifest_file,
        marker_name=args.marker_name,
    )
    if args.write_marker:
        write_marker(report)
        report = worker_env_reuse_report(
            worker_pyproject=args.worker_pyproject,
            worker_copy=args.worker_copy,
            manifest_files=args.manifest_file,
            marker_name=args.marker_name,
        )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(_render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
