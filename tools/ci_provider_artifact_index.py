#!/usr/bin/env python3
"""Build a harvest-compatible artifact index from downloaded CI artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]


def _ensure_repo_on_path(repo_root: Path) -> None:
    src_root = repo_root / "src"
    for entry in (str(src_root), str(repo_root)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    package = sys.modules.get("agilab")
    package_path = str(src_root / "agilab")
    package_paths = getattr(package, "__path__", None)
    if package_paths is not None and package_path not in list(package_paths):
        try:
            package_paths.append(package_path)
        except AttributeError:
            package.__path__ = [*package_paths, package_path]


_ensure_repo_on_path(REPO_ROOT)

from agilab.ci_artifact_harvest import DEFAULT_RELEASE_ID  # noqa: E402
from agilab.ci_provider_artifacts import (  # noqa: E402
    GENERIC_PROVIDER,
    GITLAB_CI_PROVIDER,
    SCHEMA,
    build_artifact_index_from_archives,
    write_artifact_index,
    write_sample_ci_provider_archive,
    write_sample_ci_provider_directory,
)


PROVIDER_CHOICES = (GITLAB_CI_PROVIDER, GENERIC_PROVIDER)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build an AGILAB CI artifact index from downloaded CI provider "
            "artifact ZIPs without querying the provider API."
        )
    )
    parser.add_argument(
        "--provider",
        choices=PROVIDER_CHOICES,
        default=GITLAB_CI_PROVIDER,
        help="CI provider provenance label for the downloaded archives.",
    )
    parser.add_argument(
        "--archive",
        action="append",
        type=Path,
        default=[],
        help="Downloaded provider artifact ZIP. Can be passed multiple times.",
    )
    parser.add_argument("--repo", default="", help="Provider repository or project id.")
    parser.add_argument("--run-id", default="", help="Provider pipeline/workflow run id.")
    parser.add_argument("--workflow", default="", help="Workflow or pipeline name.")
    parser.add_argument("--run-attempt", default="", help="Workflow or job attempt.")
    parser.add_argument(
        "--source-machine",
        default="ci-provider",
        help="Source-machine label stored in harvest provenance.",
    )
    parser.add_argument("--release-id", default=DEFAULT_RELEASE_ID)
    parser.add_argument(
        "--write-sample-archive",
        type=Path,
        default=None,
        help="Write a deterministic public-evidence sample archive and exit.",
    )
    parser.add_argument(
        "--write-sample-directory",
        type=Path,
        default=None,
        help="Write deterministic public-evidence files in an uploadable directory and exit.",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--compact", action="store_true")
    return parser


def _build_index(args: argparse.Namespace) -> dict[str, object]:
    if args.write_sample_archive is not None:
        archive_path = write_sample_ci_provider_archive(args.write_sample_archive)
        return {
            "schema": SCHEMA,
            "provider": args.provider,
            "status": "sample_archive_written",
            "path": str(archive_path),
        }
    if args.write_sample_directory is not None:
        directory_path = write_sample_ci_provider_directory(args.write_sample_directory)
        return {
            "schema": SCHEMA,
            "provider": args.provider,
            "status": "sample_directory_written",
            "path": str(directory_path),
        }
    if not args.archive:
        raise SystemExit("pass at least one --archive")
    return build_artifact_index_from_archives(
        args.archive,
        repository=args.repo,
        run_id=args.run_id,
        workflow=args.workflow,
        run_attempt=args.run_attempt,
        source_machine=args.source_machine,
        release_id=args.release_id,
        provider=args.provider,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    index = _build_index(args)
    if args.output is not None:
        write_artifact_index(args.output, index)
    if args.compact:
        print(json.dumps(index, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(index, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
