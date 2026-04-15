import asyncio
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from agi_cluster.agi_distributor import runtime_misc_support


logger = logging.getLogger(__name__)


def _normalize_workers(
    workers: Optional[Dict[str, int]],
    workers_default: Dict[str, int],
) -> Dict[str, int]:
    if not workers:
        return workers_default
    if not isinstance(workers, dict):
        raise ValueError("workers must be a dict. {'ip-address':nb-worker}")
    return workers


def _configure_mode(agi_cls: Any, env: Any, mode: Union[int, str]) -> None:
    if isinstance(mode, str):
        pattern = r"^[dcrp]+$"
        if not re.fullmatch(pattern, mode.lower()):
            raise ValueError("parameter <mode> must only contain the letters 'd', 'c', 'r', 'p'")
        agi_cls._mode = env.mode2int(mode)
    elif isinstance(mode, int):
        agi_cls._mode = int(mode)
    else:
        raise ValueError("parameter <mode> must be an int, a list of int or a string")

    agi_cls._run_types = ["run --no-sync", "sync --dev", "sync --upgrade --dev", "simulate"]
    if agi_cls._mode:
        if agi_cls._mode & agi_cls._RUN_MASK not in range(0, agi_cls.RAPIDS_MODE):
            raise ValueError(f"mode {agi_cls._mode} not implemented")
    else:
        agi_cls._run_type = agi_cls._run_types[
            (agi_cls._mode & agi_cls._DEPLOYEMENT_MASK) >> agi_cls.DASK_MODE
        ]


def _initialize_run_state(
    agi_cls: Any,
    env: Any,
    *,
    workers: Dict[str, int],
    workers_data_path: Optional[str],
    verbose: int,
    rapids_enabled: bool,
    args: Dict[str, Any],
    log: Any = logger,
) -> None:
    agi_cls.env = env
    agi_cls.target_path = env.manager_path
    agi_cls._target = env.target
    agi_cls._rapids_enabled = rapids_enabled
    if env.verbose > 0:
        log.info("AGI instance created for target %s with verbosity %s", env.target, env.verbose)

    agi_cls._args = args
    agi_cls.verbose = verbose
    agi_cls._workers = workers
    agi_cls._workers_data_path = workers_data_path
    agi_cls._run_time = {}


def _load_capacity_predictor(agi_cls: Any, env: Any) -> None:
    runtime_misc_support.bootstrap_capacity_predictor(
        agi_cls,
        env,
        retrain_fn=lambda: agi_cls._train_capacity(Path(env.home_abs)),
        log=logger,
    )


def _resolve_install_worker_group(agi_cls: Any, env: Any) -> None:
    runtime_misc_support.configure_install_worker_group(agi_cls, env)


async def run(
    agi_cls: Any,
    env: Any,
    scheduler: Optional[str] = None,
    workers: Optional[Dict[str, int]] = None,
    workers_data_path: Optional[str] = None,
    verbose: int = 0,
    mode: Optional[Union[int, List[int], str]] = None,
    rapids_enabled: bool = False,
    *,
    workers_default: Dict[str, int],
    process_error_type: type[BaseException],
    format_exception_chain_fn: Callable[[BaseException], str],
    traceback_format_exc_fn: Callable[[], str],
    log: Any = logger,
    **args: Any,
) -> Any:
    workers = _normalize_workers(workers, workers_default)
    _initialize_run_state(
        agi_cls,
        env,
        workers=workers,
        workers_data_path=workers_data_path,
        verbose=verbose,
        rapids_enabled=rapids_enabled,
        args=args,
        log=log,
    )

    if mode is None or isinstance(mode, list):
        mode_range = range(8) if mode is None else sorted(mode)
        return await agi_cls._benchmark(
            env, scheduler, workers, verbose, mode_range, rapids_enabled, **args
        )

    _configure_mode(agi_cls, env, mode)
    _load_capacity_predictor(agi_cls, env)
    _resolve_install_worker_group(agi_cls, env)

    try:
        return await agi_cls._main(scheduler)
    except process_error_type as exc:
        log.error("failed to run \n%s", exc)
        return None
    except ConnectionError as exc:
        message = str(exc).strip() or "Failed to connect to remote host."
        log.info(message)
        print(message, file=sys.stderr, flush=True)
        return {"status": "error", "message": message, "kind": "connection"}
    except ModuleNotFoundError as exc:
        log.error("failed to load module \n%s", exc)
        return None
    except Exception as exc:
        message = format_exception_chain_fn(exc)
        log.error("Unhandled exception in AGI.run: %s", message)
        if log.isEnabledFor(logging.DEBUG):
            log.debug("Traceback:\n%s", traceback_format_exc_fn())
        raise


