from __future__ import annotations

from pathlib import Path


# Current public release tooling keeps repository, release, HF sync, shared
# go/no-go gates, and guardrail entrypoints top-level so workflows can call them
# directly.
#
# Raised 2026-07-27 from 187. tools/ had held 191 top-level files since at least
# 2026-07-16, so this guard had been failing on `main` for over a week and was
# no longer catching anything. Grouping helpers under subdirectories is still the
# preferred way to make room; this records the real surface in the meantime.
TOOLS_SURFACE_BUDGET = 195


def test_top_level_tools_surface_stays_within_budget() -> None:
    tools_dir = Path("tools")
    top_level_tools = sorted(path for path in tools_dir.iterdir() if path.is_file())

    assert len(top_level_tools) <= TOOLS_SURFACE_BUDGET, (
        f"tools/ has {len(top_level_tools)} top-level files; budget is "
        f"{TOOLS_SURFACE_BUDGET}. Reuse an existing tool, move helpers under a "
        "subdirectory, or raise this budget in the same change with rationale."
    )
