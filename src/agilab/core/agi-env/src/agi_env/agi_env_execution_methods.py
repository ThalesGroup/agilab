"""Async execution methods exposed through ``AgiEnv``."""

import sys
from pathlib import Path

from agi_env.execution_support import (
    run as run_command_in_env,
    run_agi as run_agi_snippet,
    run_async as run_command_async,
    run_bg as run_command_in_background,
)


def _env_class():
    from agi_env.agi_env import AgiEnv

    return AgiEnv


def _class_static_method(env_cls, name: str):
    value = vars(env_cls).get(name)
    if isinstance(value, staticmethod):
        return value.__func__
    return getattr(env_cls, name)


async def run(cmd, venv, cwd=None, timeout=None, wait=True, log_callback=None):
    """Run a shell command inside a virtual environment."""
    env_cls = _env_class()
    return await run_command_in_env(
        cmd,
        venv,
        cwd=cwd,
        timeout=timeout,
        wait=wait,
        log_callback=log_callback,
        verbose=env_cls.verbose or 0,
        logger=env_cls.logger,
        build_env_fn=env_cls._build_env,
    )


async def run_bg(
    cmd,
    cwd=".",
    venv=None,
    timeout=None,
    log_callback=None,
    env_override: dict | None = None,
    remove_env: set[str] | None = None,
):
    """Run a command asynchronously and return ``(stdout, stderr)``."""
    env_cls = _env_class()
    return await run_command_in_background(
        cmd,
        cwd=cwd,
        venv=venv,
        timeout=timeout,
        log_callback=log_callback,
        env_override=env_override,
        remove_env=remove_env,
        logger=env_cls.logger,
        build_env_fn=env_cls._build_env,
    )


async def run_agi(self, code, log_callback=None, venv: Path = None, type=None):  # ty: ignore[invalid-parameter-default]
    """Asynchronous version of run_agi for use within an async context."""
    env_cls = _env_class()
    from agi_env import agi_env as agi_env_module

    return await run_agi_snippet(
        code=code,
        runenv=Path(self.runenv),
        target=str(self.target),
        log_callback=log_callback,
        venv=Path(venv) if venv else None,
        run_bg_fn=_class_static_method(env_cls, "_run_bg"),
        ensure_dir_fn=agi_env_module._ensure_dir,
        logger=env_cls.logger,
        python_executable=sys.executable,
        log_info_fn=agi_env_module.logging.info,
        snippet_type=type,
    )


async def run_async(cmd, venv=None, cwd=None, timeout=None, log_callback=None):
    """Run a shell command asynchronously and return the last non-empty line."""
    env_cls = _env_class()
    return await run_command_async(
        cmd,
        venv=venv,
        cwd=cwd,
        timeout=timeout,
        log_callback=log_callback,
        verbose=env_cls.verbose or 0,
        logger=env_cls.logger,
        build_env_fn=env_cls._build_env,
    )
