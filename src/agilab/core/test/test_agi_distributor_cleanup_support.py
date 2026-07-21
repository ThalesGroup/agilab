from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
import psutil

from agi_cluster.agi_distributor import cleanup_support


def _local_cleanup_env(tmp_path, worker_name="demo_worker"):
    home_abs = tmp_path / "home"
    return SimpleNamespace(
        home_abs=home_abs,
        wenv_abs=home_abs / "wenv" / worker_name,
    )


def test_remove_dir_forcefully_retries_oserror_and_raises(tmp_path):
    target = tmp_path / "to-remove"
    target.mkdir(parents=True, exist_ok=True)
    calls = {"count": 0}
    log = mock.Mock()

    def _fake_rmtree(_path, onerror=None):
        calls["count"] += 1
        raise OSError("rm fail")

    with pytest.raises(OSError, match="rm fail"):
        cleanup_support.remove_dir_forcefully(
            str(target),
            rmtree_fn=_fake_rmtree,
            sleep_fn=lambda *_a, **_k: None,
            log=log,
        )

    assert calls["count"] == 2
    assert log.error.call_count == 2


def test_remove_dir_forcefully_second_attempt_succeeds_after_oserror(tmp_path):
    target = tmp_path / "to-remove"
    target.mkdir(parents=True, exist_ok=True)
    calls = {"count": 0}

    def _fake_rmtree(_path, onerror=None):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError("rm fail once")
        return None

    cleanup_support.remove_dir_forcefully(
        str(target),
        rmtree_fn=_fake_rmtree,
        sleep_fn=lambda *_a, **_k: None,
    )

    assert calls["count"] == 2


def test_remove_dir_forcefully_propagates_non_filesystem_errors(tmp_path):
    target = tmp_path / "to-remove"
    target.mkdir(parents=True, exist_ok=True)
    calls = {"count": 0}

    def _fake_rmtree(_path, onerror=None):
        calls["count"] += 1
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        cleanup_support.remove_dir_forcefully(
            str(target),
            rmtree_fn=_fake_rmtree,
            sleep_fn=lambda *_a, **_k: None,
        )

    assert calls["count"] == 1


def test_remove_dir_forcefully_onerror_covers_permission_and_log_paths(tmp_path):
    target = tmp_path / "to-remove"
    target.mkdir(parents=True, exist_ok=True)
    chmod_calls = []
    removed = []
    log = mock.Mock()

    def _fake_remove(path):
        removed.append(path)

    def _fake_rmtree(_path, onerror=None):
        onerror(_fake_remove, "locked-file", (OSError, OSError("locked"), None))
        onerror(_fake_remove, "writable-file", (OSError, OSError("busy"), None))

    cleanup_support.remove_dir_forcefully(
        str(target),
        rmtree_fn=_fake_rmtree,
        sleep_fn=lambda *_a, **_k: None,
        access_fn=lambda failed_path, _mode: failed_path == "writable-file",
        chmod_fn=lambda failed_path, mode: chmod_calls.append((failed_path, mode)),
        log=log,
    )

    assert chmod_calls == [("locked-file", cleanup_support.stat.S_IWUSR)]
    assert removed == ["locked-file"]
    log.info.assert_called_once()


@pytest.mark.asyncio
async def test_remote_cmd_prefix_returns_empty_when_detection_fails():
    async def _raise_detect(_ip):
        raise OSError("ssh unavailable")

    env = SimpleNamespace(envars={}, is_local=lambda _ip: False)

    assert (
        await cleanup_support._remote_cmd_prefix(
            env,
            "10.0.0.2",
            detect_export_cmd_fn=_raise_detect,
        )
        == ""
    )
    assert env.envars == {}


