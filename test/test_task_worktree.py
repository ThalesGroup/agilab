from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "task_worktree.py"

spec = importlib.util.spec_from_file_location("task_worktree", MODULE_PATH)
assert spec is not None and spec.loader is not None
task_worktree = importlib.util.module_from_spec(spec)
spec.loader.exec_module(task_worktree)


def test_task_worktree_sanitizes_default_path():
    path = task_worktree.default_path("fix/pytorch coach", root=Path("/tmp/agilab-worktrees"))

    assert path == Path("/tmp/agilab-worktrees/fix-pytorch-coach")


def test_task_worktree_planned_command_uses_branch_path_and_start_point():
    command = task_worktree.planned_command(
        "fix/demo",
        path=Path("/tmp/demo"),
        start_point="origin/main",
        force=True,
    )

    assert command == [
        "git",
        "worktree",
        "add",
        "--force",
        "-B",
        "fix/demo",
        "/tmp/demo",
        "origin/main",
    ]
