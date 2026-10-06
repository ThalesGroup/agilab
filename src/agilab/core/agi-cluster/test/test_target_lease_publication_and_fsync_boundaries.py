"""Lease I/O failures preserve authority and leave no unpublished claims."""

import errno
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from agi_cluster.agi_distributor.runtime import lifecycle_guard_support as guard


def acquire(env, operation="install"):
    return guard.acquire_target_lease(
        env,
        operation,
        getpid_fn=lambda: 4242,
        process_factory=lambda _pid: SimpleNamespace(create_time=lambda: 100.0),
        time_fn=lambda: 200.0,
    )


@pytest.mark.parametrize("failure_phase", ["open", "fsync", "success"])
def test_directory_fsync_closes_only_an_opened_descriptor(monkeypatch, tmp_path, failure_phase):
    operations = SimpleNamespace(
        O_RDONLY=0,
        open=Mock(return_value=42),
        fsync=Mock(),
        close=Mock(),
    )
    if failure_phase == "open":
        operations.open.side_effect = PermissionError("directory unreadable")
    elif failure_phase == "fsync":
        operations.fsync.side_effect = OSError("directory fsync unavailable")
    monkeypatch.setattr(guard, "os", operations)

    guard._fsync_directory(tmp_path)

    operations.open.assert_called_once_with(tmp_path, operations.O_RDONLY)
    if failure_phase == "open":
        operations.fsync.assert_not_called()
        operations.close.assert_not_called()
    else:
        operations.fsync.assert_called_once_with(42)
        operations.close.assert_called_once_with(42)


def test_failed_initial_publication_removes_staging_and_propagates_same_io_error(
    monkeypatch, tmp_path
):
    env = SimpleNamespace(wenv_abs=tmp_path / "runtime" / "demo")
    lock = guard.target_lease_path(env)
    original_rename = Path.rename
    failure = PermissionError(errno.EACCES, "lease publication denied")

    def deny_publication(source, destination):
        if destination == lock and ".claim-" in source.name:
            raise failure
        return original_rename(source, destination)

    monkeypatch.setattr(Path, "rename", deny_publication)
    with pytest.raises(PermissionError) as raised:
        acquire(env)
    assert raised.value is failure
    assert not lock.exists()
    assert list(lock.parent.iterdir()) == []


def test_publication_io_collision_recovers_only_the_stale_owner_and_retries(
    monkeypatch, tmp_path
):
    env = SimpleNamespace(wenv_abs=tmp_path / "runtime" / "demo")
    stale = acquire(env, "stale")
    original_rename = Path.rename
    attempts = []

    def fail_first_publication(source, destination):
        if destination == stale.path and ".claim-" in source.name:
            attempts.append(source)
            if len(attempts) == 1:
                raise OSError(errno.EBUSY, "competing filesystem rename")
        return original_rename(source, destination)

    def process_factory(pid):
        if pid == 4242:
            raise psutil.NoSuchProcess(pid)
        return SimpleNamespace(create_time=lambda: 300.0)

    monkeypatch.setattr(Path, "rename", fail_first_publication)
    lease = guard.acquire_target_lease(
        env, "retry", getpid_fn=lambda: 4343, process_factory=process_factory,
    )
    assert len(attempts) == 2
    assert lease.token != stale.token
    owner = json.loads((lease.path / "owner.json").read_text(encoding="utf-8"))
    assert owner["token"] == lease.token
    assert owner["pid"] == 4343
    assert stale.remote_token in lease.recovered_remote_tokens
    assert guard._target_release_tombstone(stale.path, stale.token).is_dir()
    assert not any(".claim-" in path.name for path in lease.path.parent.iterdir())
    assert guard.release_target_lease(lease) is True


def test_bounded_publication_contention_retires_each_stale_generation_without_claim_leaks(
    monkeypatch, tmp_path
):
    env = SimpleNamespace(wenv_abs=tmp_path / "runtime" / "demo")
    lock = guard.target_lease_path(env)
    original_rename = Path.rename
    generations = []

    def competing_publication(source, destination):
        if destination == lock and ".claim-" in source.name:
            owner = json.loads((source / "owner.json").read_text(encoding="utf-8"))
            owner["pid"] = 9999
            owner["operation"] = "competitor"
            lock.mkdir()
            (lock / f"token-{owner['token']}").mkdir()
            (lock / "owner.json").write_text(json.dumps(owner), encoding="utf-8")
            generations.append(owner["token"])
            raise FileExistsError(errno.EEXIST, "competing stale owner")
        return original_rename(source, destination)

    def process_factory(pid):
        if pid == 9999:
            raise psutil.NoSuchProcess(pid)
        return SimpleNamespace(create_time=lambda: 100.0)

    monkeypatch.setattr(Path, "rename", competing_publication)
    with pytest.raises(guard.LifecycleBusyError, match="install"):
        guard.acquire_target_lease(
            env, "install", getpid_fn=lambda: 4242, process_factory=process_factory,
        )
    assert len(generations) == 3
    assert len(set(generations)) == 3
    assert not lock.exists()
    assert {path.name for path in lock.parent.iterdir()} == {
        guard._target_release_tombstone(lock, token).name for token in generations
    }
    for token in generations:
        owner = guard._read_owner(guard._target_release_tombstone(lock, token))
        assert owner["token"] == token
        assert owner["pid"] == 9999


def test_unproven_release_keeps_owner_and_marker_then_a_retry_releases_them(
    monkeypatch, tmp_path
):
    env = SimpleNamespace(wenv_abs=tmp_path / "runtime" / "demo")
    lease = acquire(env)
    owner_bytes = (lease.path / "owner.json").read_bytes()
    marker = lease.path / f"token-{lease.token}"
    original_rename = Path.rename

    def deny_release(source, destination):
        if source == marker:
            raise PermissionError(errno.EACCES, "release marker unavailable")
        return original_rename(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", deny_release)
        assert guard.release_target_lease(lease) is False
    assert guard._target_lease_still_owned(lease) is True
    assert (lease.path / "owner.json").read_bytes() == owner_bytes
    assert marker.is_dir()
    assert guard.release_target_lease(lease) is True
    assert not lease.path.exists()
    assert guard._target_release_tombstone(lease.path, lease.token).is_dir()


def test_sync_caller_identity_supports_threads_without_an_asyncio_event_loop():
    assert guard._caller_identity() == (threading.get_ident(), None)