async def install(
    agi_cls: Any,
    *,
    env: Any,
    scheduler: Optional[str] = None,
    workers: Optional[Dict[str, int]] = None,
    workers_data_path: Optional[str] = None,
    modes_enabled: int,
    verbose: Optional[int] = None,
    args: Dict[str, Any],
) -> None:
    agi_cls._run_type = "sync"
    mode = agi_cls._INSTALL_MODE | modes_enabled
    await agi_cls.run(
        env=env,
        scheduler=scheduler,
        workers=workers,
        workers_data_path=workers_data_path,
        mode=mode,
        rapids_enabled=agi_cls._INSTALL_MODE & modes_enabled,
        verbose=verbose,
        **args,
    )


async def update(
    agi_cls: Any,
    *,
    env: Any = None,
    scheduler: Optional[str] = None,
    workers: Optional[Dict[str, int]] = None,
    modes_enabled: int,
    args: Dict[str, Any],
) -> None:
    agi_cls._run_type = "upgrade"
    await agi_cls.run(
        env=env,
        scheduler=scheduler,
        workers=workers,
        mode=(agi_cls._UPDATE_MODE | modes_enabled) & agi_cls._DASK_RESET,
        rapids_enabled=agi_cls._UPDATE_MODE & modes_enabled,
        **args,
    )


async def get_distrib(
    agi_cls: Any,
    *,
    env: Any,
    scheduler: Optional[str] = None,
    workers: Optional[Dict[str, int]] = None,
    args: Dict[str, Any],
) -> Any:
    agi_cls._run_type = "simulate"
    return await agi_cls.run(env, scheduler, workers, mode=agi_cls._SIMULATE_MODE, **args)


async def distribute(
    agi_cls: Any,
    *,
    env: Any,
    scheduler: Optional[str] = None,
    workers: Optional[Dict[str, int]] = None,
    args: Dict[str, Any],
) -> Any:
    return await get_distrib(
        agi_cls,
        env=env,
        scheduler=scheduler,
        workers=workers,
        args=args,
    )


async def connect_scheduler_with_retry(
    address: str,
    *,
    timeout: float,
    heartbeat_interval: int = 5000,
    client_factory: Callable[..., Any],
    sleep_fn: Callable[[float], Any] = asyncio.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
    log: Any = logger,
) -> Any:
    deadline = monotonic_fn() + max(timeout, 1)
    attempt = 0
    last_exc: Optional[Exception] = None
    while monotonic_fn() < deadline:
        attempt += 1
        remaining = max(deadline - monotonic_fn(), 0.5)
        try:
            return await client_factory(
                address,
                heartbeat_interval=heartbeat_interval,
                timeout=remaining,
            )
        except Exception as exc:
            last_exc = exc
            sleep_for = min(1.0 * attempt, 5.0)
            log.debug(
                "Dask scheduler at %s not ready (attempt %s, retrying in %.1fs): %s",
                address,
                attempt,
                sleep_for,
                exc,
            )
            await sleep_fn(sleep_for)

    raise RuntimeError("Failed to instantiate Dask Client") from last_exc


async def detect_export_cmd(
    agi_cls: Any,
    ip: str,
    *,
    is_local_fn: Callable[[str], bool],
    local_export_bin: str,
) -> str:
    if is_local_fn(ip):
        return local_export_bin

    try:
        os_id = await agi_cls.exec_ssh(ip, "uname -s")
    except Exception:
        os_id = ""

    if any(name in os_id for name in ("Linux", "Darwin", "BSD")):
        return 'export PATH="$HOME/.local/bin:$PATH";'
    return ""


async def _prepare_scheduler_nodes(
    agi_cls: Any,
    scheduler: Optional[str],
    *,
    cli_rel: Path,
    log: Any = logger,
) -> Optional[str]:
    env = agi_cls.env
    if (agi_cls._mode_auto and agi_cls._mode == agi_cls.DASK_MODE) or not agi_cls._mode_auto:
        env.hw_rapids_capable = True
        if agi_cls._mode & agi_cls.DASK_MODE:
            if scheduler is None:
                if list(agi_cls._workers) == ["127.0.0.1"]:
                    scheduler = "127.0.0.1"
                else:
                    log.info("AGI.run(...scheduler='scheduler ip address' is required -> Stop")
            agi_cls._scheduler_ip, agi_cls._scheduler_port = agi_cls._get_scheduler(scheduler)

        for ip in list(agi_cls._workers):
            await agi_cls.send_file(
                env,
                ip,
                env.cluster_pck / "agi_distributor/cli.py",
                cli_rel,
            )
            hw_rapids_capable = env.envars.get(ip, None)
            if not hw_rapids_capable or hw_rapids_capable == "no_rapids_hw":
                env.hw_rapids_capable = False
            await agi_cls._kill(ip, os.getpid(), force=True)

        if agi_cls._scheduler_ip not in agi_cls._workers:
            await agi_cls._kill(agi_cls._scheduler_ip, os.getpid(), force=True)
    return scheduler


