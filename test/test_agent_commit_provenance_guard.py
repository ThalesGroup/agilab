from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "agent_commit_provenance_guard.py"
TEST_AGENT_EMAIL = "agent.operator@example.test"


@pytest.fixture(autouse=True)
def isolate_git_environment(tmp_path, monkeypatch):
    for key in tuple(os.environ):
        if key.startswith("GIT_") or key == "EMAIL":
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "empty-git-config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "agent_commit_provenance_guard_test_module", MODULE_PATH
    )
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


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Claude Martin", False),
        ("Talbot", False),
        ("Codex Smith", False),
        ("Claude Code", True),
        ("OpenAI Codex", True),
        ("AGILAB Codex Agent", True),
        ("github-actions[bot]", True),
    ],
)
def test_display_name_requires_explicit_agent_marker_or_runtime(name, expected):
    module = _load_module()
    assert module.is_agent_identity(module.Identity(name, TEST_AGENT_EMAIL)) is expected


@pytest.mark.parametrize(
    "email",
    [
        "203319130+jpmorard@users.noreply.github.com",
        "123456+another-operator@users.noreply.github.com",
    ],
)
def test_operator_email_preserves_agent_attribution_in_config_and_push(tmp_path, email):
    module = _load_module()
    _init_repo(tmp_path)
    _git(tmp_path, "switch", "-c", "codex/provenance")
    _git(tmp_path, "config", "user.name", module.DEFAULT_AGENT_NAME)
    _git(tmp_path, "config", "user.email", email)
    report = module.check_current_config(tmp_path)
    assert report["status"] == "pass"
    assert report["evidence"]["effective_identities"]["committer"]["email"] == email
    assert report["evidence"]["default_agent_identity"]["email"] is None
    assert "Offline" in report["evidence"]["verification_basis"]
    _git(
        tmp_path,
        "commit",
        "--allow-empty",
        "-m",
        "agent work, operator signing account",
    )
    head = _git(tmp_path, "rev-parse", "HEAD")
    spec = module.PushSpec(
        "refs/heads/codex/provenance",
        head,
        "refs/heads/codex/provenance",
        module.ZERO_SHA,
    )
    assert (
        module.check_pre_push_specs(tmp_path, [spec], base_ref="main")["status"]
        == "pass"
    )


def test_agent_looking_email_does_not_mask_human_display_name(tmp_path):
    module = _load_module()
    _init_repo(tmp_path)
    _git(tmp_path, "switch", "-c", "codex/provenance")
    _git(tmp_path, "config", "user.name", "Alex Maintainer")
    _git(tmp_path, "config", "user.email", "codex.agent@example.test")
    assert module.check_current_config(tmp_path)["status"] == "fail"


@pytest.mark.parametrize("field", ["author", "committer"])
@pytest.mark.parametrize("source", ["environment", "role-config"])
def test_effective_identity_overrides_cannot_bypass_guard(
    tmp_path, monkeypatch, field, source
):
    module = _load_module()
    _init_repo(tmp_path)
    _git(tmp_path, "switch", "-c", "codex/provenance")
    _git(tmp_path, "config", "user.name", module.DEFAULT_AGENT_NAME)
    _git(tmp_path, "config", "user.email", TEST_AGENT_EMAIL)
    if source == "environment":
        monkeypatch.setenv(f"GIT_{field.upper()}_NAME", "Jean-Pierre MORARD")
    else:
        _git(tmp_path, "config", f"{field}.name", "Jean-Pierre MORARD")
    report = module.check_current_config(tmp_path)
    assert report["status"] == "fail"
    assert {issue["field"] for issue in report["issues"]} == {field}


def test_unresolved_effective_identity_fails_with_actionable_error(tmp_path):
    module = _load_module()
    _init_repo(tmp_path)
    _git(tmp_path, "switch", "-c", "codex/provenance")
    _git(tmp_path, "config", "--unset", "user.email")
    _git(tmp_path, "config", "user.useConfigOnly", "true")
    report = module.check_current_config(tmp_path)
    assert report["status"] == "fail"
    assert {issue["rule"] for issue in report["issues"]} == {
        "agent-identity-unresolved"
    }
    assert "GIT_AUTHOR_IDENT" in report["issues"][0]["message"]
    rendered = module.render_text(report)
    assert "codex-agent@users.noreply.github.com" not in rendered
    assert "confirmed verified email" in rendered