@pytest.mark.asyncio
async def test_wait_for_port_release_success_after_retry():
    calls = {"count": 0}

    class _Sock:
        def bind(self, *_args, **_kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise OSError("busy")

        def close(self):
            return None

    time_values = iter([0.0, 0.0, 0.1])

    async def _sleep(*_args, **_kwargs):
        return None

    released = await cleanup_support.wait_for_port_release(
        "127.0.0.1",
        9000,
        timeout=0.3,
        interval=0.01,
        socket_factory=lambda *_a, **_k: _Sock(),
        sleep_fn=_sleep,
        monotonic_fn=lambda: next(time_values),
    )

    assert released is True
    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_wait_for_port_release_timeout():
    class _Sock:
        def bind(self, *_args, **_kwargs):
            raise OSError("always busy")

        def close(self):
            return None

    time_values = iter([0.0, 0.0, 0.05])

    async def _sleep(*_args, **_kwargs):
        return None

    released = await cleanup_support.wait_for_port_release(
        "127.0.0.1",
        9000,
        timeout=0.05,
        interval=0.01,
        socket_factory=lambda *_a, **_k: _Sock(),
        sleep_fn=_sleep,
        monotonic_fn=lambda: next(time_values),
    )

    assert released is False


@pytest.mark.asyncio
async def test_wait_for_port_release_ignores_close_oserror():
    class _Sock:
        def bind(self, *_args, **_kwargs):
            raise OSError("always busy")

        def close(self):
            raise OSError("close failed")

    time_values = iter([0.0, 0.0, 0.05])

    async def _sleep(*_args, **_kwargs):
        return None

    released = await cleanup_support.wait_for_port_release(
        "127.0.0.1",
        9000,
        timeout=0.05,
        interval=0.01,
        socket_factory=lambda *_a, **_k: _Sock(),
        sleep_fn=_sleep,
        monotonic_fn=lambda: next(time_values),
    )

    assert released is False


@pytest.mark.asyncio
async def test_kill_processes_cleans_pid_files_and_handles_local_and_remote_paths(tmp_path):
    wenv_parent = tmp_path / "wenv"
    wenv_abs = wenv_parent / "demo_worker"
    wenv_abs.mkdir(parents=True)
    cluster_pck = tmp_path / "cluster"
    cli_source = cluster_pck / "agi_distributor" / "cli.py"
    cli_source.parent.mkdir(parents=True)
    cli_source.write_text("print('cli')\n", encoding="utf-8")
    (wenv_parent / "ok.pid").write_text("111\n", encoding="utf-8")
    stubborn = wenv_parent / "stubborn.pid"
    stubborn.write_text("222\n", encoding="utf-8")
    (wenv_parent / "broken.pid").write_text("bad\n", encoding="utf-8")

    env = SimpleNamespace(
        uv="uv",
        wenv_abs=wenv_abs,
        wenv_rel=Path("w env's/demo worker"),
        envars={},
        cluster_pck=cluster_pck,
        agi_cluster=str(tmp_path / "cluster-runtime"),
        debug=False,
        is_local=lambda ip: ip == "127.0.0.1",
    )
    agi_cls = SimpleNamespace(env=env)
    local_runs: list[tuple[str, str]] = []
    remote_runs: list[tuple[str, str]] = []
    copied: list[tuple[Path, Path]] = []
    detected: list[str] = []
    log = mock.Mock()

    async def _fake_run(cmd, cwd):
        local_runs.append((cmd, cwd))
        return None

    async def _fake_exec_ssh(ip, cmd):
        remote_runs.append((ip, cmd))
        return {"stdout": "killed", "stderr": "warn"}

    def _fake_copy(src, dst):
        copied.append((Path(src), Path(dst)))

    async def _fake_detect_export_cmd(ip):
        detected.append(ip)
        return 'export PATH="$HOME/.local/bin:$PATH";'

    original_unlink = Path.unlink

    def _patched_unlink(self, *args, **kwargs):
        if self == stubborn:
            raise OSError("locked")
        return original_unlink(self, *args, **kwargs)

    agi_cls.exec_ssh = _fake_exec_ssh

    with mock.patch.object(cleanup_support.Path, "unlink", _patched_unlink, create=True):
        await cleanup_support.kill_processes(
            agi_cls,
            current_pid=999,
            gethostbyname_fn=lambda _name: "127.0.0.1",
            run_fn=_fake_run,
            copy_fn=_fake_copy,
            detect_export_cmd_fn=_fake_detect_export_cmd,
            log=log,
        )
        await cleanup_support.kill_processes(
            agi_cls,
            ip="10.0.0.2",
            current_pid=999,
            gethostbyname_fn=lambda _name: "127.0.0.1",
            run_fn=_fake_run,
            copy_fn=_fake_copy,
            detect_export_cmd_fn=_fake_detect_export_cmd,
            log=log,
        )

    assert copied
    assert local_runs
    assert "--with" not in local_runs[0][0]
    local_argv = shlex.split(local_runs[0][0], posix=True)
    assert local_argv == [
        str(Path(sys.executable)),
        (wenv_parent / "cli.py").as_posix(),
        "kill",
        wenv_abs.as_posix(),
        "999",
    ]
    assert all(cwd == str(wenv_abs) for _cmd, cwd in local_runs)
    assert len(remote_runs) == 1
    assert remote_runs[0][0] == "10.0.0.2"
    remote_command = remote_runs[0][1].split(";", 1)[1]
    assert remote_command.startswith("if [ -x ")
    assert ".venv/bin/python" in remote_command
    assert "; then " in remote_command
    assert "; else " in remote_command
    assert " || " not in remote_command
    direct_command = remote_command.split("; then ", 1)[1].split("; else ", 1)[0]
    direct_argv = shlex.split(direct_command, posix=True)
    assert direct_argv == [
        "w env's/demo worker/.venv/bin/python",
        "w env's/cli.py",
        "kill",
        "w env's/demo worker",
    ]
    fallback_command = remote_command.split("; else ", 1)[1].rsplit("; fi", 1)[0]
    fallback_argv = shlex.split(fallback_command, posix=True)
    assert fallback_argv == [
        "uv",
        "run",
        "--no-sync",
        "--with",
        "psutil>=7,<8",
        "python",
        "w env's/cli.py",
        "kill",
        "w env's/demo worker",
    ]
    assert detected == ["10.0.0.2"]
    assert env.envars["10.0.0.2_CMD_PREFIX"] == 'export PATH="$HOME/.local/bin:$PATH";'
    # The manager no longer unlinks ownership records before the worker CLI
    # has validated and acted on them.
    assert (wenv_parent / "ok.pid").exists()
    assert log.info.called
    assert log.error.called


@pytest.mark.asyncio
async def test_kill_processes_prefers_installed_windows_worker_python(tmp_path):
    wenv_abs = tmp_path / "worker env"
    worker_python = wenv_abs / ".venv" / "Scripts" / "python.exe"
    worker_python.parent.mkdir(parents=True)
    worker_python.write_text("", encoding="utf-8")
    cli_abs = wenv_abs.parent / "cli.py"
    cli_abs.write_text("print('cli')\n", encoding="utf-8")
    env = SimpleNamespace(
        uv="uv",
        wenv_abs=wenv_abs,
        wenv_rel=Path("wenv/demo worker"),
        envars={},
        debug=False,
        is_local=lambda _ip: True,
    )
    runs = []

    async def _run(cmd, cwd):
        runs.append((cmd, cwd))

    await cleanup_support.kill_processes(
        SimpleNamespace(env=env),
        current_pid=321,
        gethostbyname_fn=lambda _name: "127.0.0.1",
        run_fn=_run,
        os_name="nt",
    )

    assert len(runs) == 1
    argv = shlex.split(runs[0][0], posix=True)
    assert argv[0] == worker_python.as_posix()
    assert argv[-3:] == ["kill", wenv_abs.as_posix(), "321"]
    assert "--with" not in argv


@pytest.mark.asyncio
async def test_kill_processes_uses_manager_python_for_partial_windows_worker(tmp_path):
    wenv_abs = tmp_path / "worker env"
    wenv_abs.mkdir(parents=True)
    cli_abs = wenv_abs.parent / "cli.py"
    cli_abs.write_text("print('cli')\n", encoding="utf-8")
    manager_python = tmp_path / "manager env" / "Scripts" / "python.exe"
    env = SimpleNamespace(
        uv="uv",
        wenv_abs=wenv_abs,
        wenv_rel=Path("wenv/demo worker"),
        envars={},
        debug=False,
        is_local=lambda _ip: True,
    )
    runs = []

    async def _run(cmd, cwd):
        runs.append((cmd, cwd))

    await cleanup_support.kill_processes(
        SimpleNamespace(env=env),
        current_pid=321,
        gethostbyname_fn=lambda _name: "127.0.0.1",
        run_fn=_run,
        os_name="nt",
        sys_module=SimpleNamespace(executable=str(manager_python), argv=[]),
    )

    assert len(runs) == 1
    argv = shlex.split(runs[0][0], posix=True)
    assert argv[0] == str(manager_python)
    assert argv[-3:] == ["kill", wenv_abs.as_posix(), "321"]
    assert "--with" not in argv
    assert "<" not in runs[0][0]


@pytest.mark.asyncio
async def test_kill_processes_local_debug_uses_run_path_and_skips_current_pid(tmp_path):
    wenv_parent = tmp_path / "w env's"
    wenv_abs = wenv_parent / "demo_worker"
    wenv_abs.mkdir(parents=True)
    cluster_pck = tmp_path / "cluster"
    cli_source = cluster_pck / "agi_distributor" / "cli.py"
    cli_source.parent.mkdir(parents=True)
    cli_source.write_text("print('cli')\n", encoding="utf-8")
    current_pid_file = wenv_parent / "current.pid"
    current_pid_file.write_text("999\n", encoding="utf-8")

    env = SimpleNamespace(
        uv="uv",
        wenv_abs=wenv_abs,
        wenv_rel=Path("wenv/demo_worker"),
        envars={},
        cluster_pck=cluster_pck,
        agi_cluster=str(tmp_path / "cluster-runtime"),
        debug=True,
        is_local=lambda ip: ip == "127.0.0.1",
    )
    agi_cls = SimpleNamespace(env=env)
    run_path_calls = []

    await cleanup_support.kill_processes(
        agi_cls,
        current_pid=999,
        gethostbyname_fn=lambda _name: "127.0.0.1",
        run_fn=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("run_fn should not be used in debug mode")
        ),
        run_path_fn=lambda path, run_name=None: run_path_calls.append((path, run_name)),
        sys_module=SimpleNamespace(argv=[]),
        log=mock.Mock(),
    )

    assert current_pid_file.exists()
    assert run_path_calls == [(str(wenv_parent / "cli.py"), "__main__")]


