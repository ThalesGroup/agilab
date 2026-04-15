from __future__ import annotations

import asyncio
from pathlib import Path
from unittest import mock

import pytest

import agi_env.execution_support as execution_support


class _FakeStream:
    def __init__(self, lines: list[bytes] | None = None):
        self._lines = list(lines or [b""])

    async def readline(self):
        if self._lines:
            return self._lines.pop(0)
        return b""


class _FakeProc:
    def __init__(
        self,
        *,
        stdout_lines: list[bytes] | None = None,
        stderr_lines: list[bytes] | None = None,
        returncode: int = 0,
    ):
        self.stdout = _FakeStream(stdout_lines)
        self.stderr = _FakeStream(stderr_lines)
        self.returncode = returncode

    async def wait(self):
        return self.returncode

    async def communicate(self):
        stdout = b"".join(line for line in [*self.stdout._lines] if line)
        stderr = b"".join(line for line in [*self.stderr._lines] if line)
        return stdout, stderr


def test_spawn_process_shell_fallback_allows_expected_exec_failure(tmp_path: Path, monkeypatch):
    async def _raise_exec(*_args, **_kwargs):
        raise ValueError("bad command split")

    async def _fake_shell(*_args, **_kwargs):
        return _FakeProc(stdout_lines=[b"stdout line\n", b""], stderr_lines=[b""])

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _raise_exec)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _fake_shell)

    proc = asyncio.run(
        execution_support._spawn_process(
            cmd="echo hi",
            cwd=tmp_path,
            process_env={"PYTHONUNBUFFERED": "1"},
            shell_executable="/bin/bash",
        )
    )

    assert isinstance(proc, _FakeProc)


def test_spawn_process_propagates_unexpected_exec_bug(tmp_path: Path, monkeypatch):
    async def _raise_exec(*_args, **_kwargs):
        raise RuntimeError("exec bug")

    async def _unexpected_shell(*_args, **_kwargs):
        raise AssertionError("shell fallback should not run")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _raise_exec)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _unexpected_shell)

    with pytest.raises(RuntimeError, match="exec bug"):
        asyncio.run(
            execution_support._spawn_process(
                cmd="echo hi",
                cwd=tmp_path,
                process_env={"PYTHONUNBUFFERED": "1"},
                shell_executable="/bin/bash",
            )
        )


def test_raise_process_error_wraps_non_runtime_and_logs_traceback():
    logger = mock.Mock()

    with pytest.raises(RuntimeError, match="wrapped error"):
        try:
            raise ValueError("broken exec")
        except ValueError as err:
            execution_support._raise_process_error(
                err,
                proc=None,
                logger=logger,
                wrap_message="wrapped error",
                trace_non_runtime=True,
            )

    assert logger.error.called


def test_raise_process_error_preserves_runtime_and_kills_proc():
    logger = mock.Mock()

    class _Proc:
        def __init__(self):
            self.killed = False

        def kill(self):
            self.killed = True

    proc = _Proc()

    with pytest.raises(RuntimeError, match="worker boom"):
        execution_support._raise_process_error(
            RuntimeError("worker boom"),
            proc=proc,
            logger=logger,
            wrap_message="unused wrapper",
            command_context="Error during: echo boom",
        )

    assert proc.killed is True
    logger.error.assert_any_call("Error during: echo boom")
    assert any(str(call.args[0]) == "worker boom" for call in logger.error.call_args_list)


def test_run_shell_fallback_allows_expected_exec_failure(tmp_path: Path, monkeypatch):
    async def _raise_exec(*_args, **_kwargs):
        raise ValueError("bad command split")

    async def _fake_shell(*_args, **_kwargs):
        return _FakeProc(stdout_lines=[b"stdout line\n", b""], stderr_lines=[b""])

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _raise_exec)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _fake_shell)

    result = asyncio.run(execution_support.run("echo hi", tmp_path, cwd=tmp_path, logger=None))

    assert result == "stdout line"


def test_run_propagates_unexpected_exec_bug(tmp_path: Path, monkeypatch):
    async def _raise_exec(*_args, **_kwargs):
        raise RuntimeError("exec bug")

    async def _unexpected_shell(*_args, **_kwargs):
        raise AssertionError("shell fallback should not run")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _raise_exec)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _unexpected_shell)

    with pytest.raises(RuntimeError, match="exec bug"):
        asyncio.run(execution_support.run("echo hi", tmp_path, cwd=tmp_path, logger=None))


def test_run_bg_shell_fallback_allows_expected_exec_failure(tmp_path: Path, monkeypatch):
    async def _raise_exec(*_args, **_kwargs):
        raise ValueError("bad command split")

    async def _fake_shell(*_args, **_kwargs):
        return _FakeProc(stderr_lines=[b"stderr line\n", b""])

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _raise_exec)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _fake_shell)

    stdout, stderr = asyncio.run(execution_support.run_bg("echo hi", cwd=tmp_path, venv=tmp_path))

    assert stdout == ""
    assert stderr == ""


def test_run_bg_propagates_unexpected_exec_bug(tmp_path: Path, monkeypatch):
    async def _raise_exec(*_args, **_kwargs):
        raise RuntimeError("exec bug")

    async def _unexpected_shell(*_args, **_kwargs):
        raise AssertionError("shell fallback should not run")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _raise_exec)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _unexpected_shell)

    with pytest.raises(RuntimeError, match="exec bug"):
        asyncio.run(execution_support.run_bg("echo hi", cwd=tmp_path, venv=tmp_path))


def test_run_async_shell_fallback_allows_expected_exec_failure(tmp_path: Path, monkeypatch):
    async def _raise_exec(*_args, **_kwargs):
        raise ValueError("bad command split")

    async def _fake_shell(*_args, **_kwargs):
        return _FakeProc(stdout_lines=[b"stdout line\n", b""], stderr_lines=[b"stderr line\n", b""])

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _raise_exec)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _fake_shell)

    result = asyncio.run(execution_support.run_async("echo hi", venv=tmp_path, cwd=tmp_path))

    assert result == "stderr line"


def test_run_async_propagates_unexpected_exec_bug(tmp_path: Path, monkeypatch):
    async def _raise_exec(*_args, **_kwargs):
        raise RuntimeError("exec bug")

    async def _unexpected_shell(*_args, **_kwargs):
        raise AssertionError("shell fallback should not run")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _raise_exec)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _unexpected_shell)

    with pytest.raises(RuntimeError, match="exec bug"):
        asyncio.run(execution_support.run_async("echo hi", venv=tmp_path, cwd=tmp_path))
