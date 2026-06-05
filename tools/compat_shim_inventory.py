"""Inventory AGILAB compatibility shims and prevent silent growth."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAX_COUNT = 252
SHIM_MARKERS = (
    "Compatibility shim",
    "Compatibility import",
)


def _tracked_python_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=repo_root,
        check=True,
        text=True,
        capture_output=True,
    )
    return [repo_root / line for line in result.stdout.splitlines() if line.strip()]


def is_compat_shim(path: Path) -> bool:
    try:
        prefix = path.read_text(encoding="utf-8").splitlines()[:12]
    except UnicodeDecodeError:
        return False
    return any(marker in "\n".join(prefix) for marker in SHIM_MARKERS)


def _area_for(path: Path, repo_root: Path) -> str:
    rel = path.relative_to(repo_root)
    parts = rel.parts
    if len(parts) >= 5 and parts[:3] == ("src", "agilab", "core"):
        return "/".join(parts[:4])
    if len(parts) >= 5 and parts[:3] == ("src", "agilab", "lib"):
        return "/".join(parts[:4])
    if len(parts) >= 5 and parts[:3] == ("src", "agilab", "apps"):
        return "/".join(parts[:5])
    if len(parts) >= 3 and parts[:2] == ("src", "agilab"):
        return "src/agilab"
    return parts[0] if parts else "."


def build_inventory(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    shims = [
        path.relative_to(repo_root).as_posix()
        for path in _tracked_python_files(repo_root)
        if is_compat_shim(path)
    ]
    by_area = Counter(_area_for(repo_root / rel, repo_root) for rel in shims)
    return {
        "schema_version": "agilab.compat_shim_inventory.v1",
        "total": len(shims),
        "max_allowed": DEFAULT_MAX_COUNT,
        "by_area": dict(sorted(by_area.items())),
        "files": sorted(shims),
    }


def render_text(inventory: dict[str, Any]) -> str:
    lines = [
        "AGILAB compatibility shim inventory",
        f"total: {inventory['total']}",
        f"max allowed: {inventory['max_allowed']}",
        "by area:",
    ]
    for area, count in inventory["by_area"].items():
        lines.append(f"  - {area}: {count}")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root to scan.",
    )
    parser.add_argument(
        "--max-count",
        type=int,
        default=DEFAULT_MAX_COUNT,
        help="Fail if tracked compatibility shims exceed this count.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    inventory = build_inventory(repo_root)
    inventory["max_allowed"] = args.max_count
    if args.json:
        print(json.dumps(inventory, indent=2, sort_keys=True))
    else:
        print(render_text(inventory))
    if inventory["total"] > args.max_count:
        print(
            f"compatibility shim count {inventory['total']} exceeds cap {args.max_count}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
