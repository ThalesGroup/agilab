#!/usr/bin/env python3
"""Check that SVG arrow-marker sizing and local references are explicit."""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


MARKER_UNITS = {"strokeWidth", "userSpaceOnUse"}
LOCAL_URL_REFERENCE = re.compile(r"url\(\s*['\"]?#([A-Za-z_][\w:.-]*)['\"]?\s*\)")
CSS_MARKER_REFERENCE = re.compile(
    r"marker-(?:start|mid|end)\s*:\s*url\(\s*['\"]?#([A-Za-z_][\w:.-]*)['\"]?\s*\)",
    re.IGNORECASE,
)
MARKER_ATTRIBUTES = {"marker-start", "marker-mid", "marker-end"}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def check_svg(path: Path) -> tuple[list[str], int]:
    """Return marker-contract errors and the number of marker definitions."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as error:
        return [f"cannot parse SVG: {error}"], 0

    markers: dict[str, ET.Element] = {}
    errors: list[str] = []
    for marker in (
        element for element in root.iter() if _local_name(element.tag) == "marker"
    ):
        marker_id = marker.attrib.get("id", "").strip()
        label = f"marker #{marker_id}" if marker_id else "marker without id"
        if not marker_id:
            errors.append(f"{label}: add a stable id")
        elif marker_id in markers:
            errors.append(f"{label}: duplicate id")
        else:
            markers[marker_id] = marker

        marker_units = marker.attrib.get("markerUnits")
        if marker_units is None:
            errors.append(
                f"{label}: markerUnits is implicit; declare userSpaceOnUse or strokeWidth"
            )
        elif marker_units not in MARKER_UNITS:
            errors.append(
                f"{label}: unsupported markerUnits={marker_units!r}; expected userSpaceOnUse or strokeWidth"
            )

    references: set[str] = set()
    for element in root.iter():
        for name, value in element.attrib.items():
            local_name = _local_name(name)
            if local_name in MARKER_ATTRIBUTES:
                references.update(LOCAL_URL_REFERENCE.findall(value))
            elif local_name == "style":
                references.update(CSS_MARKER_REFERENCE.findall(value))
        if element.text and _local_name(element.tag) == "style":
            references.update(CSS_MARKER_REFERENCE.findall(element.text))

    for marker_id in sorted(references - markers.keys()):
        errors.append(
            f"marker reference #{marker_id}: no matching <marker id=...> definition"
        )

    return errors, sum(
        1 for element in root.iter() if _local_name(element.tag) == "marker"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate explicit SVG marker sizing and local marker references."
    )
    parser.add_argument("svg", nargs="+", type=Path, help="SVG file(s) to check")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    failed = False
    for path in args.svg:
        errors, marker_count = check_svg(path)
        if errors:
            failed = True
            for error in errors:
                print(f"{path}: {error}", file=sys.stderr)
        else:
            print(f"OK {path}: {marker_count} marker(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