def test_clean_dirs_local_kills_dask_processes_before_verified_delete(tmp_path):
    agi_cls = SimpleNamespace(env=_local_cleanup_env(tmp_path))
    agi_cls.env.wenv_abs.mkdir(parents=True, exist_ok=True)
    owned_pid = agi_cls.env.wenv_abs / "dask_worker_0.pid"
    owned_pid.write_text("4242\n", encoding="utf-8")
    killed: list[int] = []
    waited: list[tuple[int, float]] = []
    removed: list[str] = []
    real_rmtree = cleanup_support.shutil.rmtree

    def _remove(path, onerror=None):
        removed.append(path)
        real_rmtree(path, onerror=onerror)

    class _Proc:
        def __init__(self, info, raise_on_kill=False):
            self.info = info
            self._raise_on_kill = raise_on_kill

        def kill(self):
            if self._raise_on_kill:
                raise psutil.AccessDenied(pid=self.info["pid"])
            killed.append(self.info["pid"])
            self.info["cmdline"] = []

        def wait(self, timeout):
            waited.append((self.info["pid"], timeout))
            return 0

    procs = [
        _Proc({"pid": 100, "username": "me", "cmdline": ["dask-worker"]}),
        _Proc({"pid": 4242, "username": "me", "cmdline": ["dask", "worker", str(agi_cls.env.wenv_abs)]}),
        _Proc({"pid": 4343, "username": "me", "cmdline": ["python", "other"]}),
        _Proc({"pid": 4444, "username": "me", "cmdline": ["python", "dask scheduler"]}, raise_on_kill=True),
    ]

    cleanup_support.clean_dirs_local(
        agi_cls,
        process_iter_fn=lambda *_a, **_k: procs,
        getuser_fn=lambda: "me",
        getpid_fn=lambda: 100,
        rmtree_fn=_remove,
    )

    assert 4242 in killed
    assert 4343 not in killed
    assert waited == [(4242, 3.0)]
    assert removed == [str(agi_cls.env.wenv_abs.resolve())]


