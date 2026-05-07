"""Async command execution helpers extracted from ``AgiEnv``."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any, Awaitable, Callable

from agi_env.agi_logger import AgiLogger
from agi_env.process_support import (
    apply_inline_path_export,
    build_subprocess_env,
    command_failure_hint,
    format_command_failure_message,
    inject_uv_preview_flag,
    strip_time_level_prefix,
)

PROCESS_WRAP_EXCEPTIONS = (RuntimeError, ValueError, OSError, subprocess.SubprocessError)
SHELL_SYNTAX_PATTERN = re.compile(r"(?:&&|\|\||[;|<>`]\s*|\$\(|\n)")
SHELL_ASSIGNMENT_PATTERN = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*=.*\s+\S+")
SHELL_BUILTIN_PATTERN = re.compile(r"^\s*(?:cd|source|export|unset|set)\b")


def _invoke_callback(callback: Callable[..., Any], message: str) -> None:
    try:
        callback(message, extra={"subprocess": True})
    except TypeError:
        callback(message)


def _resolve_stream_callbacks(
    *,
    log_callback: Callable[..., Any] | None,
    logger: Any,
) -> tuple[Callable[..., Any], Callable[..., Any]]:
    if log_callback:
        return log_callback, log_callback
    return (logger.info if logger else logging.info), (logger.error if logger else logging.error)


async def _read_stream(
    stream: asyncio.StreamReader | None,
    *,
    callback: Callable[..., Any],
    result: list[str],
) -> None:
    if stream is None:
        return

    enc = sys.stdout.encoding or "utf-8"
    while True:
        line = await stream.readline()
        if not line:
            break
        text = line.decode("utf-8", errors="replace").rstrip()
        if not text:
            continue
        safe = text.encode(enc, errors="replace").decode(enc)
        plain = AgiLogger.decolorize(safe)
        message = strip_time_level_prefix(plain)
        _invoke_callback(callback, message)
        result.append(message)


def _create_process_env(
    *,
    venv: Path | str | None,
    build_env_fn: Callable[[Path | str | None], dict[str, str]] | None,
) -> dict[str, str]:
    if build_env_fn:
        env = build_env_fn(venv)
        if isinstance(env, dict):
            return env
        return dict(env)
    return build_subprocess_env(base_env=os.environ.copy(), venv=venv)


def _command_requires_shell(cmd: str) -> bool:
    """Return ``True`` when ``cmd`` intentionally uses shell syntax."""

    return bool(
        SHELL_SYNTAX_PATTERN.search(cmd)
        or SHELL_ASSIGNMENT_PATTERN.match(cmd)
        or SHELL_BUILTIN_PATTERN.match(cmd)
    )


async def _spawn_process(
    *,
    cmd: str,
    cwd: str | Path | None,
    process_env: dict[str, str],
    shell_executable: str | None = None,
    allow_shell: bool = True,
    stdout: int | None = asyncio.subprocess.PIPE,
    stderr: int | None = asyncio.subprocess.PIPE,
) -> asyncio.subprocess.Process:
    if _command_requires_shell(cmd):
        if not allow_shell:
            raise ValueError(f"Shell syntax is not allowed for this command: {cmd}")
        return await asyncio.create_subprocess_shell(
            cmd,
            stdout=stdout,
            stderr=stderr,
            cwd=str(cwd) if cwd else None,
            env=process_env,
            executable=shell_executable,
        )
    cmd_list = shlex.split(cmd)
    return await asyncio.create_subprocess_exec(
        *cmd_list,
        stdout=stdout,
        stderr=stderr,
        cwd=str(cwd) if cwd else None,
        env=process_env,
    )


async def _stream_process_output(
    proc: asyncio.subprocess.Process,
    *,
    timeout: float | None,
    out_cb: Callable[..., Any],
    err_cb: Callable[..., Any],
    result: list[str],
    wait_for_exit: bool = False,
) -> None:
    coroutines: list[Awaitable[Any]] = [
        _read_stream(proc.stdout, callback=out_cb, result=result),
        _read_stream(proc.stderr, callback=err_cb, result=result),
    ]
    if wait_for_exit:
        coroutines.append(proc.wait())
    await asyncio.wait_for(asyncio.gather(*coroutines), timeout=timeout)


def _raise_process_error(
    err: Exception,
    *,
    proc: asyncio.subprocess.Process | None,
    logger: Any,
    wrap_message: str,
    trace_non_runtime: bool = False,
    command_context: str | None = None,
) -> None:
    if proc is not None:
        proc.kill()
    if logger:
        if command_context:
            logger.error(command_context)
        if trace_non_runtime and not isinstance(err, RuntimeError):
            logger.error(traceback.format_exc())
        elif not trace_non_runtime:
            logger.error(err)
    if isinstance(err, RuntimeError):
        raise err
    raise RuntimeError(wrap_message) from err


def _raise_nonzero_process_result(
    *,
    returncode: int,
    cmd: str,
    logger: Any,
    result: list[str] | None = None,
    simple_message: bool = False,
    include_diagnostic_hint: bool = False,
) -> None:
    if logger:
        logger.error("Command failed with exit code %s: %s", returncode, cmd)
    if simple_message:
        raise RuntimeError(f"Command failed (exit {returncode})")

    lines = result or []
    diagnostic_hint = command_failure_hint(cmd, lines) if include_diagnostic_hint else None
    raise RuntimeError(format_command_failure_message(returncode, cmd, lines, diagnostic_hint))


async def run(
    cmd: str | None,
    venv,
    *,
    cwd=None,
    timeout=None,
    wait: bool = True,
    log_callback: Callable[..., Any] | None = None,
    verbose: int = 0,
    logger: Any = None,
    build_env_fn: Callable[[Path | str | None], dict[str, str]] | None = None,
) -> str | int:
    """Run a shell command and stream output in real time."""

    if verbose > 0:
        try:
            vname = Path(venv).name if venv is not None else "<venv>"
        except (TypeError, ValueError):
            vname = str(venv)
        if logger:
            logger.info(f"@{vname}: {cmd}")

    cmd = inject_uv_preview_flag(cmd)
    if not cwd:
        cwd = venv

    process_env = _create_process_env(venv=venv, build_env_fn=build_env_fn)
    cmd = apply_inline_path_export(cmd, process_env)
    shell_executable = None if sys.platform == "win32" else "/bin/bash"

    if not wait:
        if not cmd:
            return 0

        proc = await _spawn_process(
            cmd=cmd,
            cwd=cwd,
            process_env=process_env,
            shell_executable=shell_executable,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        asyncio.create_task(proc.wait())
        return 0

    if not cmd:
        return ""

    result: list[str] = []
    proc = None
    try:
        proc = await _spawn_process(
            cmd=cmd,
            cwd=cwd,
            process_env=process_env,
            shell_executable=shell_executable,
        )

        out_cb, err_cb = _resolve_stream_callbacks(log_callback=log_callback, logger=logger)
        await _stream_process_output(
            proc,
            timeout=timeout,
            out_cb=out_cb,
            err_cb=err_cb,
            result=result,
        )
        returncode = await proc.wait()
        if returncode != 0:
            _raise_nonzero_process_result(
                returncode=returncode,
                cmd=cmd,
                logger=logger,
                result=result,
                include_diagnostic_hint=True,
            )
        return "\n".join(result)
    except asyncio.TimeoutError as err:
        if proc is not None:
            proc.kill()
        raise RuntimeError(f"Command timed out after {timeout} seconds: {cmd}") from err
    except PROCESS_WRAP_EXCEPTIONS as err:
        _raise_process_error(
            err,
            proc=None,
            logger=logger,
            wrap_message=f"Command execution error: {err}",
            trace_non_runtime=True,
        )


async def run_bg(
    cmd: str,
    *,
    cwd=".",
    venv=None,
    timeout=None,
    log_callback: Callable[..., Any] | None = None,
    env_override: dict | None = None,
    remove_env: set[str] | None = None,
    logger: Any = None,
    build_env_fn: Callable[[Path | str | None], dict[str, str]] | None = None,
) -> tuple[str, str]:
    """Run a command asynchronously and return ``(stdout, stderr)``."""

    process_env = _create_process_env(venv=venv, build_env_fn=build_env_fn)
    process_env["PYTHONUNBUFFERED"] = "1"
    if remove_env:
        for key in remove_env:
            process_env.pop(key, None)
    if env_override:
        process_env.update(env_override)

    cmd = inject_uv_preview_flag(cmd)
    result: list[str] = []

    proc = await _spawn_process(
        cmd=cmd,
        cwd=cwd,
        process_env=process_env,
        shell_executable=None,
    )

    out_cb, err_cb = _resolve_stream_callbacks(log_callback=log_callback, logger=logger)
    try:
        await _stream_process_output(
            proc,
            timeout=timeout,
            out_cb=out_cb,
            err_cb=err_cb,
            result=result,
            wait_for_exit=True,
        )
    except asyncio.TimeoutError as err:
        proc.kill()
        raise RuntimeError(f"Timeout expired for command: {cmd}") from err
    stdout, stderr = await proc.communicate()
    returncode = proc.returncode

    if returncode != 0:
        _raise_nonzero_process_result(
            returncode=returncode,
            cmd=cmd,
            logger=logger,
            simple_message=True,
        )

    return stdout.decode(), stderr.decode()


async def run_async(
    cmd,
    *,
    venv=None,
    cwd=None,
    timeout=None,
    log_callback: Callable[..., Any] | None = None,
    verbose: int = 0,
    logger: Any = None,
    build_env_fn: Callable[[Path | str | None], dict[str, str]] | None = None,
) -> str:
    """Run a command and return the last non-empty output line."""

    if verbose > 0 and logger:
        logger.info(f"Executing in {venv}: {cmd}")

    if cwd is None:
        cwd = venv

    process_env = _create_process_env(venv=venv, build_env_fn=build_env_fn)
    process_env["PYTHONUNBUFFERED"] = "1"
    shell_executable = None if os.name == "nt" else "/bin/bash"

    if isinstance(cmd, (list, tuple)):
        cmd = " ".join(cmd)
    cmd = inject_uv_preview_flag(cmd)

    result: list[str] = []
    proc = None
    try:
        proc = await _spawn_process(
            cmd=cmd,
            cwd=cwd,
            process_env=process_env,
            shell_executable=shell_executable,
        )

        out_cb, err_cb = _resolve_stream_callbacks(log_callback=log_callback, logger=logger)
        await _stream_process_output(
            proc,
            timeout=timeout,
            out_cb=out_cb,
            err_cb=err_cb,
            result=result,
            wait_for_exit=True,
        )
    except PROCESS_WRAP_EXCEPTIONS as err:
        _raise_process_error(
            err,
            proc=proc,
            logger=logger,
            wrap_message=f"Subprocess execution error for: {cmd}",
            command_context=f"Error during: {cmd}",
        )

    rc = proc.returncode
    if rc != 0:
        _raise_nonzero_process_result(
            returncode=rc,
            cmd=cmd,
            logger=logger,
            result=result,
        )

    for line in reversed(result):
        if line.strip():
            return line
    return ""


async def run_agi(
    *,
    code: str,
    runenv: Path,
    target: str,
    log_callback: Callable[..., Any] | None = None,
    venv: Path | None = None,
    run_bg_fn: Callable[..., Awaitable[tuple[str, str]]],
    ensure_dir_fn: Callable[[str | Path], Path],
    logger: Any = None,
    python_executable: str | Path = sys.executable,
    log_info_fn: Callable[[str], Any] = logging.info,
    snippet_type=None,
) -> tuple[str, str]:
    """Execute generated AGI snippet code and stream logs."""

    _ = snippet_type
    pattern = r"await\s+(?:Agi\.)?([^\(]+)\("
    matches = re.findall(pattern, code)
    if not matches:
        message = "Could not determine snippet name from code."
        if log_callback:
            log_callback(message)
        elif logger:
            logger.info(message)
        return "", ""

    snippet_name = matches[0]
    is_install_snippet = "install" in snippet_name.lower()
    runenv_path = ensure_dir_fn(runenv)
    snippet_file = runenv_path / "{}_{}.py".format(
        re.sub(r"[^0-9A-Za-z_]+", "_", str(snippet_name)).strip("_") or "AGI.unknown_command",
        re.sub(r"[^0-9A-Za-z_]+", "_", str(target)).strip("_") or "unknown_app_name",
    )
    with open(snippet_file, "w") as file:
        file.write(code)

    project_root = Path(venv) if venv else None
    project_venv = None
    if project_root:
        if project_root.name == ".venv" or (project_root / "pyvenv.cfg").exists():
            project_venv = project_root
        else:
            candidate = project_root / ".venv"
            if (candidate / "pyvenv.cfg").exists():
                project_venv = candidate

    if not is_install_snippet and project_root and project_venv is None:
        message = f"No virtual environment found in {project_root}. Run INSTALL first."
        if log_callback:
            log_callback(message)
        elif logger:
            logger.warning(message)
        return "", message

    if project_venv:
        python_bin = project_venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        cmd = f"{shlex.quote(str(python_bin))} {shlex.quote(str(snippet_file))}"
        result = await run_bg_fn(
            cmd,
            cwd=str(project_root),
            venv=project_venv,
            remove_env={"PYTHONPATH", "PYTHONHOME"},
            log_callback=log_callback,
        )
    else:
        python_bin = Path(python_executable)
        cmd = f"{shlex.quote(str(python_bin))} {shlex.quote(str(snippet_file))}"
        result = await run_bg_fn(
            cmd,
            cwd=str(project_root or runenv),
            venv=Path(sys.prefix),
            remove_env={"PYTHONPATH", "PYTHONHOME"},
            log_callback=log_callback,
        )

    if log_callback:
        log_callback("Process finished")
    else:
        log_info_fn("Process finished")
    return result
