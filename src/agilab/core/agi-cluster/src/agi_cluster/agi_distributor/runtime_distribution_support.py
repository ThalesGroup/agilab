import asyncio
import inspect
import logging
import os
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Callable, Dict, Optional


logger = logging.getLogger(__name__)

_CMD_PREFIX_LOOKUP_EXCEPTIONS = (ConnectionError, OSError, RuntimeError, TimeoutError)
_WORKER_START_EXCEPTIONS = (ConnectionError, FileNotFoundError, OSError, RuntimeError, TimeoutError)
_SYNC_RETRY_EXCEPTIONS = (ConnectionError, OSError, RuntimeError, TimeoutError)
_STOP_RETRY_EXCEPTIONS = (ConnectionError, OSError, RuntimeError, TimeoutError)


async def _maybe_await(result: Any) -> Any:
    if inspect.isawaitable(result):
        return await result
    return result


async def _scheduler_info_payload(client: Any) -> Any:
    return await _maybe_await(client.scheduler_info())


def dask_env_prefix(agi_cls: Any) -> str:
    level = agi_cls._dask_log_level
    if not level:
        return ""
    env_vars = [
        f"DASK_DISTRIBUTED__LOGGING__distributed={level}",
    ]
    return "".join(f"{var} " for var in env_vars)


async def run_local(
    agi_cls: Any,
    *,
    base_worker_cls: Any,
    validate_worker_uv_sources_fn: Callable[[Path], None],
    run_async_fn: Callable[[str, Path], Any],
    log: Any = logger,
) -> Any:
    env = agi_cls.env
    env.hw_rapids_capable = env.envars.get("127.0.0.1", "hw_rapids_capable")

    if not (env.wenv_abs / ".venv").exists():
        log.info("Worker installation not found")
        raise FileNotFoundError("Worker installation (.venv) not found")
    validate_worker_uv_sources_fn(env.wenv_abs / "pyproject.toml")

    pid_file = "dask_worker_0.pid"
    current_pid = os.getpid()
    with open(pid_file, "w", encoding="utf-8") as stream:
        stream.write(str(current_pid))

    await agi_cls._kill(current_pid=current_pid, force=True)

    log.info("debug=%s", env.debug)
    if env.debug:
        base_worker_cls._new(env=env, mode=agi_cls._mode, verbose=env.verbose, args=agi_cls._args)
        res = await base_worker_cls._run(
            env=env,
            mode=agi_cls._mode,
            workers=agi_cls._workers,
            verbose=env.verbose,
            args=agi_cls._args,
        )
    else:
        cmd = (
            f"{env.uv} run --preview-features python-upgrade --no-sync --project {env.wenv_abs} python -c \""
            f"from agi_node.agi_dispatcher import  BaseWorker\n"
            f"import asyncio\n"
            f"async def main():\n"
            f"  BaseWorker._new(app='{env.target_worker}', mode={agi_cls._mode}, verbose={env.verbose}, args={agi_cls._args})\n"
            f"  res = await BaseWorker._run(mode={agi_cls._mode}, workers={agi_cls._workers}, args={agi_cls._args})\n"
            f"  print(res)\n"
            f"if __name__ == '__main__':\n"
            f"  asyncio.run(main())\""
        )
        res = await run_async_fn(cmd, env.wenv_abs)

    if not res:
        return None
    if isinstance(res, list):
        return res
    res_lines = res.split("\n")
    if len(res_lines) < 2:
        return res
    return res_lines[-2]


