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


@pytest.mark.parametrize(
    "replacement,authorized",
    [
        ("invalid", ["a" * 32]),
        ("b" * 32, []),
        ("b" * 32, ["invalid"]),
        ("b" * 32, ["a" * 32, "a" * 32]),
        ("a" * 32, ["a" * 32]),
        ("b" * 32, ["c" * 32]),
    ],
)
def test_recovery_requires_distinct_exact_generation_authority(
    lease, replacement, authorized
):
    target, token, lock = lease
    before = {p.name: p.read_bytes() for p in lock.iterdir()}
    assert cli.recover_remote_target_lease(target, replacement, authorized) is False
    assert {p.name: p.read_bytes() for p in lock.iterdir()} == before
    assert cli.remote_target_lease_owned(target, token)


def test_recovery_is_idempotent_for_already_acquired_replacement(lease):
    target, token, _ = lease
    assert cli.recover_remote_target_lease(target, token, ["b" * 32])
    assert cli.remote_target_lease_owned(target, token)


def test_recovery_cannot_acquire_after_failed_generation_release(lease, monkeypatch):
    target, token, _ = lease
    calls = []
    monkeypatch.setattr(cli, "release_remote_target_lease", lambda *args: False)
    monkeypatch.setattr(
        cli, "acquire_remote_target_lease", lambda *args: calls.append(args)
    )
    assert cli.recover_remote_target_lease(target, "b" * 32, [token]) is False
    assert calls == []
    assert cli.remote_target_lease_owned(target, token)


@pytest.mark.parametrize("stage", ["publication", "owner", "marker"])
def test_interrupted_acquire_preserves_exact_recovery_capability(
    tmp_path, monkeypatch, stage
):
    target = tmp_path / "worker"
    token = "a" * 32
    lock = cli._remote_target_lease_path(target)
    marker = cli._remote_target_lease_marker(lock, token)
    original = Path.open

    def interrupted(path, *args, **kwargs):
        selected = (
            (stage == "publication" and ".acquire-claim-" in path.name)
            or (stage == "owner" and path.name.startswith(".owner."))
            or (stage == "marker" and path == marker)
        )
        if selected:
            raise PermissionError("injected acquire interruption")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", interrupted)
        assert cli.acquire_remote_target_lease(target, token, "install") is False

    if stage == "publication":
        assert not lock.exists()
        assert not cli._acquire_publication_claims(lock, token)
        assert cli.acquire_remote_target_lease(target, token, "install")
    else:
        assert lock.exists()
        assert cli._acquire_publication_claims(lock, token)
        assert cli.recover_remote_target_lease(target, "b" * 32, ["c" * 32]) is False
        assert cli.recover_remote_target_lease(target, "b" * 32, [token]) is True
        assert cli.remote_target_lease_owned(target, "b" * 32)


@pytest.mark.parametrize("claim_kind", ["owner", "publication"])
@pytest.mark.parametrize("action", ["release", "recover"])
def test_interrupted_claim_resumption_keeps_exact_generation_authority(
    lease, claim_kind, action
):
    target, token, lock = lease
    cli._remote_target_lease_marker(lock, token).unlink()
    prefix = "release-owner-claim" if claim_kind == "owner" else "acquire-claim"
    claim = lock.parent / f".{lock.name}.{prefix}-{token}-interrupted"
    (lock / "owner.json").rename(claim)
    assert cli.recover_remote_target_lease(target, "b" * 32, ["c" * 32]) is False
    assert claim.exists()
    if action == "recover":
        assert cli.recover_remote_target_lease(target, "b" * 32, [token])
        assert cli.remote_target_lease_owned(target, "b" * 32)
    else:
        assert cli.release_remote_target_lease(target, token)
        assert not lock.exists()
    assert not claim.exists()


@pytest.mark.parametrize("failure_point", ["generation", "quarantine"])
def test_historical_owner_claim_is_restored_after_io_failure(
    lease, monkeypatch, failure_point
):
    target, token, lock = lease
    cli._remote_target_lease_marker(lock, token).unlink()
    original_open, original_rename = Path.open, Path.rename

    def open_file(path, *args, **kwargs):
        if failure_point == "generation" and path.name == f"release-generation-{token}":
            raise PermissionError("generation unavailable")
        return original_open(path, *args, **kwargs)

    def rename(path, dest):
        if failure_point == "quarantine" and path == lock:
            raise PermissionError("quarantine unavailable")
        return original_rename(path, dest)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", open_file)
        patch.setattr(Path, "rename", rename)
        assert cli.release_remote_target_lease(target, token) is False
    if failure_point == "generation":
        assert cli._read_remote_target_lease(target)["token"] == token
    else:
        claims = cli._release_owner_claims(lock, token)
        assert len(claims) == 1
        assert cli._read_json_file(claims[0])["token"] == token
    assert cli.release_remote_target_lease(target, token)


def test_existing_tombstone_cannot_authorize_removing_same_generation_again(lease):
    target, token, lock = lease
    tombstone = cli._remote_release_tombstone(lock, token)
    tombstone.mkdir()
    (tombstone / "keep").write_text("first release retained")
    assert cli.release_remote_target_lease(target, token) is False
    assert lock.exists()
    assert cli._read_remote_target_lease(target)["token"] == token
    assert (tombstone / "keep").read_text() == "first release retained"


@pytest.mark.parametrize("error", [FileNotFoundError, PermissionError])
def test_release_racing_successor_never_removes_new_owner(lease, monkeypatch, error):
    target, token, lock = lease
    original_rename = Path.rename
    tombstone = cli._remote_release_tombstone(lock, token)
    successor = "b" * 32

    def rename(path, destination):
        if path == lock:
            original_rename(path, tombstone)
            assert cli.acquire_remote_target_lease(target, successor, "run")
            raise error("another releaser completed the transition")
        return original_rename(path, destination)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", rename)
        assert cli.release_remote_target_lease(target, token) is True
    assert cli.remote_target_lease_owned(target, successor)
    before = {p.name: p.read_bytes() for p in lock.iterdir()}
    assert cli.release_remote_target_lease(target, token) is True
    assert {p.name: p.read_bytes() for p in lock.iterdir()} == before


def test_recovery_loses_to_competing_acquire_without_removing_successor(
    lease, monkeypatch
):
    target, token, lock = lease
    original_release = cli.release_remote_target_lease

    def release(target, generation):
        result = original_release(target, generation)
        assert cli.acquire_remote_target_lease(target, "c" * 32, "competing manager")
        return result

    monkeypatch.setattr(cli, "release_remote_target_lease", release)
    assert cli.recover_remote_target_lease(target, "b" * 32, [token]) is False
    assert cli.remote_target_lease_owned(target, "c" * 32)


@pytest.mark.parametrize("payload", ["[]", "null", '"text"', "broken"])
def test_malformed_claims_do_not_authorize_release(lease, payload):
    target, token, lock = lease
    cli._remote_target_lease_marker(lock, token).unlink()
    (lock / "owner.json").unlink()
    for prefix in ("release-owner-claim", "acquire-claim"):
        claim = lock.parent / f".{lock.name}.{prefix}-{token}-bad"
        claim.write_text(payload)
    assert cli.release_remote_target_lease(target, token) is False
    assert cli.recover_remote_target_lease(target, "b" * 32, [token]) is False
    assert lock.exists()


def test_recovery_of_absent_lock_acquires_new_generation(tmp_path):
    target = tmp_path / "worker"
    assert cli.recover_remote_target_lease(target, "b" * 32, ["a" * 32])
    assert cli.remote_target_lease_owned(target, "b" * 32)
