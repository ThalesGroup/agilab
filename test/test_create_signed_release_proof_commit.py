from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from tools.release_proof import create_signed_release_proof_commit as signing
from tools.release_proof import validate_release_proof_signing as validation


REPOSITORY = "ThalesGroup/agilab"
BRANCH = "automation/release-evidence-signing-test"
OID = "b" * 40


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "checkout"
    root.mkdir()

    def git(*args):
        return subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "user.name=Release Test Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "-c",
                "commit.gpgsign=false",
                *args,
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    git("init", "--initial-branch", "main")
    for name in (*signing.RELEASE_METADATA_PATHS, "source.py"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "fixture baseline")
    head = git("rev-parse", "HEAD")
    return root, head


class GitHub:
    def __init__(self, head):
        self.head = head
        self.calls = []
        self.commit = None
        self.deleted = False
        self.author = "github-actions[bot]"
        self.corruption = None
        self.move_after_probe = False
        self.probed = False
        self.stale_error_type = "STALE_DATA"
        self.accept_stale = False

    def __call__(self, endpoint, payload=None, *, method=None):
        self.calls.append((endpoint, copy.deepcopy(payload), method))
        if endpoint.endswith("/git/refs"):
            assert payload["sha"] == self.head
            return {"object": {"sha": self.head}}
        if endpoint == "graphql":
            data = payload["variables"]["input"]
            if data["expectedHeadOid"] != self.head:
                self.probed = True
                if self.accept_stale:
                    self.head = "c" * 40
                    return {
                        "data": {"createCommitOnBranch": {"commit": {"oid": self.head}}}
                    }
                raise signing.GitHubGraphQLError(
                    endpoint, [{"type": self.stale_error_type}]
                )
            self.commit = {
                "sha": OID,
                "parents": [{"sha": self.head}],
                "author": {"login": self.author},
                "commit": {"verification": {"verified": True, "reason": "valid"}},
                "files": [],
            }
            for item in data["fileChanges"]["additions"]:
                body = base64.b64decode(item["contents"])
                blob = hashlib.sha1(
                    b"blob " + str(len(body)).encode() + b"\0" + body
                ).hexdigest()
                self.commit["files"].append({"filename": item["path"], "sha": blob})
            self.head = OID
            return {
                "data": {
                    "createCommitOnBranch": {
                        "commit": {"oid": OID},
                        "ref": {"target": {"oid": OID}},
                    }
                }
            }
        if "/commits/" in endpoint:
            commit = copy.deepcopy(self.commit)
            if self.corruption == "unsigned":
                commit["commit"]["verification"] = {
                    "verified": False,
                    "reason": "unsigned",
                }
            elif self.corruption == "blob":
                commit["files"][0]["sha"] = "c" * 40
            elif self.corruption == "parent":
                commit["parents"] = [{"sha": "c" * 40}]
            return commit
        if "/git/ref/heads/" in endpoint:
            return {
                "object": {
                    "sha": "c" * 40
                    if self.probed and self.move_after_probe
                    else self.head
                }
            }
        if "/git/refs/heads/" in endpoint and method == "DELETE":
            self.deleted = True
            return {}
        raise AssertionError((endpoint, payload, method))


def test_signing_uses_cas_and_exact_changed_metadata_blobs(checkout, monkeypatch):
    root, head = checkout
    (root / "CHANGELOG.md").write_text("new evidence\n", encoding="utf-8")
    github = GitHub(head)
    monkeypatch.setattr(signing, "_github_api", github)

    result = signing.create_signed_commit(root, REPOSITORY, BRANCH, head)

    assert result["verified"] is True
    assert result["commit"] == OID
    assert result["parent"] == head
    assert result["files"] == ["CHANGELOG.md"]
    data = github.calls[1][1]["variables"]["input"]
    assert data["expectedHeadOid"] == head
    assert data["branch"] == {
        "repositoryNameWithOwner": REPOSITORY,
        "branchName": BRANCH,
    }
    assert data["fileChanges"]["additions"] == [
        {
            "path": "CHANGELOG.md",
            "contents": base64.b64encode(b"new evidence\n").decode(),
        }
    ]
    assert "author" not in data and "committer" not in data
    assert signing._git(root, "rev-parse", "HEAD").strip() == head


@pytest.mark.parametrize("corruption", ["unsigned", "blob", "parent"])
def test_unverified_or_changed_server_commit_never_produces_success_output(
    checkout, monkeypatch, corruption
):
    root, head = checkout
    (root / "CHANGELOG.md").write_text("new evidence\n", encoding="utf-8")
    github = GitHub(head)
    github.corruption = corruption
    monkeypatch.setattr(signing, "_github_api", github)
    output = root / "github-output.txt"

    assert (
        signing.main(
            [
                "--root",
                str(root),
                "--repository",
                REPOSITORY,
                "--branch",
                BRANCH,
                "--expected-head",
                head,
                "--github-output",
                str(output),
            ]
        )
        == 1
    )
    assert not output.exists()


@pytest.mark.parametrize(
    "problem", ["outside-scope", "deleted", "executable", "symlink", "wrong-head"]
)
def test_source_guard_fails_before_creating_any_remote_branch(
    checkout, monkeypatch, problem
):
    root, head = checkout
    path = root / "CHANGELOG.md"
    path.write_text("new evidence\n", encoding="utf-8")
    if problem == "outside-scope":
        (root / "source.py").write_text("source modification\n", encoding="utf-8")
    elif problem == "deleted":
        path.unlink()
    elif problem == "executable":
        path.chmod(0o755)
    elif problem == "symlink":
        path.unlink()
        path.symlink_to(root / "source.py")
    elif problem == "wrong-head":
        head = "a" * 40
    github = GitHub(head)
    monkeypatch.setattr(signing, "_github_api", github)

    with pytest.raises(ValueError):
        signing.create_signed_commit(root, REPOSITORY, BRANCH, head)
    assert github.calls == []


