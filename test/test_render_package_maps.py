# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Guards for the curated docs package-map figures."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "render_package_maps", REPO_ROOT / "tools" / "render_package_maps.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()
PACKAGES = MODULE.PACKAGE_MAPS


@pytest.mark.parametrize("package", PACKAGES, ids=lambda pkg: pkg.slug)
def test_every_module_belongs_to_a_curated_group(package) -> None:
    """A new module must not be able to vanish from the published map."""

    assert MODULE.uncovered_modules(package) == ()


@pytest.mark.parametrize("package", PACKAGES, ids=lambda pkg: pkg.slug)
def test_groups_are_disjoint_so_counts_cannot_inflate(package) -> None:
    groups = MODULE._resolved_groups(package)
    members = [name for group in groups for name in group.members]
    assert len(members) == len(set(members))


@pytest.mark.parametrize("package", PACKAGES, ids=lambda pkg: pkg.slug)
def test_duplicate_stems_are_only_explicit_compatibility_shims(package) -> None:
    assert MODULE.ambiguous_module_stems(package) == {}


def test_distinct_modules_with_the_same_stem_cannot_disappear(tmp_path: Path) -> None:
    for folder in (tmp_path / "alpha", tmp_path / "beta"):
        folder.mkdir()
        (folder / "worker.py").write_text("VALUE = 1\n", encoding="utf-8")
    package = MODULE.PackageMap(
        slug="ambiguous",
        title="Ambiguous",
        subtitle="",
        source_root=tmp_path,
        groups=(MODULE.Group("Workers", ("**/*.py",)),),
    )

    assert MODULE.ambiguous_module_stems(package) == {
        "worker": ("alpha/worker.py", "beta/worker.py")
    }


@pytest.mark.parametrize("package", PACKAGES, ids=lambda pkg: pkg.slug)
def test_every_curated_group_contains_at_least_one_module(package) -> None:
    empty = [group.title for group in MODULE._resolved_groups(package) if not group.members]
    assert not empty, f"{package.slug}: empty responsibility groups: {empty}"


def test_distributor_capacity_modules_stay_in_their_named_group() -> None:
    package = next(pkg for pkg in PACKAGES if pkg.slug == "packages_agi_distributor")
    groups = {group.title: group.members for group in MODULE._resolved_groups(package)}

    assert groups["Capacity and cleanup"] == (
        "background_jobs_support",
        "capacity_support",
        "cleanup_support",
    )


@pytest.mark.parametrize("package", PACKAGES, ids=lambda pkg: pkg.slug)
def test_rendered_text_stays_inside_its_container(package) -> None:
    """The defect that motivated these figures: labels crossing a box edge."""

    svg = MODULE.render_svg(package)
    width = int(re.search(r'width="(\d+)"', svg).group(1))
    margin = 46
    card_w = 316
    body_w = card_w - 40

    for match in re.finditer(
        r'<text class="(?P<cls>[\w-]+)"[^>]*x="(?P<x>\d+)"[^>]*>(?P<text>[^<]*)</text>', svg
    ):
        cls = match.group("cls")
        text = match.group("text")
        x = int(match.group("x"))
        font = {
            "title": 24,
            "subtitle": 15,
            "card-title": 17,
            "card-note": 13,
            "member": 13,
            "count": 12,
            "footer": 13,
        }[cls]
        rendered = len(text) * font * MODULE.CHAR_EM
        if cls in {"card-title", "card-note", "member"}:
            assert rendered <= body_w, f"{package.slug}: {cls} overflows its card: {text!r}"
        elif cls in {"title", "subtitle", "footer"}:
            assert x + rendered <= width - margin + 1, (
                f"{package.slug}: {cls} overflows the canvas: {text!r}"
            )


@pytest.mark.parametrize("package", PACKAGES, ids=lambda pkg: pkg.slug)
def test_render_is_deterministic(package) -> None:
    assert MODULE.render_svg(package) == MODULE.render_svg(package)


def test_checked_in_figures_match_a_fresh_render() -> None:
    """Fails when the source grew a module and the figures were not re-rendered."""

    rendered = MODULE.render_all(REPO_ROOT / "docs" / "source" / "diagrams")
    stale = [path.name for path, text in rendered.items() if path.read_text(encoding="utf-8") != text]
    assert not stale, (
        f"stale package maps: {stale}; rerun "
        "`python tools/render_package_maps.py --apply` against the canonical docs "
        "checkout and sync the mirror"
    )