async def start(
    agi_cls: Any,
    scheduler: Optional[str],
    *,
    set_env_var_fn: Callable[..., Any],
    create_task_fn: Callable[..., Any] = asyncio.create_task,
    log: Any = logger,
) -> bool:
    env = agi_cls.env
    dask_env = dask_env_prefix(agi_cls)

    if not await agi_cls._start_scheduler(scheduler):
        return False

    for i, (ip, n) in enumerate(agi_cls._workers.items()):
        is_local = env.is_local(ip)
        cmd_prefix = env.envars.get(f"{ip}_CMD_PREFIX", "")
        if not cmd_prefix:
            try:
                cmd_prefix = await agi_cls._detect_export_cmd(ip) or ""
            except _CMD_PREFIX_LOOKUP_EXCEPTIONS:
                cmd_prefix = ""
            if cmd_prefix:
                set_env_var_fn(f"{ip}_CMD_PREFIX", cmd_prefix)

        for j in range(n):
            try:
                log.info(f"Starting worker #{i}.{j} on [{ip}]")
                pid_file = f"dask_worker_{i}_{j}.pid"
                if is_local:
                    wenv_abs = env.wenv_abs
                    cmd = (
                        f'{cmd_prefix}{dask_env}{env.uv} --project {wenv_abs} run --no-sync '
                        f'dask worker '
                        f'tcp://{agi_cls._scheduler} --no-nanny '
                        f'--pid-file {wenv_abs / pid_file}'
                    )
                    agi_cls._exec_bg(cmd, str(wenv_abs))
                else:
                    wenv_rel = env.wenv_rel
                    cmd = (
                        f'{cmd_prefix}{dask_env}{env.uv} --project {wenv_rel} run --no-sync '
                        f'dask worker '
                        f'tcp://{agi_cls._scheduler} --no-nanny --pid-file {wenv_rel.parent / pid_file}'
                    )
                    create_task_fn(agi_cls.exec_ssh_async(ip, cmd))
                    log.info(f"Launched remote worker in background on {ip}: {cmd}")

            except _WORKER_START_EXCEPTIONS as exc:
                log.error(f"Failed to start worker on {ip}: {exc}")
                raise

            if agi_cls._worker_init_error:
                raise FileNotFoundError(f"Please run AGI.install([{ip}])")

    await agi_cls._sync(timeout=agi_cls._TIMEOUT)

    if not agi_cls._mode_auto or (agi_cls._mode_auto and agi_cls._mode == 0):
        await agi_cls._build_lib_remote()
        if agi_cls._mode & agi_cls.DASK_MODE:
            for egg_file in (agi_cls.env.wenv_abs / "dist").glob("*.egg"):
                agi_cls._dask_client.upload_file(str(egg_file))
    return True


async def sync(
    agi_cls: Any,
    *,
    timeout: int = 60,
    client_type: type[Any],
    sleep_fn: Callable[[float], Any] = asyncio.sleep,
    time_fn: Callable[[], float] = time.time,
    log: Any = logger,
) -> None:
    if not isinstance(agi_cls._dask_client, client_type):
        return
    start_time = time_fn()
    expected_workers = sum(agi_cls._workers.values())

    while True:
        try:
            info = await _scheduler_info_payload(agi_cls._dask_client)
            workers_info = info.get("workers")
            if workers_info is None:
                log.info("Scheduler info 'workers' not ready yet.")
                await sleep_fn(3)
                if time_fn() - start_time > timeout:
                    log.error("Timeout waiting for scheduler workers info.")
                    raise TimeoutError("Timed out waiting for scheduler workers info")
                continue

            runners = list(workers_info.keys())
            current_count = len(runners)
            remaining = expected_workers - current_count

            if runners:
                log.info(f"Current workers connected: {runners}")
            log.info(f"Waiting for number of workers to attach: {remaining} remaining...")

            if current_count >= expected_workers or remaining <= 0:
                break

            if time_fn() - start_time > timeout:
                log.error("Timeout waiting for all workers. {remaining} workers missing.")
                raise TimeoutError("Timed out waiting for all workers to attach")
            await sleep_fn(3)

        except _SYNC_RETRY_EXCEPTIONS as exc:
            log.info(f"Exception in _sync: {exc}")
            await sleep_fn(1)
            if time_fn() - start_time > timeout:
                raise TimeoutError(f"Timeout waiting for all workers due to exception: {exc}")

    log.info("All workers successfully attached to scheduler")


def scale_cluster(agi_cls: Any, *, log: Any = logger) -> None:
    if not agi_cls._dask_workers:
        return

    nb_kept_workers = {}
    workers_to_remove = []
    for dask_worker in agi_cls._dask_workers:
        ip = dask_worker.split(":")[0]
        if ip in agi_cls._workers:
            if ip not in nb_kept_workers:
                nb_kept_workers[ip] = 0
            if nb_kept_workers[ip] >= agi_cls._workers[ip]:
                workers_to_remove.append(dask_worker)
            else:
                nb_kept_workers[ip] += 1
        else:
            workers_to_remove.append(dask_worker)

    if workers_to_remove:
        log.info(f"unused workers: {len(workers_to_remove)}")
        for worker in workers_to_remove:
            agi_cls._dask_workers.remove(worker)


