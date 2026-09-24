"""SSH transport contracts with synthetic streams and owned fake processes."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agi_cluster.agi_distributor.runtime import transport_support as transport


def _owner(connection):
    @asynccontextmanager
    async def connect(_ip):
        yield connection
    return SimpleNamespace(get_ssh_connection=connect, _worker_init_error=False)


@pytest.mark.parametrize("stdout,stderr", [(b"result\xff", b"progress\xff"), ("", ""), ("result", "progress")])
def test_sync_ssh_verbose_text_and_bytes(stdout, stderr, monkeypatch):
    monkeypatch.setattr(transport, "_verbose_logging_enabled", lambda: True)
    run = AsyncMock(return_value=SimpleNamespace(stdout=stdout, stderr=stderr))
    log = Mock()
    result = asyncio.run(transport.exec_ssh(_owner(SimpleNamespace(run=run)), "worker", "command", log=log))
    def expected(value):
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    assert result == expected(stdout) + "\n" + expected(stderr)
    run.assert_awaited_once_with("command", check=True)
    assert log.info.call_count == 1 + bool(stdout) + bool(stderr)


def test_sync_ssh_process_error_preserves_original_and_decodes_diagnostics():
    class FailedProcess(Exception):
        stdout = b"output\xff"
        stderr = b"failure\xff"
    error = FailedProcess()
    log = Mock()
    with pytest.raises(FailedProcess) as caught:
        asyncio.run(transport.exec_ssh(
            _owner(SimpleNamespace(run=AsyncMock(side_effect=error))), "worker", "command",
            process_error_cls=FailedProcess, log=log,
        ))
    assert caught.value is error
    log.error.assert_called_once_with("Remote command stderr: failure\ufffd")


@pytest.mark.parametrize("chunks,expected", [
    ([b"one", b"two", b""], b"onetwo"), (["é", "two", ""], "étwo"),
    ([b""], b""), ([""], ""),
])
def test_stream_reader_preserves_chunk_type_with_exact_utf8_budget(chunks, expected):
    reader = AsyncMock(side_effect=chunks)
    limit = len(expected if isinstance(expected, bytes) else expected.encode())
    assert asyncio.run(transport._read_stream_bounded(SimpleNamespace(read=reader), limit=limit)) == expected
    assert all(call.args[0] >= 1 for call in reader.await_args_list)


def test_remote_cleanup_uses_wait_when_wait_closed_is_unavailable():
    process = SimpleNamespace(kill=Mock(), close=Mock(), wait=AsyncMock())
    asyncio.run(transport._stop_remote_process(process))
    process.kill.assert_called_once_with()
    process.close.assert_called_once_with()
    process.wait.assert_awaited_once_with()


def test_stream_failure_cancels_other_reader_and_waits_for_cleanup():
    async def scenario():
        waiting = asyncio.Event()
        cancelled = asyncio.Event()
        async def blocked(_size):
            waiting.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()
        async def fail(_size):
            await waiting.wait()
            raise OSError("stream disconnected")
        process = SimpleNamespace(
            stdout=SimpleNamespace(read=fail), stderr=SimpleNamespace(read=blocked),
            terminate=Mock(), close=Mock(), wait_closed=AsyncMock(), wait=AsyncMock(),
        )
        owner = _owner(SimpleNamespace(create_process=AsyncMock(return_value=process)))
        with pytest.raises(OSError, match="stream disconnected"):
            await transport.exec_ssh_async(owner, "worker", "command")
        assert cancelled.is_set()
        process.terminate.assert_called_once_with()
        process.wait_closed.assert_awaited_once_with()
        process.wait.assert_not_awaited()
    asyncio.run(scenario())


def test_cancellation_during_stream_error_cleanup_still_reaps_process():
    async def scenario():
        cleaning = asyncio.Event()
        allow_reap = asyncio.Event()
        reaped = asyncio.Event()
        async def wait_closed():
            cleaning.set()
            await allow_reap.wait()
            reaped.set()
        process = SimpleNamespace(
            stdout=SimpleNamespace(read=AsyncMock(side_effect=OSError("disconnected"))),
            terminate=Mock(), close=Mock(), wait_closed=wait_closed,
        )
        task = asyncio.create_task(transport.exec_ssh_async(
            _owner(SimpleNamespace(create_process=AsyncMock(return_value=process))), "worker", "command"
        ))
        await cleaning.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        allow_reap.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert reaped.is_set()
    asyncio.run(scenario())


def test_cancellation_during_scp_timeout_cleanup_still_reaps_process(monkeypatch):
    async def scenario():
        cleaning = asyncio.Event()
        allow_reap = asyncio.Event()
        reaped = asyncio.Event()
        async def wait():
            cleaning.set()
            await allow_reap.wait()
            reaped.set()
        process = SimpleNamespace(
            communicate=AsyncMock(side_effect=asyncio.TimeoutError), kill=Mock(), wait=wait,
        )
        spawn = AsyncMock(return_value=process)
        monkeypatch.setattr(transport.asyncio, "create_subprocess_exec", spawn)
        task = asyncio.create_task(transport._run_scp_command(
            ["scp", "source", "target"], local_path="source", remote="target"
        ))
        await cleaning.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        allow_reap.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert reaped.is_set()
        process.kill.assert_called_once_with()
        assert spawn.call_args.kwargs["stdin"] == asyncio.subprocess.DEVNULL
    asyncio.run(scenario())


@pytest.mark.parametrize("stdout,stderr", [(b"[ProjectError] invalid", b""), (b"", b"[ProjectError] invalid")])
def test_async_remote_error_sets_worker_initialization_flag(stdout, stderr):
    process = SimpleNamespace(
        stdout=SimpleNamespace(read=AsyncMock(side_effect=[stdout, b""])),
        stderr=SimpleNamespace(read=AsyncMock(side_effect=[stderr, b""])),
        wait=AsyncMock(return_value=SimpleNamespace(exit_status=None)), exit_status=2,
    )
    owner = _owner(SimpleNamespace(create_process=AsyncMock(return_value=process)))
    with pytest.raises(ConnectionError, match="ProjectError"):
        asyncio.run(transport.exec_ssh_async(owner, "worker", "command", log=Mock()))
    assert owner._worker_init_error is True


@pytest.mark.parametrize("attribute,mapping,ambient,expected", [
    ("first", "second", "third", "first"),
    ("", "second", "third", "second"),
    (None, "", "third", "third"),
    (None, None, None, None),
    (17, None, None, "17"),
])
def test_transport_environment_precedence(monkeypatch, attribute, mapping, ambient, expected):
    key = "AGILAB_TEST_TRANSPORT_OPTION"
    if ambient is None:
        monkeypatch.delenv(key, raising=False)
    else:
        monkeypatch.setenv(key, ambient)
    env = SimpleNamespace(envars={key: mapping})
    setattr(env, key, attribute)
    assert transport._env_lookup(env, key) == expected


def test_local_file_copy_resolves_relative_destination_under_home(tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(transport, "_is_local_ip", lambda _: True)
    source = tmp_path / "source.txt"
    source.write_text("payload")
    home = tmp_path / "home"
    asyncio.run(transport.send_file(SimpleNamespace(home_abs=home), "local", source, Path("out/file.txt")))
    assert (home / "out/file.txt").read_text() == "payload"


def test_empty_file_batch_creates_no_transfer():
    sender = AsyncMock()
    asyncio.run(transport.send_files(SimpleNamespace(send_file=sender), SimpleNamespace(), "remote", [], None))
    sender.assert_not_awaited()


def test_password_on_windows_logs_auth_limitation_without_exposing_secret(tmp_path, monkeypatch):
    monkeypatch.setattr(transport, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(transport, "_scp_host_key_options", lambda _: [])
    run = AsyncMock()
    monkeypatch.setattr(transport, "_run_scp_command", run)
    log = Mock()
    source = tmp_path / "source"
    source.write_text("payload")
    asyncio.run(transport._send_remote_paths(
        SimpleNamespace(user="alice", password="secret-value"),
        "worker", [source], "remote/file", log=log,
    ))
    command = run.await_args.args[0]
    assert command[0] == "scp"
    assert "secret-value" not in repr(command)
    assert run.await_args.kwargs["extra_env"] == {}
    log.error.assert_called_once()
    assert "secret-value" not in repr(log.error.call_args)


def test_remote_transfer_rethrows_last_error_after_one_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(transport, "_scp_host_key_options", lambda _: [])
    first, last = OSError("first failure"), ConnectionError("retry failed")
    run = AsyncMock(side_effect=[first, last])
    monkeypatch.setattr(transport, "_run_scp_command", run)
    with pytest.raises(ConnectionError) as caught:
        asyncio.run(transport._send_remote_paths(
            SimpleNamespace(user="alice", password=None), "worker", [tmp_path / "source"], "remote"
        ))
    assert caught.value is last
    assert run.await_count == 2
    assert "BatchMode=yes" in run.await_args.args[0]


def test_missing_known_hosts_file_does_not_spawn_keygen(tmp_path, monkeypatch):
    run = Mock()
    monkeypatch.setattr(transport.subprocess, "run", run)
    assert transport._known_host_entry_exists("worker", tmp_path / "missing") is False
    run.assert_not_called()


@pytest.mark.parametrize("error", [OSError("keyscan absent"), transport.subprocess.TimeoutExpired("ssh-keyscan", 10)])
def test_keyscan_failure_preserves_existing_keys(tmp_path, monkeypatch, error):
    target = tmp_path / "known_hosts"
    target.write_text("original-key\n")
    monkeypatch.setattr(transport.subprocess, "run", Mock(side_effect=error))
    assert transport._append_known_host_from_scan("worker", target, log=Mock()) is False
    assert target.read_text() == "original-key\n"


def test_keyscan_permission_failure_still_appends_exact_returned_keys(tmp_path, monkeypatch):
    from pathlib import Path
    target = tmp_path / "known_hosts"
    target.write_text("old-key\n")
    monkeypatch.setattr(transport, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(Path, "chmod", Mock(side_effect=OSError("filesystem has no chmod")))
    monkeypatch.setattr(transport.subprocess, "run", Mock(return_value=SimpleNamespace(
        stdout="# scanner\n\nhashed-host ssh-ed25519 payload\n", stderr="", returncode=0,
    )))
    assert transport._append_known_host_from_scan("worker", target, log=Mock()) is True
    assert target.read_text() == "old-key\nhashed-host ssh-ed25519 payload\n"


def test_private_key_probe_rejects_directory(tmp_path):
    assert transport.is_private_ssh_key_file(tmp_path) is False
