from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TRACKED_CHANGE_SELECTORS = (
    "src/agilab/reuse/reuse_catalog.py",
    "tools/agent_context_router.py",
    "tools/agent_skill_quality_guard.py",
    "tools/agi_core_change_guard.py",
    "tools/coverage_badge_guard.py",
    "tools/ga_regression_selector.py",
    "tools/impact_validate.py",
    "tools/maintenance_memory.py",
    "tools/pypi_publish.py",
    "tools/pre_push_changed_files.py",
    "tools/release_plan.py",
    "tools/skill_security_scan.py",
    "tools/workflow_parity.py",
    "tools/worktree_scope_guard.py",
)
SHELL_CHANGE_SELECTORS = ("tools/demo_agentic_agilab_workflow.sh",)


@pytest.mark.parametrize("relative_path", TRACKED_CHANGE_SELECTORS)
def test_tracked_change_selectors_do_not_filter_change_types(relative_path: str) -> None:
    text = (ROOT / relative_path).read_text(encoding="utf-8")
    diff_commands = [
        command
        for command in re.findall(
            r'[\[(]\s*(?:"git",\s*)?"diff(?:-tree)?".*?[\])]',
            text,
            flags=re.DOTALL,
        )
        if '"--name-only"' in command
    ]

    assert diff_commands
    assert "--diff-filter=" not in text
    assert all('"--no-renames"' in command for command in diff_commands)
    assert all('"-z"' in command for command in diff_commands)


@pytest.mark.parametrize("relative_path", SHELL_CHANGE_SELECTORS)
def test_shell_change_selectors_preserve_rename_sources(relative_path: str) -> None:
    lines = (ROOT / relative_path).read_text(encoding="utf-8").splitlines()
    diff_lines = [line for line in lines if "git diff" in line and "--name-only" in line]

    assert diff_lines
    assert all("--no-renames" in line for line in diff_lines)
    assert all(" -z" in line for line in diff_lines)
