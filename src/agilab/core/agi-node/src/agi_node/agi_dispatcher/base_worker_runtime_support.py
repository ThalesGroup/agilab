from __future__ import annotations

import io
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, MutableMapping


def _log_level_for_verbosity(verbosity: int) -> int:
    if verbosity >= 2:
        return logging.DEBUG
    if verbosity == 1:
        return logging.INFO
    return logging.WARNING


def capture_logs_and_result(
    func: Callable[..., Any],
    *args: Any,
    verbosity: int = logging.CRITICAL,
    root_logger: logging.Logger | None = None,
    **kwargs: Any,
) -> tuple[str, Any]:
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    active_logger = root_logger or logging.getLogger()
    previous_level = active_logger.level

    active_logger.setLevel(_log_level_for_verbosity(verbosity))
    active_logger.addHandler(handler)
    try:
        result = func(*args, **kwargs)
    finally:
        active_logger.removeHandler(handler)
        handler.close()
        active_logger.setLevel(previous_level)

    return log_stream.getvalue(), result


def exec_command(
    cmd: str,
    path: str | Path,
    worker: str,
    *,
    normalize_path_fn: Callable[[str | Path], str],
    subprocess_run: Callable[..., Any] = subprocess.run,
    logger_obj: logging.Logger,
) -> Any:
    normalized_path = normalize_path_fn(path)
    result = subprocess_run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        check=False,
        cwd=normalized_path,
    )
    if result.returncode == 0:
        return result

    stderr = result.stderr or ""
    if stderr.startswith("WARNING"):
        logger_obj.error("warning: worker %s - %s", worker, cmd)
        logger_obj.error(stderr)
        return result

    raise RuntimeError(f"error on node {worker} - {cmd} {stderr}")


def log_import_error(
    module: str,
    target_class: str,
    target_module: str,
    *,
    logger_obj: logging.Logger,
    file_path: str,
    sys_path: list[str],
) -> None:
    logger_obj.error("file:  %s", file_path)
    logger_obj.error("__import__('%s', fromlist=['%s'])", module, target_class)
    logger_obj.error("getattr('%s %s')", target_module, target_class)
    logger_obj.error("sys.path: %s", sys_path)


def load_module(
    module_name: str,
    module_class: str,
    *,
    import_fn: Callable[..., Any] | None = None,
) -> Any:
    active_import = import_fn or __import__
    try:
        module = active_import(module_name, fromlist=[module_class])
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(f"module {module_name} is not installed") from exc
    return getattr(module, module_class)


def load_manager(
    env: Any,
    *,
    load_module_fn: Callable[[str, str], Any],
    sys_modules: MutableMapping[str, Any] | None = None,
) -> Any:
    active_modules = sys_modules if sys_modules is not None else sys.modules
    module_name = f"{env.module}.{env.module}"
    active_modules.pop(module_name, None)
    return load_module_fn(module_name, env.target_class)


def load_worker(
    env: Any,
    mode: int,
    *,
    load_module_fn: Callable[[str, str], Any],
    sys_modules: MutableMapping[str, Any] | None = None,
) -> Any:
    active_modules = sys_modules if sys_modules is not None else sys.modules
    module_name = env.target_worker
    active_modules.pop(module_name, None)
    if mode & 2:
        module_name = f"{module_name}_cy"
    else:
        module_name = f"{module_name}.{module_name}"
    return load_module_fn(module_name, env.target_worker_class)


def is_cython_installed(
    env: Any,
    *,
    import_fn: Callable[..., Any] | None = None,
) -> bool:
    active_import = import_fn or __import__
    try:
        active_import(f"{env.target_worker}_cy", fromlist=[env.target_worker_class])
    except ModuleNotFoundError:
        return False
    return True


__all__ = [
    "capture_logs_and_result",
    "exec_command",
    "is_cython_installed",
    "load_manager",
    "load_module",
    "load_worker",
    "log_import_error",
]