async def _ensure_local_scheduler_port(agi_cls: Any, *, log: Any = logger) -> None:
    released = await agi_cls._wait_for_port_release(agi_cls._scheduler_ip, agi_cls._scheduler_port)
    if not released:
        new_port = agi_cls.find_free_port()
        log.warning(
            "Scheduler port %s:%s still busy. Switching scheduler port to %s.",
            agi_cls._scheduler_ip,
            agi_cls._scheduler_port,
            new_port,
        )
        agi_cls._scheduler_port = new_port
        agi_cls._scheduler = f"{agi_cls._scheduler_ip}:{agi_cls._scheduler_port}"
    elif agi_cls._mode_auto:
        new_port = agi_cls.find_free_port()
        agi_cls._scheduler_ip, agi_cls._scheduler_port = agi_cls._get_scheduler(
            {agi_cls._scheduler_ip: new_port}
        )


async def _resolve_scheduler_cmd_prefix(
    agi_cls: Any,
    *,
    set_env_var_fn: Callable[..., Any],
) -> str:
    env = agi_cls.env
    cmd_prefix = env.envars.get(f"{agi_cls._scheduler_ip}_CMD_PREFIX", "")
    if not cmd_prefix:
        try:
            cmd_prefix = await agi_cls._detect_export_cmd(agi_cls._scheduler_ip) or ""
        except Exception:
            cmd_prefix = ""
        if cmd_prefix:
            set_env_var_fn(f"{agi_cls._scheduler_ip}_CMD_PREFIX", cmd_prefix)
    return cmd_prefix


async def _launch_scheduler_process(
    agi_cls: Any,
    *,
    cmd_prefix: str,
    create_task_fn: Callable[..., Any],
    sleep_fn: Callable[[float], Any],
    log: Any = logger,
) -> None:
    env = agi_cls.env
    toml_local = env.active_app / "pyproject.toml"
    wenv_rel = env.wenv_rel
    wenv_abs = env.wenv_abs
    dask_env = agi_cls._dask_env_prefix()
    if env.is_local(agi_cls._scheduler_ip):
        await sleep_fn(1)
        local_prefix = cmd_prefix or env.export_local_bin or ""
        cmd = (
            f"{local_prefix}{dask_env}{env.uv} run --no-sync --project {env.wenv_abs} "
            f"dask scheduler "
            f"--port {agi_cls._scheduler_port} "
            f"--host {agi_cls._scheduler_ip} "
            f"--dashboard-address :0 "
            f"--pid-file {wenv_abs.parent / 'dask_scheduler.pid'} "
        )
        log.info("Starting dask scheduler locally: %s", cmd)
        result = agi_cls._exec_bg(cmd, env.app)
        if result:
            log.info(result)
        return

    cmd = (
        f"{cmd_prefix}{env.uv} run --no-sync python -c "
        f"\"import os; os.makedirs('{wenv_rel}', exist_ok=True)\""
    )
    await agi_cls.exec_ssh(agi_cls._scheduler_ip, cmd)

    toml_wenv = wenv_rel / "pyproject.toml"
    await agi_cls.send_file(env, agi_cls._scheduler_ip, toml_local, toml_wenv)

    cmd = (
        f"{cmd_prefix}{dask_env}{env.uv} --project {wenv_rel} run --no-sync "
        f"dask scheduler "
        f"--port {agi_cls._scheduler_port} "
        f"--host {agi_cls._scheduler_ip} --dashboard-address :0 --pid-file dask_scheduler.pid"
    )
    create_task_fn(agi_cls.exec_ssh_async(agi_cls._scheduler_ip, cmd))


async def start_scheduler(
    agi_cls: Any,
    scheduler: Optional[str],
    *,
    set_env_var_fn: Callable[..., Any],
    create_task_fn: Callable[..., Any] = asyncio.create_task,
    sleep_fn: Callable[[float], Any] = asyncio.sleep,
    log: Any = logger,
) -> bool:
    env = agi_cls.env
    cli_rel = env.wenv_rel.parent / "cli.py"
    await _prepare_scheduler_nodes(
        agi_cls,
        scheduler,
        cli_rel=cli_rel,
        log=log,
    )

    if env.is_local(agi_cls._scheduler_ip):
        await _ensure_local_scheduler_port(agi_cls, log=log)

    cmd_prefix = await _resolve_scheduler_cmd_prefix(
        agi_cls,
        set_env_var_fn=set_env_var_fn,
    )
    await _launch_scheduler_process(
        agi_cls,
        cmd_prefix=cmd_prefix,
        create_task_fn=create_task_fn,
        sleep_fn=sleep_fn,
        log=log,
    )

    await sleep_fn(1)
    try:
        client = await agi_cls._connect_scheduler_with_retry(
            agi_cls._scheduler,
            timeout=max(agi_cls._TIMEOUT * 3, 15),
            heartbeat_interval=5000,
        )
        agi_cls._dask_client = client
    except Exception as exc:
        log.error("Dask Client instantiation trouble, run aborted due to:")
        log.info(exc)
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError("Failed to instantiate Dask Client") from exc

    agi_cls._install_done = True
    if agi_cls._worker_init_error:
        raise FileNotFoundError(f"Please run AGI.install([{agi_cls._scheduler_ip}])")
    return True