def test_clean_dirs_local_only_kills_exact_username_matches(tmp_path):
    # Regression: the suffix match (username.endswith(me)) let user 'ed'
    # kill processes owned by 'fred'; only exact matches (after DOMAIN\
    # normalization) may be killed.
    agi_cls = SimpleNamespace(env=_local_cleanup_env(tmp_path))
    agi_cls.env.wenv_abs.mkdir(parents=True, exist_ok=True)
    for pid in (200, 201, 202):
        (agi_cls.env.wenv_abs / f"dask_worker_{pid}.pid").write_text(
            f"{pid}\n", encoding="utf-8"
        )
    killed: list[int] = []

    class _Proc:
        def __init__(self, info):
            self.info = info

        def kill(self):
            killed.append(self.info["pid"])
            self.info["cmdline"] = []

    procs = [
        _Proc({"pid": 200, "username": "fred", "cmdline": ["dask-worker", f"{agi_cls.env.wenv_abs}-other"]}),
        _Proc({"pid": 201, "username": "ed", "cmdline": ["dask-worker", str(agi_cls.env.wenv_abs)]}),
        _Proc({"pid": 202, "username": "CORP\\ed", "cmdline": ["dask", "scheduler", str(agi_cls.env.wenv_abs)]}),
    ]

    cleanup_support.clean_dirs_local(
        agi_cls,
        process_iter_fn=lambda *_a, **_k: procs,
        getuser_fn=lambda: "ed",
        getpid_fn=lambda: 100,
    )

    assert killed == [201, 202]


