from __future__ import annotations

from pathlib import Path

import pytest


# Current public release tooling keeps repository, release, HF sync, shared
# go/no-go gates, and guardrail entrypoints top-level so workflows can call them
# directly.
#
# Raised 2026-07-27 from 187. tools/ had held 191 top-level files since at least
# 2026-07-16, so this guard had been failing on `main` for over a week and was
# no longer catching anything. Grouping helpers under subdirectories is still the
# preferred way to make room; this records the real surface in the meantime.
# Raised 2026-09-30 from 195 for generate_agilab_xcode_project.py, a public
# IDE entrypoint alongside the existing PyCharm and VS Code generators.
TOOLS_SURFACE_BUDGET = 196


def test_top_level_tools_surface_stays_within_budget() -> None:
    tools_dir = Path("tools")
    top_level_tools = sorted(
        path
        for path in tools_dir.iterdir()
        if path.is_file() and path.name not in {".DS_Store", ".DS_store"}
    )

    assert len(top_level_tools) <= TOOLS_SURFACE_BUDGET, (
        f"tools/ has {len(top_level_tools)} top-level files; budget is "
        f"{TOOLS_SURFACE_BUDGET}. Reuse an existing tool, move helpers under a "
        "subdirectory, or raise this budget in the same change with rationale."
    )


@pytest.mark.parametrize("metadata_name", [".DS_Store", ".DS_store"])
def test_tools_budget_ignores_finder_metadata_but_counts_new_entrypoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, metadata_name: str
) -> None:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "existing_tool.py").write_text("# public entrypoint\n")
    (tools_dir / metadata_name).write_bytes(b"Finder metadata")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(globals(), "TOOLS_SURFACE_BUDGET", 1)

    test_top_level_tools_surface_stays_within_budget()

    (tools_dir / "new_tool.py").write_text("# additional public entrypoint\n")
    with pytest.raises(AssertionError, match="2 top-level files; budget is 1"):
        test_top_level_tools_surface_stays_within_budget()