@pytest.mark.parametrize(
    "branch", ["main", "refs/tags/v2026.10.07_1", "automation/release-evidence-../main"]
)
def test_signing_cannot_update_main_tags_or_an_unscoped_ref(checkout, branch):
    root, head = checkout
    with pytest.raises(ValueError, match="Only a new"):
        signing.create_signed_commit(root, REPOSITORY, branch, head)


def test_graphql_errors_are_preserved_without_echoing_cli_secrets(monkeypatch):
    monkeypatch.setattr(
        signing.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a[0], 1, json.dumps({"errors": [{"type": "STALE_DATA"}]}), "secret-token"
        ),
    )
    with pytest.raises(signing.GitHubGraphQLError) as exc:
        signing._github_api("graphql", {"query": "probe"})
    assert exc.value.errors == [{"type": "STALE_DATA"}]
    assert "secret-token" not in str(exc.value)


@pytest.mark.parametrize(
    "method,payload,response",
    [
        (None, None, '{"object":{"sha":"abc"}}'),
        (None, {"query": "mutation"}, '{"data":{"ok":true}}'),
        ("DELETE", None, ""),
    ],
)
def test_github_transport_keeps_payload_on_stdin_and_accepts_empty_delete(
    monkeypatch, method, payload, response
):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, response, "")

    monkeypatch.setattr(signing.subprocess, "run", run)
    result = signing._github_api("fixture-endpoint", payload, method=method)
    assert result == (json.loads(response) if response else {})
    argv, kwargs = calls[0]
    assert kwargs["input"] == (json.dumps(payload) if payload is not None else None)
    assert not any("mutation" in value for value in argv)
    if payload:
        assert argv[-4:] == ["--method", "POST", "--input", "-"]
    elif method:
        assert argv[-2:] == ["--method", method]


@pytest.mark.parametrize("code,stdout", [(1, ""), (0, "not-json")])
def test_github_transport_fails_closed_without_echoing_credentials(
    monkeypatch, code, stdout
):
    monkeypatch.setattr(
        signing.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], code, stdout, "secret-token"),
    )
    with pytest.raises(RuntimeError) as exc:
        signing._github_api("fixture-endpoint")
    assert "secret-token" not in str(exc.value)


def test_signing_cli_emits_verified_commit_only_after_all_checks(checkout, monkeypatch):
    root, head = checkout
    (root / "CHANGELOG.md").write_text("new evidence\n", encoding="utf-8")
    monkeypatch.setattr(signing, "_github_api", GitHub(head))
    output = root / "github-output.txt"
    assert (
        signing.main(
            [
                "--root",
                str(root),
                "--repository",
                REPOSITORY,
                "--branch",
                BRANCH,
                "--expected-head",
                head,
                "--github-output",
                str(output),
            ]
        )
        == 0
    )
    assert output.read_text() == f"release_commit={OID}\n"


def test_bot_validation_proves_stale_cas_and_cleans_only_the_owned_branch(
    checkout, monkeypatch
):
    root, head = checkout
    original = (root / "CHANGELOG.md").read_bytes()
    github = GitHub(head)
    monkeypatch.setattr(signing, "_github_api", github)

    result = validation.validate_signing(root, REPOSITORY, head, "123", "2")

    assert result["status"] == "pass"
    assert result["github_author"] == "github-actions[bot]"
    assert result["stale_head_rejected"] is True
    assert result["head_after_stale_probe"] == OID
    assert github.deleted is True
    assert github.calls[-2][0].endswith(
        "/git/ref/heads/automation/release-evidence-signing-validation-123-2"
    )
    assert github.calls[-1] == (
        f"repos/{REPOSITORY}/git/refs/heads/automation/release-evidence-signing-validation-123-2",
        None,
        "DELETE",
    )
    assert (root / "CHANGELOG.md").read_bytes() == original


@pytest.mark.parametrize(
    "problem", ["personal-token", "branch-moved", "wrong-error", "accepted-stale"]
)
def test_bot_validation_rejects_wrong_actor_or_changed_cleanup_target(
    checkout, monkeypatch, problem
):
    root, head = checkout
    original = (root / "CHANGELOG.md").read_bytes()
    github = GitHub(head)
    github.author = "jpmorard" if problem == "personal-token" else "github-actions[bot]"
    github.move_after_probe = problem == "branch-moved"
    github.stale_error_type = "FORBIDDEN" if problem == "wrong-error" else "STALE_DATA"
    github.accept_stale = problem == "accepted-stale"
    monkeypatch.setattr(signing, "_github_api", github)

    result = validation.validate_signing(root, REPOSITORY, head, "123", "2")

    assert result["status"] == "fail"
    assert github.deleted is False
    assert (root / "CHANGELOG.md").read_bytes() == original


def test_validation_cli_preserves_failed_receipt_and_original_fixture(
    checkout, monkeypatch
):
    root, head = checkout
    github = GitHub(head)
    github.author = "jpmorard"
    monkeypatch.setattr(signing, "_github_api", github)
    output = root / "reports" / "agilab-release-proof-signing-validation.json"
    assert (
        validation.main(
            [
                "--root",
                str(root),
                "--repository",
                REPOSITORY,
                "--source",
                head,
                "--run-id",
                "123",
                "--run-attempt",
                "2",
                "--output",
                str(output),
            ]
        )
        == 1
    )
    receipt = json.loads(output.read_text())
    assert receipt["status"] == "fail"
    assert "real github-actions[bot]" in receipt["error"]
    assert github.deleted is False
    assert (root / "CHANGELOG.md").read_text() == "original\n"