def test_clean_dirs_local_preserves_live_sibling_pid_evidence(tmp_path):
    env = _local_cleanup_env(tmp_path, "target_worker")
    target = env.wenv_abs
    sibling = target.parent / "sibling_worker"
    target.mkdir(parents=True)
    sibling.mkdir()
    target_pid_file = target.parent / "dask_worker_target.pid"
    sibling_pid_file = target.parent / "dask_worker_sibling.pid"
    target_pid_file.write_text(
        '{"pid": 321, "process_start_time": 10.0}\n',
        encoding="utf-8",
    )
    sibling_payload = b'{"pid": 654, "process_start_time": 20.0}\n'
    sibling_pid_file.write_bytes(sibling_payload)
    killed = []

    class _Proc:
        def __init__(self, info):
            self.info = info

        def kill(self):
            killed.append(self.info["pid"])
            self.info["cmdline"] = []

        def wait(self, timeout):
            return 0

    target_proc = _Proc(
        {
            "pid": 321,
            "username": "me",
            "cmdline": ["dask", "worker", str(target)],
            "create_time": 10.0,
        }
    )
    sibling_proc = _Proc(
        {
            "pid": 654,
            "username": "me",
            "cmdline": [
                "dask",
                "worker",
                str(sibling),
                f"--pid-file={sibling_pid_file}",
            ],
            "create_time": 20.0,
        }
    )
    processes = [target_proc, sibling_proc]

    cleanup_support.clean_dirs_local(
        SimpleNamespace(env=env),
        process_iter_fn=lambda *_a, **_k: processes,
        getuser_fn=lambda: "me",
        getpid_fn=lambda: 999,
    )

    assert killed == [321]
    assert not target.exists()
    assert not target_pid_file.exists()
    assert sibling.exists()
    assert sibling_pid_file.read_bytes() == sibling_payload


def test_clean_dirs_local_refuses_out_of_scope_target_before_process_mutation(tmp_path):
    home = tmp_path / "home"
    unsafe_target = tmp_path / "outside" / "worker"
    unsafe_target.mkdir(parents=True)
    env = SimpleNamespace(home_abs=home, wenv_abs=unsafe_target)

    with pytest.raises(RuntimeError, match="Refusing unsafe"):
        cleanup_support.clean_dirs_local(
            SimpleNamespace(env=env),
            process_iter_fn=lambda *_a, **_k: (_ for _ in ()).throw(
                AssertionError("process scan must follow target validation")
            ),
        )

    assert unsafe_target.exists()


def test_clean_dirs_local_refuses_symlink_alias_outside_worker_root(tmp_path):
    env = _local_cleanup_env(tmp_path, "aliased_worker")
    outside = tmp_path / "outside"
    env.wenv_abs.parent.mkdir(parents=True)
    outside.mkdir()
    try:
        env.wenv_abs.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    with pytest.raises(RuntimeError, match="Refusing unsafe"):
        cleanup_support.clean_dirs_local(
            SimpleNamespace(env=env),
            process_iter_fn=lambda *_a, **_k: [],
        )

    assert outside.exists()


def test_clean_dirs_local_reports_rmtree_typeerror(tmp_path):
    agi_cls = SimpleNamespace(env=_local_cleanup_env(tmp_path))
    agi_cls.env.wenv_abs.mkdir(parents=True, exist_ok=True)
    removed = []

    def _fake_rmtree(path, onerror=None):
        removed.append((path, onerror is not None))
        raise TypeError("bad signature")

    with pytest.raises(RuntimeError, match="PID ownership evidence was retained"):
        cleanup_support.clean_dirs_local(
            agi_cls,
            process_iter_fn=lambda *_a, **_k: [],
            getuser_fn=lambda: "me",
            getpid_fn=lambda: 100,
            rmtree_fn=_fake_rmtree,
        )

    assert removed == [(str(agi_cls.env.wenv_abs.resolve()), True)]


def test_clean_dirs_local_retries_partial_delete_and_restores_pid_evidence(tmp_path):
    env = _local_cleanup_env(tmp_path)
    wenv_abs = env.wenv_abs
    wenv_abs.mkdir(parents=True)
    pid_file = wenv_abs / "dask_worker_0.pid"
    payload = b'{"pid": 321, "process_start_time": 10.0}\n'
    pid_file.write_bytes(payload)
    attempts = []

    def _partial_delete(path, onerror=None):
        attempts.append((path, onerror is not None))
        pid_file.unlink(missing_ok=True)
        raise OSError("locked remainder")

    with pytest.raises(RuntimeError, match="PID ownership evidence was retained"):
        cleanup_support.clean_dirs_local(
            SimpleNamespace(env=env),
            process_iter_fn=lambda *_a, **_k: [],
            getuser_fn=lambda: "me",
            getpid_fn=lambda: 999,
            rmtree_fn=_partial_delete,
            sleep_fn=lambda _seconds: None,
        )

    assert attempts == [
        (str(wenv_abs.resolve()), True),
        (str(wenv_abs.resolve()), True),
    ]
    assert pid_file.read_bytes() == payload


