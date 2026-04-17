#!/usr/bin/env python3
"""Generate static badges for public repo Claude and Codex skill counts."""

from __future__ import annotations

import argparse
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

PROVIDERS = {
    "codex": {
        "label": "Codex skills",
        "skills_dir": REPO_ROOT / ".codex" / "skills",
        "badge": REPO_ROOT / "badges" / "skills-codex.svg",
        "color": "#4F46E5",
    },
    "claude": {
        "label": "Claude skills",
        "skills_dir": REPO_ROOT / ".claude" / "skills",
        "badge": REPO_ROOT / "badges" / "skills-claude.svg",
        "color": "#4F46E5",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--providers",
        nargs="+",
        choices=sorted(PROVIDERS),
        help="Only refresh the selected skill badge provider(s).",
    )
    parser.add_argument(
        "--include-repo",
        action="append",
        default=[],
        help=(
            "Additional local repo root(s) whose matching skill trees should contribute "
            "to the count. Skill names are unioned across repos so shared skills are not "
            "double-counted. Intended for local-only composite badge refreshes."
        ),
    )
    return parser.parse_args()


def text_width(text: str) -> int:
    return 10 + len(text) * 7


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


def visible_skill_names(skills_dir: Path) -> set[str]:
    if not skills_dir.exists():
        return set()
    return {
        path.name
        for path in skills_dir.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    }


def format_skill_count(count: int) -> str:
    suffix = "skill" if count == 1 else "skills"
    return f"{count} {suffix}"


def selected_provider_items(requested: list[str] | None) -> list[tuple[str, dict[str, object]]]:
    if not requested:
        return list(PROVIDERS.items())
    return [(name, PROVIDERS[name]) for name in requested]


def provider_skill_names(config: dict[str, object], include_repos: list[str]) -> set[str]:
    names = set(visible_skill_names(config["skills_dir"]))
    repo_relative_skills_dir = config["skills_dir"].relative_to(REPO_ROOT)
    for repo_root in include_repos:
        names.update(visible_skill_names(Path(repo_root) / repo_relative_skills_dir))
    return names


def main() -> int:
    args = parse_args()
    for name, config in selected_provider_items(args.providers):
        count = len(provider_skill_names(config, args.include_repo))
        value = format_skill_count(count)
        svg = render_badge(config["label"], value, config["color"])
        badge_path = config["badge"]
        badge_path.parent.mkdir(parents=True, exist_ok=True)
        badge_path.write_text(svg, encoding="utf-8")
        print(f"{name}: {value} -> {badge_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
