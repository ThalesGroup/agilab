import asyncio
import contextlib
import inspect
import logging
import os
import shlex
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from zipfile import BadZipFile, ZipFile

from agi_cluster.agi_distributor import background_jobs_support, deployment_remote_support


logger = logging.getLogger(__name__)

_CMD_PREFIX_LOOKUP_EXCEPTIONS = (ConnectionError, OSError, RuntimeError, TimeoutError)
_WORKER_START_EXCEPTIONS = (ConnectionError, FileNotFoundError, OSError, RuntimeError, TimeoutError)
_SYNC_RETRY_EXCEPTIONS = (ConnectionError, OSError, RuntimeError, TimeoutError)
_STOP_RETRY_EXCEPTIONS = (ConnectionError, OSError, RuntimeError, TimeoutError)
_TOP_LEVEL_UI_MODULE_SUFFIX = "_args_form.py"
_TOP_LEVEL_UI_BYTECODE_SUFFIX = "_args_form."


def _sorted_glob_matches(root: Path, pattern: str) -> list[Path]:
    return sorted(root.glob(pattern), key=lambda candidate: candidate.name)


def _is_top_level_ui_artifact(name: str) -> bool:
    parts = Path(name).parts
    if len(parts) == 1:
        filename = parts[0]
        return filename == "app_args_form.py" or filename.endswith(_TOP_LEVEL_UI_MODULE_SUFFIX)
    if len(parts) == 2 and parts[0] == "__pycache__":
        filename = parts[1]
        return (
            filename.endswith(".pyc")
            and (
                filename.startswith("app_args_form.")
                or _TOP_LEVEL_UI_BYTECODE_SUFFIX in filename
            )
        )
    return False


def _clean_top_level_ui_source_artifacts(src_dir: Path, *, log: Any = logger) -> list[Path]:
    if not src_dir.exists():
        return []
    removed: list[Path] = []
    for pattern in ("app_args_form.py", "*_args_form.py"):
        for candidate in src_dir.glob(pattern):
            if candidate.is_file():
                candidate.unlink()
                removed.append(candidate)
    pycache_dir = src_dir / "__pycache__"
    if pycache_dir.exists():
        for pattern in ("app_args_form.*.pyc", "*_args_form.*.pyc"):
            for candidate in pycache_dir.glob(pattern):
                if candidate.is_file():
                    candidate.unlink()
                    removed.append(candidate)
        try:
            pycache_dir.rmdir()
        except OSError:
            pass
    for candidate in removed:
        log.info("Removed UI-only worker source artifact: %s", candidate)
    return removed


def _sanitize_egg_top_level_metadata(name: str, data: bytes) -> bytes:
    if name != "EGG-INFO/top_level.txt":
        return data
    lines = data.decode("utf-8", errors="ignore").splitlines()
    kept = [
        line
        for line in lines
        if line.strip() != "app_args_form" and not line.strip().endswith("_args_form")
    ]
    text = "\n".join(kept)
    if text:
        text += "\n"
    return text.encode("utf-8")


def _sanitize_worker_upload_egg(egg_file: Path, *, log: Any = logger) -> list[str]:
    tmp_file = egg_file.with_name(f".{egg_file.name}.tmp")
    removed: list[str] = []
    changed = False
    try:
        with ZipFile(egg_file, "r") as source, ZipFile(tmp_file, "w") as dest:
            for info in source.infolist():
                name = info.filename
                if _is_top_level_ui_artifact(name):
                    removed.append(name)
                    changed = True
                    continue
                data = source.read(name)
                sanitized = _sanitize_egg_top_level_metadata(name, data)
                if sanitized != data:
                    changed = True
                dest.writestr(info, sanitized)
    except (BadZipFile, OSError) as exc:
        with contextlib.suppress(OSError):
            tmp_file.unlink()
        log.warning("Could not sanitize worker egg %s: %s", egg_file, exc)
        return []

    if changed:
        tmp_file.replace(egg_file)
        for name in removed:
            log.info("Removed UI-only worker egg artifact: %s!%s", egg_file, name)
        return removed

    with contextlib.suppress(OSError):
        tmp_file.unlink()
    return []


