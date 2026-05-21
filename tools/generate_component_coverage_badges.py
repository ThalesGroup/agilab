#!/usr/bin/env python3
"""Generate static coverage badges from Cobertura XML reports."""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

COMPONENTS = {
    "agi-env": {
        "label": "agi-env coverage",
        "xml": REPO_ROOT / "coverage-agi-env.xml",
        "prefix": "src/agilab/core/agi-env/",
        "badge": REPO_ROOT / "badges" / "coverage-agi-env.svg",
    },
    "agi-node": {
        "label": "agi-node coverage",
        "xml": REPO_ROOT / "coverage-agi-node.xml",
        "prefix": "src/agilab/core/agi-node/",
        "badge": REPO_ROOT / "badges" / "coverage-agi-node.svg",
    },
    "agi-cluster": {
        "label": "agi-cluster coverage",
        "xml": REPO_ROOT / "coverage-agi-cluster.xml",
        "prefix": "src/agilab/core/agi-cluster/",
        "badge": REPO_ROOT / "badges" / "coverage-agi-cluster.svg",
    },
    "agi-gui": {
        "label": "agi-gui coverage",
        "xml": REPO_ROOT / "coverage-agi-gui.xml",
        "prefix": "src/agilab/",
        "badge": REPO_ROOT / "badges" / "coverage-agi-gui.svg",
    },
    "agi-core": {
        "label": "agi-core coverage",
        "aggregate": ("agi-env", "agi-node", "agi-cluster"),
        "aggregate_policy": "minimum",
        "badge": REPO_ROOT / "badges" / "coverage-agi-core.svg",
    },
    "agilab": {
        "label": "agilab coverage",
        "aggregate": ("agi-env", "agi-node", "agi-cluster", "agi-gui"),
        "badge": REPO_ROOT / "badges" / "coverage-agilab.svg",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--combined-xml",
        default=str(REPO_ROOT / "coverage-agilab.combined.xml"),
        help="Optional Cobertura XML used only by components that explicitly opt into combined fallback.",
    )
    parser.add_argument(
        "--components",
        nargs="+",
        choices=sorted(COMPONENTS),
        help="Only refresh the selected coverage badge component(s).",
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


def coverage_counts_from_prefixed_xml(path: Path, prefix: str) -> tuple[int, int] | None:
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
    return covered, total


def compute_from_combined_xml(path: Path, prefix: str) -> float | None:
    counts = coverage_counts_from_prefixed_xml(path, prefix)
    if counts is None:
        return None
    covered, total = counts
    return covered * 100.0 / total


def resolve_component_counts(name: str, combined_xml: Path) -> tuple[int, int] | None:
    config = COMPONENTS[name]
    xml_path = config.get("xml")
    if isinstance(xml_path, Path):
        counts = coverage_counts_from_xml(xml_path)
        if counts is not None:
            return counts

    prefix = config.get("prefix")
    if not isinstance(prefix, str):
        return None

    fallback_paths: list[Path] = []
    for candidate in config.get("fallback_xmls", ()):
        if isinstance(candidate, Path):
            fallback_paths.append(candidate)
    if config.get("allow_combined_fallback") and combined_xml not in fallback_paths:
        fallback_paths.append(combined_xml)

    for fallback_path in fallback_paths:
        counts = coverage_counts_from_prefixed_xml(fallback_path, prefix)
        if counts is not None:
            return counts
    return None


def compute_aggregate_percent(
    components: tuple[str, ...],
    combined_xml: Path,
    *,
    policy: str = "weighted",
) -> float | None:
    covered = 0
    total = 0
    component_percents: list[float] = []
    for component in components:
        counts = resolve_component_counts(component, combined_xml)
        if counts is None:
            return None
        component_covered, component_total = counts
        if component_total == 0:
            return None
        component_percents.append(component_covered * 100.0 / component_total)
        covered += component_covered
        total += component_total
    if policy == "minimum":
        return min(component_percents) if component_percents else None
    if total == 0:
        return None
    return covered * 100.0 / total


def selected_component_items(requested: list[str] | None) -> list[tuple[str, dict[str, object]]]:
    if not requested:
        return list(COMPONENTS.items())
    return [(name, COMPONENTS[name]) for name in requested]


def main() -> int:
    args = parse_args()
    combined_xml = Path(args.combined_xml)
    for name, config in selected_component_items(args.components):
        percent = None
        if "aggregate" in config:
            policy = str(config.get("aggregate_policy", "weighted"))
            percent = compute_aggregate_percent(config["aggregate"], combined_xml, policy=policy)
        elif "xml" in config:
            counts = resolve_component_counts(name, combined_xml)
            if counts is not None:
                covered, total = counts
                percent = covered * 100.0 / total
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
