"""Temporary-filesystem regressions for worker lease release failures."""

import json
from pathlib import Path

import pytest

from agi_node.agi_dispatcher import cli


@pytest.fixture
def lease(tmp_path):
    target = tmp_path / "wenv" / "worker"
    target.mkdir(parents=True)
    token = "a" * 32
    assert cli.acquire_remote_target_lease(target, token, "install")
    lock = cli._remote_target_lease_path(target)
    return target, token, lock


@pytest.mark.parametrize("token", ["", "a" * 31, "x" * 32])
def test_release_rejects_invalid_tokens_without_mutation(lease, token):
    target, _, lock = lease
    before = {p.name: p.read_bytes() for p in lock.iterdir()}
    assert cli.release_remote_target_lease(target, token) is False
    assert {p.name: p.read_bytes() for p in lock.iterdir()} == before


def test_release_of_absent_generation_is_idempotent(tmp_path):
    assert cli.release_remote_target_lease(tmp_path / "missing", "a" * 32) is True


@pytest.mark.parametrize("failure_point", ["marker", "generation", "quarantine"])
def test_release_io_failure_preserves_owner_and_can_be_retried(
    lease, monkeypatch, failure_point
):
    target, token, lock = lease
    marker = cli._remote_target_lease_marker(lock, token)
    original_rename = Path.rename
    original_open = Path.open

    def rename(path, destination):
        if (failure_point == "marker" and path == marker) or (
            failure_point == "quarantine" and path == lock
        ):
            raise PermissionError("injected lease publication failure")
        return original_rename(path, destination)

    def open_file(path, *args, **kwargs):
        if failure_point == "generation" and path.name == f"release-generation-{token}":
            raise PermissionError("injected lease persistence failure")
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", rename)
        patch.setattr(Path, "open", open_file)
        assert cli.release_remote_target_lease(target, token) is False
    assert lock.exists()
    assert cli._read_remote_target_lease(target)["token"] == token
    assert marker.exists()
    assert cli.acquire_remote_target_lease(target, "b" * 32, "run") is False
    assert cli.release_remote_target_lease(target, token) is True
    assert cli.acquire_remote_target_lease(target, "b" * 32, "run") is True


def test_missing_generation_evidence_cannot_authorize_release(lease):
    target, token, lock = lease
    cli._remote_target_lease_marker(lock, token).unlink()
    (lock / "owner.json").unlink()
    assert cli.release_remote_target_lease(target, token) is False
    assert lock.exists()


@pytest.mark.parametrize("historical_owner", [False, True])
def test_invalid_schema_restores_claimed_generation(lease, historical_owner):
    target, token, lock = lease
    marker = cli._remote_target_lease_marker(lock, token)
    owner = json.loads((lock / "owner.json").read_text())
    owner["schema"] = "unsupported"
    (lock / "owner.json").write_text(json.dumps(owner))
    if historical_owner:
        marker.unlink()
    assert cli.release_remote_target_lease(target, token) is False
    assert lock.exists()
    assert json.loads((lock / "owner.json").read_text()) == owner
    if not historical_owner:
        assert marker.exists()


def test_conflicting_release_owner_claim_is_preserved(lease):
    target, token, lock = lease
    cli._remote_target_lease_marker(lock, token).unlink()
    claim = lock.parent / f".{lock.name}.release-owner-claim-{token}-conflict"
    claim.write_bytes((lock / "owner.json").read_bytes())
    assert cli.release_remote_target_lease(target, token) is False
    assert claim.exists() and (lock / "owner.json").exists()


def test_historical_owner_rename_failure_is_retryable(lease, monkeypatch):
    target, token, lock = lease
    cli._remote_target_lease_marker(lock, token).unlink()
    rename = Path.rename

    def fail_owner(path, destination):
        if path == lock / "owner.json":
            raise PermissionError("injected owner claim failure")
        return rename(path, destination)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", fail_owner)
        assert cli.release_remote_target_lease(target, token) is False
    assert cli._read_remote_target_lease(target)["token"] == token
    assert cli.release_remote_target_lease(target, token) is True