def test_failed_target_delete_does_not_resurrect_removed_sibling_pid_evidence(
    tmp_path,
):
    env = _local_cleanup_env(tmp_path, "target_worker")
    wenv_abs = env.wenv_abs
    wenv_abs.mkdir(parents=True)
    target_pid_file = wenv_abs / "dask_worker_0.pid"
    sibling_pid_file = wenv_abs.parent / "dask_worker_sibling.pid"
    target_payload = b'{"pid": 321, "process_start_time": 10.0}\n'
    target_pid_file.write_bytes(target_payload)
    sibling_pid_file.write_bytes(
        b'{"pid": 654, "process_start_time": 20.0}\n'
    )

    def _partial_delete(_path, onerror=None):
        target_pid_file.unlink(missing_ok=True)
        sibling_pid_file.unlink(missing_ok=True)
        raise OSError("locked remainder")

    with pytest.raises(RuntimeError, match="PID ownership evidence was retained"):
        cleanup_support.clean_dirs_local(
            SimpleNamespace(env=env),
            process_iter_fn=lambda *_a, **_k: [],
            getuser_fn=lambda: "me",
            getpid_fn=lambda: 999,
            rmtree_fn=_partial_delete,
            sleep_fn=lambda _seconds: None,
        )

    assert target_pid_file.read_bytes() == target_payload
    assert not sibling_pid_file.exists()


def test_clean_dirs_local_preserves_unowned_dask_and_reused_pid(tmp_path):
    env = _local_cleanup_env(tmp_path)
    wenv_abs = env.wenv_abs
    wenv_abs.mkdir(parents=True)
    (wenv_abs / "dask_worker_0.pid").write_text(
        '{"pid": 321, "process_start_time": 10.0}\n',
        encoding="utf-8",
    )
    killed = []

    class _Proc:
        info = {
            "pid": 321,
            "username": "me",
            "cmdline": ["dask", "worker", str(wenv_abs)],
            # Same PID now belongs to a later process generation.
            "create_time": 20.0,
        }

        def kill(self):
            killed.append(321)

    removed = []
    with pytest.raises(RuntimeError, match="still reference the target"):
        cleanup_support.clean_dirs_local(
            SimpleNamespace(env=env),
            process_iter_fn=lambda *_a, **_k: [_Proc()],
            getuser_fn=lambda: "me",
            getpid_fn=lambda: 999,
            rmtree_fn=lambda path, **_kwargs: removed.append(path),
        )

    assert killed == []
    assert removed == []


def test_command_target_match_rejects_path_prefix_collision(tmp_path):
    wenv_abs = tmp_path / "wenv"
    pid_file = wenv_abs / "dask_worker_0.pid"

    assert cleanup_support._command_belongs_to_target(
        ["dask-worker", f"{wenv_abs}-other/bin/python"],
        pid_file=pid_file,
        wenv_abs=wenv_abs,
    ) is False
    assert cleanup_support._command_belongs_to_target(
        ["dask-worker", f"--pid-file={pid_file}"],
        pid_file=pid_file,
        wenv_abs=wenv_abs,
    ) is True


def test_clean_dirs_local_refuses_active_target_without_pid_file(tmp_path):
    env = _local_cleanup_env(tmp_path)
    wenv_abs = env.wenv_abs
    wenv_abs.mkdir(parents=True)
    removed = []

    class _Proc:
        info = {
            "pid": 321,
            "username": "me",
            "cmdline": [str(wenv_abs / "bin" / "python"), "-m", "distributed.cli.dask_worker"],
        }

    with pytest.raises(RuntimeError, match="still reference the target"):
        cleanup_support.clean_dirs_local(
            SimpleNamespace(env=env),
            process_iter_fn=lambda *_a, **_k: [_Proc()],
            getuser_fn=lambda: "me",
            getpid_fn=lambda: 999,
            rmtree_fn=lambda path, **_kwargs: removed.append(path),
        )

    assert removed == []


def test_clean_dirs_local_refuses_delete_when_owned_process_cannot_be_stopped(tmp_path):
    env = _local_cleanup_env(tmp_path)
    wenv_abs = env.wenv_abs
    wenv_abs.mkdir(parents=True)
    (wenv_abs / "dask_worker_0.pid").write_text("321\n", encoding="utf-8")
    removed = []

    class _Proc:
        info = {
            "pid": 321,
            "username": "me",
            "cmdline": ["dask", "worker", str(wenv_abs)],
        }

        def kill(self):
            raise psutil.AccessDenied(pid=321)

    with pytest.raises(RuntimeError, match="remain active"):
        cleanup_support.clean_dirs_local(
            SimpleNamespace(env=env),
            process_iter_fn=lambda *_a, **_k: [_Proc()],
            getuser_fn=lambda: "me",
            getpid_fn=lambda: 999,
            rmtree_fn=lambda path, ignore_errors=True: removed.append(path),
        )

    assert removed == []


