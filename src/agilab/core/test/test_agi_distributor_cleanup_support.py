from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
import psutil

from agi_cluster.agi_distributor import cleanup_support


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
        wenv_rel=Path("wenv/demo_worker"),
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
    log = mock.Mock()

    async def _fake_run(cmd, cwd):
        local_runs.append((cmd, cwd))
        return None

    async def _fake_exec_ssh(ip, cmd):
        remote_runs.append((ip, cmd))
        return {"stdout": "killed", "stderr": "warn"}

    def _fake_copy(src, dst):
        copied.append((Path(src), Path(dst)))

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
            log=log,
        )
        await cleanup_support.kill_processes(
            agi_cls,
            ip="10.0.0.2",
            current_pid=999,
            gethostbyname_fn=lambda _name: "127.0.0.1",
            run_fn=_fake_run,
            copy_fn=_fake_copy,
            log=log,
        )

    assert copied
    assert local_runs
    assert any("cli.py' kill 999" in cmd for cmd, _cwd in local_runs)
    assert remote_runs == [("10.0.0.2", "uv run --no-sync python 'wenv/cli.py' kill")]
    assert not (wenv_parent / "ok.pid").exists()
    assert log.warning.called
    assert log.info.called
    assert log.error.called


def test_clean_dirs_local_kills_dask_processes_and_ignores_errors(tmp_path):
    agi_cls = SimpleNamespace(env=SimpleNamespace(wenv_abs=tmp_path / "wenv"))
    agi_cls.env.wenv_abs.mkdir(parents=True, exist_ok=True)
    killed: list[int] = []
    removed: list[tuple[str, bool]] = []

    class _Proc:
        def __init__(self, info, raise_on_kill=False):
            self.info = info
            self._raise_on_kill = raise_on_kill

        def kill(self):
            if self._raise_on_kill:
                raise psutil.AccessDenied(pid=self.info["pid"])
            killed.append(self.info["pid"])

    procs = [
        _Proc({"pid": 100, "username": "me", "cmdline": ["dask-worker"]}),
        _Proc({"pid": 4242, "username": "me", "cmdline": ["python", "DASK worker"]}),
        _Proc({"pid": 4343, "username": "me", "cmdline": ["python", "other"]}),
        _Proc({"pid": 4444, "username": "me", "cmdline": ["python", "dask scheduler"]}, raise_on_kill=True),
    ]

    cleanup_support.clean_dirs_local(
        agi_cls,
        process_iter_fn=lambda *_a, **_k: procs,
        getuser_fn=lambda: "me",
        getpid_fn=lambda: 100,
        rmtree_fn=lambda path, ignore_errors=True: removed.append((path, ignore_errors)),
        gettempdir_fn=lambda: "/tmp/demo",
    )

    assert 4242 in killed
    assert 4343 not in killed
    assert removed == [
        ("/tmp/demo/dask-scratch-space", True),
        (str(agi_cls.env.wenv_abs), True),
    ]


@pytest.mark.asyncio
async def test_clean_dirs_removes_local_wenv_and_execs_remote(tmp_path):
    wenv_abs = tmp_path / "wenv"
    wenv_abs.mkdir(parents=True, exist_ok=True)
    env = SimpleNamespace(
        uv="/usr/bin/uv",
        wenv_abs=wenv_abs,
        wenv_rel=Path("wenv"),
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

    assert removed == [str(wenv_abs)]
    assert made_dirs == [(wenv_abs / "src", True)]
    assert ssh_calls
    assert "clean wenv" in ssh_calls[0][1]
