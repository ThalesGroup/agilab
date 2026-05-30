from __future__ import annotations

from pathlib import Path


# Current public release tooling keeps repository, release, HF sync, and
# guardrail entrypoints top-level so workflows can call them directly.
TOOLS_SURFACE_BUDGET = 163


def test_top_level_tools_surface_stays_within_budget() -> None:
    tools_dir = Path("tools")
    top_level_tools = sorted(path for path in tools_dir.iterdir() if path.is_file())

    assert len(top_level_tools) <= TOOLS_SURFACE_BUDGET, (
        f"tools/ has {len(top_level_tools)} top-level files; budget is "
        f"{TOOLS_SURFACE_BUDGET}. Reuse an existing tool, move helpers under a "
        "subdirectory, or raise this budget in the same change with rationale."
    )
