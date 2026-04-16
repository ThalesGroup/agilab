import runpy
import sys
import zipfile
from pathlib import Path
import signal
from types import SimpleNamespace

import pytest

from agi_cluster.agi_distributor import cli as cli_mod


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


def test_kill_invokes_sigkill_after_grace(monkeypatch):
    calls = []
    monkeypatch.setattr(cli_mod, "get_processes_containing", lambda _name: {10, 11})
    monkeypatch.setattr(cli_mod, "_poll_until_dead", lambda pids: set(pids))
    monkeypatch.setattr(cli_mod.Path, "glob", lambda self, _pattern: [])
    monkeypatch.setattr(cli_mod.os, "getpid", lambda: 999)

    def _fake_kill_pids(pids, sig):
        calls.append((set(pids), sig))
        return set()

    monkeypatch.setattr(cli_mod, "kill_pids", _fake_kill_pids)
    cli_mod.kill(exclude_pids=set())
    assert calls[0][1] == signal.SIGTERM
    assert calls[1][1] == signal.SIGKILL


def test_kill_handles_pid_files_and_children(monkeypatch, tmp_path):
    pid_file = tmp_path / "demo.pid"
    pid_file.write_text("321", encoding="utf-8")

    monkeypatch.setattr(cli_mod, "get_processes_containing", lambda _name: set())
    monkeypatch.setattr(cli_mod.Path, "glob", lambda self, _pattern: [pid_file])
    monkeypatch.setattr(cli_mod.os, "getpid", lambda: 999)
    monkeypatch.setattr(cli_mod, "get_child_pids", lambda pids: {654} if pids == {321} else set())

    calls = []

    def _fake_kill_pids(pids, sig):
        calls.append((set(pids), sig))
        return set()

    monkeypatch.setattr(cli_mod, "kill_pids", _fake_kill_pids)
    monkeypatch.setattr(cli_mod, "_poll_until_dead", lambda pids: set())

    cli_mod.kill(exclude_pids=set())
    assert ({321, 654}, signal.SIGTERM) in calls


