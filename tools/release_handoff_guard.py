#!/usr/bin/env python3
"""Guard against stale release handoff files presented as current."""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
HANDOFF_DIR = ROOT / "tools" / "release_handoffs"
PROOF_MANIFEST = ROOT / "docs" / "source" / "data" / "release_proof.toml"
TAG_RE = re.compile(r"v\d{4}\.\d{2}\.\d{2}(?:-\d+)?")


def _tag_key(tag: str) -> tuple[int, int, int, int]:
    body = tag.removeprefix("v")
    suffix = 0
    if "-" in body:
        body, raw_suffix = body.rsplit("-", 1)
        suffix = int(raw_suffix) if raw_suffix.isdigit() else 0
    year, month, day = (int(part) for part in body.split("."))
    return year, month, day, suffix


def latest_release_tag(manifest: Path = PROOF_MANIFEST) -> str:
    payload = tomllib.loads(manifest.read_text(encoding="utf-8"))
    release = payload.get("release", {})
    tag = str(release.get("github_release_tag") or "")
    if not TAG_RE.fullmatch(tag):
        raise RuntimeError(f"could not determine latest release tag from {manifest}")
    return tag


def handoff_tag(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")
    match = TAG_RE.search(path.name) or TAG_RE.search(text)
    return match.group(0) if match else None


def is_archived(path: Path) -> bool:
    head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:20]).lower()
    return "status: archived" in head


def stale_handoffs(
    *,
    handoff_dir: Path = HANDOFF_DIR,
    latest_tag: str | None = None,
) -> list[Path]:
    latest = latest_tag or latest_release_tag()
    latest_key = _tag_key(latest)
    stale: list[Path] = []
    for path in sorted(handoff_dir.glob("*.md")):
        tag = handoff_tag(path)
        if tag is None:
            continue
        if _tag_key(tag) < latest_key and not is_archived(path):
            stale.append(path)
    return stale


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff-dir", type=Path, default=HANDOFF_DIR)
    parser.add_argument("--latest-tag")
    parser.add_argument("--compact", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    stale = stale_handoffs(handoff_dir=args.handoff_dir, latest_tag=args.latest_tag)
    if stale:
        if args.compact:
            print("stale release handoffs: " + ", ".join(str(path) for path in stale))
        else:
            print("Stale release handoffs must be marked with `Status: archived`:")
            for path in stale:
                print(f"- {path}")
        return 2
    print("release handoff guard passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
