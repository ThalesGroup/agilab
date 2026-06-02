import asyncio
import getpass
import logging
import os
import runpy
import shutil
import socket
import stat
import sys
import time
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Awaitable, Callable, Optional

import psutil

from agi_env import AgiEnv


logger = logging.getLogger(__name__)
REMOVE_DIR_RETRY_EXCEPTIONS = (OSError, shutil.Error)
CMD_PREFIX_LOOKUP_EXCEPTIONS = (ConnectionError, OSError, RuntimeError, TimeoutError)


async def _remote_cmd_prefix(
    env: Any,
    ip: str,
    *,
    detect_export_cmd_fn: Optional[Callable[[str], Awaitable[str]]] = None,
) -> str:
    cmd_prefix = str(env.envars.get(f"{ip}_CMD_PREFIX", "") or "")
    if cmd_prefix or env.is_local(ip) or detect_export_cmd_fn is None:
        return cmd_prefix

    try:
        cmd_prefix = str(await detect_export_cmd_fn(ip) or "")
    except CMD_PREFIX_LOOKUP_EXCEPTIONS:
        return ""

    if cmd_prefix:
        env.envars[f"{ip}_CMD_PREFIX"] = cmd_prefix
    return cmd_prefix


def remove_dir_forcefully(
    path: str,
    *,
    rmtree_fn: Callable[..., Any] = shutil.rmtree,
    sleep_fn: Callable[[float], Any] = time.sleep,
    access_fn: Callable[[Any, int], bool] = os.access,
    chmod_fn: Callable[[Any, int], Any] = os.chmod,
    log: Any = logger,
) -> None:
    def onerror(func: Callable[..., Any], failed_path: Any, exc_info: Any) -> None:
        if not access_fn(failed_path, os.W_OK):
            chmod_fn(failed_path, stat.S_IWUSR)
            func(failed_path)
        else:
            log.info("%s not removed due to %s", failed_path, exc_info[1])

    try:
        rmtree_fn(path, onerror=onerror)
    except REMOVE_DIR_RETRY_EXCEPTIONS as exc:
        log.error("Exception while deleting %s: %s", path, exc)
        sleep_fn(1)
        try:
            rmtree_fn(path, onerror=onerror)
        except REMOVE_DIR_RETRY_EXCEPTIONS as second_exc:
            log.error("Second failure deleting %s: %s", path, second_exc)
            raise


async def kill_processes(
    agi_cls: Any,
    ip: Optional[str] = None,
    current_pid: Optional[int] = None,
    force: bool = True,
    *,
    gethostbyname_fn: Callable[[str], str] = socket.gethostbyname,
    run_fn: Callable[[str, str], Awaitable[Any]] = AgiEnv.run,
    copy_fn: Callable[[Any, Any], Any] = shutil.copy,
    run_path_fn: Callable[..., Any] = runpy.run_path,
    sys_module: Any = sys,
    path_cls: type[Path] = Path,
    detect_export_cmd_fn: Optional[Callable[[str], Awaitable[str]]] = None,
    log: Any = logger,
) -> Optional[Any]:
    env = agi_cls.env
    uv = env.uv
    localhost = gethostbyname_fn("localhost")
    ip = ip or localhost
    current_pid = current_pid or os.getpid()

    for pid_file in sorted(path_cls(env.wenv_abs.parent).glob("*.pid"), key=lambda candidate: candidate.name):
        try:
            pid = int(pid_file.read_text().strip())
            if pid == current_pid:
                continue
        except (OSError, ValueError):
            log.warning("Could not read PID from %s, skipping", pid_file)
        try:
            pid_file.unlink()
        except OSError as exc:
            log.warning("Failed to remove pid file %s: %s", pid_file, exc)

    cmds: list[str] = []
    cli_rel = env.wenv_rel.parent / "cli.py"
    cli_abs = env.wenv_abs.parent / cli_rel.name
    cmd_prefix = await _remote_cmd_prefix(
        env,
        ip,
        detect_export_cmd_fn=detect_export_cmd_fn,
    )
    kill_prefix = f"{cmd_prefix}{uv} run --no-sync python"
    if env.is_local(ip):
        if not cli_abs.exists():
            copy_fn(env.cluster_pck / "agi_distributor/cli.py", cli_abs)
        if force:
            exclude_arg = f" {current_pid}" if current_pid else ""
            cmds.append(f"{kill_prefix} '{cli_abs}' kill{exclude_arg}")
    elif force:
        cmds.append(f"{kill_prefix} '{cli_rel.as_posix()}' kill")

    last_res = None
    for cmd in cmds:
        cwd = env.agi_cluster if ip == localhost else str(env.wenv_abs)
        if env.is_local(ip):
            if env.debug:
                sys_module.argv = cmd.split("python ")[1].split(" ")
                run_path_fn(sys_module.argv[0], run_name="__main__")
            else:
                await run_fn(cmd, cwd)
        else:
            last_res = await agi_cls.exec_ssh(ip, cmd)

        if isinstance(last_res, dict):
            out = last_res.get("stdout", "")
            err = last_res.get("stderr", "")
            log.info(out)
            if err:
                log.error(err)

    return last_res


