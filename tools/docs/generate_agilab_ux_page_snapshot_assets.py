#!/usr/bin/env python3
"""Refresh canonical AGILAB PNG/SVG overviews from verified browser captures."""
from __future__ import annotations

import argparse
import base64
from html import escape
import json
from pathlib import Path
import shutil
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
from agilab.ui.screenshot_manifest import build_screenshot_record, sha256_file, utc_now

PAGES = {
    "HOME": ("core-pages-overview", "Native React HOME with project selection, workspace navigation and contextual Tools closed."),
    "PROJECT": ("project-page", "Native React PROJECT with project actions and compact readiness cards."),
    "ORCHESTRATE": ("orchestrate-page", "Native React ORCHESTRATE with execution controls and visible blocking reason before collapsed configuration."),
    "WORKFLOW": ("workflow-page", "Native React WORKFLOW with run controls before graph inspection and collapsed status, graph and new-stage details."),
    "ANALYSIS": ("analysis-page", "Native React ANALYSIS with wrapped evidence filenames and contextual Tools closed."),
}


def refresh(matrix_path: Path, output: Path) -> None:
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    selected = {}
    for route in PAGES:
        matches = [
            item for item in matrix["cases"]
            if item["route"] == route and item["viewport"] == "desktop"
        ]
        if len(matches) != 1:
            raise ValueError(f"Expected one desktop capture for {route}")
        item = matches[0]
        if item["status"] != "captured" or item["geometry"]["horizontalPageOverflow"] or item["geometry"]["errors"]:
            raise ValueError(f"Unverified browser capture for {route}")
        source = (REPO_ROOT / item["fullPageScreenshot"]).resolve()
        if not source.is_relative_to(REPO_ROOT) or source.suffix != ".png" or not source.is_file():
            raise ValueError(f"Invalid screenshot source for {route}")
        selected[route] = (item, source)
    manifest_path = output / "screenshot_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = {row["image_path"]: row for row in manifest["screenshots"]}
    captured_at = utc_now()
    command = ["python", "tools/docs/generate_agilab_ux_page_snapshot_assets.py", "--matrix", matrix_path.as_posix()]
    scope = (
        "Actual native Python/React source pages with copied builtin flight/weather apps "
        "and process-local isolated settings; synthetic local data; no installation, worker "
        "or model jobs; HTTP server selects its own headless plotting backend."
    )
    for route, (item, source) in selected.items():
        stem, alt = PAGES[route]
        target = output / (stem + ".png")
        shutil.copyfile(source, target)
        record = build_screenshot_record(
            target, root=output, page=stem, project="flight_telemetry_project",
            source_command=command, created_at=captured_at, alt=alt, url=item["url"],
        ).as_dict()
        width, height = record["width_px"], record["height_px"]
        svg_path = target.with_suffix(".svg")
        encoded = base64.b64encode(target.read_bytes()).decode("ascii")
        description = escape(alt + " " + scope + " Captured " + captured_at + ".")
        svg_path.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">'
            f'<title id="title">{escape(alt)}</title><desc id="desc">{description}</desc>'
            f'<image width="{width}" height="{height}" href="data:image/png;base64,{encoded}"/>'
            '</svg>\n', encoding="utf-8",
        )
        record.update(
            capture_kind="real-browser-png", capture_scope=scope,
            browser_source_sha256=sha256_file(source),
            svg_summary_kind="screenshot-embedded-raster",
            svg_summary_path=svg_path.name, svg_summary_sha256=sha256_file(svg_path),
            svg_summary_size_bytes=svg_path.stat().st_size,
            source_base_commit=matrix["baseCommit"],
        )
        records[target.name] = record
    manifest["created_at"] = captured_at
    manifest["screenshots"] = [records[name] for name in sorted(records)]
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, required=True)
    args = parser.parse_args()
    refresh(args.matrix, REPO_ROOT / "docs/source/_static/page-shots")


if __name__ == "__main__":
    main()
