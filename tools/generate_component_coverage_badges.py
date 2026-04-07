#!/usr/bin/env python3
"""Generate static coverage badges from Cobertura XML reports."""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

COMPONENTS = {
    "agi-env": {
        "label": "agi-env",
        "xml": REPO_ROOT / "coverage-agi-env.xml",
        "prefix": "src/agilab/core/agi-env/",
        "badge": REPO_ROOT / "badges" / "coverage-agi-env.svg",
    },
    "agi-node": {
        "label": "agi-node",
        "xml": REPO_ROOT / "coverage-agi-node.xml",
        "prefix": "src/agilab/core/agi-node/",
        "badge": REPO_ROOT / "badges" / "coverage-agi-node.svg",
    },
    "agi-cluster": {
        "label": "agi-cluster",
        "xml": REPO_ROOT / "coverage-agi-cluster.xml",
        "prefix": "src/agilab/core/agi-cluster/",
        "badge": REPO_ROOT / "badges" / "coverage-agi-cluster.svg",
    },
    "agi-gui": {
        "label": "agi-gui",
        "xml": REPO_ROOT / "coverage-agi-gui.xml",
        "prefix": "src/agilab/",
        "badge": REPO_ROOT / "badges" / "coverage-agi-gui.svg",
    },
    "agi-core": {
        "label": "agi-core",
        "aggregate": ("agi-env", "agi-node", "agi-cluster"),
        "badge": REPO_ROOT / "badges" / "coverage-agi-core.svg",
    },
    "agilab": {
        "label": "agilab",
        "aggregate": ("agi-env", "agi-node", "agi-cluster", "agi-gui"),
        "badge": REPO_ROOT / "badges" / "coverage-agilab.svg",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--combined-xml",
        default=str(REPO_ROOT / "coverage-agilab.combined.xml"),
        help="Fallback Cobertura XML used when a component-specific report is missing.",
    )
    return parser.parse_args()


def badge_color(percent: float) -> str:
    if percent >= 80:
        return "#2ea44f"
    if percent >= 65:
        return "#97ca00"
    if percent >= 60:
        return "#a4a61d"
    if percent >= 45:
        return "#dfb317"
    if percent >= 30:
        return "#fe7d37"
    return "#e05d44"


def text_width(text: str) -> int:
    return 10 + len(text) * 7


def format_percent(percent: float) -> str:
    # Truncate instead of rounding so badges stay stable across tiny local/CI
    # coverage deltas near threshold boundaries.
    return f"{int(percent)}%"


def render_badge(label: str, value: str, color: str) -> str:
    left = text_width(label)
    right = text_width(value)
    total = left + right
    left_mid = left / 2
    right_mid = left + right / 2
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="20" role="img" aria-label="{label}: {value}">
<linearGradient id="b" x2="0" y2="100%">
  <stop offset="0" stop-color="#fff" stop-opacity=".7"/>
  <stop offset=".1" stop-opacity=".1"/>
  <stop offset=".9" stop-opacity=".3"/>
  <stop offset="1" stop-opacity=".5"/>
</linearGradient>
<mask id="a">
  <rect width="{total}" height="20" rx="3" fill="#fff"/>
</mask>
<g mask="url(#a)">
  <rect width="{left}" height="20" fill="#555"/>
  <rect x="{left}" width="{right}" height="20" fill="{color}"/>
  <rect width="{total}" height="20" fill="url(#b)"/>
</g>
<g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
  <text x="{left_mid}" y="15" fill="#010101" fill-opacity=".3">{label}</text>
  <text x="{left_mid}" y="14">{label}</text>
  <text x="{right_mid}" y="15" fill="#010101" fill-opacity=".3">{value}</text>
  <text x="{right_mid}" y="14">{value}</text>
</g>
</svg>
"""


def compute_from_component_xml(path: Path) -> float | None:
    if not path.exists():
        return None
    root = ET.parse(path).getroot()
    line_rate = root.attrib.get("line-rate")
    if line_rate is None:
        return None
    return float(line_rate) * 100.0


def coverage_counts_from_xml(path: Path) -> tuple[int, int] | None:
    if not path.exists():
        return None
    root = ET.parse(path).getroot()
    covered = root.attrib.get("lines-covered")
    total = root.attrib.get("lines-valid")
    if covered is None or total is None:
        return None
    return int(covered), int(total)


def compute_from_combined_xml(path: Path, prefix: str) -> float | None:
    if not path.exists():
        return None
    root = ET.parse(path).getroot()
    covered = 0
    total = 0
    for class_el in root.findall(".//class"):
        filename = class_el.attrib.get("filename", "")
        if not filename.startswith(prefix):
            continue
        for line_el in class_el.findall("./lines/line"):
            total += 1
            if int(line_el.attrib.get("hits", "0")) > 0:
                covered += 1
    if total == 0:
        return None
    return covered * 100.0 / total


def compute_aggregate_percent(components: tuple[str, ...]) -> float | None:
    covered = 0
    total = 0
    for component in components:
        counts = coverage_counts_from_xml(COMPONENTS[component]["xml"])
        if counts is None:
            return None
        component_covered, component_total = counts
        covered += component_covered
        total += component_total
    if total == 0:
        return None
    return covered * 100.0 / total


def main() -> int:
    args = parse_args()
    combined_xml = Path(args.combined_xml)
    for name, config in COMPONENTS.items():
        percent = None
        if "aggregate" in config:
            percent = compute_aggregate_percent(config["aggregate"])
        elif "xml" in config:
            percent = compute_from_component_xml(config["xml"])
            if percent is None:
                percent = compute_from_combined_xml(combined_xml, config["prefix"])
        if percent is None:
            raise SystemExit(f"Missing coverage data for {name}")
        value = format_percent(percent)
        svg = render_badge(config["label"], value, badge_color(percent))
        badge_path = config["badge"]
        badge_path.parent.mkdir(parents=True, exist_ok=True)
        badge_path.write_text(svg, encoding="utf-8")
        print(f"{name}: {value} -> {badge_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
