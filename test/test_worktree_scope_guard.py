from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "worktree_scope_guard.py"

spec = importlib.util.spec_from_file_location("worktree_scope_guard", MODULE_PATH)
assert spec is not None and spec.loader is not None
scope_guard = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = scope_guard
spec.loader.exec_module(scope_guard)


def test_scope_for_path_groups_app_source_package_and_tests_together():
    paths = [
        "src/agilab/apps/builtin/pytorch_playground_project/src/pytorch_playground/playground_ui.py",
        "src/agilab/lib/agi-app-pytorch-playground/src/agi_app_pytorch_playground/project/pytorch_playground_project/src/pytorch_playground/playground_ui.py",
        "test/test_pytorch_playground_app.py",
    ]

    report = scope_guard.analyze_scope(paths)

    assert set(report.groups) == {"app:pytorch_playground_project"}
    assert report.mixed is False


def test_scope_for_path_groups_apps_pages_by_page_name():
    assert (
        scope_guard.scope_for_path("src/agilab/apps-pages/view_maps_3d/pyproject.toml")
        == "page:view_maps_3d"
    )


def test_scope_for_path_groups_git_hooks_as_infrastructure():
    assert scope_guard.scope_for_path(".githooks/pre-push") == "git-hooks"


def test_scope_guard_flags_mixed_unrelated_worktree():
    report = scope_guard.analyze_scope(
        [
            "src/agilab/apps/builtin/pytorch_playground_project/src/pytorch_playground/playground_ui.py",
            "src/agilab/apps/builtin/mission_decision_project/README.md",
            ".codex/skills/agilab-release-verification/SKILL.md",
        ],
        max_scopes=1,
    )

    assert report.mixed is True
    text = scope_guard.render_text(report)
    assert "MIXED" in text
    assert "app:pytorch_playground_project" in text
    assert "app:mission_decision_project" in text
    assert "agent-skills" in text
    assert "./dev task-worktree <branch-name>" in text


def test_scope_guard_allows_explicit_scope():
    report = scope_guard.analyze_scope(
        [
            "src/agilab/apps/builtin/pytorch_playground_project/README.md",
            "docs/source/public-app-catalog.rst",
        ],
        max_scopes=1,
        allowed_scopes=("docs",),
    )

    assert report.counted_scopes == ("app:pytorch_playground_project",)
    assert report.mixed is False
    assert "docs (allowed)" in scope_guard.render_text(report)


def test_scope_guard_json_payload_is_stable():
    report = scope_guard.analyze_scope(
        ["tools/agilab_dev.py", "test/test_agilab_dev_shortcuts.py"],
        max_scopes=2,
    )
    payload = scope_guard.report_to_json(report)

    assert payload["schema"] == "agilab.worktree_scope_guard.v1"
    assert payload["mixed"] is False
    assert payload["groups"] == {
        "repo-tools": ["tools/agilab_dev.py"],
        "tests": ["test/test_agilab_dev_shortcuts.py"],
    }
    assert json.loads(json.dumps(payload)) == payload


def test_changed_files_uses_staged_or_full_diff():
    calls: list[tuple[str, ...]] = []

    def fake_git(args):
        calls.append(tuple(args))
        if "--cached" in args:
            return "staged.py\n"
        if "ls-files" in args:
            return "new.py\n"
        return "dirty.py\n"

    assert scope_guard.changed_files(git=fake_git) == ("dirty.py", "staged.py")
    assert scope_guard.changed_files(staged=True, git=fake_git) == ("staged.py",)
    assert scope_guard.changed_files(include_untracked=True, git=fake_git) == (
        "dirty.py",
        "new.py",
        "staged.py",
    )


def test_main_includes_untracked_by_default(capsys, monkeypatch):
    calls: list[dict[str, object]] = []

    def fake_changed_files(**kwargs):
        calls.append(kwargs)
        return ("new.py",)

    monkeypatch.setattr(scope_guard, "changed_files", fake_changed_files)

    assert scope_guard.main(["--max-scopes", "2"]) == 0
    assert scope_guard.main(["--staged", "--max-scopes", "2"]) == 0
    assert scope_guard.main(["--tracked-only", "--max-scopes", "2"]) == 0

    assert [call["include_untracked"] for call in calls] == [True, False, False]
    assert [call["staged"] for call in calls] == [False, True, False]
    assert "worktree scope:" in capsys.readouterr().out


def test_main_allows_infrastructure_scopes_by_default(capsys):
    assert (
        scope_guard.main(
            [
                "--changed-file",
                "AGENTS.md",
                "--changed-file",
                ".githooks/pre-push",
                "--changed-file",
                "tools/worktree_scope_guard.py",
                "--changed-file",
                "test/test_worktree_scope_guard.py",
            ]
        )
        == 0
    )
    assert "0 counted scope(s)" in capsys.readouterr().out


def test_main_strict_counts_infrastructure_scopes(capsys):
    assert (
        scope_guard.main(
            [
                "--strict",
                "--changed-file",
                "AGENTS.md",
                "--changed-file",
                ".githooks/pre-push",
                "--changed-file",
                "tools/worktree_scope_guard.py",
            ]
        )
        == 1
    )
    assert "3 counted scope(s)" in capsys.readouterr().out
