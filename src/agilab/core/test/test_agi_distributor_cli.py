import json
import os
import runpy
import shutil
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
import signal
from types import SimpleNamespace

import pytest

from agi_cluster.agi_distributor import cli as cli_mod


def test_bootstrap_cli_runs_before_new_agi_env_is_installed(tmp_path):
    legacy_root = tmp_path / "legacy-site"
    legacy_agi_env = legacy_root / "agi_env"
    legacy_agi_env.mkdir(parents=True)
    (legacy_agi_env / "__init__.py").write_text("", encoding="utf-8")
    (legacy_agi_env / "data_archive_support.py").write_text(
        "def validate_archive_members_stay_within_dest(*args, **kwargs):\n"
        "    return None\n",
        encoding="utf-8",
    )
    bootstrap_cli = tmp_path / "worker-cli.py"
    shutil.copy2(Path(cli_mod.__file__), bootstrap_cli)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(legacy_root)

    completed = subprocess.run(
        [sys.executable, str(bootstrap_cli), "platform"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr


def test_get_processes_containing_parses_unix_ps(monkeypatch):
    output = "\n".join(
        [
            "101 python dask scheduler",
            "202 python other.py",
            "303 python DASK worker",
        ]
    )
    monkeypatch.setattr(cli_mod.os, "name", "posix", raising=False)
    monkeypatch.setattr(cli_mod.subprocess, "check_output", lambda *args, **kwargs: output)
    pids = cli_mod.get_processes_containing("dask")
    assert pids == {101, 303}


def test_get_processes_containing_parses_windows_tasklist(monkeypatch):
    output = "\n".join(
        [
            '"dask-scheduler.exe","111","Console","1","10,000 K"',
            '"python.exe","222","Console","1","10,000 K"',
            '"DASK-worker.exe","333","Console","1","10,000 K"',
        ]
    )
    monkeypatch.setattr(cli_mod.os, "name", "nt", raising=False)
    monkeypatch.setattr(cli_mod.subprocess, "check_output", lambda *args, **kwargs: output)
    assert cli_mod.get_processes_containing("dask") == {111, 333}


def test_get_processes_containing_returns_empty_on_failure(monkeypatch):
    monkeypatch.setattr(cli_mod.os, "name", "posix", raising=False)
    monkeypatch.setattr(
        cli_mod.subprocess,
        "check_output",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("ps failed")),
    )
    assert cli_mod.get_processes_containing("dask") == set()


def test_get_processes_containing_skips_malformed_unix_lines(monkeypatch):
    output = "\n".join(["101 python dask scheduler", "malformed-line", "202 python other"])
    monkeypatch.setattr(cli_mod.os, "name", "posix", raising=False)
    monkeypatch.setattr(cli_mod.subprocess, "check_output", lambda *args, **kwargs: output)
    assert cli_mod.get_processes_containing("dask") == {101}


def test_get_processes_containing_skips_bad_windows_pid(monkeypatch):
    output = '"dask-scheduler.exe","not-int","Console","1","10,000 K"'
    monkeypatch.setattr(cli_mod.os, "name", "nt", raising=False)
    monkeypatch.setattr(cli_mod.subprocess, "check_output", lambda *args, **kwargs: output)
    assert cli_mod.get_processes_containing("dask") == set()


def test_get_processes_containing_handles_windows_tasklist_failure(monkeypatch):
    warnings = []
    monkeypatch.setattr(cli_mod.os, "name", "nt", raising=False)
    monkeypatch.setattr(
        cli_mod.subprocess,
        "check_output",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("tasklist failed")),
    )
    monkeypatch.setattr(cli_mod.logger, "warning", lambda message: warnings.append(str(message)))

    assert cli_mod.get_processes_containing("dask") == set()
    assert any("Windows tasklist failed" in message for message in warnings)


def test_get_child_pids_parses_ppid_map(monkeypatch):
    output = "\n".join(["100 1", "200 100", "300 999", "400 200"])
    monkeypatch.setattr(cli_mod.os, "name", "posix", raising=False)
    monkeypatch.setattr(cli_mod.subprocess, "check_output", lambda *args, **kwargs: output)
    children = cli_mod.get_child_pids({100})
    assert children == {200}


def test_get_child_pids_returns_empty_on_failure(monkeypatch):
    monkeypatch.setattr(cli_mod.os, "name", "posix", raising=False)
    monkeypatch.setattr(
        cli_mod.subprocess,
        "check_output",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("ps failed")),
    )
    assert cli_mod.get_child_pids({100}) == set()


def test_get_child_pids_returns_empty_when_no_parent_pid():
    assert cli_mod.get_child_pids(set()) == set()


def test_get_child_pids_skips_malformed_lines(monkeypatch):
    output = "\n".join(["100 1", "bad-line", "200 100"])
    monkeypatch.setattr(cli_mod.os, "name", "posix", raising=False)
    monkeypatch.setattr(cli_mod.subprocess, "check_output", lambda *args, **kwargs: output)
    assert cli_mod.get_child_pids({100}) == {200}


def test_process_helpers_cover_windows_and_child_scan(monkeypatch):
    monkeypatch.setattr(cli_mod.os, "name", "nt", raising=False)
    monkeypatch.setattr(
        cli_mod.subprocess,
        "check_output",
        lambda *_a, **_k: '"dask-worker.exe","1234"\n"python.exe","oops"\n',
    )
    assert cli_mod.get_processes_containing("dask") == {1234}

    monkeypatch.setattr(cli_mod.os, "name", "posix", raising=False)
    monkeypatch.setattr(
        cli_mod.subprocess,
        "check_output",
        lambda *_a, **_k: "10 1\n11 10\nbad line\n",
    )
    assert cli_mod.get_child_pids({10}) == {11}


def test_poll_until_dead_returns_empty_when_all_dead(monkeypatch):
    monkeypatch.setattr(cli_mod, "_is_alive", lambda _pid: False)
    remaining = cli_mod._poll_until_dead({1, 2}, total=0.05, interval=0.01)
    assert remaining == set()


