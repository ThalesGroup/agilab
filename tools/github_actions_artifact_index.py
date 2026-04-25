#!/usr/bin/env python3
"""Build a harvest-compatible artifact index from GitHub Actions artifacts."""

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
    DEFAULT_SOURCE_MACHINE,
    SCHEMA,
    build_artifact_index_from_archives,
    build_github_actions_artifact_index,
    token_from_env,
    write_artifact_index,
    write_sample_github_actions_archive,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build an AGILAB CI artifact index from GitHub Actions artifact "
            "archives. Use --archive for already-downloaded ZIP files, or "
            "--live-github to query and download artifacts from a workflow run."
        )
    )
    parser.add_argument(
        "--archive",
        action="append",
        type=Path,
        default=[],
        help="Downloaded GitHub Actions artifact ZIP. Can be passed multiple times.",
    )
    parser.add_argument(
        "--live-github",
        action="store_true",
        help="Query the GitHub Actions API and download workflow-run artifacts.",
    )
    parser.add_argument("--repo", default="", help="GitHub repository as owner/name.")
    parser.add_argument("--run-id", default="", help="GitHub Actions workflow run id.")
    parser.add_argument("--workflow", default="", help="Workflow name for provenance.")
    parser.add_argument("--run-attempt", default="", help="Workflow run attempt.")
    parser.add_argument(
        "--source-machine",
        default=DEFAULT_SOURCE_MACHINE,
        help="Source-machine label stored in harvest provenance.",
    )
    parser.add_argument("--release-id", default=DEFAULT_RELEASE_ID)
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=None,
        help="Directory for live GitHub artifact ZIP downloads.",
    )
    parser.add_argument(
        "--token-env",
        default="GITHUB_TOKEN",
        help="Environment variable that contains the GitHub API token.",
    )
    parser.add_argument(
        "--write-sample-archive",
        type=Path,
        default=None,
        help="Write a deterministic public-evidence sample archive and exit.",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--compact", action="store_true")
    return parser


def _build_index(args: argparse.Namespace) -> dict[str, object]:
    if args.write_sample_archive is not None:
        archive_path = write_sample_github_actions_archive(args.write_sample_archive)
        return {
            "schema": SCHEMA,
            "status": "sample_archive_written",
            "path": str(archive_path),
        }
    if args.live_github:
        if not args.repo or not args.run_id:
            raise SystemExit("--live-github requires --repo and --run-id")
        return build_github_actions_artifact_index(
            repository=args.repo,
            run_id=args.run_id,
            download_dir=args.download_dir,
            token=token_from_env(args.token_env),
            workflow=args.workflow,
            run_attempt=args.run_attempt,
            source_machine=args.source_machine,
            release_id=args.release_id,
        )
    if not args.archive:
        raise SystemExit("pass at least one --archive or use --live-github")
    return build_artifact_index_from_archives(
        args.archive,
        repository=args.repo,
        run_id=args.run_id,
        workflow=args.workflow,
        run_attempt=args.run_attempt,
        source_machine=args.source_machine,
        release_id=args.release_id,
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
