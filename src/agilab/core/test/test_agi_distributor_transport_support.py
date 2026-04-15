from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_cluster.agi_distributor import transport_support


@pytest.mark.asyncio
async def test_send_file_local_relative_destination(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    local_file = tmp_path / "source.txt"
    local_file.write_text("payload", encoding="utf-8")
    env = SimpleNamespace(home_abs=str(home), user="user", password="pwd")

    monkeypatch.setattr(transport_support.AgiEnv, "is_local", staticmethod(lambda _ip: True))

    await transport_support.send_file(
        env=env,
        ip="127.0.0.1",
        local_path=local_file,
        remote_path=Path("remote/result.txt"),
    )

    copied = home / "remote" / "result.txt"
    assert copied.exists()
    assert copied.read_text(encoding="utf-8") == "payload"


@pytest.mark.asyncio
async def test_send_file_local_directory_copies_tree(monkeypatch, tmp_path):
    src_dir = tmp_path / "srcdir"
    (src_dir / "nested").mkdir(parents=True, exist_ok=True)
    (src_dir / "nested" / "data.txt").write_text("payload", encoding="utf-8")
    env = SimpleNamespace(home_abs=tmp_path / "home")

    monkeypatch.setattr(transport_support.AgiEnv, "is_local", staticmethod(lambda _ip: True))

    await transport_support.send_file(
        env=env,
        ip="127.0.0.1",
        local_path=src_dir,
        remote_path=Path("remote/srcdir"),
    )

    assert (
        env.home_abs / "remote" / "srcdir" / "nested" / "data.txt"
    ).read_text(encoding="utf-8") == "payload"


@pytest.mark.asyncio
async def test_send_file_remote_success_and_command_construction(monkeypatch, tmp_path):
    local_file = tmp_path / "src.bin"
    local_file.write_text("x", encoding="utf-8")
    env = SimpleNamespace(
        user="alice",
        password="secret",
        ssh_key_path=str(tmp_path / "id_rsa"),
    )
    calls = []

    class _Proc:
        returncode = 0

        async def communicate(self):
            return b"ok", b""

    async def _fake_subproc(*cmd, **_kwargs):
        calls.append(cmd)
        return _Proc()

    monkeypatch.setattr(transport_support.AgiEnv, "is_local", staticmethod(lambda _ip: False))
    monkeypatch.setattr(transport_support.asyncio, "create_subprocess_exec", _fake_subproc)

    await transport_support.send_file(
        env=env,
        ip="10.0.0.9",
        local_path=local_file,
        remote_path=Path("/tmp/remote.bin"),
        user=None,
        password=None,
    )

    assert len(calls) == 1
    flat = list(calls[0])
    assert flat[0] == "sshpass"
    assert "scp" in flat
    assert "-i" in flat
    assert str(local_file) in flat
    assert "alice@10.0.0.9:/tmp/remote.bin" in flat


@pytest.mark.asyncio
async def test_send_file_remote_retries_with_password_auth_on_first_failure(monkeypatch, tmp_path):
    local_file = tmp_path / "src.bin"
    local_file.write_text("x", encoding="utf-8")
    env = SimpleNamespace(user="alice", password="secret", ssh_key_path=None)
    calls = []
    procs = [
        SimpleNamespace(returncode=1, communicate=lambda: asyncio.sleep(0, result=(b"", b"fail-1"))),
        SimpleNamespace(returncode=0, communicate=lambda: asyncio.sleep(0, result=(b"ok", b""))),
    ]

    async def _fake_subproc(*cmd, **_kwargs):
        calls.append(cmd)
        return procs.pop(0)

    monkeypatch.setattr(transport_support.AgiEnv, "is_local", staticmethod(lambda _ip: False))
    monkeypatch.setattr(transport_support.asyncio, "create_subprocess_exec", _fake_subproc)

    await transport_support.send_file(
        env=env,
        ip="10.0.0.9",
        local_path=local_file,
        remote_path=Path("/tmp/remote.bin"),
    )

    assert len(calls) == 2
    assert calls[0][0] == "sshpass"
    assert calls[1][0] == "sshpass"
    assert "-p" in calls[0]
    assert "-p" in calls[1]


@pytest.mark.asyncio
async def test_send_file_remote_raises_after_retry_failure(monkeypatch, tmp_path):
    local_file = tmp_path / "src.bin"
    local_file.write_text("x", encoding="utf-8")
    env = SimpleNamespace(user="alice", password="secret", ssh_key_path=None)

    async def _fake_subproc(*_cmd, **_kwargs):
        return SimpleNamespace(
            returncode=1,
            communicate=lambda: asyncio.sleep(0, result=(b"", b"fail")),
        )

    monkeypatch.setattr(transport_support.AgiEnv, "is_local", staticmethod(lambda _ip: False))
    monkeypatch.setattr(transport_support.asyncio, "create_subprocess_exec", _fake_subproc)

    with pytest.raises(ConnectionError, match="SCP error"):
        await transport_support.send_file(
            env=env,
            ip="10.0.0.9",
            local_path=local_file,
            remote_path=Path("/tmp/remote.bin"),
        )


def test_discover_private_ssh_keys_ignores_config_and_public_metadata(tmp_path):
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "config").write_text("Host remote\n  User agi\n", encoding="utf-8")
    (ssh_dir / "known_hosts").write_text("remote ssh-ed25519 AAAA\n", encoding="utf-8")
    (ssh_dir / "authorized_keys").write_text("ssh-ed25519 AAAA comment\n", encoding="utf-8")
    (ssh_dir / "id_ed25519.pub").write_text("ssh-ed25519 AAAA comment\n", encoding="utf-8")
    (ssh_dir / "id_rsa").write_text(
        "-----BEGIN RSA PRIVATE KEY-----\nmock\n-----END RSA PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    (ssh_dir / "id_ed25519").write_text(
        "-----BEGIN OPENSSH PRIVATE KEY-----\nmock\n-----END OPENSSH PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    (ssh_dir / "id_rsa.old").write_text("stale backup", encoding="utf-8")

    keys = transport_support.discover_private_ssh_keys(ssh_dir)

    assert keys == [str(ssh_dir / "id_ed25519"), str(ssh_dir / "id_rsa")]


def test_private_key_discovery_handles_missing_dir_and_unreadable_files(tmp_path, monkeypatch):
    assert transport_support.discover_private_ssh_keys(tmp_path / ".ssh") == []

    unreadable = tmp_path / "id_demo"
    unreadable.write_text("x", encoding="utf-8")
    monkeypatch.setattr(Path, "read_text", lambda self, *args, **kwargs: (_ for _ in ()).throw(OSError("boom")), raising=False)

    assert transport_support.is_private_ssh_key_file(unreadable) is False


@pytest.mark.asyncio
async def test_send_files_delegates_to_send_file(tmp_path):
    sent = []
    files = [tmp_path / "a.txt", tmp_path / "b.txt"]
    for file_path in files:
        file_path.write_text("x", encoding="utf-8")

    async def _fake_send_file(_env, ip, local_path, remote_path, user=None, password=None):
        sent.append((ip, local_path.name, remote_path.name, user))

    agi_cls = SimpleNamespace(send_file=_fake_send_file)
    await transport_support.send_files(
        agi_cls,
        SimpleNamespace(),
        "10.0.0.2",
        files,
        Path("/remote"),
        user="bob",
    )

    assert sent == [
        ("10.0.0.2", "a.txt", "a.txt", "bob"),
        ("10.0.0.2", "b.txt", "b.txt", "bob"),
    ]


@pytest.mark.asyncio
async def test_get_ssh_connection_reuses_cached_connection(monkeypatch):
    class _Conn:
        def is_closed(self):
            return False

    agi_cls = SimpleNamespace(
        env=SimpleNamespace(user="alice", password=None, ssh_key_path=None),
        _ssh_connections={"10.0.0.2": _Conn()},
    )
    monkeypatch.setattr(transport_support.AgiEnv, "is_local", staticmethod(lambda _ip: False))

    async with transport_support.get_ssh_connection(agi_cls, "10.0.0.2") as conn:
        assert conn is agi_cls._ssh_connections["10.0.0.2"]


@pytest.mark.asyncio
async def test_get_ssh_connection_requires_user_when_remote(monkeypatch):
    agi_cls = SimpleNamespace(
        env=SimpleNamespace(user=None, password=None, ssh_key_path=None),
        _ssh_connections={},
    )
    monkeypatch.setattr(transport_support.AgiEnv, "is_local", staticmethod(lambda _ip: False))

    with pytest.raises(ValueError, match="SSH username is not configured"):
        async with transport_support.get_ssh_connection(agi_cls, "10.0.0.2"):
            pass


@pytest.mark.asyncio
async def test_get_ssh_connection_timeout_permission_and_network(monkeypatch):
    agi_cls = SimpleNamespace(
        env=SimpleNamespace(user="alice", password=None, ssh_key_path=None),
        _ssh_connections={},
    )
    monkeypatch.setattr(transport_support.AgiEnv, "is_local", staticmethod(lambda _ip: False))

    async def _fake_connect(*_args, **_kwargs):
        return None

    monkeypatch.setattr(transport_support.asyncssh, "connect", _fake_connect)

    async def _raise_timeout(_awaitable, timeout):
        _awaitable.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(transport_support.asyncio, "wait_for", _raise_timeout)
    with pytest.raises(ConnectionError, match="timed out"):
        async with transport_support.get_ssh_connection(agi_cls, "10.0.0.2", timeout_sec=1):
            pass

    async def _raise_permission(_awaitable, timeout):
        _awaitable.close()
        raise transport_support.asyncssh.PermissionDenied("denied")

    monkeypatch.setattr(transport_support.asyncio, "wait_for", _raise_permission)
    with pytest.raises(ConnectionError, match="Authentication failed"):
        async with transport_support.get_ssh_connection(agi_cls, "10.0.0.3", timeout_sec=1):
            pass

    async def _raise_network(_awaitable, timeout):
        _awaitable.close()
        raise OSError(transport_support.errno.EHOSTUNREACH, "host unreachable")

    monkeypatch.setattr(transport_support.asyncio, "wait_for", _raise_network)
    with pytest.raises(ConnectionError, match="Unable to connect"):
        async with transport_support.get_ssh_connection(agi_cls, "10.0.0.4", timeout_sec=1):
            pass


@pytest.mark.asyncio
async def test_get_ssh_connection_handles_asyncssh_error(monkeypatch):
    agi_cls = SimpleNamespace(
        env=SimpleNamespace(user="alice", password=None, ssh_key_path=None),
        _ssh_connections={},
    )
    monkeypatch.setattr(transport_support.AgiEnv, "is_local", staticmethod(lambda _ip: False))

    async def _fake_connect(*_args, **_kwargs):
        return None

    monkeypatch.setattr(transport_support.asyncssh, "connect", _fake_connect)

    async def _raise_asyncssh(_awaitable, timeout):
        _awaitable.close()
        raise transport_support.asyncssh.Error(1, "generic ssh error")

    monkeypatch.setattr(transport_support.asyncio, "wait_for", _raise_asyncssh)
    with pytest.raises(ConnectionError, match="generic ssh error"):
        async with transport_support.get_ssh_connection(agi_cls, "10.0.0.5", timeout_sec=1):
            pass


@pytest.mark.asyncio
async def test_get_ssh_connection_wraps_unexpected_exception(monkeypatch):
    agi_cls = SimpleNamespace(
        env=SimpleNamespace(user="alice", password=None, ssh_key_path=None),
        _ssh_connections={},
    )
    monkeypatch.setattr(transport_support.AgiEnv, "is_local", staticmethod(lambda _ip: False))

    async def _fake_connect(*_args, **_kwargs):
        return None

    monkeypatch.setattr(transport_support.asyncssh, "connect", _fake_connect)

    async def _raise_unexpected(_awaitable, timeout):
        _awaitable.close()
        raise ValueError("boom")

    monkeypatch.setattr(transport_support.asyncio, "wait_for", _raise_unexpected)
    with pytest.raises(ConnectionError, match="Unexpected error while connecting to 10.0.0.6: boom"):
        async with transport_support.get_ssh_connection(agi_cls, "10.0.0.6", timeout_sec=1):
            pass


@pytest.mark.asyncio
async def test_exec_ssh_success_and_error_paths():
    class _Result:
        stdout = b"line-1\n"
        stderr = b"warn\n"

    class _Conn:
        async def run(self, _cmd, check=True):
            return _Result()

    class _ProcessError(Exception):
        def __init__(self, msg="process error", stdout=b"", stderr=b""):
            super().__init__(msg)
            self.stdout = stdout
            self.stderr = stderr

    @asynccontextmanager
    async def _conn_ctx(_ip):
        yield _Conn()

    agi_cls = SimpleNamespace(get_ssh_connection=_conn_ctx)
    output = await transport_support.exec_ssh(agi_cls, "10.0.0.2", "echo hi", process_error_cls=_ProcessError)
    assert "line-1" in output
    assert "warn" in output

    class _ErrConn:
        async def run(self, _cmd, check=True):
            raise _ProcessError("boom", stdout=b"", stderr=b"stderr")

    @asynccontextmanager
    async def _err_ctx(_ip):
        yield _ErrConn()

    agi_cls.get_ssh_connection = _err_ctx
    with pytest.raises(_ProcessError):
        await transport_support.exec_ssh(agi_cls, "10.0.0.2", "echo hi", process_error_cls=_ProcessError)

    class _OsErrConn:
        async def run(self, _cmd, check=True):
            raise OSError("socket failure")

    @asynccontextmanager
    async def _os_err_ctx(_ip):
        yield _OsErrConn()

    agi_cls.get_ssh_connection = _os_err_ctx
    with pytest.raises(ConnectionError, match="Connection to 10.0.0.2 failed"):
        await transport_support.exec_ssh(agi_cls, "10.0.0.2", "echo hi", process_error_cls=_ProcessError)


@pytest.mark.asyncio
async def test_exec_ssh_async_and_close_all_connections():
    class _Stdout:
        async def read(self):
            return b"\nalpha\nbeta\n"

    class _Proc:
        def __init__(self):
            self.stdout = _Stdout()

        async def wait(self):
            return None

    class _Conn:
        def __init__(self):
            self.closed = False
            self.waited = False

        async def create_process(self, _cmd):
            return _Proc()

        def close(self):
            self.closed = True

        async def wait_closed(self):
            self.waited = True

        def is_closed(self):
            return self.closed

    conn = _Conn()

    @asynccontextmanager
    async def _conn_ctx(_ip):
        yield conn

    agi_cls = SimpleNamespace(
        get_ssh_connection=_conn_ctx,
        _ssh_connections={"10.0.0.2": conn},
    )

    last_line = await transport_support.exec_ssh_async(agi_cls, "10.0.0.2", "run")
    assert last_line == b"beta"

    await transport_support.close_all_connections(agi_cls)
    assert agi_cls._ssh_connections == {}
    assert conn.closed is True
    assert conn.waited is True
