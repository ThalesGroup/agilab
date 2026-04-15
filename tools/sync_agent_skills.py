#!/usr/bin/env python3
"""Sync selected shared repo skills from `.claude/skills` into `.codex/skills`."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLAUDE_ROOT = ROOT / ".claude" / "skills"
CODEX_ROOT = ROOT / ".codex" / "skills"
SKIP_NAMES = {"README.md", ".DS_Store"}


def iter_skill_dirs(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    )


def sync_skill(source: Path, destination_root: Path) -> Path:
    destination = destination_root / source.name
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(*SKIP_NAMES),
    )
    return destination


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--all",
        action="store_true",
        help="Sync every repo Claude skill into `.codex/skills`.",
    )
    selection.add_argument(
        "--skills",
        nargs="+",
        help="Subset of skill folder names to sync.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    if not CLAUDE_ROOT.exists():
        raise SystemExit(f"Missing source skills root: {CLAUDE_ROOT}")
    CODEX_ROOT.mkdir(parents=True, exist_ok=True)

    skill_dirs = iter_skill_dirs(CLAUDE_ROOT)
    if args.skills:
        selected = set(args.skills)
        skill_dirs = [path for path in skill_dirs if path.name in selected]
        missing = sorted(selected - {path.name for path in skill_dirs})
        if missing:
            raise SystemExit(f"Unknown skill(s): {', '.join(missing)}")

    synced: list[Path] = []
    for source in skill_dirs:
        synced.append(sync_skill(source, CODEX_ROOT))

    print(f"Synced {len(synced)} skill(s) from {CLAUDE_ROOT} to {CODEX_ROOT}")
    for path in synced:
        print(f"- {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
