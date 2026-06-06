#!/usr/bin/env python3
"""Check whether a generated worker environment can be reused by manifest hash."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from performance_cache import manifest_digest


SCHEMA_VERSION = "agilab.worker-env-reuse.v1"
DEFAULT_MARKER_NAME = ".agilab-worker-env-fingerprint.json"


def _marker_path(worker_copy: Path, marker_name: str = DEFAULT_MARKER_NAME) -> Path:
    return worker_copy.expanduser() / marker_name


def _read_marker(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA_VERSION:
        return None
    return payload


def worker_env_reuse_report(
    *,
    worker_pyproject: Path,
    worker_copy: Path,
    manifest_files: Sequence[Path] = (),
    marker_name: str = DEFAULT_MARKER_NAME,
) -> dict[str, object]:
    manifest_paths = [worker_pyproject, *manifest_files]
    fingerprint = manifest_digest(manifest_paths, namespace="worker-env")
    marker = _marker_path(worker_copy, marker_name)
    existing = _read_marker(marker)
    digest = str(fingerprint["digest"])
    if existing is None:
        status = "rebuild"
        reason = "marker-missing"
    elif existing.get("digest") == digest:
        status = "reuse"
        reason = "manifest-unchanged"
    else:
        status = "rebuild"
        reason = "manifest-changed"
    return {
        "schema": SCHEMA_VERSION,
        "status": status,
        "reason": reason,
        "digest": digest,
        "marker": marker.as_posix(),
        "manifest": fingerprint,
    }


def write_marker(report: dict[str, object]) -> Path:
    marker = Path(str(report["marker"])).expanduser()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return marker


def _render_text(report: dict[str, object]) -> str:
    return "\n".join(
        [
            "AGILAB worker env reuse",
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
