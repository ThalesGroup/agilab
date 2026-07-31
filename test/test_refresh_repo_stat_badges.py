# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Guards for the hand-maintained GitHub stat badges."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "refresh_repo_stat_badges", REPO_ROOT / "tools" / "refresh_repo_stat_badges.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load()


@pytest.mark.parametrize("badge", MODULE.BADGES, ids=lambda b: b.slug)
def test_renderer_reproduces_the_committed_badge(badge) -> None:
    """The renderer must be a faithful generator, not a reformatter.

    If this drifts, `--apply` would rewrite geometry or styling as a side
    effect of refreshing a number.
    """

    committed = badge.path.read_text(encoding="utf-8")
    value = MODULE.committed_value(badge)
    assert value is not None, f"{badge.slug} has no aria-label value"
    raw = value.removesuffix("/month")
    assert MODULE.render_badge(badge, raw) == committed


@pytest.mark.parametrize(
    ("text", "expected"),
    [("stars", 45), ("commit activity", 115), ("18", 24), ("248/month", 73)],
)
def test_width_model_matches_the_committed_geometry(text: str, expected: int) -> None:
    assert MODULE.side_width(text) == expected


@pytest.mark.parametrize("value", [7, 18, 100, 1234])
def test_geometry_stays_consistent_across_digit_counts(value: int) -> None:
    """A value that changes digit count must still render correct geometry."""

    svg = MODULE.render_badge(MODULE.STARS, value)
    total = int(re.search(r'<svg[^>]*width="(\d+)"', svg).group(1))
    left = MODULE.side_width(MODULE.STARS.label)
    right = MODULE.side_width(str(value))
    assert total == left + right
    # The value text is centred in the right-hand rectangle.
    value_x = float(re.findall(r'<text x="([\d.]+)" y="14">', svg)[-1])
    assert value_x == pytest.approx(left + right / 2)
    assert f'aria-label="stars: {value}"' in svg


def test_drift_report_degrades_when_github_is_unreachable(monkeypatch) -> None:
    """Offline must report "not checked", never a wrong or guessed value."""

    monkeypatch.setattr(MODULE, "live_values", lambda: None)
    report = MODULE.drift_report()
    assert report["available"] is False
    assert report["drifted"] == []


def test_drift_report_flags_a_behind_badge() -> None:
    report = MODULE.drift_report({MODULE.STARS.slug: 999999})
    assert report["available"] is True
    assert [entry["badge"] for entry in report["drifted"]] == [MODULE.STARS.slug]
    assert report["drifted"][0]["live"] == "999999"


def test_drift_report_is_quiet_when_badges_match() -> None:
    values = {}
    for badge in MODULE.BADGES:
        raw = MODULE.committed_value(badge).removesuffix("/month")
        values[badge.slug] = int(raw)
    assert MODULE.drift_report(values)["drifted"] == []


def test_check_without_strict_never_fails_on_drift(monkeypatch, capsys) -> None:
    """A new star must not turn CI red."""

    monkeypatch.setattr(MODULE, "live_values", lambda: {MODULE.STARS.slug: 999999})
    assert MODULE.main(["--check"]) == 0
    assert MODULE.main(["--check", "--strict"]) == 1
    capsys.readouterr()


def test_apply_refuses_without_live_stats(monkeypatch, capsys) -> None:
    monkeypatch.setattr(MODULE, "live_values", lambda: None)
    assert MODULE.main(["--apply"]) == 1
    assert "refusing to rewrite" in capsys.readouterr().err
