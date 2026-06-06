from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
ROADMAP_DOC = REPO_ROOT / "docs" / "source" / "roadmap" / "agilab-future-work.md"
ROADMAP_ISSUE_TEMPLATE = REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "roadmap-vote.yml"


def _current_github_roadmap_candidates(roadmap_text: str) -> list[str]:
    candidates: list[str] = []
    in_section = False
    for line in roadmap_text.splitlines():
        if line == "### Current GitHub roadmap candidates":
            in_section = True
            continue
        if not in_section:
            continue
        if line.startswith("### ") or line.startswith("## "):
            break
        if line.startswith("- "):
            candidates.append(line.removeprefix("- ").strip())
    return candidates


def _roadmap_lane_options(template: dict) -> list[str]:
    lane_field = next(
        item
        for item in template["body"]
        if item.get("type") == "dropdown" and item.get("id") == "investment"
    )
    return list(lane_field["attributes"]["options"])


def test_github_roadmap_intake_uses_one_issue_based_voting_path() -> None:
    roadmap_text = ROADMAP_DOC.read_text(encoding="utf-8")
    issue_template_text = ROADMAP_ISSUE_TEMPLATE.read_text(encoding="utf-8")

    assert "## GitHub roadmap voting" in roadmap_text
    assert "Final consolidated poll" not in roadmap_text
    assert "discussions/new?category=polls" not in roadmap_text
    assert "discussions/categories/polls" not in roadmap_text
    assert "label%3Aroadmap" in roadmap_text
    assert "label%3Aroadmap" in issue_template_text


def test_roadmap_issue_template_tracks_current_github_candidates() -> None:
    roadmap_text = ROADMAP_DOC.read_text(encoding="utf-8")
    template = yaml.safe_load(ROADMAP_ISSUE_TEMPLATE.read_text(encoding="utf-8"))

    candidates = _current_github_roadmap_candidates(roadmap_text)
    options = _roadmap_lane_options(template)

    assert template["name"] == "Roadmap proposal"
    assert template["title"] == "[Roadmap] "
    assert options[:-1] == candidates
    assert options[-1] == "Other / write-in"