def test_kill_handles_pid_files_children_and_exclusions(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    (tmp_path / "keep.pid").write_text("999\n", encoding="utf-8")
    (tmp_path / "worker.pid").write_text("111\n", encoding="utf-8")
    (tmp_path / "broken.pid").write_text("bad\n", encoding="utf-8")

    kill_calls = []
    monkeypatch.setattr(cli_mod, "get_processes_containing", lambda _name: set())
    monkeypatch.setattr(cli_mod.os, "getpid", lambda: 999)
    monkeypatch.setattr(cli_mod, "get_child_pids", lambda pids: {222} if 111 in pids else set())
    monkeypatch.setattr(cli_mod, "kill_pids", lambda pids, sig: kill_calls.append((set(pids), sig)) or set())
    monkeypatch.setattr(cli_mod, "_poll_until_dead", lambda pids, **_k: set())

    cli_mod.kill()

    assert kill_calls
    assert any(pids == {111, 222} for pids, _sig in kill_calls)
    assert not (tmp_path / "worker.pid").exists()
    assert not (tmp_path / "keep.pid").exists()
    assert not (tmp_path / "broken.pid").exists()


def test_kill_logs_no_dask_when_no_processes_or_pid_files(monkeypatch, caplog):
    monkeypatch.setattr(cli_mod, "get_processes_containing", lambda _name: set())
    monkeypatch.setattr(cli_mod.Path, "glob", lambda self, _pattern: [])
    monkeypatch.setattr(cli_mod.os, "getpid", lambda: 999)

    with caplog.at_level("INFO"):
        cli_mod.kill(exclude_pids=set())

    assert "No Dask process running." in caplog.text


def test_kill_warns_on_pid_file_cleanup_failure_and_sigkills_survivors(monkeypatch, tmp_path, caplog):
    pid_file = tmp_path / "demo.pid"
    pid_file.write_text("321", encoding="utf-8")

    monkeypatch.setattr(cli_mod, "get_processes_containing", lambda _name: set())
    monkeypatch.setattr(cli_mod.Path, "glob", lambda self, _pattern: [pid_file])
    monkeypatch.setattr(cli_mod.os, "getpid", lambda: 999)
    monkeypatch.setattr(cli_mod, "get_child_pids", lambda pids: set())

    original_unlink = Path.unlink

    def _patched_unlink(self, *args, **kwargs):
        if self == pid_file:
            raise OSError("unlink boom")
        return original_unlink(self, *args, **kwargs)

    calls = []

    def _fake_kill_pids(pids, sig):
        calls.append((set(pids), sig))
        return set()

    monkeypatch.setattr(cli_mod.Path, "unlink", _patched_unlink)
    monkeypatch.setattr(cli_mod, "kill_pids", _fake_kill_pids)
    monkeypatch.setattr(cli_mod, "_poll_until_dead", lambda pids: {321})

    with caplog.at_level("WARNING"):
        cli_mod.kill(exclude_pids=set())

    assert ({321}, signal.SIGTERM) in calls
    assert ({321}, signal.SIGKILL) in calls
    assert "Could not remove pid file" in caplog.text


def test_clean_and_unzip_cover_success_and_failure(monkeypatch, tmp_path):
    scratch_root = tmp_path / "tmpdir"
    scratch_root.mkdir()
    scratch = scratch_root / "dask-scratch-space"
    scratch.mkdir()
    wenv = tmp_path / "wenv"
    wenv.mkdir()
    egg = wenv / "demo.egg"
    with zipfile.ZipFile(egg, "w") as zf:
        zf.writestr("pkg/module.py", "print('ok')\n")

    monkeypatch.setattr(cli_mod, "gettempdir", lambda: str(scratch_root))
    cli_mod.unzip(str(wenv))
    assert (wenv / "src" / "pkg" / "module.py").exists()

    monkeypatch.setattr(cli_mod.shutil, "rmtree", lambda *_a, **_k: (_ for _ in ()).throw(OSError("locked")))
    cli_mod.clean(str(wenv))


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


def test_clean_handles_oserror(monkeypatch):
    monkeypatch.setattr(
        cli_mod.shutil,
        "rmtree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("fail-clean")),
    )
    cli_mod.clean("/tmp/whatever")


def test_clean_propagates_unexpected_runtime_bug(monkeypatch):
    monkeypatch.setattr(
        cli_mod.shutil,
        "rmtree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("fail-clean")),
    )
    with pytest.raises(RuntimeError, match="fail-clean"):
        cli_mod.clean("/tmp/whatever")


def test_clean_removes_temp_and_wenv(tmp_path, monkeypatch):
    scratch_root = tmp_path / "tmp"
    scratch_dir = scratch_root / "dask-scratch-space"
    wenv_dir = tmp_path / "wenv"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    wenv_dir.mkdir(parents=True, exist_ok=True)
    (scratch_dir / "a.txt").write_text("x", encoding="utf-8")
    (wenv_dir / "b.txt").write_text("y", encoding="utf-8")

    monkeypatch.setattr(cli_mod, "gettempdir", lambda: str(scratch_root))
    cli_mod.clean(str(wenv_dir))
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

    cli_mod.unzip(str(wenv))

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

    cli_mod.unzip(str(root))
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


def test_cli_main_clean_runs_with_arg(monkeypatch, tmp_path):
    target = tmp_path / "to-clean"
    target.mkdir(parents=True, exist_ok=True)
    _run_cli_as_main(monkeypatch, ["clean", str(target)])


def test_cli_main_unzip_runs_with_arg(monkeypatch, tmp_path):
    root = tmp_path / "worker"
    root.mkdir(parents=True, exist_ok=True)
    _run_cli_as_main(monkeypatch, ["unzip", str(root)])


def test_cli_main_threaded_runs(monkeypatch):
    _run_cli_as_main(monkeypatch, ["threaded"])


def test_cli_main_kill_warns_for_invalid_excluded_pid(monkeypatch, caplog):
    monkeypatch.setattr(cli_mod.subprocess, "check_output", lambda *args, **kwargs: "")
    monkeypatch.setattr(cli_mod.Path, "glob", lambda self, pattern: [])
    monkeypatch.setattr(cli_mod.os, "getpid", lambda: 999)

    caplog.set_level("WARNING")
    _run_cli_as_main(monkeypatch, ["kill", "100,bad"])

    assert "Invalid PID to exclude: bad" in caplog.text
