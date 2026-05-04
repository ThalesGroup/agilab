#!/usr/bin/env python3
"""Generate a versioned manifest for AGILAB screenshot artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agilab.screenshot_manifest import (  # noqa: E402
    build_page_shots_manifest,
    screenshot_manifest_path,
    write_screenshot_manifest,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate an AGILAB screenshot_manifest.json artifact.")
    parser.add_argument(
        "--root",
        default="docs/source/_static/page-shots",
        help="Directory containing screenshot images. Defaults to docs/source/_static/page-shots.",
    )
    parser.add_argument(
        "--output",
        help="Manifest output path. Defaults to <root>/screenshot_manifest.json.",
    )
    parser.add_argument(
        "--manifest-root",
        help="Portable root value to store in the manifest. Defaults to the screenshot root path.",
    )
    parser.add_argument(
        "--created-at",
        help="Stable ISO-8601 timestamp to stamp into the manifest. Defaults to current UTC time.",
    )
    parser.add_argument(
        "--source-command",
        nargs=argparse.REMAINDER,
        help="Command that produced or refreshed the screenshots. Captures all remaining arguments.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    root = Path(args.root).expanduser()
    output = Path(args.output).expanduser() if args.output else screenshot_manifest_path(root)
    source_command = tuple(args.source_command or ())
    if not source_command:
        source_command = (
            "python",
            "tools/generate_screenshot_manifest.py",
            "--root",
            str(root),
            "--output",
            str(output),
        )

    manifest = build_page_shots_manifest(
        root,
        manifest_root=args.manifest_root,
        source_command=source_command,
        created_at=args.created_at,
    )
    path = write_screenshot_manifest(manifest, output)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