def sanitize_worker_upload_artifacts(wenv_abs: Path, *, log: Any = logger) -> list[str | Path]:
    """Ensure existing worker upload artifacts do not import Streamlit-only forms."""
    removed: list[str | Path] = []
    removed.extend(_clean_top_level_ui_source_artifacts(wenv_abs / "src", log=log))
    for egg_file in _sorted_glob_matches(wenv_abs / "dist", "*.egg"):
        removed.extend(_sanitize_worker_upload_egg(egg_file, log=log))
    return removed


def _manager_apps_path(env: Any) -> Path | None:
    active_app = getattr(env, "active_app", None)
    if isinstance(active_app, Path):
        parent = active_app.parent
        if parent.name == "builtin":
            return parent
    apps_path = getattr(env, "apps_path", None)
    if isinstance(apps_path, Path):
        return apps_path
    if isinstance(active_app, Path):
        return active_app.parent
    return None


def _manager_app_name(env: Any) -> str:
    app_name = getattr(env, "app", None)
    if isinstance(app_name, str) and app_name:
        return app_name
    active_app = getattr(env, "active_app", None)
    if isinstance(active_app, Path):
        return active_app.name
    target = getattr(env, "target", None)
    if isinstance(target, str) and target:
        return f"{target}_project"
    target_worker = getattr(env, "target_worker", None)
    if isinstance(target_worker, str) and target_worker.endswith("_worker"):
        return target_worker.removesuffix("_worker") + "_project"
    return "flight_telemetry_project"


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


def _worker_startup_args(agi_cls: Any) -> dict[str, Any]:
    worker_args = getattr(agi_cls, "_worker_args", None)
    if worker_args is None:
        worker_args = getattr(agi_cls, "_args", None)
    return dict(worker_args or {})


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
        worker_args = _worker_startup_args(agi_cls)
        base_worker_cls._new(env=env, mode=agi_cls._mode, verbose=env.verbose, args=worker_args)
        res = await base_worker_cls._run(
            env=env,
            mode=agi_cls._mode,
            workers=agi_cls._workers,
            verbose=env.verbose,
            args=agi_cls._args,
        )
    else:
        uv_worker = getattr(env, "uv_worker", env.uv)
        pyvers_worker = getattr(env, "pyvers_worker", None)
        python_selector = f" --python {pyvers_worker}" if pyvers_worker else ""
        manager_apps_path = _manager_apps_path(env)
        manager_app = _manager_app_name(env)
        manager_apps_expr = (
            f"Path({repr(str(manager_apps_path))})" if manager_apps_path is not None else "None"
        )
        manager_app_expr = repr(manager_app)
        worker_args = _worker_startup_args(agi_cls)
        cmd = (
            f"{uv_worker} run --preview-features python-upgrade --no-sync --project {env.wenv_abs}"
            f"{python_selector} python -c \""
            f"from pathlib import Path\n"
            f"from agi_env import AgiEnv\n"
            f"from agi_node.agi_dispatcher import  BaseWorker\n"
            f"import asyncio\n"
            f"async def main():\n"
            f"  env = AgiEnv(apps_path={manager_apps_expr}, app={manager_app_expr}, verbose={env.verbose})\n"
            f"  BaseWorker._new(env=env, mode={agi_cls._mode}, verbose={env.verbose}, args={worker_args})\n"
            f"  res = await BaseWorker._run(env=env, mode={agi_cls._mode}, workers={agi_cls._workers}, args={agi_cls._args})\n"
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
    sanitize_worker_upload_artifacts_fn: Callable[..., Any] = sanitize_worker_upload_artifacts,
    log: Any = logger,
) -> bool:
    env = agi_cls.env
    dask_env = dask_env_prefix(agi_cls)

    if not await agi_cls._start_scheduler(scheduler):
        return False

    await ensure_remote_cluster_shares(agi_cls)

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
                    local_cmd = [
                        *shlex.split(str(env.uv), posix=os.name != "nt"),
                        "--project",
                        str(wenv_abs),
                        "run",
                        "--no-sync",
                        "dask",
                        "worker",
                        f"tcp://{agi_cls._scheduler}",
                        "--no-nanny",
                        "--pid-file",
                        str(wenv_abs / pid_file),
                    ]
                    process_env = background_jobs_support.background_env_from_prefixes(cmd_prefix, dask_env)
                    agi_cls._exec_bg(local_cmd, str(wenv_abs), env=process_env)
                else:
                    wenv_rel = env.wenv_rel
                    remote_cmd = (
                        f'{cmd_prefix}{dask_env}{env.uv} --project {wenv_rel} run --no-sync '
                        f'dask worker '
                        f'tcp://{agi_cls._scheduler} --no-nanny --pid-file {wenv_rel.parent / pid_file}'
                    )
                    create_task_fn(agi_cls.exec_ssh_async(ip, remote_cmd))
                    log.info(f"Launched remote worker in background on {ip}: {remote_cmd}")

            except _WORKER_START_EXCEPTIONS as exc:
                log.error(f"Failed to start worker on {ip}: {exc}")
                raise

            if agi_cls._worker_init_error:
                raise FileNotFoundError(f"Please run AGI.install([{ip}])")

    await agi_cls._sync(timeout=agi_cls._TIMEOUT)

    if not agi_cls._mode_auto or (agi_cls._mode_auto and agi_cls._mode == 0):
        await agi_cls._build_lib_remote()
        if agi_cls._mode & agi_cls.DASK_MODE:
            sanitize_worker_upload_artifacts_fn(agi_cls.env.wenv_abs, log=log)
            for egg_file in _sorted_glob_matches(agi_cls.env.wenv_abs / "dist", "*.egg"):
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


