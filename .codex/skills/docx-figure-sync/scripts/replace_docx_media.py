#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path


def list_media(docx_path: Path) -> list[str]:
    with zipfile.ZipFile(docx_path) as archive:
        return sorted(
            name
            for name in archive.namelist()
            if name.startswith("word/media/") and not name.endswith("/")
        )


def resolve_media_target(media_entries: list[str], selector: str) -> str:
    if selector in media_entries:
        return selector
    matches = [name for name in media_entries if Path(name).name == selector]
    if not matches:
        raise FileNotFoundError(f"Media entry not found: {selector}")
    if len(matches) > 1:
        raise ValueError(f"Media selector is ambiguous: {selector} -> {matches}")
    return matches[0]


def replace_media(docx_path: Path, target_media: str, replacement_path: Path, output_path: Path) -> None:
    replacement_bytes = replacement_path.read_bytes()
    with zipfile.ZipFile(docx_path) as source:
        media_entries = list_media(docx_path)
        target_entry = resolve_media_target(media_entries, target_media)
        if Path(target_entry).suffix.lower() != replacement_path.suffix.lower():
            raise ValueError(
                f"Replacement suffix mismatch: {replacement_path.suffix} vs {Path(target_entry).suffix}"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as dest:
            for item in source.infolist():
                data = replacement_bytes if item.filename == target_entry else source.read(item.filename)
                dest.writestr(item, data)


def main() -> None:
    parser = argparse.ArgumentParser(description="List or replace media inside a DOCX package.")
    parser.add_argument("docx", type=Path, help="Input DOCX path")
    parser.add_argument("--list", action="store_true", help="List media entries and exit")
    parser.add_argument("--media", help="Media entry path or basename, e.g. image35.png")
    parser.add_argument("--replacement", type=Path, help="Replacement image path")
    parser.add_argument("--output", "-o", type=Path, help="Output DOCX path")
    parser.add_argument("--in-place", action="store_true", help="Replace media in place")
    args = parser.parse_args()

    if args.list:
        for entry in list_media(args.docx):
            print(entry)
        return

    if not args.media or not args.replacement:
        raise SystemExit("--media and --replacement are required unless --list is used")

    if args.in_place and args.output:
        raise SystemExit("Use either --output or --in-place, not both")

    if args.in_place:
        temp_output = args.docx.with_suffix(".tmp.docx")
        replace_media(args.docx, args.media, args.replacement, temp_output)
        shutil.move(temp_output, args.docx)
        return

    if not args.output:
        raise SystemExit("Provide --output or use --in-place")

    replace_media(args.docx, args.media, args.replacement, args.output)


if __name__ == "__main__":
    main()
