"""
Helper utilities to work with PyCharm Local History outside the IDE.

Use cases:
- Back up the Local History store before experimenting.
- Search for occurrences of a filename inside Local History to locate snapshots.

Limitations:
- JetBrains Local History is a proprietary binary format; this script does not
  reconstruct full file contents. It is intended to help locate and preserve
  history data so you can recover it with the PyCharm UI or manual inspection.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


DEFAULT_ROOTS = [
    Path.home() / "Library/Caches/JetBrains",  # macOS
    Path.home() / ".cache/JetBrains",          # Linux
    Path.home() / "AppData/Local/JetBrains",   # Windows
]


@dataclass
class HistoryLocation:
    """Represents a Local History directory."""

    product: str
    path: Path


def find_local_history_roots(search_paths: Iterable[Path]) -> List[HistoryLocation]:
    """Return candidate Local History directories under common JetBrains cache roots."""
    locations: List[HistoryLocation] = []
    for base in search_paths:
        if not base.exists():
            continue
        for child in base.iterdir():
            if not child.is_dir():
                continue
            history = child / "LocalHistory"
            if (history / "changes.storageData").exists():
                locations.append(HistoryLocation(product=child.name, path=history))
    return locations


def backup_local_history(src: Path, dest: Path) -> Path:
    """Copy the Local History directory to a destination folder."""
    dest = dest.expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / src.parent.name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(src, target)
    return target


def _read_ascii_windows(data: bytes, window: int, needle: bytes) -> Iterable[Tuple[int, bytes]]:
    """Yield (offset, slice) around occurrences of the needle."""
    start = 0
    while True:
        idx = data.find(needle, start)
        if idx == -1:
            break
        start = idx + len(needle)
        lo = max(0, idx - window)
        hi = min(len(data), idx + len(needle) + window)
        yield idx, data[lo:hi]


def search_storage_for(data_file: Path, token: str, context: int = 256) -> List[Tuple[int, str]]:
    """Return snippets around a token inside changes.storageData."""
    raw = data_file.read_bytes()
    needle = token.encode("utf-8")
    hits: List[Tuple[int, str]] = []
    for offset, chunk in _read_ascii_windows(raw, context, needle):
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        hits.append((offset, text))
    return hits


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PyCharm Local History helper")
    parser.add_argument(
        "--backup",
        type=Path,
        help="Directory to copy the LocalHistory folder into (creates product-named subfolder).",
    )
    parser.add_argument(
        "--grep",
        type=str,
        help="Filename or path fragment to look for inside changes.storageData.",
    )
    parser.add_argument(
        "--context",
        type=int,
        default=256,
        help="Number of bytes of surrounding context to show for --grep (default: 256).",
    )
    parser.add_argument(
        "--root",
        type=Path,
        action="append",
        help="Override search roots (can be passed multiple times). Defaults include JetBrains cache directories.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    search_roots = args.root or DEFAULT_ROOTS
    locations = find_local_history_roots(search_roots)
    if not locations:
        print("No Local History stores found under:", ", ".join(str(p) for p in search_roots))
        return 1

    # Choose the newest product by default (sorted by name for determinism)
    locations.sort(key=lambda loc: loc.product, reverse=True)
    active = locations[0]
    print(f"Using Local History from: {active.product} @ {active.path}")

    if args.backup:
        target = backup_local_history(active.path, args.backup)
        print(f"Backed up Local History to: {target}")

    if args.grep:
        storage = active.path / "changes.storageData"
        hits = search_storage_for(storage, args.grep, context=args.context)
        if not hits:
            print(f"No matches for '{args.grep}' in {storage}")
        else:
            for idx, text in hits:
                print(f"\n@{idx}: {text}")

    if not args.backup and not args.grep:
        print("Nothing to do. Pass --backup or --grep.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