async def ensure_remote_cluster_shares(
    agi_cls: Any,
    *,
    prepare_remote_cluster_share_fn: Callable[..., Any] | None = None,
    log: Any = logger,
) -> list[str]:
    """Revalidate SSHFS-backed worker shares before Dask workers start.

    Remote mounts can disappear after an install while the worker venv remains valid.
    Reusing the install-time mount routine here keeps RUN idempotent and prevents
    workers from reading an empty local directory with a stale `AGI_CLUSTER_SHARE`.
    """
    remote_share = str(getattr(agi_cls, "_workers_data_path", "") or "").strip()
    if not remote_share:
        return []

    if prepare_remote_cluster_share_fn is None:
        prepare_remote_cluster_share_fn = deployment_remote_support._prepare_remote_cluster_share

    env = agi_cls.env
    mounted: list[str] = []
    for ip in sorted(getattr(agi_cls, "_workers", {}) or {}):
        if env.is_local(ip):
            continue
        await prepare_remote_cluster_share_fn(
            agi_cls,
            ip,
            env,
            remote_share,
            log=log,
        )
        mounted.append(ip)
    return mounted


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
                app=_manager_app_name(env),
                mode=agi_cls._mode,
                verbose=agi_cls.verbose,
                worker_id=dask_workers.index(worker),
                worker=worker,
                args=_worker_startup_args(agi_cls),
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


def exec_bg(agi_cls: Any, cmd: Any, cwd: str, *, env: Optional[Dict[str, str]] = None) -> None:
    if env is None:
        job = agi_cls._jobs.new(cmd, cwd=cwd)
    else:
        job = agi_cls._jobs.new(cmd, cwd=cwd, env=env)
    job_id = getattr(job, "num", 0)
    if not agi_cls._jobs.result(job_id):
        raise RuntimeError(f"running {cmd} at {cwd}")