def test_poll_until_dead_sleeps_while_processes_remain(monkeypatch):
    status = iter([True, False])
    sleeps = []

    monkeypatch.setattr(cli_mod, "_is_alive", lambda _pid: next(status))
    monkeypatch.setattr(cli_mod.time, "sleep", lambda interval: sleeps.append(interval))

    remaining = cli_mod._poll_until_dead({1}, total=0.05, interval=0.01)

    assert remaining == set()
    assert sleeps == [0.01]


def test_is_alive_handles_expected_exceptions(monkeypatch):
    monkeypatch.setattr(
        cli_mod.os,
        "kill",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ProcessLookupError()),
    )
    assert cli_mod._is_alive(1) is False

    monkeypatch.setattr(
        cli_mod.os,
        "kill",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError()),
    )
    assert cli_mod._is_alive(1) is True


def test_is_alive_returns_true_on_unknown_oserror(monkeypatch):
    monkeypatch.setattr(
        cli_mod.os,
        "kill",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("unexpected")),
    )
    assert cli_mod._is_alive(1) is True


def test_is_alive_propagates_unexpected_runtime_bug(monkeypatch):
    monkeypatch.setattr(
        cli_mod.os,
        "kill",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unexpected")),
    )
    with pytest.raises(RuntimeError, match="unexpected"):
        cli_mod._is_alive(1)


def test_kill_pids_collects_survivors_on_errors(monkeypatch):
    calls = []

    def _fake_kill(pid, _sig):
        calls.append(pid)
        if pid == 2:
            raise PermissionError()
        if pid == 3:
            raise OSError("boom")

    monkeypatch.setattr(cli_mod.os, "kill", _fake_kill)
    survivors = cli_mod.kill_pids({1, 2, 3}, signal.SIGTERM)
    assert survivors == {2, 3}
    assert set(calls) == {1, 2, 3}


def test_kill_pids_propagates_unexpected_runtime_bug(monkeypatch):
    monkeypatch.setattr(
        cli_mod.os,
        "kill",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unexpected kill bug")),
    )
    with pytest.raises(RuntimeError, match="unexpected kill bug"):
        cli_mod.kill_pids({1}, signal.SIGTERM)


def test_kill_pids_handles_process_lookup(monkeypatch):
    def _fake_kill(_pid, _sig):
        raise ProcessLookupError()

    monkeypatch.setattr(cli_mod.os, "kill", _fake_kill)
    assert cli_mod.kill_pids({1}, signal.SIGTERM) == set()


def test_incarnation_access_denied_never_signals_and_remains_a_survivor(monkeypatch):
    monkeypatch.setattr(
        cli_mod.psutil,
        "Process",
        lambda _pid: (_ for _ in ()).throw(cli_mod.psutil.AccessDenied(pid=321)),
    )
    signal_calls = []
    monkeypatch.setattr(
        cli_mod.os, "kill", lambda pid, sig: signal_calls.append((pid, sig))
    )

    assert cli_mod._process_incarnation_state(321, 10.0) is None
    assert (
        cli_mod.kill_pids(
            {321}, signal.SIGTERM, process_starts={321: 10.0}
        )
        == set()
    )
    assert cli_mod._poll_process_incarnations_until_dead({321: 10.0}, total=0) == {
        321
    }
    assert signal_calls == []


@pytest.mark.skipif(not hasattr(signal, "SIGKILL"), reason="SIGKILL is not available on this platform")
def test_kill_invokes_sigkill_after_grace(monkeypatch):
    calls = []
    monkeypatch.setattr(cli_mod, "get_processes_matching", lambda _match: {10, 11})
    monkeypatch.setattr(cli_mod, "_poll_until_dead", lambda pids: set(pids))
    monkeypatch.setattr(cli_mod.Path, "glob", lambda self, _pattern: [])
    monkeypatch.setattr(cli_mod.os, "getpid", lambda: 999)

    def _fake_kill_pids(pids, sig):
        calls.append((set(pids), sig))
        return set()

    monkeypatch.setattr(cli_mod, "kill_pids", _fake_kill_pids)
    cli_mod.kill(exclude_pids=set(), force_scan=True)
    assert calls[0][1] == signal.SIGTERM
    assert calls[1][1] == signal.SIGKILL


def test_kill_handles_pid_files_and_children(monkeypatch, tmp_path):
    pid_file = tmp_path / "demo.pid"
    pid_file.write_text("321", encoding="utf-8")

    monkeypatch.setattr(cli_mod, "get_processes_matching", lambda _match: {321})
    monkeypatch.setattr(cli_mod.Path, "glob", lambda self, _pattern: [pid_file])
    monkeypatch.setattr(cli_mod.os, "getpid", lambda: 999)
    monkeypatch.setattr(cli_mod, "get_child_pids", lambda pids: {654} if pids == {321} else set())

    calls = []

    def _fake_kill_pids(pids, sig):
        calls.append((set(pids), sig))
        return set()

    monkeypatch.setattr(cli_mod, "kill_pids", _fake_kill_pids)
    monkeypatch.setattr(cli_mod, "_poll_until_dead", lambda pids: set())

    cli_mod.kill(exclude_pids=set(), force_scan=True)
    assert ({321, 654}, signal.SIGTERM) in calls


