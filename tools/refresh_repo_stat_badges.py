# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Refresh the hand-maintained GitHub stat badges.

``badges/github-stars.svg`` and ``badges/commit-activity.svg`` have no
generator: they only move when a human notices, so they drift silently. Stars
sat at 16 against 18 live, and commit activity at 214/month against 248.

This renders them from the live GitHub API. Drift is deliberately **not** a
blocking condition anywhere: a star arriving would otherwise turn CI red, so
``--check`` reports drift and still exits 0 unless ``--strict`` is passed, and
the maintenance dashboard surfaces it as a warning.

Usage::

    python tools/refresh_repo_stat_badges.py --check
    python tools/refresh_repo_stat_badges.py --apply
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
BADGES_DIR = REPO_ROOT / "badges"
REPO_SLUG = "ThalesGroup/agilab"

# Both checked-in badges follow shields' geometry exactly: each side is
# 7px per character plus 10px of padding, and the value text is centred in the
# right-hand rectangle. Verified against the committed SVGs before use, so a
# value that changes digit count still renders correct geometry.
CHAR_W = 7
SIDE_PAD = 10


def side_width(text: str) -> int:
    return CHAR_W * len(text) + SIDE_PAD


@dataclass(frozen=True)
class StatBadge:
    slug: str
    label: str
    #: Renders the API value into the badge's display string.
    fmt: str = "{value}"

    @property
    def path(self) -> Path:
        return BADGES_DIR / f"{self.slug}.svg"

    def display(self, value: int | str) -> str:
        return self.fmt.format(value=value)


STARS = StatBadge("github-stars", "stars")
COMMIT_ACTIVITY = StatBadge("commit-activity", "commit activity", "{value}/month")
BADGES = (STARS, COMMIT_ACTIVITY)


def render_badge(badge: StatBadge, value: int | str) -> str:
    """Render the badge SVG, matching the committed format byte for byte."""

    display = badge.display(value)
    left = side_width(badge.label)
    right = side_width(display)
    total = left + right
    label_x = left / 2
    value_x = left + right / 2

    def coord(number: float) -> str:
        return f"{number:.1f}"

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="20" role="img" aria-label="{badge.label}: {display}">
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
  <rect x="{left}" width="{right}" height="20" fill="#007ec6"/>
  <rect width="{total}" height="20" fill="url(#b)"/>
</g>
<g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
  <text x="{coord(label_x)}" y="15" fill="#010101" fill-opacity=".3">{badge.label}</text>
  <text x="{coord(label_x)}" y="14">{badge.label}</text>
  <text x="{coord(value_x)}" y="15" fill="#010101" fill-opacity=".3">{display}</text>
  <text x="{coord(value_x)}" y="14">{display}</text>
</g>
</svg>
"""


def committed_value(badge: StatBadge) -> str | None:
    """Read the value currently rendered in the checked-in badge."""

    if not badge.path.is_file():
        return None
    match = re.search(
        rf'aria-label="{re.escape(badge.label)}: ([^"]*)"',
        badge.path.read_text(encoding="utf-8"),
    )
    return match.group(1) if match else None


def _gh_api(path: str) -> object | None:
    try:
        completed = subprocess.run(
            ["gh", "api", path],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None


def live_values() -> dict[str, int] | None:
    """Fetch live stats, or None when GitHub is unreachable.

    Offline is a normal state for this tool: it degrades to "unknown" rather
    than guessing or failing, because a wrong badge is worse than a stale one.
    """

    repo = _gh_api(f"repos/{REPO_SLUG}")
    if not isinstance(repo, dict) or "stargazers_count" not in repo:
        return None
    values = {STARS.slug: int(repo["stargazers_count"])}

    participation = _gh_api(f"repos/{REPO_SLUG}/stats/participation")
    if isinstance(participation, dict) and isinstance(participation.get("all"), list):
        weekly = [int(week) for week in participation["all"][-4:]]
        values[COMMIT_ACTIVITY.slug] = sum(weekly)
    return values


def drift_report(values: dict[str, int] | None = None) -> dict[str, object]:
    """Compare committed badges against live stats."""

    if values is None:
        values = live_values()
    if values is None:
        return {"available": False, "drifted": [], "checked": []}

    drifted: list[dict[str, object]] = []
    checked: list[str] = []
    for badge in BADGES:
        if badge.slug not in values:
            continue
        checked.append(badge.slug)
        want = badge.display(values[badge.slug])
        have = committed_value(badge)
        if have != want:
            drifted.append({"badge": badge.slug, "committed": have, "live": want})
    return {"available": True, "drifted": drifted, "checked": checked}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Report drift (exit 0 unless --strict).")
    mode.add_argument("--apply", action="store_true", help="Rewrite the badges from live stats.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="With --check, exit 1 on drift. Off by default: a new star must not fail CI.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the report as JSON.")
    args = parser.parse_args(argv)

    values = live_values()
    report = drift_report(values)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif not report["available"]:
        print("GitHub stats unavailable (offline or gh not authenticated); badges left untouched")
    elif not report["drifted"]:
        print(f"stat badges up to date: {', '.join(report['checked'])}")
    else:
        for entry in report["drifted"]:
            print(f"{entry['badge']}: committed {entry['committed']!r}, live {entry['live']!r}")

    if args.apply:
        if not report["available"]:
            print("refusing to rewrite badges without live stats", file=sys.stderr)
            return 1
        for badge in BADGES:
            if badge.slug in values:
                badge.path.write_text(render_badge(badge, values[badge.slug]), encoding="utf-8")
                print(f"wrote {badge.path}")
        return 0

    if args.strict and report["available"] and report["drifted"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
