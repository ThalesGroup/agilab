import asyncio
import logging
import os
import socket
import time
from pathlib import Path
from typing import Any, Callable, Optional, Set

from agi_env import AgiEnv


logger = logging.getLogger(__name__)


async def clean_remote_procs(
    agi_cls: Any,
    list_ip: Set[str],
    *,
    force: bool = True,
    is_local_fn: Callable[[str], bool] = AgiEnv.is_local,
) -> None:
    tasks = []
    for ip in list_ip:
        if not is_local_fn(ip):
            tasks.append(asyncio.create_task(agi_cls._kill(ip, os.getpid(), force=force)))

    if tasks:
        await asyncio.gather(*tasks)


async def clean_remote_dirs(agi_cls: Any, list_ip: Set[str]) -> None:
    tasks = [asyncio.create_task(agi_cls._clean_dirs(ip)) for ip in list_ip]
    if tasks:
        await asyncio.gather(*tasks)


async def clean_nodes(
    agi_cls: Any,
    scheduler_addr: Optional[str],
    *,
    force: bool = True,
    is_local_fn: Callable[[str], bool] = AgiEnv.is_local,
    gethostbyname_fn: Callable[[str], str] = socket.gethostbyname,
) -> Set[str]:
    list_ip = set(list(agi_cls._workers) + [agi_cls._get_scheduler(scheduler_addr)[0]])
    localhost_ip = gethostbyname_fn("localhost")
    if not list_ip:
        list_ip.add(localhost_ip)

    for ip in list_ip:
        if is_local_fn(ip):
            agi_cls._clean_dirs_local()

    await agi_cls._clean_remote_procs(list_ip=list_ip, force=force)
    await agi_cls._clean_remote_dirs(list_ip=list_ip)
    return list_ip


def reset_deploy_state(agi_cls: Any) -> None:
    agi_cls._run_type = agi_cls._run_types[(agi_cls._mode & agi_cls._DEPLOYEMENT_MASK) >> 4]
    agi_cls._install_done_local = False
    agi_cls._install_done = False
    agi_cls._worker_init_error = False


async def deploy_application(
    agi_cls: Any,
    scheduler_addr: Optional[str],
    *,
    time_fn: Callable[[], float] = time.time,
    log: Any = logger,
) -> None:
    reset_deploy_state(agi_cls)
    env = agi_cls.env
    app_path = env.active_app
    wenv_rel = env.wenv_rel
    options_worker = ""
    if isinstance(env.base_worker_cls, str):
        options_worker = " --extra " + " --extra ".join(agi_cls.install_worker_group)

    node_ips = set(list(agi_cls._workers) + [agi_cls._get_scheduler(scheduler_addr)[0]])
    agi_cls._venv_todo(node_ips)
    start_time = time_fn()
    if env.verbose > 0:
        log.info(f"Installing {app_path} on 127.0.0.1")

    await agi_cls._deploy_local_worker(app_path, Path(wenv_rel), options_worker)
    if agi_cls._mode & agi_cls.DASK_MODE:
        tasks = []
        for ip in node_ips:
            if env.verbose > 0:
                log.info(f"Installing worker on {ip}")
            if not env.is_local(ip):
                tasks.append(
                    asyncio.create_task(
                        agi_cls._deploy_remote_worker(ip, env, wenv_rel, options_worker)
                    )
                )
        await asyncio.gather(*tasks)

    if agi_cls.verbose:
        duration = agi_cls._format_elapsed(time_fn() - start_time)
        if env.verbose > 0:
            log.info(f"uv {agi_cls._run_type} completed in {duration}")