def test_force_clean_dirs_local_is_explicit_broad_operator_path(tmp_path):
    env = _local_cleanup_env(tmp_path)
    wenv_abs = env.wenv_abs
    wenv_abs.mkdir(parents=True)
    killed = []
    removed = []

    class _Proc:
        info = {"pid": 321, "username": "me", "cmdline": ["dask-scheduler"]}

        def kill(self):
            killed.append(321)

    cleanup_support.force_clean_dirs_local(
        SimpleNamespace(env=env),
        process_iter_fn=lambda *_a, **_k: [_Proc()],
        getuser_fn=lambda: "me",
        getpid_fn=lambda: 999,
        rmtree_fn=lambda path, ignore_errors=True: removed.append(path),
        # A trailing native separator makes raw string concatenation produce a
        # malformed path on every platform, not only a mixed path on Windows.
        gettempdir_fn=lambda: f"{tmp_path / 'tmp'}{os.sep}",
    )

    assert killed == [321]
    assert removed == [
        str(tmp_path / "tmp" / "dask-scratch-space"),
        str(wenv_abs),
    ]


@pytest.mark.asyncio
async def test_clean_dirs_removes_local_wenv_and_execs_remote(tmp_path):
    wenv_abs = tmp_path / "wenv"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    env = SimpleNamespace(
        uv="/usr/bin/uv",
        wenv_abs=wenv_abs,
        wenv_rel=Path("w env's"),
        python_version="3.13",
        envars={"10.0.0.9_CMD_PREFIX": "source /env && "},
    )
    agi_cls = SimpleNamespace(env=env)
    removed: list[str] = []
    made_dirs: list[tuple[Path, bool]] = []
    ssh_calls: list[tuple[str, str]] = []

    async def _fake_exec(ip, cmd):
        ssh_calls.append((ip, cmd))
        return "ok"

    agi_cls.exec_ssh = _fake_exec

    await cleanup_support.clean_dirs(
        agi_cls,
        "10.0.0.9",
        makedirs_fn=lambda path, exist_ok=True: made_dirs.append((path, exist_ok)),
        remove_dir_forcefully_fn=lambda path: removed.append(path),
    )

    assert removed == []
    assert made_dirs == []
    assert ssh_calls
    command = ssh_calls[0][1].split("&& ", 1)[1]
    assert command.startswith("if [ -x ")
    assert " || " not in command
    direct = shlex.split(
        command.split("; then ", 1)[1].split("; else ", 1)[0],
        posix=True,
    )
    assert direct == [
        "w env's/.venv/bin/python",
        "cli.py",
        "clean",
        "w env's",
    ]
    fallback = shlex.split(
        command.split("; else ", 1)[1].rsplit("; fi", 1)[0],
        posix=True,
    )
    assert fallback == [
        "/usr/bin/uv",
        "run",
        "--no-sync",
        "--with",
        "psutil>=7,<8",
        "-p",
        "3.13",
        "python",
        "cli.py",
        "clean",
        "w env's",
    ]


@pytest.mark.asyncio
async def test_remote_target_lease_token_wraps_remote_clean_lifecycle(tmp_path):
    env = SimpleNamespace(
        uv="/usr/bin/uv",
        wenv_rel=Path("w env's/demo worker"),
        python_version="3.13",
        envars={},
    )
    calls = []

    async def _exec(ip, cmd):
        calls.append((ip, cmd))
        return "ok"

    agi_cls = SimpleNamespace(
        env=env,
        exec_ssh=_exec,
        _lifecycle_call_token="a" * 32,
        _lifecycle_call_operation="install",
        _remote_target_leases={},
    )

    lease = await cleanup_support.acquire_remote_target_lease(
        agi_cls,
        "10.0.0.9",
        cmd_prefix="",
    )
    await cleanup_support.clean_dirs(agi_cls, "10.0.0.9")
    await cleanup_support.release_remote_target_leases(agi_cls)

    assert lease.token == "a" * 32
    acquire_argv = shlex.split(calls[0][1], posix=True)
    release_argv = shlex.split(calls[2][1], posix=True)
    assert acquire_argv[acquire_argv.index("python") + 2] == "target-lease-acquire"
    assert release_argv[release_argv.index("python") + 2] == "target-lease-release"
    clean_command = calls[1][1]
    assert " || " not in clean_command
    assert " clean " in clean_command
    fallback = shlex.split(
        clean_command.split("; else ", 1)[1].rsplit("; fi", 1)[0],
        posix=True,
    )
    assert fallback[3:5] == ["--with", "psutil>=7,<8"]
    assert fallback[-1] == "a" * 32
    assert agi_cls._remote_target_leases == {}