@pytest.mark.parametrize(
    "name,expected", [("AGILAB Codex Agent", "pass"), ("Jean-Pierre MORARD", "fail")]
)
def test_github_inventory_distinguishes_agent_name_from_operator_email(
    monkeypatch, name, expected
):
    module = _load_module()

    def github(args):
        if args[1] == "list":
            return [{"number": 1, "headRefName": "codex/example"}]
        return {
            "commits": [
                {
                    "oid": "a" * 40,
                    "authors": [
                        {
                            "name": name,
                            "email": "203319130+jpmorard@users.noreply.github.com",
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(module, "_run_gh_json", github)
    assert (
        module.inventory_github_prs(repo="example/repo", limit=1, prefixes=["codex"])[
            "status"
        ]
        == expected
    )


def test_current_config_fails_for_human_identity_on_agent_branch(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _init_repo(tmp_path)
    _git(tmp_path, "switch", "-c", "codex/provenance")
    _git(tmp_path, "config", "user.name", "GuilaumeDemets")
    _git(tmp_path, "config", "user.email", "g.demets02@gmail.com")

    report = module.check_current_config(tmp_path)

    assert report["status"] == "fail"
    assert report["issues"][0]["rule"] == "agent-branch-human-identity"
    assert {issue["field"] for issue in report["issues"]} == {"author", "committer"}


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
    _git(tmp_path, "config", "user.email", TEST_AGENT_EMAIL)
    (tmp_path / "agent.txt").write_text("agent identity\n", encoding="utf-8")
    _git(tmp_path, "add", "agent.txt")
    _git(tmp_path, "commit", "-m", "good agent identity")
    head = _git(tmp_path, "rev-parse", "HEAD")
    spec = module.PushSpec("refs/heads/codex/provenance", head, "refs/heads/codex/provenance", module.ZERO_SHA)

    report = module.check_pre_push_specs(tmp_path, [spec], base_ref="main")

    assert report["status"] == "pass"
    assert report["issues"] == []


def test_pre_push_excludes_public_base_commits_after_branch_update(tmp_path: Path) -> None:
    module = _load_module()
    _init_repo(tmp_path)
    _git(tmp_path, "switch", "-c", "agent/provenance")
    _git(tmp_path, "config", "user.name", module.DEFAULT_AGENT_NAME)
    _git(tmp_path, "config", "user.email", TEST_AGENT_EMAIL)
    (tmp_path / "agent.txt").write_text("first agent change\n", encoding="utf-8")
    _git(tmp_path, "add", "agent.txt")
    _git(tmp_path, "commit", "-m", "first agent change")
    remote_head = _git(tmp_path, "rev-parse", "HEAD")

    _git(tmp_path, "switch", "main")
    _git(tmp_path, "config", "user.name", "Jean-Pierre MORARD")
    _git(tmp_path, "config", "user.email", "jean-pierre.morard@thalesgroup.com")
    (tmp_path / "main.txt").write_text("public main change\n", encoding="utf-8")
    _git(tmp_path, "add", "main.txt")
    _git(tmp_path, "commit", "-m", "public main change")
    public_main_head = _git(tmp_path, "rev-parse", "HEAD")

    _git(tmp_path, "switch", "agent/provenance")
    _git(tmp_path, "config", "user.name", module.DEFAULT_AGENT_NAME)
    _git(tmp_path, "config", "user.email", TEST_AGENT_EMAIL)
    _git(tmp_path, "merge", "--no-edit", "main")
    (tmp_path / "agent.txt").write_text("second agent change\n", encoding="utf-8")
    _git(tmp_path, "add", "agent.txt")
    _git(tmp_path, "commit", "-m", "second agent change")
    local_head = _git(tmp_path, "rev-parse", "HEAD")
    spec = module.PushSpec(
        "refs/heads/agent/provenance",
        local_head,
        "refs/heads/agent/provenance",
        remote_head,
    )

    report = module.check_pre_push_specs(tmp_path, [spec], base_ref="main")

    assert report["status"] == "pass"
    assert report["issues"] == []
    checked_commits = {
        commit["sha"] for commit in report["evidence"]["commits"]
    }
    assert public_main_head not in checked_commits
    assert local_head in checked_commits


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
    _git(tmp_path, "config", "user.email", TEST_AGENT_EMAIL)
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