async def wait_for_port_release(
    ip: str,
    port: int,
    timeout: float = 5.0,
    interval: float = 0.2,
    *,
    gethostbyname_fn: Callable[[str], str] = socket.gethostbyname,
    socket_factory: Callable[..., Any] = socket.socket,
    sleep_fn: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> bool:
    ip = ip or gethostbyname_fn("localhost")
    deadline = monotonic_fn() + timeout
    while monotonic_fn() < deadline:
        sock = socket_factory(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((ip, port))
        except OSError:
            await sleep_fn(interval)
        else:
            sock.close()
            return True
        finally:
            try:
                sock.close()
            except OSError:
                pass
    return False


def clean_dirs_local(
    agi_cls: Any,
    *,
    process_iter_fn: Callable[..., Any] = psutil.process_iter,
    getuser_fn: Callable[[], str] = getpass.getuser,
    getpid_fn: Callable[[], int] = os.getpid,
    rmtree_fn: Callable[..., Any] = shutil.rmtree,
    gettempdir_fn: Callable[[], str] = gettempdir,
) -> None:
    me = getuser_fn()
    self_pid = getpid_fn()
    for proc in process_iter_fn(["pid", "username", "cmdline"]):
        try:
            if (
                proc.info["username"]
                and proc.info["username"].endswith(me)
                and proc.info["pid"]
                and proc.info["pid"] != self_pid
                and proc.info["cmdline"]
                and any("dask" in part.lower() for part in proc.info["cmdline"])
            ):
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    for directory in [
        f"{gettempdir_fn()}/dask-scratch-space",
        f"{agi_cls.env.wenv_abs}",
    ]:
        try:
            rmtree_fn(directory, ignore_errors=True)
        except (OSError, TypeError):
            pass


async def clean_dirs(
    agi_cls: Any,
    ip: str,
    *,
    makedirs_fn: Callable[..., Any] = os.makedirs,
    remove_dir_forcefully_fn: Optional[Callable[[str], None]] = None,
) -> None:
    env = agi_cls.env
    uv = env.uv
    wenv_abs = env.wenv_abs
    if wenv_abs.exists():
        remover = remove_dir_forcefully_fn or agi_cls._remove_dir_forcefully
        remover(str(wenv_abs))
    makedirs_fn(wenv_abs / "src", exist_ok=True)
    cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")
    wenv = env.wenv_rel
    cli = wenv.parent / "cli.py"
    cmd = f"{cmd_prefix}{uv} run --no-sync -p {env.python_version} python {cli.as_posix()} clean {wenv}"
    await agi_cls.exec_ssh(ip, cmd)
