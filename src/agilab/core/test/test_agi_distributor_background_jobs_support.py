from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_cluster.agi_distributor import background_jobs_support, runtime_distribution_support


def test_background_process_manager_tracks_running_completed_and_dead_jobs(monkeypatch, tmp_path):
    popen_calls: list[dict[str, object]] = []

    class FakeProcess:
        def __init__(self, status):
            self._status = status

        def poll(self):
            return self._status

    processes = [FakeProcess(None), FakeProcess(0), FakeProcess(3)]

    def fake_popen(cmd, shell, cwd, start_new_session):
        popen_calls.append(
            {
                "cmd": cmd,
                "shell": shell,
                "cwd": cwd,
                "start_new_session": start_new_session,
            }
        )
        return processes.pop(0)

    monkeypatch.setattr(background_jobs_support.subprocess, "Popen", fake_popen)

    manager = background_jobs_support.BackgroundProcessManager()
    running = manager.new("echo running", cwd=tmp_path)
    completed = manager.new("echo completed", cwd=tmp_path)
    dead = manager.new("echo dead", cwd=tmp_path / "missing")

    assert running.num == 0
    assert completed.num == 1
    assert dead.num == 2
    assert popen_calls[0]["cwd"] == str(tmp_path)
    assert popen_calls[2]["cwd"] is None
    assert manager.result(running.num) is running.process
    assert manager.result(completed.num) is completed.process
    assert manager.result(dead.num) is None
    assert completed in manager.completed
    assert dead in manager.dead

    manager.flush()

    assert completed.num not in manager.all
    assert dead.num not in manager.all
    assert running.num in manager.all
    assert manager.completed == []
    assert manager.dead == []


def test_background_process_manager_normalize_cwd_handles_invalid_values():
    manager = background_jobs_support.BackgroundProcessManager()

    assert manager._normalize_cwd(None) is None
    assert manager._normalize_cwd("") is None
    assert manager._normalize_cwd(Path("/definitely/missing/path")) is None

    class BrokenPath:
        def __fspath__(self):
            raise RuntimeError("boom")

    assert manager._normalize_cwd(BrokenPath()) is None


def test_background_process_manager_normalize_cwd_propagates_unexpected_value_error():
    manager = background_jobs_support.BackgroundProcessManager()

    class BrokenPath:
        def __fspath__(self):
            raise ValueError("unexpected path bug")

    with pytest.raises(ValueError, match="unexpected path bug"):
        manager._normalize_cwd(BrokenPath())


def test_background_process_manager_result_returns_none_for_unknown_job():
    manager = background_jobs_support.BackgroundProcessManager()

    assert manager.result(42) is None


def test_background_job_manager_uses_subprocess_and_real_directories_only(monkeypatch, tmp_path):
    calls = []

    class _Proc:
        def poll(self):
            return None

    def _fake_popen(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return _Proc()

    monkeypatch.setattr(background_jobs_support.subprocess, "Popen", _fake_popen)
    jobs = background_jobs_support.bg.BackgroundJobManager()

    missing_cwd = tmp_path / "missing-cwd"

    first = jobs.new("echo test", cwd=missing_cwd)
    second = jobs.new("echo test 2", cwd=tmp_path)

    assert first.num == 0
    assert second.num == 1
    assert calls[0][0] == "echo test"
    assert calls[0][1]["shell"] is True
    assert calls[0][1]["cwd"] is None
    assert calls[0][1]["start_new_session"] is True
    assert calls[1][1]["cwd"] == str(tmp_path)
    assert jobs.result(second.num) is second.result


def test_exec_bg_raises_when_background_job_fails():
    class _Jobs:
        def __init__(self):
            self.new_calls = []

        def new(self, cmd, cwd=None):
            self.new_calls.append((cmd, cwd))

        def result(self, _index):
            return False

    agi = SimpleNamespace(_jobs=_Jobs())
    with pytest.raises(RuntimeError, match="running echo test"):
        runtime_distribution_support.exec_bg(agi, "echo test", "/tmp")


def test_exec_bg_uses_launched_job_id():
    seen = {}

    class _Job:
        def __init__(self, num):
            self.num = num

    class _Jobs:
        def new(self, cmd, cwd=None):
            seen["new"] = (cmd, cwd)
            return _Job(7)

        def result(self, index):
            seen["result"] = index
            return True

    agi = SimpleNamespace(_jobs=_Jobs())
    runtime_distribution_support.exec_bg(agi, "echo test", "/tmp")

    assert seen["new"] == ("echo test", "/tmp")
    assert seen["result"] == 7
