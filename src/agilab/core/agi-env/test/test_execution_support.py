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
        self.wait_calls = 0

    async def wait(self):
        self.wait_calls += 1
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


def test_stream_process_output_collects_lines_and_waits_for_proc():
    proc = _FakeProc(stdout_lines=[b"stdout line\n", b""], stderr_lines=[b"stderr line\n", b""])
    seen_out: list[str] = []
    seen_err: list[str] = []
    result: list[str] = []

    asyncio.run(
        execution_support._stream_process_output(
            proc,
            timeout=1,
            out_cb=seen_out.append,
            err_cb=seen_err.append,
            result=result,
            wait_for_exit=True,
        )
    )

    assert seen_out == ["stdout line"]
    assert seen_err == ["stderr line"]
    assert result == ["stdout line", "stderr line"]
    assert proc.wait_calls == 1


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


def test_raise_nonzero_process_result_formats_with_diagnostic_hint(monkeypatch):
    logger = mock.Mock()
    captured = {}

    def _fake_hint(cmd, result):
        captured["hint_args"] = (cmd, list(result))
        return "install hint"

    def _fake_formatter(returncode, cmd, result, diagnostic_hint=None):
        captured["format_args"] = (returncode, cmd, list(result), diagnostic_hint)
        return f"formatted {returncode}: {diagnostic_hint}"

    monkeypatch.setattr(execution_support, "command_failure_hint", _fake_hint)
    monkeypatch.setattr(execution_support, "format_command_failure_message", _fake_formatter)

    with pytest.raises(RuntimeError, match="formatted 7: install hint"):
        execution_support._raise_nonzero_process_result(
            returncode=7,
            cmd="uv pip install demo",
            logger=logger,
            result=["dependency failure"],
            include_diagnostic_hint=True,
        )

    logger.error.assert_called_once_with("Command failed with exit code %s: %s", 7, "uv pip install demo")
    assert captured["hint_args"] == ("uv pip install demo", ["dependency failure"])
    assert captured["format_args"] == (7, "uv pip install demo", ["dependency failure"], "install hint")


def test_raise_nonzero_process_result_simple_message_skips_formatter(monkeypatch):
    logger = mock.Mock()

    def _unexpected_formatter(*_args, **_kwargs):
        raise AssertionError("formatter should not run")

    monkeypatch.setattr(execution_support, "format_command_failure_message", _unexpected_formatter)

    with pytest.raises(RuntimeError, match=r"Command failed \(exit 4\)"):
        execution_support._raise_nonzero_process_result(
            returncode=4,
            cmd="echo hi",
            logger=logger,
            simple_message=True,
        )

    logger.error.assert_called_once_with("Command failed with exit code %s: %s", 4, "echo hi")


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


def test_run_propagates_unexpected_stream_bug(tmp_path: Path, monkeypatch):
    class _BrokenStream:
        async def readline(self):
            raise AssertionError("stream bug")

    class _Proc:
        def __init__(self):
            self.stdout = _BrokenStream()
            self.stderr = _FakeStream([b""])
            self.returncode = 0

        async def wait(self):
            return self.returncode

    async def _fake_exec(*_args, **_kwargs):
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    with pytest.raises(AssertionError, match="stream bug"):
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


def test_run_async_propagates_unexpected_stream_bug(tmp_path: Path, monkeypatch):
    class _BrokenStream:
        async def readline(self):
            raise AssertionError("stream bug")

    class _Proc:
        def __init__(self):
            self.stdout = _BrokenStream()
            self.stderr = _FakeStream([b""])
            self.returncode = 0
            self.killed = False

        async def wait(self):
            return self.returncode

        def kill(self):
            self.killed = True

    proc = _Proc()

    async def _fake_exec(*_args, **_kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    with pytest.raises(AssertionError, match="stream bug"):
        asyncio.run(execution_support.run_async("echo hi", venv=tmp_path, cwd=tmp_path))

    assert proc.killed is False