async def distribute(
    agi_cls: Any,
    *,
    work_dispatcher_cls: Any,
    base_worker_cls: Any,
    time_fn: Callable[[], float] = time.time,
    log: Any = logger,
) -> str:
    env = agi_cls.env

    agi_cls._dask_workers = [
        worker.split("/")[-1]
        for worker in list(agi_cls._dask_client.scheduler_info()["workers"].keys())
    ]
    log.info(f"AGI run mode={agi_cls._mode} on {list(agi_cls._dask_workers)} ... ")

    agi_cls._workers, workers_plan, workers_plan_metadata = await work_dispatcher_cls._do_distrib(
        env, agi_cls._workers, agi_cls._args
    )
    agi_cls._work_plan = workers_plan
    agi_cls._work_plan_metadata = workers_plan_metadata

    agi_cls._scale_cluster()

    dask_workers = list(agi_cls._dask_workers)
    client = agi_cls._dask_client

    agi_cls._dask_client.gather(
        [
            client.submit(
                base_worker_cls._new,
                env=0 if env.debug else None,
                app=env.target_worker,
                mode=agi_cls._mode,
                verbose=agi_cls.verbose,
                worker_id=dask_workers.index(worker),
                worker=worker,
                args=agi_cls._args,
                workers=[worker],
            )
            for worker in dask_workers
        ]
    )

    await agi_cls._calibration()

    started_at = time_fn()
    futures = {}
    for worker_idx, worker_addr in enumerate(dask_workers):
        plan_payload = agi_cls._wrap_worker_chunk(workers_plan or [], worker_idx)
        metadata_payload = agi_cls._wrap_worker_chunk(workers_plan_metadata or [], worker_idx)
        futures[worker_addr] = client.submit(
            base_worker_cls._do_works,
            plan_payload,
            metadata_payload,
            workers=[worker_addr],
        )

    gathered_logs = client.gather(list(futures.values())) if futures else []
    worker_logs: Dict[str, str] = {}
    for idx, worker_addr in enumerate(futures.keys()):
        log_value = gathered_logs[idx] if idx < len(gathered_logs) else ""
        worker_logs[worker_addr] = log_value or ""
    if agi_cls.debug and not worker_logs:
        worker_logs = {worker: "" for worker in dask_workers}

    for worker, worker_log in worker_logs.items():
        log.info(f"\n=== Worker {worker} logs ===\n{worker_log}")

    runtime = time_fn() - started_at
    log.info(f"{env.mode2str(agi_cls._mode)} {runtime}")
    return f"{env.mode2str(agi_cls._mode)} {runtime}"


async def main(
    agi_cls: Any,
    scheduler: Optional[str],
    *,
    background_job_manager_factory: Callable[[], Any],
    time_fn: Callable[[], float] = time.time,
) -> Any:
    cond_clean = True
    agi_cls._jobs = background_job_manager_factory()

    if (agi_cls._mode & agi_cls._DEPLOYEMENT_MASK) == agi_cls._SIMULATE_MODE:
        res = await agi_cls._run()
    elif agi_cls._mode >= agi_cls._INSTALL_MODE:
        started_at = time_fn()
        agi_cls._clean_dirs_local()
        await agi_cls._prepare_local_env()
        if agi_cls._mode & agi_cls.DASK_MODE:
            await agi_cls._prepare_cluster_env(scheduler)
        await agi_cls._deploy_application(scheduler)
        res = time_fn() - started_at
    elif agi_cls._mode & agi_cls.DASK_MODE:
        await agi_cls._start(scheduler)
        res = await agi_cls._distribute()
        agi_cls._update_capacity()
        await agi_cls._stop()
    else:
        res = await agi_cls._run()

    agi_cls._clean_job(cond_clean)
    return res


def clean_job(agi_cls: Any, cond_clean: bool) -> None:
    if agi_cls._jobs and cond_clean:
        if agi_cls.verbose:
            agi_cls._jobs.flush()
        else:
            with open(os.devnull, "w") as f, redirect_stdout(f), redirect_stderr(f):
                agi_cls._jobs.flush()


async def stop(
    agi_cls: Any,
    *,
    sleep_fn: Callable[[float], Any] = asyncio.sleep,
    log: Any = logger,
) -> None:
    log.info("stop Agi core")

    retire_attempts = 0
    while retire_attempts < agi_cls._TIMEOUT:
        try:
            scheduler_info = await _scheduler_info_payload(agi_cls._dask_client)
        except _STOP_RETRY_EXCEPTIONS as exc:
            log.debug("Unable to fetch scheduler info during shutdown: %s", exc)
            break

        workers = scheduler_info.get("workers") or {}
        if not workers:
            break

        retire_attempts += 1
        try:
            await _maybe_await(
                agi_cls._dask_client.retire_workers(
                    workers=list(workers.keys()),
                    close_workers=True,
                    remove=True,
                )
            )
        except _STOP_RETRY_EXCEPTIONS as exc:
            log.debug("retire_workers failed: %s", exc)
            break

        await sleep_fn(1)

    try:
        if ((agi_cls._mode_auto and (agi_cls._mode == 7 or agi_cls._mode == 15))
                or not agi_cls._mode_auto):
            await _maybe_await(agi_cls._dask_client.shutdown())
    except _STOP_RETRY_EXCEPTIONS as exc:
        log.debug("Dask client shutdown raised: %s", exc)

    await agi_cls._close_all_connections()


def exec_bg(agi_cls: Any, cmd: str, cwd: str) -> None:
    job = agi_cls._jobs.new(cmd, cwd=cwd)
    job_id = getattr(job, "num", 0)
    if not agi_cls._jobs.result(job_id):
        raise RuntimeError(f"running {cmd} at {cwd}")
