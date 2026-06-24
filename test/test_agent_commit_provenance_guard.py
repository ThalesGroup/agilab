from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "agent_commit_provenance_guard.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("agent_commit_provenance_guard_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def _init_repo(root: Path) -> None:
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "Base Human")
    _git(root, "config", "user.email", "base@example.test")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "base")


def test_agent_branch_detection_covers_codex_dash_and_slash() -> None:
    module = _load_module()

    assert module.is_agent_branch("codex/release-fix")
    assert module.is_agent_branch("codex-7-axis-review")
    assert module.is_agent_branch("claude/provenance")
    assert not module.is_agent_branch("main")


def test_current_config_fails_for_human_identity_on_agent_branch(tmp_path: Path) -> None:
    module = _load_module()
    _init_repo(tmp_path)
    _git(tmp_path, "switch", "-c", "codex/provenance")
    _git(tmp_path, "config", "user.name", "GuilaumeDemets")
    _git(tmp_path, "config", "user.email", "g.demets02@gmail.com")

    report = module.check_current_config(tmp_path)

    assert report["status"] == "fail"
    assert report["issues"][0]["rule"] == "agent-branch-human-identity"
    assert report["issues"][0]["field"] == "git-config"


def test_pre_push_fails_for_human_identity_commit_on_agent_branch(tmp_path: Path) -> None:
    module = _load_module()
    _init_repo(tmp_path)
    _git(tmp_path, "switch", "-c", "codex/provenance")
    _git(tmp_path, "config", "user.name", "GuilaumeDemets")
    _git(tmp_path, "config", "user.email", "g.demets02@gmail.com")
    (tmp_path / "agent.txt").write_text("bad identity\n", encoding="utf-8")
    _git(tmp_path, "add", "agent.txt")
    _git(tmp_path, "commit", "-m", "bad agent identity")
    head = _git(tmp_path, "rev-parse", "HEAD")
    spec = module.PushSpec("refs/heads/codex/provenance", head, "refs/heads/codex/provenance", module.ZERO_SHA)

    report = module.check_pre_push_specs(tmp_path, [spec], base_ref="main")

    assert report["status"] == "fail"
    assert {issue["field"] for issue in report["issues"]} == {"author", "committer"}


def test_pre_push_allows_explicit_agent_identity_on_agent_branch(tmp_path: Path) -> None:
    module = _load_module()
    _init_repo(tmp_path)
    _git(tmp_path, "switch", "-c", "codex/provenance")
    _git(tmp_path, "config", "user.name", module.DEFAULT_AGENT_NAME)
    _git(tmp_path, "config", "user.email", module.DEFAULT_AGENT_EMAIL)
    (tmp_path / "agent.txt").write_text("agent identity\n", encoding="utf-8")
    _git(tmp_path, "add", "agent.txt")
    _git(tmp_path, "commit", "-m", "good agent identity")
    head = _git(tmp_path, "rev-parse", "HEAD")
    spec = module.PushSpec("refs/heads/codex/provenance", head, "refs/heads/codex/provenance", module.ZERO_SHA)

    report = module.check_pre_push_specs(tmp_path, [spec], base_ref="main")

    assert report["status"] == "pass"
    assert report["issues"] == []


def test_git_history_inventory_flags_direct_guillaume_local_identity(tmp_path: Path) -> None:
    module = _load_module()
    _init_repo(tmp_path)
    _git(tmp_path, "config", "user.name", "GuillaumeDemets")
    _git(tmp_path, "config", "user.email", "g.demets02@gmail.com")
    (tmp_path / "direct.txt").write_text("direct human-looking identity\n", encoding="utf-8")
    _git(tmp_path, "add", "direct.txt")
    _git(tmp_path, "commit", "-m", "direct suspect identity")

    report = module.inventory_git_history(
        tmp_path,
        ["main"],
        repo_label="thales_agilab",
        first_parent=True,
    )

    assert report["status"] == "fail"
    assert {issue["field"] for issue in report["issues"]} == {"author", "committer"}
    assert {issue["rule"] for issue in report["issues"]} == {
        "direct-history-suspect-human-identity"
    }
    assert report["evidence"]["repo_label"] == "thales_agilab"


def test_git_history_inventory_ignores_non_suspect_human_identity(tmp_path: Path) -> None:
    module = _load_module()
    _init_repo(tmp_path)
    _git(tmp_path, "config", "user.name", "Jean-Pierre MORARD")
    _git(tmp_path, "config", "user.email", "jean-pierre.morard@thalesgroup.com")
    (tmp_path / "human.txt").write_text("human maintainer\n", encoding="utf-8")
    _git(tmp_path, "add", "human.txt")
    _git(tmp_path, "commit", "-m", "human maintainer commit")

    report = module.inventory_git_history(tmp_path, ["main"], repo_label="agilab", first_parent=True)

    assert report["status"] == "pass"
    assert report["issues"] == []


def test_git_history_inventory_skips_merges_by_default(tmp_path: Path) -> None:
    module = _load_module()
    _init_repo(tmp_path)
    _git(tmp_path, "switch", "-c", "feature")
    _git(tmp_path, "config", "user.name", module.DEFAULT_AGENT_NAME)
    _git(tmp_path, "config", "user.email", module.DEFAULT_AGENT_EMAIL)
    (tmp_path / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(tmp_path, "add", "feature.txt")
    _git(tmp_path, "commit", "-m", "feature")
    _git(tmp_path, "switch", "main")
    _git(tmp_path, "config", "user.name", "GuillaumeDemets")
    _git(tmp_path, "config", "user.email", "g.demets02@gmail.com")
    _git(tmp_path, "merge", "--no-ff", "feature", "-m", "suspect merge identity")

    report = module.inventory_git_history(tmp_path, ["main"], repo_label="agilab", first_parent=True)

    assert report["status"] == "pass"
    assert report["issues"] == []
