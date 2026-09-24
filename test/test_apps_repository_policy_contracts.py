"""External app checkout trust is verified independently of inherited Git state."""
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agilab.security import apps_repository_policy as policy


ORIGIN = "https://example.invalid/reviewed/apps.git"
SHA = "a" * 40


def result(stdout="", code=0):
    return subprocess.CompletedProcess([], code, stdout, "")


@pytest.mark.parametrize("probe", [None, result("true", 1), result("false")])
def test_failed_git_probe_cannot_claim_checkout(monkeypatch, tmp_path, probe):
    run = Mock(return_value=probe)
    monkeypatch.setattr(policy, "_run_git", run)
    assert policy._verified_git_state(tmp_path) == ({"is_git_checkout": False, "git_verified": False}, None)
    run.assert_called_once()


@pytest.mark.parametrize("head", [None, result("", 1), result("not-a-commit")])
def test_head_must_resolve_to_verified_commit(monkeypatch, tmp_path, head):
    monkeypatch.setattr(policy, "_run_git", Mock(side_effect=[result("true"), result("", 1), head, result(ORIGIN), result()]))
    state, origin = policy._verified_git_state(tmp_path)
    assert state["head_state"] == "unknown"
    assert state["git_verified"]
    assert state["worktree_clean"]
    assert origin == ORIGIN


@pytest.mark.parametrize("status,clean", [(None, False), (result("", 1), False), (result("?? injected.py"), False),
                                         (result("!! ignored.py"), False), (result(" M module.py"), False), (result(), True)])
def test_untracked_ignored_and_modified_content_are_unreviewed(monkeypatch, tmp_path, status, clean):
    run = Mock(side_effect=[result("true"), result("", 1), result(SHA), result(ORIGIN), status])
    monkeypatch.setattr(policy, "_run_git", run)
    state, _ = policy._verified_git_state(tmp_path)
    assert state["head_state"] == "detached"
    assert state["commit"] == SHA
    assert state["worktree_clean"] is clean
    assert run.call_args.args[1:] == ("status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching")


@pytest.mark.parametrize("branch", [None, result("", 1), result(""), result("main")])
def test_branch_probe_classifies_floating_head(monkeypatch, tmp_path, branch):
    monkeypatch.setattr(policy, "_run_git", Mock(side_effect=[result("true"), branch, result(SHA), None, result()]))
    state, origin = policy._verified_git_state(tmp_path)
    assert state["head_state"] == ("branch" if branch is not None and branch.stdout == "main" else "detached")
    assert origin is None


