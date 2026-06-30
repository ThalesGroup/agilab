from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "agilab_audit.py"
sys.path.insert(0, str(ROOT / "tools"))

spec = importlib.util.spec_from_file_location("agilab_audit_test_module", MODULE_PATH)
assert spec is not None and spec.loader is not None
agilab_audit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = agilab_audit
spec.loader.exec_module(agilab_audit)


_FULL_HEAD = "dcc3b7233bc4f2ef4147c39be2d2465f9bfb8a63"


def _fake_detached_git(args: list[str], *, cwd: Path) -> tuple[int, str, str]:
    del cwd
    if args == ["status", "--short", "--branch", "--untracked-files=no"]:
        return 0, "## HEAD (no branch)", ""
    if args == ["branch", "--show-current"]:
        return 0, "", ""
    if args == ["rev-parse", "--short", "HEAD"]:
        return 0, _FULL_HEAD[:7], ""
    if args == ["rev-parse", "HEAD"]:
        return 0, _FULL_HEAD, ""
    if args == ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]:
        return 128, "", "fatal: no upstream configured"
    if args == ["rev-list", "--left-right", "--count", "HEAD...origin/main"]:
        return 0, "0\t0", ""
    raise AssertionError(f"unexpected git args: {args}")


def test_strict_audit_allows_expected_github_tag_detached_checkout(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(agilab_audit, "_git", _fake_detached_git)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REF_TYPE", "tag")
    monkeypatch.setenv("GITHUB_SHA", _FULL_HEAD)

    report = agilab_audit._audit_worktree(tmp_path, fetch=False)

    assert report["detached"] is True
    assert report["detached_expected"] is True
    assert "detached HEAD" not in report["warnings"]


def test_strict_audit_still_warns_on_unexpected_detached_checkout(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(agilab_audit, "_git", _fake_detached_git)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_REF_TYPE", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)

    report = agilab_audit._audit_worktree(tmp_path, fetch=False)

    assert report["detached"] is True
    assert report["detached_expected"] is False
    assert "detached HEAD" in report["warnings"]


def test_audit_worktree_reports_missing_path_without_running_git(tmp_path: Path) -> None:
    missing = tmp_path / "stale-worktree"

    report = agilab_audit._audit_worktree(missing, fetch=True)

    assert report["status"] == "missing worktree path"
    assert report["head"] is None
    assert "missing worktree path; run git worktree prune" in report["warnings"]


def test_audit_preflight_accepts_selected_first_publish_project(monkeypatch) -> None:
    calls = []

    monkeypatch.setattr(agilab_audit, "_worktrees", lambda: [])
    monkeypatch.setattr(
        agilab_audit,
        "_command_check",
        lambda name, command, timeout=120: {
            "name": name,
            "status": "pass",
            "returncode": 0,
            "summary": "ok",
        },
    )

    def fake_preflight_report(**kwargs):
        calls.append(kwargs)
        return {
            "status": "pass",
            "summary": {
                "checked": 1,
                "current": 0,
                "to_publish": 0,
                "allowed_missing_projects": 1,
                "blockers": 0,
            },
        }

    monkeypatch.setattr(agilab_audit, "pypi_preflight_report", fake_preflight_report)
    monkeypatch.setenv("AGILAB_ALLOW_MISSING_PYPI_PROJECTS", "agi-app-extra")

    report = agilab_audit.build_report(
        fetch=False,
        network=True,
        pypi_package_names=["agi-app-data-quality-gate"],
        allowed_missing_pypi_projects=["agi-app-data-quality-gate"],
    )

    assert report["status"] == "pass"
    assert calls == [
        {
            "repo_root": agilab_audit.ROOT,
            "package_names": ["agi-app-data-quality-gate"],
            "roles": [],
            "allowed_missing_projects": [
                "agi-app-data-quality-gate",
                "agi-app-extra",
            ],
        }
    ]
