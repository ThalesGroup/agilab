#!/usr/bin/env python3
"""Generate static badges for public repo agent and skill metadata."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _badge_svg import render_badge  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[1]

SKILL_TREE_DIRS = (
    Path(".claude") / "skills",
    Path(".codex") / "skills",
)

SKILL_BADGE = {
    "label": "Skills",
    "badge": REPO_ROOT / "badges" / "skills.svg",
    "color": "#0F766E",
}

AGENT_BADGES = {
    "standard": {
        "label": "Standard",
        "value": "Agent Skills",
        "badge": REPO_ROOT / "badges" / "agent-standard.svg",
        "color": "#5B6CFF",
    },
    "works-with": {
        "label": "Works with",
        "value": "Codex Claude Aider OpenCode Mistral Vibe",
        "badge": REPO_ROOT / "badges" / "agent-works-with.svg",
        "color": "#0F766E",
    },
    "agent-api": {
        "label": "Agent API",
        "value": "CLI Python",
        "badge": REPO_ROOT / "badges" / "agent-api.svg",
        "color": "#5B6CFF",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
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


def visible_skill_names(skills_dir: Path) -> set[str]:
    if not skills_dir.exists():
        return set()
    return {
        path.name
        for path in skills_dir.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    }


def repo_skill_names(include_repos: list[str]) -> set[str]:
    names: set[str] = set()
    for relative_dir in SKILL_TREE_DIRS:
        names.update(visible_skill_names(REPO_ROOT / relative_dir))
    for repo_root in include_repos:
        for relative_dir in SKILL_TREE_DIRS:
            names.update(visible_skill_names(Path(repo_root) / relative_dir))
    return names


def refresh_skill_badge(include_repos: list[str]) -> None:
    value = str(len(repo_skill_names(include_repos)))
    svg = render_badge(str(SKILL_BADGE["label"]), value, str(SKILL_BADGE["color"]))
    badge_path = SKILL_BADGE["badge"]
    badge_path.parent.mkdir(parents=True, exist_ok=True)
    badge_path.write_text(svg, encoding="utf-8")
    print(f"skills: {value} -> {badge_path.relative_to(REPO_ROOT)}")


def refresh_agent_badges(include_repos: list[str]) -> None:
    for name, config in AGENT_BADGES.items():
        value = str(config["value"])
        svg = render_badge(str(config["label"]), value, str(config["color"]))
        badge_path = config["badge"]
        badge_path.parent.mkdir(parents=True, exist_ok=True)
        badge_path.write_text(svg, encoding="utf-8")
        print(f"{name}: {value} -> {badge_path.relative_to(REPO_ROOT)}")


def main() -> int:
    args = parse_args()
    refresh_skill_badge(args.include_repo)
    refresh_agent_badges(args.include_repo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