def test_git_inspection_strips_inherited_git_controls(monkeypatch, tmp_path):
    monkeypatch.setattr(policy, "os", SimpleNamespace(environ={
        "GIT_DIR": "/unrelated", "GIT_WORK_TREE": "/unrelated", "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.fsmonitor", "GIT_CONFIG_VALUE_0": "unsafe",
        "PATH": "/bin", "REGULAR_SETTING": "kept",
    }))
    run = Mock(return_value=result())
    monkeypatch.setattr(policy, "subprocess", SimpleNamespace(run=run))
    assert policy._run_git(tmp_path, "status").returncode == 0
    assert run.call_args.kwargs["env"] == {"PATH": "/bin", "REGULAR_SETTING": "kept",
                                          "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}
    command = run.call_args.args[0]
    assert command[:5] == ["git", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false"]
    assert command[-3:] == ["-C", str(tmp_path), "status"]


def test_missing_git_executable_is_unverified(monkeypatch, tmp_path):
    monkeypatch.setattr(policy, "subprocess", SimpleNamespace(run=Mock(side_effect=OSError("not installed"))))
    assert policy._run_git(tmp_path, "status") is None


@pytest.mark.parametrize("strict,origin,allowlist,head,clean,floating,status,summary", [
    (True, None, ORIGIN, "detached", True, False, "fail", "no origin"),
    (True, ORIGIN, "", "detached", True, False, "fail", "requires an origin allowlist"),
    (True, ORIGIN, "https://other.invalid/apps", "detached", True, True, "fail", "not in"),
    (True, ORIGIN, ORIGIN, "unknown", True, True, "fail", "committed Git revision"),
    (False, ORIGIN, "", "unknown", True, False, "warn", "committed Git revision"),
    (True, ORIGIN, ORIGIN, "detached", False, False, "fail", "unreviewed working-tree"),
    (True, ORIGIN, ORIGIN, "detached", False, True, "warn", "unreviewed working-tree"),
    (False, ORIGIN, "", "detached", False, False, "warn", "unreviewed working-tree"),
    (True, ORIGIN, ORIGIN, "branch", True, False, "fail", "floating branch"),
    (True, ORIGIN, ORIGIN, "branch", True, True, "warn", "floating branch"),
    (False, ORIGIN, "", "branch", True, False, "warn", "floating branch"),
    (False, ORIGIN, "https://other.invalid/apps", "detached", True, False, "warn", "not in"),
    (True, ORIGIN, ORIGIN, "detached", True, False, "pass", "pinned and allowlisted"),
    (False, ORIGIN, "", "detached", True, False, "pass", "not on a floating branch"),
])
def test_external_repository_policy_decision_matrix(monkeypatch, tmp_path, strict, origin, allowlist, head, clean, floating, status, summary):
    state = {"is_git_checkout": True, "git_verified": True, "head_state": head,
             "worktree_clean": clean, "name": "main", "commit": SHA}
    monkeypatch.setattr(policy, "_verified_git_state", lambda _: (state, origin))
    configured = {"APPS_REPOSITORY": str(tmp_path), policy.APPS_ALLOWLIST_ENV: allowlist}
    checked = policy.evaluate_apps_repository_policy(configured, cwd=tmp_path, strict=strict, allow_floating=floating)
    assert checked.status == status
    assert summary in checked.summary
    assert checked.details["git_verified"]
    assert checked.details["allow_floating"] is floating


@pytest.mark.parametrize("strict", [True, False])
@pytest.mark.parametrize("kind", ["missing", "file", "non_git"])
def test_invalid_repository_location_never_passes(monkeypatch, tmp_path, strict, kind):
    selected = tmp_path / "apps"
    if kind == "file":
        selected.write_text("not a repository")
    elif kind == "non_git":
        selected.mkdir()
        monkeypatch.setattr(policy, "_verified_git_state", lambda _: ({"is_git_checkout": False}, None))
    checked = policy.evaluate_apps_repository_policy({"APPS_REPOSITORY": str(selected)}, cwd=tmp_path, strict=strict)
    assert checked.status == ("fail" if strict else "warn")


def test_unconfigured_repository_does_not_invoke_git(monkeypatch, tmp_path):
    probe = Mock(side_effect=AssertionError("must not inspect Git"))
    monkeypatch.setattr(policy, "_verified_git_state", probe)
    checked = policy.evaluate_apps_repository_policy({}, cwd=tmp_path, strict=True)
    assert checked.status == "pass"
    assert checked.details["path"] is None


def test_allowlist_file_and_environment_are_exact_deduplicated_urls(tmp_path):
    path = tmp_path / "reviewed-origins.txt"
    path.write_text("# reviewed only\n" + ORIGIN + "; https://example.invalid/second.git\n\n")
    configured = {policy.APPS_ALLOWLIST_ENV: ORIGIN + ", https://example.invalid/third.git",
                  policy.APPS_ALLOWLIST_FILE_ENV: "'reviewed-origins.txt'"}
    assert policy.apps_repository_allowlist(configured, cwd=tmp_path) == sorted([
        ORIGIN, "https://example.invalid/second.git", "https://example.invalid/third.git"])


def test_policy_report_redacts_origin_credentials(monkeypatch, tmp_path):
    origin = "https://synthetic-user:synthetic-secret@example.invalid/apps.git"
    monkeypatch.setattr(policy, "_verified_git_state", lambda _: ({
        "is_git_checkout": True, "git_verified": True, "head_state": "detached", "worktree_clean": True}, origin))
    checked = policy.evaluate_apps_repository_policy({"APPS_REPOSITORY": str(tmp_path)}, cwd=tmp_path)
    text = json.dumps(checked.as_dict())
    assert "synthetic-user" not in text
    assert "synthetic-secret" not in text
    assert checked.details["origin_url"] == "https://<redacted>@example.invalid/apps.git"


@pytest.mark.parametrize("json_mode,status,exit_code", [(True, "fail", 1), (False, "fail", 1), (False, "warn", 0), (False, "pass", 0)])
def test_policy_cli_status_stream_and_exit_code(monkeypatch, capsys, json_mode, status, exit_code):
    checked = policy.AppsRepositoryPolicyResult(status, "repository decision", "required next action", {})
    evaluate = Mock(return_value=checked)
    monkeypatch.setattr(policy, "evaluate_apps_repository_policy", evaluate)
    assert policy.main(["--repository", "selected-apps", *(["--json"] if json_mode else [])]) == exit_code
    output = capsys.readouterr()
    if json_mode:
        assert json.loads(output.out)["status"] == status
        assert not output.err
    elif status == "fail":
        assert "Error: repository decision" in output.err
        assert "required next action" in output.err
        assert not output.out
    else:
        assert "repository decision" in output.out
        assert not output.err
    assert evaluate.call_args.args[0]["APPS_REPOSITORY"] == "selected-apps"


@pytest.mark.parametrize("head,state", [("ref: refs/heads/topic", "branch"), ("ref: refs/tags/v1", "ref"),
                                      (SHA, "detached"), ("corrupt head", "unknown"), (None, "unknown")])
def test_linked_worktree_reads_common_config_but_own_head(tmp_path, head, state):
    repo = tmp_path / "checkout"
    private = tmp_path / "common" / "worktrees" / "linked"
    repo.mkdir()
    private.mkdir(parents=True)
    (repo / ".git").write_text("gitdir: ../common/worktrees/linked\n")
    (private / "commondir").write_text("../..\n")
    (tmp_path / "common" / "config").write_text(
        '# ignored\n; ignored too\n[core]\nurl = wrong\n[remote "origin"]\nnot an assignment\nurl = ' + ORIGIN + '\n')
    if head is not None:
        (private / "HEAD").write_text(head)
    assert policy._resolve_git_dir(repo) == private
    assert policy._git_origin_url(repo) == ORIGIN
    actual = policy._git_head_state(repo)
    assert actual["head_state"] == state
    if state == "detached":
        assert actual["commit"] == SHA
    elif state in ("branch", "ref"):
        assert actual["name"] == ("topic" if state == "branch" else "v1")


@pytest.mark.parametrize("metadata", ["absent", "invalid_file", "directory"])
def test_missing_or_invalid_git_metadata_does_not_invent_origin(tmp_path, metadata):
    if metadata == "invalid_file":
        (tmp_path / ".git").write_text("not a gitdir pointer")
    elif metadata == "directory":
        (tmp_path / ".git").mkdir()
    assert policy._git_origin_url(tmp_path) is None
    if metadata != "directory":
        assert policy._git_head_state(tmp_path) == {"is_git_checkout": False}


def test_absent_config_key_and_common_directory_fallback(tmp_path):
    git = tmp_path / ".git"
    git.mkdir()
    (git / "config").write_text('[remote "upstream"]\nurl = ' + ORIGIN + '\n')
    assert policy._git_common_dir(git) == git
    assert policy._git_origin_url(tmp_path) is None


@pytest.mark.parametrize("key", ["AGILAB_SHARED_MODE", "AGILAB_STRICT_APPS_REPOSITORY"])
def test_shared_policy_config_enables_strict_mode(tmp_path, key):
    checked = policy.evaluate_apps_repository_policy({"APPS_REPOSITORY": str(tmp_path / "missing"), key: "enabled"}, cwd=tmp_path)
    assert checked.status == "fail"
    assert checked.details["strict"]


@pytest.mark.parametrize("key", ["AGILAB_ALLOW_FLOATING_APPS_REPOSITORY", "AGILAB_DEV_APPS_REPOSITORY"])
def test_development_config_is_explicitly_recorded(tmp_path, key):
    checked = policy.evaluate_apps_repository_policy({key: "yes"}, cwd=tmp_path)
    assert checked.details["allow_floating"]
