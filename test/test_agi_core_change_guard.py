from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "agi_core_change_guard.py"

spec = importlib.util.spec_from_file_location("agi_core_change_guard", MODULE_PATH)
assert spec is not None and spec.loader is not None
guard = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guard
spec.loader.exec_module(guard)


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _repo_with_protected_file(
    tmp_path: Path,
    *,
    filename: str = "pyproject.toml",
) -> tuple[Path, Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.name", "AGILAB Test")
    _git(repo, "config", "user.email", "agilab-test@example.invalid")
    _git(repo, "config", "core.quotePath", "true")
    protected = repo / "src/agilab/core/agi-core" / filename
    protected.parent.mkdir(parents=True)
    protected.write_text("[project]\nname = 'agi-core'\n", encoding="utf-8")
    _git(repo, "add", protected.relative_to(repo).as_posix())
    _git(repo, "commit", "--quiet", "-m", "add protected file")
    return repo, protected, _git(repo, "rev-parse", "HEAD")


def test_protected_path_detection_is_limited_to_agi_core() -> None:
    assert guard.protected_changed_files(
        [
            "src/agilab/core/agi-core/src/agi_core/runtime.py",
            "src/agilab/core/agi-node/src/agi_node/runtime.py",
            "test/test_agi_core_change_guard.py",
        ]
    ) == ("src/agilab/core/agi-core/src/agi_core/runtime.py",)


def test_jpmorard_can_change_protected_agi_core_path() -> None:
    result = guard.evaluate(
        ["src/agilab/core/agi-core/pyproject.toml"],
        actor="jpmorard",
    )

    assert result.passed
    assert result.actor_allowed


def test_other_actor_is_blocked_for_protected_agi_core_path() -> None:
    result = guard.evaluate(
        ["src/agilab/core/agi-core/pyproject.toml"],
        actor="other-user",
    )

    assert not result.passed
    assert not result.actor_allowed
    assert "other-user" in guard.render_result(result)
    assert "src/agilab/core/agi-core/pyproject.toml" in guard.render_result(result)


def test_other_actor_can_change_unprotected_paths() -> None:
    result = guard.evaluate(
        ["src/agilab/core/agi-node/pyproject.toml"],
        actor="other-user",
    )

    assert result.passed


def test_changed_files_between_includes_deleted_protected_path(tmp_path: Path) -> None:
    repo, protected, base = _repo_with_protected_file(tmp_path)

    protected.unlink()
    _git(repo, "add", "--all")
    _git(repo, "commit", "--quiet", "-m", "delete protected file")
    head = _git(repo, "rev-parse", "HEAD")

    changed = guard.changed_files_between(base, head, repo_root=repo)
    result = guard.evaluate(changed, actor="other-user")

    assert changed == ("src/agilab/core/agi-core/pyproject.toml",)
    assert not result.passed


def test_changed_files_between_includes_protected_rename_source(tmp_path: Path) -> None:
    repo, protected, base = _repo_with_protected_file(tmp_path)
    moved = repo / "src/agilab/core/moved.py"
    protected.rename(moved)
    _git(repo, "add", "--all")
    _git(repo, "commit", "--quiet", "-m", "move protected file")
    head = _git(repo, "rev-parse", "HEAD")

    changed = guard.changed_files_between(base, head, repo_root=repo)
    result = guard.evaluate(changed, actor="other-user")

    assert changed == (
        "src/agilab/core/agi-core/pyproject.toml",
        "src/agilab/core/moved.py",
    )
    assert not result.passed


def test_changed_files_between_preserves_unicode_protected_path(tmp_path: Path) -> None:
    repo, protected, base = _repo_with_protected_file(tmp_path, filename="mód.py")
    protected.write_text("VALUE = 2\n", encoding="utf-8")
    _git(repo, "add", protected.relative_to(repo).as_posix())
    _git(repo, "commit", "--quiet", "-m", "update unicode protected file")
    head = _git(repo, "rev-parse", "HEAD")

    changed = guard.changed_files_between(base, head, repo_root=repo)
    result = guard.evaluate(changed, actor="other-user")

    assert changed == ("src/agilab/core/agi-core/mód.py",)
    assert not result.passed