def test_kill_handles_pid_files_children_and_exclusions(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    (tmp_path / "keep.pid").write_text("999\n", encoding="utf-8")
    (tmp_path / "worker.pid").write_text("111\n", encoding="utf-8")
    (tmp_path / "broken.pid").write_text("bad\n", encoding="utf-8")

    kill_calls = []
    monkeypatch.setattr(cli_mod, "get_processes_matching", lambda _match: {111, 999})
    monkeypatch.setattr(cli_mod.os, "getpid", lambda: 999)
    monkeypatch.setattr(cli_mod, "get_child_pids", lambda pids: {222} if 111 in pids else set())
    monkeypatch.setattr(cli_mod, "kill_pids", lambda pids, sig: kill_calls.append((set(pids), sig)) or set())
    monkeypatch.setattr(cli_mod, "_poll_until_dead", lambda pids, **_k: set())

    cli_mod.kill(force_scan=True)

    assert kill_calls
    assert any(pids == {111, 222} for pids, _sig in kill_calls)
    assert not (tmp_path / "worker.pid").exists()
    assert not (tmp_path / "keep.pid").exists()
    assert not (tmp_path / "broken.pid").exists()


def test_kill_logs_no_dask_when_no_processes_or_pid_files(monkeypatch, caplog):
    monkeypatch.setattr(cli_mod, "get_processes_matching", lambda _match: set())
    monkeypatch.setattr(cli_mod.Path, "glob", lambda self, _pattern: [])
    monkeypatch.setattr(cli_mod.os, "getpid", lambda: 999)

    with caplog.at_level("INFO"):
        cli_mod.kill(exclude_pids=set(), force_scan=True)

    assert "No Dask process running." in caplog.text


@pytest.mark.skipif(not hasattr(signal, "SIGKILL"), reason="SIGKILL is not available on this platform")
def test_force_kill_retains_pid_evidence_when_process_survives_sigkill(
    monkeypatch, tmp_path, caplog
):
    pid_file = tmp_path / "demo.pid"
    pid_file.write_text("321", encoding="utf-8")

    monkeypatch.setattr(cli_mod, "get_processes_matching", lambda _match: {321})
    monkeypatch.setattr(cli_mod.Path, "glob", lambda self, _pattern: [pid_file])
    monkeypatch.setattr(cli_mod.os, "getpid", lambda: 999)
    monkeypatch.setattr(cli_mod, "get_child_pids", lambda pids: set())

    calls = []

    def _fake_kill_pids(pids, sig):
        calls.append((set(pids), sig))
        return set()

    monkeypatch.setattr(cli_mod, "kill_pids", _fake_kill_pids)
    monkeypatch.setattr(cli_mod, "_poll_until_dead", lambda pids: {321})

    with caplog.at_level("ERROR"):
        result = cli_mod.kill(exclude_pids=set(), force_scan=True)

    assert result is False
    assert ({321}, signal.SIGTERM) in calls
    assert ({321}, signal.SIGKILL) in calls
    assert pid_file.exists()
    assert "survived force cleanup" in caplog.text


def test_scoped_kill_isolated_across_two_manager_targets(monkeypatch, tmp_path):
    target_a = tmp_path / "wenv" / "manager-a-worker"
    target_b = tmp_path / "wenv" / "manager-b-worker"
    target_a.mkdir(parents=True)
    target_b.mkdir()
    pid_file_a = target_a.parent / "dask_worker_a.pid"
    pid_file_b = target_b.parent / "dask_worker_b.pid"
    pid_file_a.write_text(
        '{"pid": 101, "process_start_time": 10.0, '
        f'"target": "{target_a.as_posix()}"}}\n',
        encoding="utf-8",
    )
    pid_file_b.write_text(
        '{"pid": 202, "process_start_time": 20.0, '
        f'"target": "{target_b.as_posix()}"}}\n',
        encoding="utf-8",
    )
    identities = {
        101: (10.0, target_a),
        202: (20.0, target_b),
    }
    alive = {101, 202}
    signals = []

    def _identity(pid):
        if pid not in alive:
            return None
        started, target = identities[pid]
        return (
            object(),
            started,
            [str(target / ".venv" / "bin" / "dask"), "worker"],
            target,
        )

    def _target_processes(target):
        normalized = Path(target).resolve(strict=False)
        return {
            pid: started
            for pid, (started, owner) in identities.items()
            if pid in alive and owner == normalized
        }

    def _kill_pids(pids, sig, *, process_starts=None):
        signals.append((set(pids), sig, dict(process_starts or {})))
        alive.difference_update(pids)
        return set()

    monkeypatch.setattr(cli_mod.os, "getpid", lambda: 999)
    monkeypatch.setattr(cli_mod, "_process_identity", _identity)
    monkeypatch.setattr(cli_mod, "_target_dask_processes", _target_processes)
    monkeypatch.setattr(cli_mod, "_add_child_incarnations", lambda _starts: True)
    monkeypatch.setattr(cli_mod, "kill_pids", _kill_pids)
    monkeypatch.setattr(
        cli_mod,
        "_poll_process_incarnations_until_dead",
        lambda process_starts: set(process_starts) & alive,
    )

    assert cli_mod.kill(target_a, home_path=tmp_path, cwd_path=tmp_path) is True
    assert not pid_file_a.exists()
    assert pid_file_b.exists()
    assert alive == {202}
    assert signals[0][0] == {101}

    assert cli_mod.kill(target_b, home_path=tmp_path, cwd_path=tmp_path) is True
    assert not pid_file_b.exists()
    assert alive == set()
    assert signals[1][0] == {202}


@pytest.mark.skipif(
    not hasattr(signal, "SIGKILL"), reason="SIGKILL is not available on this platform"
)
def test_scoped_kill_denied_sigkill_survivor_retains_pid_evidence(
    monkeypatch, tmp_path
):
    target = tmp_path / "wenv" / "worker"
    target.mkdir(parents=True)
    pid_file = target / "dask_worker_0.pid"
    pid_file.write_text(
        '{"pid": 321, "process_start_time": 10.0, '
        f'"target": "{target.as_posix()}"}}\n',
        encoding="utf-8",
    )
    signals = []

    monkeypatch.setattr(cli_mod.os, "getpid", lambda: 999)
    monkeypatch.setattr(
        cli_mod,
        "_process_identity",
        lambda _pid: (
            object(),
            10.0,
            [str(target / ".venv" / "bin" / "dask"), "worker"],
            target,
        ),
    )
    monkeypatch.setattr(cli_mod, "_target_dask_processes", lambda _target: {321: 10.0})
    monkeypatch.setattr(cli_mod, "_add_child_incarnations", lambda _starts: True)
    monkeypatch.setattr(
        cli_mod,
        "kill_pids",
        lambda pids, sig, **_kwargs: signals.append((set(pids), sig)) or set(pids),
    )
    monkeypatch.setattr(
        cli_mod,
        "_poll_process_incarnations_until_dead",
        lambda process_starts: set(process_starts),
    )

    assert cli_mod.kill(target, home_path=tmp_path, cwd_path=tmp_path) is False
    assert signals == [({321}, signal.SIGTERM), ({321}, signal.SIGKILL)]
    assert pid_file.exists()


def test_scoped_kill_rejects_reused_pid_incarnation(monkeypatch, tmp_path):
    target = tmp_path / "wenv" / "worker"
    target.mkdir(parents=True)
    pid_file = target / "dask_worker_0.pid"
    original = (
        '{"pid": 321, "process_start_time": 10.0, '
        f'"target": "{target.as_posix()}"}}\n'
    )
    pid_file.write_text(original, encoding="utf-8")
    signals = []

    monkeypatch.setattr(cli_mod.os, "getpid", lambda: 999)
    monkeypatch.setattr(
        cli_mod,
        "_process_identity",
        lambda _pid: (
            object(),
            20.0,
            [str(target / ".venv" / "bin" / "dask"), "worker"],
            target,
        ),
    )
    monkeypatch.setattr(cli_mod, "_target_dask_processes", lambda _target: {321: 20.0})
    monkeypatch.setattr(cli_mod, "_add_child_incarnations", lambda _starts: True)
    monkeypatch.setattr(
        cli_mod,
        "kill_pids",
        lambda pids, sig, **_kwargs: signals.append((set(pids), sig)) or set(),
    )

    assert cli_mod.kill(target, home_path=tmp_path, cwd_path=tmp_path) is False
    assert signals == []
    assert pid_file.read_text(encoding="utf-8") == original


def test_kill_allows_production_cwd_equal_to_target(monkeypatch, tmp_path):
    home = tmp_path / "home"
    target = home / "wenv" / "worker"
    target.mkdir(parents=True)
    scoped_calls = []
    monkeypatch.setattr(
        cli_mod,
        "_scoped_kill",
        lambda *args, **kwargs: scoped_calls.append((args, kwargs)) or True,
    )

    assert cli_mod.kill(target, home_path=home, cwd_path=target) is True
    assert scoped_calls == [((target.resolve(strict=False), {os.getpid()}), {})]


def test_command_target_match_requires_runtime_path_not_pid_file(tmp_path):
    target = tmp_path / "worker"
    sibling = tmp_path / "worker-other"

    assert cli_mod._command_belongs_to_target(
        [str(target / ".venv" / "bin" / "dask"), "worker"], target
    )
    assert cli_mod._command_belongs_to_target(
        ["uv", "--project", str(target), "run", "dask", "worker"], target
    )
    assert not cli_mod._command_belongs_to_target(
        ["dask-worker", "--pid-file", str(target / "dask_worker_0.pid")],
        target,
    )
    assert not cli_mod._command_belongs_to_target(
        ["dask", "worker"], target, process_cwd=target
    )
    assert not cli_mod._command_belongs_to_target(
        [str(sibling / ".venv" / "bin" / "dask"), "worker"], target
    )


def test_clean_and_unzip_cover_success_and_failure(monkeypatch, tmp_path):
    scratch_root = tmp_path / "tmpdir"
    scratch_root.mkdir()
    scratch = scratch_root / "dask-scratch-space"
    scratch.mkdir()
    wenv = tmp_path / "wenv" / "demo_worker"
    wenv.mkdir(parents=True)
    egg = wenv / "demo.egg"
    with zipfile.ZipFile(egg, "w") as zf:
        zf.writestr("pkg/module.py", "print('ok')\n")

    monkeypatch.setattr(cli_mod, "gettempdir", lambda: str(scratch_root))
    cli_mod.unzip(str(wenv))
    assert (wenv / "src" / "pkg" / "module.py").exists()

    monkeypatch.setattr(cli_mod.shutil, "rmtree", lambda *_a, **_k: (_ for _ in ()).throw(OSError("locked")))
    cli_mod.clean(str(wenv), home_path=tmp_path, cwd_path=tmp_path)


def test_signal_helpers_cover_alive_and_permission_paths(monkeypatch):
    calls = []

    def _fake_kill(pid, sig):
        calls.append((pid, sig))
        if pid == 2:
            raise ProcessLookupError()
        if pid == 3:
            raise PermissionError()
        if pid == 4:
            raise OSError("boom")

    monkeypatch.setattr(cli_mod.os, "kill", _fake_kill)

    assert cli_mod._is_alive(1) is True
    assert cli_mod._is_alive(2) is False
    assert cli_mod._is_alive(3) is True

    survivors = cli_mod.kill_pids({1, 2, 3, 4}, cli_mod.signal.SIGTERM)
    assert survivors == {3, 4}
    assert calls


def test_choose_iters_calibration(monkeypatch):
    monkeypatch.setattr(cli_mod, "_time_busy", lambda _iters: 0.2)
    iters = cli_mod._choose_iters(target_s=0.15)
    assert 149000 <= iters <= 151000

    monkeypatch.setattr(cli_mod, "_time_busy", lambda _iters: 0.0)
    assert cli_mod._choose_iters(target_s=0.15) == 5000000


def test_threaded_runs_requested_number_of_workers(monkeypatch):
    calls = {"count": 0}

    def _fake_busy(_iters):
        calls["count"] += 1
        return 0

    monkeypatch.setattr(cli_mod, "_busy_work", _fake_busy)
    dt = cli_mod.threaded(nthreads=3, iters=1)
    assert dt >= 0.0
    assert calls["count"] == 3


def test_clean_handles_oserror(monkeypatch, tmp_path):
    target = tmp_path / "wenv" / "locked-worker"
    target.mkdir(parents=True)
    monkeypatch.setattr(
        cli_mod.shutil,
        "rmtree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("fail-clean")),
    )
    # New contract: clean reports failure to its caller.
    assert cli_mod.clean(target, home_path=tmp_path, cwd_path=tmp_path) is False


def test_clean_propagates_unexpected_runtime_bug(monkeypatch, tmp_path):
    target = tmp_path / "wenv" / "worker"
    target.mkdir(parents=True)
    monkeypatch.setattr(
        cli_mod.shutil,
        "rmtree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("fail-clean")),
    )
    with pytest.raises(RuntimeError, match="fail-clean"):
        cli_mod.clean(target, home_path=tmp_path, cwd_path=tmp_path)


def test_clean_absent_target_is_successful_fresh_remote_install_noop(tmp_path):
    target = tmp_path / "wenv" / "fresh-worker"

    assert cli_mod.clean(target, home_path=tmp_path, cwd_path=tmp_path) is True
    assert not target.exists()


@pytest.mark.parametrize(
    "target_kind",
    ("filesystem-root", "home", "cwd", "outside", "empty", "traversal"),
)
def test_clean_refuses_unsafe_recursive_delete_targets(
    target_kind,
    monkeypatch,
    tmp_path,
):
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    targets = {
        "filesystem-root": Path(Path.cwd().anchor),
        "home": home,
        "cwd": cwd,
        "outside": tmp_path / "outside",
        "empty": "",
        "traversal": "wenv/../outside",
    }
    rmtree_calls = []
    monkeypatch.setattr(
        cli_mod.shutil,
        "rmtree",
        lambda *args, **kwargs: rmtree_calls.append((args, kwargs)),
    )

    assert cli_mod.clean(
        targets[target_kind],
        home_path=home,
        cwd_path=cwd,
    ) is False
    assert rmtree_calls == []


def test_clean_refuses_symlink_alias_outside_worker_root(monkeypatch, tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    worker_root = home / "wenv"
    outside = tmp_path / "outside"
    worker_root.mkdir(parents=True)
    cwd.mkdir()
    outside.mkdir()
    alias = worker_root / "aliased-worker"
    try:
        alias.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    rmtree_calls = []
    monkeypatch.setattr(
        cli_mod.shutil,
        "rmtree",
        lambda *args, **kwargs: rmtree_calls.append((args, kwargs)),
    )

    assert cli_mod.clean(alias, home_path=home, cwd_path=cwd) is False
    assert outside.exists()
    assert rmtree_calls == []


@pytest.mark.parametrize(
    "target_kind",
    ("filesystem-root", "home", "cwd", "outside", "empty", "traversal"),
)
def test_kill_refuses_unsafe_targets_before_process_discovery(
    target_kind,
    monkeypatch,
    tmp_path,
):
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    targets = {
        "filesystem-root": Path(Path.cwd().anchor),
        "home": home,
        "cwd": cwd,
        "outside": tmp_path / "outside",
        "empty": "",
        "traversal": "wenv/../outside",
    }
    scoped_calls = []
    monkeypatch.setattr(
        cli_mod,
        "_scoped_kill",
        lambda *args, **kwargs: scoped_calls.append((args, kwargs)) or True,
    )

    assert cli_mod.kill(
        targets[target_kind],
        home_path=home,
        cwd_path=cwd,
    ) is False
    assert scoped_calls == []


def test_kill_refuses_symlink_alias_outside_worker_root(monkeypatch, tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    worker_root = home / "wenv"
    outside = tmp_path / "outside"
    worker_root.mkdir(parents=True)
    cwd.mkdir()
    outside.mkdir()
    alias = worker_root / "aliased-worker"
    try:
        alias.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    scoped_calls = []
    monkeypatch.setattr(
        cli_mod,
        "_scoped_kill",
        lambda *args, **kwargs: scoped_calls.append((args, kwargs)) or True,
    )

    assert cli_mod.kill(alias, home_path=home, cwd_path=cwd) is False
    assert scoped_calls == []


def test_remote_target_lease_serializes_cross_manager_clean_and_start(tmp_path):
    target = tmp_path / "wenv" / "worker"
    target.mkdir(parents=True)
    (target / "installed.txt").write_text("ready", encoding="utf-8")
    clean_token = "a" * 32
    start_token = "b" * 32

    assert cli_mod.acquire_remote_target_lease(target, clean_token, "install") is True
    assert cli_mod.acquire_remote_target_lease(target, start_token, "run") is False
    assert cli_mod.clean(
        target,
        lease_token=start_token,
        home_path=tmp_path,
        cwd_path=tmp_path,
    ) is False
    assert target.exists()

    assert cli_mod.clean(
        target,
        lease_token=clean_token,
        home_path=tmp_path,
        cwd_path=tmp_path,
    ) is True
    assert not target.exists()
    assert cli_mod.release_remote_target_lease(target, clean_token) is True
    assert cli_mod.acquire_remote_target_lease(target, start_token, "run") is True
    assert cli_mod.release_remote_target_lease(target, start_token) is True


def test_remote_acquire_never_replaces_unknown_empty_destination(tmp_path):
    target = tmp_path / "worker"
    token = "a" * 32
    lock_path = cli_mod._remote_target_lease_path(target)
    lock_path.mkdir(parents=True)

    assert cli_mod.acquire_remote_target_lease(target, token, "run") is False
    assert lock_path.is_dir()
    assert list(lock_path.iterdir()) == []
    assert cli_mod._acquire_publication_claims(lock_path, token) == []


def test_remote_recovery_resumes_empty_token_scoped_publication(
    monkeypatch,
    tmp_path,
):
    target = tmp_path / "worker"
    stale_token = "a" * 32
    replacement_token = "b" * 32
    real_open = Path.open
    interrupted = False

    def _interrupt_before_owner_publication(self, *args, **kwargs):
        nonlocal interrupted
        if self.name.startswith(f".owner.{stale_token}.") and not interrupted:
            interrupted = True
            raise KeyboardInterrupt("publication interrupted before owner")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _interrupt_before_owner_publication)
    with pytest.raises(KeyboardInterrupt, match="before owner"):
        cli_mod.acquire_remote_target_lease(target, stale_token, "install")

    lock_path = cli_mod._remote_target_lease_path(target)
    assert lock_path.is_dir()
    assert not (lock_path / "owner.json").exists()
    assert cli_mod._acquire_publication_claims(lock_path, stale_token)

    assert cli_mod.recover_remote_target_lease(
        target,
        replacement_token,
        [stale_token],
        "run",
    )
    assert cli_mod.remote_target_lease_owned(target, replacement_token)
    assert cli_mod.release_remote_target_lease(target, replacement_token)


def test_remote_target_recovery_requires_identity_proven_exact_generation(tmp_path):
    target = tmp_path / "worker"
    live_token = "a" * 32
    replacement_token = "b" * 32
    unrelated_token = "c" * 32

    assert cli_mod.acquire_remote_target_lease(target, live_token, "install") is True

    # A successor without the exact capability cannot infer staleness from age
    # or replace the live generation.
    assert (
        cli_mod.recover_remote_target_lease(
            target,
            replacement_token,
            [unrelated_token],
            "run",
        )
        is False
    )
    assert cli_mod.remote_target_lease_owned(target, live_token) is True

    # Once the manager-side incarnation guard has authorized the exact stale
    # token, recovery replaces only that generation.
    assert (
        cli_mod.recover_remote_target_lease(
            target,
            replacement_token,
            [live_token],
            "run",
        )
        is True
    )
    assert cli_mod.remote_target_lease_owned(target, live_token) is False
    assert cli_mod.remote_target_lease_owned(target, replacement_token) is True
    assert cli_mod.release_remote_target_lease(target, replacement_token) is True


def test_remote_recovery_resumes_interrupted_exact_release_claim(
    monkeypatch,
    tmp_path,
):
    target = tmp_path / "worker"
    stale_token = "a" * 32
    replacement_token = "b" * 32
    wrong_successor_token = "c" * 32
    assert cli_mod.acquire_remote_target_lease(target, stale_token, "install")

    lock_path = cli_mod._remote_target_lease_path(target)
    tombstone = cli_mod._remote_release_tombstone(lock_path, stale_token)
    real_rename = Path.rename
    interrupted = False

    def _interrupt_after_marker_claim(self, destination):
        nonlocal interrupted
        if self == lock_path and destination == tombstone and not interrupted:
            interrupted = True
            raise KeyboardInterrupt("release interrupted after marker claim")
        return real_rename(self, destination)

    monkeypatch.setattr(Path, "rename", _interrupt_after_marker_claim)
    with pytest.raises(KeyboardInterrupt, match="after marker claim"):
        cli_mod.release_remote_target_lease(target, stale_token)

    assert not (lock_path / f"token-{stale_token}").exists()
    assert cli_mod._release_marker_claims(lock_path, stale_token)
    assert cli_mod.recover_remote_target_lease(
        target,
        replacement_token,
        [stale_token],
        "run",
    )
    assert tombstone.is_dir()
    assert cli_mod.remote_target_lease_owned(target, replacement_token)

    # An arbitrarily delayed stale releaser/recoverer observes the successor
    # and cannot move it into the old deterministic tombstone.
    assert cli_mod.release_remote_target_lease(target, stale_token)
    assert not cli_mod.recover_remote_target_lease(
        target,
        wrong_successor_token,
        [stale_token],
        "run",
    )
    assert cli_mod.remote_target_lease_owned(target, replacement_token)
    assert cli_mod.release_remote_target_lease(target, replacement_token)


def test_remote_recovery_handles_historical_owner_before_marker_publication(
    tmp_path,
):
    target = tmp_path / "worker"
    stale_token = "a" * 32
    replacement_token = "b" * 32
    lock_path = cli_mod._remote_target_lease_path(target)
    lock_path.mkdir(parents=True)
    (lock_path / "owner.json").write_text(
        json.dumps(
            {
                "schema": cli_mod._REMOTE_TARGET_LEASE_SCHEMA,
                "token": stale_token,
                "operation": "install",
                "created_at": 1.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert cli_mod.recover_remote_target_lease(
        target,
        replacement_token,
        [stale_token],
        "run",
    )
    assert cli_mod._remote_release_tombstone(lock_path, stale_token).is_dir()
    assert cli_mod.remote_target_lease_owned(target, replacement_token)
    assert cli_mod.release_remote_target_lease(target, replacement_token)


def test_delayed_old_remote_lease_release_cannot_remove_successor(
    monkeypatch, tmp_path
):
    target = tmp_path / "worker"
    old_token = "a" * 32
    successor_token = "b" * 32
    assert cli_mod.acquire_remote_target_lease(target, old_token, "install") is True

    delayed_at_claim = threading.Event()
    resume_delayed = threading.Event()
    real_rename = Path.rename

    def _controlled_rename(self, destination):
        if (
            threading.current_thread().name == "delayed-old-release"
            and self.name == f"token-{old_token}"
        ):
            delayed_at_claim.set()
            assert resume_delayed.wait(timeout=5.0)
        return real_rename(self, destination)

    monkeypatch.setattr(Path, "rename", _controlled_rename)
    delayed_result = []

    def _delayed_release():
        delayed_result.append(
            cli_mod.release_remote_target_lease(target, old_token)
        )

    delayed_thread = threading.Thread(
        target=_delayed_release,
        name="delayed-old-release",
    )
    delayed_thread.start()
    assert delayed_at_claim.wait(timeout=5.0)

    assert cli_mod.release_remote_target_lease(target, old_token) is True
    assert cli_mod.acquire_remote_target_lease(target, successor_token, "run") is True
    resume_delayed.set()
    delayed_thread.join(timeout=5.0)

    assert not delayed_thread.is_alive()
    assert delayed_result == [True]
    assert cli_mod.remote_target_lease_owned(target, successor_token) is True
    assert cli_mod.release_remote_target_lease(target, successor_token) is True


def test_clean_removes_temp_and_wenv(tmp_path, monkeypatch):
    scratch_root = tmp_path / "tmp"
    scratch_dir = scratch_root / "dask-scratch-space"
    wenv_dir = tmp_path / "wenv" / "demo_worker"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    wenv_dir.mkdir(parents=True, exist_ok=True)
    (scratch_dir / "a.txt").write_text("x", encoding="utf-8")
    (wenv_dir / "b.txt").write_text("y", encoding="utf-8")

    monkeypatch.setattr(cli_mod, "gettempdir", lambda: str(scratch_root))
    cli_mod.clean(str(wenv_dir), home_path=tmp_path, cwd_path=tmp_path)
    assert scratch_dir.exists()
    assert not wenv_dir.exists()

    wenv_dir.mkdir()
    cli_mod.clean(
        str(wenv_dir),
        force_scratch=True,
        home_path=tmp_path,
        cwd_path=tmp_path,
    )
    assert not scratch_dir.exists()
    assert not wenv_dir.exists()


def test_unzip_handles_bad_zip(monkeypatch, tmp_path):
    errors = []
    wenv = tmp_path / "worker"
    wenv.mkdir()
    (wenv / "demo.egg").write_bytes(b"not-a-zip")

    monkeypatch.setattr(
        cli_mod.zipfile,
        "ZipFile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(zipfile.BadZipFile("boom-unzip")),
    )
    monkeypatch.setattr(cli_mod.logger, "error", lambda message: errors.append(message))

    # New contract: unzip reports failure to its caller so the CLI can exit
    # nonzero instead of hiding extraction errors from the remote manager.
    assert cli_mod.unzip(str(wenv)) is False

    assert errors == ["Error during unzip: boom-unzip"]


def test_unzip_propagates_unexpected_runtime_bug(monkeypatch):
    root = Path("/tmp/worker")
    monkeypatch.setattr(
        cli_mod.Path,
        "glob",
        lambda self, pattern: [root / "demo.egg"] if self == root and pattern == "*.egg" else [],
    )
    monkeypatch.setattr(
        cli_mod.zipfile,
        "ZipFile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom-unzip")),
    )
    with pytest.raises(RuntimeError, match="boom-unzip"):
        cli_mod.unzip("/tmp/worker")


def test_process_listing_helpers_propagate_unexpected_runtime_bug(monkeypatch):
    monkeypatch.setattr(cli_mod.os, "name", "posix", raising=False)
    monkeypatch.setattr(
        cli_mod.subprocess,
        "check_output",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("unexpected ps bug")),
    )

    with pytest.raises(ValueError, match="unexpected ps bug"):
        cli_mod.get_processes_containing("dask")

    with pytest.raises(ValueError, match="unexpected ps bug"):
        cli_mod.get_child_pids({100})


def test_unzip_extracts_egg_contents(tmp_path):
    root = tmp_path / "worker"
    root.mkdir(parents=True, exist_ok=True)
    egg_path = root / "demo.egg"
    with zipfile.ZipFile(egg_path, "w") as zf:
        zf.writestr("demo_pkg/data.txt", "hello")

    assert cli_mod.unzip(str(root)) is True
    extracted = root / "src" / "demo_pkg" / "data.txt"
    assert extracted.exists()
    assert extracted.read_text(encoding="utf-8") == "hello"


def test_python_version_returns_structured_tag():
    tag = cli_mod.python_version()
    assert "-" in tag
    assert "none" in tag


def test_test_python_threads_logs_both_outcomes(monkeypatch):
    seq = iter([1.0, 0.5])
    monkeypatch.setattr(cli_mod, "threaded", lambda nthreads=1: next(seq))
    cli_mod.test_python_threads()

    seq2 = iter([1.0, 0.95])
    monkeypatch.setattr(cli_mod, "threaded", lambda nthreads=1: next(seq2))
    cli_mod.test_python_threads()


def test_python_version_os_mapping(monkeypatch):
    monkeypatch.setattr(cli_mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(cli_mod.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(cli_mod.platform, "python_version", lambda: "3.13.0")
    tag = cli_mod.python_version()
    assert "macos" in tag
    assert "aarch64" in tag


def test_python_version_covers_windows_and_freethreaded_tags(monkeypatch):
    monkeypatch.setattr(cli_mod.platform, "system", lambda: "Windows")
    monkeypatch.setattr(cli_mod.platform, "machine", lambda: "amd64")
    monkeypatch.setattr(cli_mod.platform, "python_version", lambda: "3.13.0")
    monkeypatch.setattr(cli_mod.sys, "implementation", SimpleNamespace(name="cpython", cache_tag="cpython-313-freethreaded"))

    tag = cli_mod.python_version()

    assert "windows" in tag
    assert "x86_64" in tag
    assert "+freethreaded" in tag


def test_python_version_handles_linux_and_unknown_platform(monkeypatch):
    monkeypatch.setattr(cli_mod.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(cli_mod.platform, "python_version", lambda: "3.13.0")
    monkeypatch.setattr(cli_mod.sys, "implementation", SimpleNamespace(name="cpython", cache_tag="cpython-313"))
    monkeypatch.setattr(cli_mod.platform, "system", lambda: "Linux")
    assert cli_mod.python_version().endswith("-linux-x86_64-none")

    monkeypatch.setattr(cli_mod.platform, "system", lambda: "Plan9")
    assert cli_mod.python_version().endswith("-plan9-x86_64-none")


def test_rapids_probe_detects_nvidia_gpu(monkeypatch):
    monkeypatch.setattr(cli_mod.shutil, "which", lambda _name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(cli_mod, "_NVIDIA_SMI_CANDIDATES", ("nvidia-smi",))
    monkeypatch.setattr(
        cli_mod,
        "_run_nvidia_smi_probe",
        lambda executable: SimpleNamespace(
            returncode=0,
            stdout="GPU 0: NVIDIA RTX 4090 (UUID: GPU-demo)\n",
            stderr="",
            args=[executable, "-L"],
        ),
    )

    result = cli_mod.rapids_probe()

    assert result["rapids_capable"] is True
    assert result["command"] == "/usr/bin/nvidia-smi"
    assert result["gpus"] == ["NVIDIA RTX 4090"]


def test_rapids_probe_reports_false_when_nvidia_smi_missing(monkeypatch):
    monkeypatch.setattr(cli_mod.shutil, "which", lambda _name: None)
    monkeypatch.setattr(cli_mod, "_NVIDIA_SMI_CANDIDATES", ("nvidia-smi",))
    monkeypatch.setattr(
        cli_mod,
        "_run_nvidia_smi_probe",
        lambda _executable: (_ for _ in ()).throw(FileNotFoundError("nvidia-smi")),
    )

    result = cli_mod.rapids_probe()

    assert result["rapids_capable"] is False
    assert result["command"] is None
    assert result["attempts"][0]["command"] == "nvidia-smi"


def _run_cli_as_main(monkeypatch, args):
    monkeypatch.setattr(sys, "argv", [str(Path(cli_mod.__file__))] + args)
    return runpy.run_path(str(Path(cli_mod.__file__)), run_name="__main__")


def test_cli_main_without_args_exits(monkeypatch):
    with pytest.raises(SystemExit):
        _run_cli_as_main(monkeypatch, [])


def test_cli_main_unknown_command_exits(monkeypatch):
    with pytest.raises(SystemExit):
        _run_cli_as_main(monkeypatch, ["unknown"])


def test_cli_main_clean_missing_arg_exits(monkeypatch):
    with pytest.raises(SystemExit):
        _run_cli_as_main(monkeypatch, ["clean"])


def test_cli_main_unzip_missing_arg_exits(monkeypatch):
    with pytest.raises(SystemExit):
        _run_cli_as_main(monkeypatch, ["unzip"])


def test_cli_main_platform_runs(monkeypatch):
    _run_cli_as_main(monkeypatch, ["platform"])


def test_cli_main_rapids_probe_runs(monkeypatch, capfd):
    import shutil as shutil_mod
    import subprocess as subprocess_mod

    monkeypatch.setattr(shutil_mod, "which", lambda _name: None)
    monkeypatch.setattr(
        subprocess_mod,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("nvidia-smi")),
    )

    _run_cli_as_main(monkeypatch, ["rapids-probe"])

    output = capfd.readouterr().out
    assert '"rapids_capable": false' in output


def test_cli_main_clean_runs_with_arg(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    target = tmp_path / "wenv" / "to-clean"
    target.mkdir(parents=True, exist_ok=True)
    _run_cli_as_main(monkeypatch, ["clean", str(target)])

    assert not target.exists()


def test_cli_main_recovers_only_the_authorized_remote_generation(
    monkeypatch,
    tmp_path,
):
    target = tmp_path / "worker"
    stale_token = "a" * 32
    replacement_token = "b" * 32
    assert cli_mod.acquire_remote_target_lease(target, stale_token, "install")

    _run_cli_as_main(
        monkeypatch,
        [
            "target-lease-recover",
            str(target),
            replacement_token,
            stale_token,
            "run",
        ],
    )

    assert cli_mod.remote_target_lease_owned(target, replacement_token)
    assert cli_mod.release_remote_target_lease(target, replacement_token)


def test_cli_main_unzip_runs_with_arg(monkeypatch, tmp_path):
    root = tmp_path / "worker"
    root.mkdir(parents=True, exist_ok=True)
    _run_cli_as_main(monkeypatch, ["unzip", str(root)])


def test_cli_main_threaded_runs(monkeypatch):
    _run_cli_as_main(monkeypatch, ["threaded"])


def test_cli_main_unzip_failure_exits_nonzero(monkeypatch, tmp_path):
    # Regression: a corrupt egg must make `cli.py unzip` exit nonzero so the
    # manager's check=True SSH invocation surfaces the failed deploy step.
    root = tmp_path / "worker"
    root.mkdir(parents=True, exist_ok=True)
    (root / "demo.egg").write_bytes(b"not-a-zip")

    with pytest.raises(SystemExit) as excinfo:
        _run_cli_as_main(monkeypatch, ["unzip", str(root)])

    assert excinfo.value.code == 1


def test_is_dask_command_only_matches_dask_entrypoints():
    # Regression: kill() must not match arbitrary same-user processes whose
    # command line merely contains the substring "dask".
    assert cli_mod._is_dask_command("/usr/bin/python /venv/bin/dask-scheduler")
    assert cli_mod._is_dask_command("python -m distributed.cli.dask_worker tcp://1.2.3.4:8786")
    assert cli_mod._is_dask_command("dask worker tcp://1.2.3.4:8786")
    assert not cli_mod._is_dask_command("vim /home/user/notes/dask_tuning.md")
    assert not cli_mod._is_dask_command("python my_daskboard.py")


def test_kill_does_not_target_unrelated_dask_named_processes(monkeypatch):
    output = "\n".join(
        [
            "101 python /venv/bin/dask-scheduler",
            "202 vim /home/user/notes/dask_tuning.md",
            "303 python -m distributed.cli.dask_worker tcp://1.2.3.4:8786",
        ]
    )
    monkeypatch.setattr(cli_mod.os, "name", "posix", raising=False)
    monkeypatch.setattr(cli_mod.subprocess, "check_output", lambda *args, **kwargs: output)

    class _NoPidPath:
        def __init__(self, *_args, **_kwargs):
            pass

        @property
        def parent(self):
            return self

        def glob(self, _pattern):
            return []

    monkeypatch.setattr(cli_mod, "Path", _NoPidPath)
    monkeypatch.setattr(cli_mod.os, "getpid", lambda: 999)
    monkeypatch.setattr(cli_mod, "_poll_until_dead", lambda pids: set())

    killed: list[set] = []
    monkeypatch.setattr(
        cli_mod, "kill_pids", lambda pids, sig: killed.append(set(pids)) or set()
    )

    cli_mod.kill(exclude_pids=set(), force_scan=True)

    assert killed and killed[0] == {101, 303}


def test_cli_main_kill_warns_for_invalid_excluded_pid(monkeypatch, caplog):
    monkeypatch.setattr(cli_mod.subprocess, "check_output", lambda *args, **kwargs: "")
    monkeypatch.setattr(cli_mod.Path, "glob", lambda self, pattern: [])
    monkeypatch.setattr(cli_mod.os, "getpid", lambda: 999)

    caplog.set_level("WARNING")
    target = Path.home() / "wenv" / "demo-runtime"
    _run_cli_as_main(monkeypatch, ["kill", str(target), "100,bad"])

    assert "Invalid PID to exclude: bad" in caplog.text


def test_cli_main_kill_survivor_contract_exits_nonzero(monkeypatch, tmp_path):
    target = tmp_path / "worker"
    target.mkdir()
    (target / "dask_worker_0.pid").write_text("not-a-pid\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        _run_cli_as_main(monkeypatch, ["kill", str(target)])

    assert excinfo.value.code == 1
