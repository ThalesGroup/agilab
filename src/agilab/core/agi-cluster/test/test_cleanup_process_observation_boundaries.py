"""Cleanup uses synthetic process handles and preserves evidence on uncertainty."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from agi_cluster.agi_distributor.runtime import cleanup_support as cleanup


@pytest.fixture
def worker_target(tmp_path):
    home = tmp_path / "home"
    target = home / "wenv" / "demo_worker"
    target.mkdir(parents=True)
    pidfile = target / "dask_worker_0.pid"
    pidfile.write_text(json.dumps({"pid": 123, "process_start_time": 20}))
    state = SimpleNamespace(env=SimpleNamespace(home_abs=home, wenv_abs=target))
    process = SimpleNamespace(
        info={"pid": 123, "username": "owner", "cmdline": ["dask", "worker", str(target)], "create_time": 20},
        kill=Mock(), wait=Mock(),
    )
    return state, target, pidfile, process


def _clean(state, processes, **kwargs):
    cleanup.clean_dirs_local(
        state, process_iter_fn=processes, getuser_fn=lambda: "owner",
        getpid_fn=lambda: 999, sleep_fn=lambda _: None, **kwargs,
    )


@pytest.mark.parametrize("error", [psutil.NoSuchProcess(123), psutil.AccessDenied(123), OSError("wait failed")])
def test_owned_process_wait_failure_only_allows_proven_exit(worker_target, error):
    state, target, pidfile, process = worker_target
    process.wait.side_effect = error
    snapshots = Mock(side_effect=[[process], []])
    if isinstance(error, psutil.NoSuchProcess):
        _clean(state, snapshots)
        assert not target.exists()
    else:
        with pytest.raises(RuntimeError, match="remain active"):
            _clean(state, snapshots)
        assert target.is_dir() and pidfile.exists()
    process.kill.assert_called_once_with()
    process.wait.assert_called_once_with(timeout=3.0)


@pytest.mark.parametrize("error", [psutil.NoSuchProcess(123), psutil.AccessDenied(123), OSError("kill denied")])
def test_owned_process_kill_error_keeps_evidence_unless_process_is_gone(worker_target, error):
    state, target, pidfile, process = worker_target
    process.kill.side_effect = error
    snapshots = Mock(side_effect=[[process], []])
    if isinstance(error, psutil.NoSuchProcess):
        _clean(state, snapshots)
        assert not target.exists()
    else:
        with pytest.raises(RuntimeError, match="remain active"):
            _clean(state, snapshots)
        assert target.is_dir() and pidfile.exists()
    process.wait.assert_not_called()


@pytest.mark.parametrize("record", ['"invalid"', "[]", '{"pid": "bad"}', '{"pid":123,"process_start_time":"bad"}'])
def test_invalid_local_pid_evidence_never_authorizes_signalling(worker_target, record):
    state, target, pidfile, process = worker_target
    pidfile.write_text(record)
    # No matching process in either current observation permits stale tree removal.
    _clean(state, lambda _: [])
    assert not target.exists()
    process.kill.assert_not_called()


def test_invalid_live_incarnation_timestamp_blocks_deletion_without_kill(worker_target):
    state, target, pidfile, process = worker_target
    process.info["create_time"] = "unknown"
    with pytest.raises(RuntimeError, match="still reference the target"):
        _clean(state, lambda _: [process])
    process.kill.assert_not_called()
    assert target.exists() and pidfile.exists()


def test_failed_deletion_that_keeps_target_restores_pid_evidence(worker_target, monkeypatch):
    state, target, pidfile, process = worker_target
    before = pidfile.read_bytes()
    def incomplete(_path, **kwargs):
        pidfile.unlink()
    monkeypatch.setattr(cleanup, "remove_dir_forcefully", incomplete)
    with pytest.raises(RuntimeError, match="PID ownership evidence was retained"):
        _clean(state, lambda _: [])
    assert target.exists()
    assert pidfile.read_bytes() == before
    process.kill.assert_not_called()


@pytest.mark.parametrize("error", [psutil.NoSuchProcess(123), psutil.AccessDenied(123)])
def test_operator_force_cleanup_continues_after_process_disappears_or_access_denied(worker_target, tmp_path, error):
    state, target, _, process = worker_target
    process.kill.side_effect = error
    remove = Mock(side_effect=OSError("directory busy"))
    cleanup.force_clean_dirs_local(
        state, process_iter_fn=lambda _: [process], getuser_fn=lambda: "owner",
        getpid_fn=lambda: 999, rmtree_fn=remove, gettempdir_fn=lambda: str(tmp_path),
    )
    process.kill.assert_called_once_with()
    assert remove.call_count == 2
    assert target.exists()


def test_untrusted_missing_home_root_refuses_process_cleanup():
    process_iter = Mock()
    state = SimpleNamespace(env=SimpleNamespace(wenv_abs="/untrusted"))
    with pytest.raises(RuntimeError, match="trusted home root"):
        _clean(state, process_iter)
    process_iter.assert_not_called()


@pytest.mark.parametrize("info", [{}, {"pid": None}, {"pid": "not-an-integer"}])
def test_process_snapshot_skips_unusable_process_identity(info):
    valid = SimpleNamespace(info={"pid": 123})
    invalid = SimpleNamespace(info=info)
    assert cleanup._process_snapshot(lambda _: [invalid, valid]) == {123: valid}


def test_command_ownership_rejects_malformed_quoted_path(tmp_path):
    assert cleanup._command_belongs_to_target(
        '"unterminated command', pid_file=None, wenv_abs=tmp_path
    ) is False


def test_different_drive_path_comparison_cannot_prove_ownership(tmp_path, monkeypatch):
    import os
    path_api = SimpleNamespace(**{name: getattr(os.path, name) for name in dir(os.path)})
    path_api.commonpath = Mock(side_effect=ValueError("different drives"))
    monkeypatch.setattr(cleanup, "os", SimpleNamespace(name=os.name, path=path_api))
    assert cleanup._command_belongs_to_target(
        [str(tmp_path / "worker")], pid_file=None, wenv_abs=tmp_path
    ) is False


def test_force_cleanup_rejects_unverifiable_scratch_root(worker_target, tmp_path, monkeypatch):
    state, target, _, _ = worker_target
    remove = Mock()
    monkeypatch.setattr(cleanup, "safe_destructive_path", Mock(side_effect=ValueError("outside safe root")))
    with pytest.raises(RuntimeError, match="Refusing unsafe Dask scratch cleanup"):
        cleanup.force_clean_dirs_local(
            state, process_iter_fn=lambda _: [], getuser_fn=lambda: "owner",
            getpid_fn=lambda: 999, rmtree_fn=remove, gettempdir_fn=lambda: str(tmp_path),
        )
    remove.assert_not_called()
    assert target.exists()