@pytest.mark.asyncio
async def test_remote_target_lease_uses_identity_proven_recovery_capabilities():
    env = SimpleNamespace(
        uv="/usr/bin/uv",
        wenv_rel=Path("workers/demo"),
        python_version="3.13",
        envars={},
    )
    calls = []

    async def _exec(ip, cmd):
        calls.append((ip, shlex.split(cmd, posix=True)))
        return "ok"

    agi_cls = SimpleNamespace(
        env=env,
        exec_ssh=_exec,
        _lifecycle_call_token="f" * 32,
        _lifecycle_remote_token="b" * 32,
        _lifecycle_remote_recovery_tokens=("a" * 32,),
        _lifecycle_call_operation="run",
        _remote_target_leases={},
    )

    lease = await cleanup_support.acquire_remote_target_lease(
        agi_cls,
        "10.0.0.9",
        cmd_prefix="",
    )

    argv = calls[0][1]
    assert lease.token == "b" * 32
    assert lease.recovery_tokens == ("a" * 32,)
    assert argv[7:] == [
        "target-lease-recover",
        "workers/demo",
        "b" * 32,
        "a" * 32,
        "run",
    ]


@pytest.mark.asyncio
async def test_remote_acquire_transport_failure_retains_exact_local_evidence():
    env = SimpleNamespace(
        uv="/usr/bin/uv",
        wenv_rel=Path("workers/demo"),
        python_version="3.13",
        envars={},
    )
    agi_cls = SimpleNamespace(
        env=env,
        exec_ssh=lambda *_args: None,
        _lifecycle_remote_token="b" * 32,
        _lifecycle_call_operation="run",
        _remote_target_leases={},
    )

    async def _failed_exec(*_args):
        raise RuntimeError("transport failed after remote claim")

    agi_cls.exec_ssh = _failed_exec
    with pytest.raises(RuntimeError, match="transport failed"):
        await cleanup_support.acquire_remote_target_lease(
            agi_cls,
            "10.0.0.9",
            cmd_prefix="",
        )

    retained = agi_cls._remote_target_leases["10.0.0.9"]
    assert retained.token == "b" * 32
    assert retained.target == Path("workers/demo")


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["token", "target"])
async def test_acquire_rejects_mismatched_cached_remote_lease(mismatch):
    env = SimpleNamespace(
        uv="/usr/bin/uv",
        wenv_rel=Path("workers/demo"),
        python_version="3.13",
        envars={},
    )
    active_token = "b" * 32
    cached = cleanup_support.RemoteTargetLease(
        ip="10.0.0.9",
        target=Path("workers/other" if mismatch == "target" else "workers/demo"),
        token="a" * 32 if mismatch == "token" else active_token,
        operation="install",
        cmd_prefix="",
    )
    ssh_calls = []

    async def _exec(*args):
        ssh_calls.append(args)

    agi_cls = SimpleNamespace(
        env=env,
        exec_ssh=_exec,
        _lifecycle_remote_token=active_token,
        _lifecycle_call_operation="run",
        _remote_target_leases={"10.0.0.9": cached},
    )

    with pytest.raises(RuntimeError, match="does not match"):
        await cleanup_support.acquire_remote_target_lease(
            agi_cls,
            "10.0.0.9",
            cmd_prefix="",
        )

    assert ssh_calls == []


@pytest.mark.asyncio
async def test_clean_rejects_cached_remote_lease_for_another_target():
    env = SimpleNamespace(
        uv="/usr/bin/uv",
        wenv_rel=Path("workers/demo"),
        python_version="3.13",
        envars={},
    )
    active_token = "b" * 32
    cached = cleanup_support.RemoteTargetLease(
        ip="10.0.0.9",
        target=Path("workers/other"),
        token=active_token,
        operation="install",
        cmd_prefix="",
    )
    ssh_calls = []

    async def _exec(*args):
        ssh_calls.append(args)

    agi_cls = SimpleNamespace(
        env=env,
        exec_ssh=_exec,
        _lifecycle_remote_token=active_token,
        _remote_target_leases={"10.0.0.9": cached},
    )

    with pytest.raises(RuntimeError, match="does not match"):
        await cleanup_support.clean_dirs(agi_cls, "10.0.0.9")

    assert ssh_calls == []
