import asyncio
import contextlib
import inspect
import logging
import os
import signal
import shlex
import subprocess
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path, PurePath
from typing import Any, Callable, Dict, Optional
from zipfile import BadZipFile, ZipFile

import psutil

from agi_cluster.agi_distributor import background_jobs_support, deployment_remote_support
from agi_env.process_support import project_virtualenv_script_path


logger = logging.getLogger(__name__)

RUNTIME_CLEANUP_TIMEOUT_SECONDS = 30.0


class RuntimeCleanupRequiredError(RuntimeError):
    """Raised when owned runtime shutdown cannot be proven within its bound."""


_CMD_PREFIX_LOOKUP_EXCEPTIONS = (ConnectionError, OSError, RuntimeError, TimeoutError)
_WORKER_START_EXCEPTIONS = (ConnectionError, FileNotFoundError, OSError, RuntimeError, TimeoutError)
_SYNC_RETRY_EXCEPTIONS = (ConnectionError, OSError, RuntimeError, TimeoutError)
_BACKGROUND_TREE_CLEANUP_EXCEPTIONS = (
    AttributeError,
    OSError,
    RuntimeError,
    subprocess.SubprocessError,
    TypeError,
    ValueError,
    psutil.Error,
)
_STOP_RETRY_EXCEPTIONS = (ConnectionError, OSError, RuntimeError, TimeoutError)
_TOP_LEVEL_UI_MODULE_SUFFIX = "_args_form.py"
_TOP_LEVEL_UI_BYTECODE_SUFFIX = "_args_form."
_SYNC_POLL_DELAYS_SECONDS = (0.2, 0.5, 1.0, 3.0)


def _sorted_glob_matches(root: Path, pattern: str) -> list[Path]:
    return sorted(root.glob(pattern), key=lambda candidate: candidate.name)


def _sync_poll_delay(attempt: int) -> float:
    if attempt < 0:
        attempt = 0
    if attempt >= len(_SYNC_POLL_DELAYS_SECONDS):
        return _SYNC_POLL_DELAYS_SECONDS[-1]
    return _SYNC_POLL_DELAYS_SECONDS[attempt]


# Default listen-port range pinned on dask workers so clean installs stay
# firewall-friendly (the client connects INBOUND to each worker's listen
# port). Override with AGILAB_DASK_WORKER_PORT_RANGE; set it to "ephemeral"
# to restore OS-assigned random ports.
DEFAULT_WORKER_PORT_RANGE = "9000:9100"


def _worker_port_range(env: Any) -> str | None:
    """Fixed listen-port range for dask workers (firewall pinning).

    Accepts a single port ("9000") or an inclusive range ("9000:9100"), the
    same syntax as `dask worker --worker-port`. Defaults to
    :data:`DEFAULT_WORKER_PORT_RANGE`; the value "ephemeral" disables pinning.
    """
    raw = deployment_remote_support._env_lookup(
        env,
        "AGILAB_DASK_WORKER_PORT_RANGE",
        "DASK_WORKER_PORT_RANGE",
        "dask_worker_port_range",
    )
    if raw in (None, ""):
        return DEFAULT_WORKER_PORT_RANGE
    text = str(raw).strip()
    if text.lower() == "ephemeral":
        return None
    parts = text.split(":")
    if len(parts) not in (1, 2):
        raise ValueError(f"Invalid dask worker port range: {raw!r}")
    try:
        ports = [int(part.strip()) for part in parts]
    except ValueError as exc:
        raise ValueError(f"Invalid dask worker port range: {raw!r}") from exc
    if any(not 1 <= port <= 65535 for port in ports):
        raise ValueError(f"Invalid dask worker port range: {raw!r}")
    if len(ports) == 2 and ports[0] > ports[1]:
        raise ValueError(f"Invalid dask worker port range: {raw!r}")
    return ":".join(str(port) for port in ports)


def _local_dask_worker_command(
    uv_cmd: str,
    wenv_abs: Path,
    scheduler: str,
    pid_file: str,
    *,
    worker_port: str | None = None,
    os_name: str = os.name,
) -> list[str]:
    port_args = ["--worker-port", worker_port] if worker_port else []
    dask_exe = project_virtualenv_script_path(wenv_abs, "dask", os_name=os_name)
    if dask_exe.exists():
        return [
            str(dask_exe),
            "worker",
            f"tcp://{scheduler}",
            "--no-nanny",
            *port_args,
            "--pid-file",
            str(wenv_abs / pid_file),
        ]
    return [
        *shlex.split(str(uv_cmd), posix=os_name != "nt"),
        "--project",
        str(wenv_abs),
        "run",
        "--no-sync",
        "dask",
        "worker",
        f"tcp://{scheduler}",
        "--no-nanny",
        *port_args,
        "--pid-file",
        str(wenv_abs / pid_file),
    ]


def _remote_prefix(value: Any) -> str:
    text = str(value or "")
    if text and not text.endswith(" "):
        text += " "
    return text


def _remote_path(value: Path | str) -> str:
    # Mirror cleanup_support/deployment_remote_support._remote_arg: remote hosts
    # are POSIX shells, so Path values must keep forward separators even when
    # the manager runs on Windows.
    if isinstance(value, PurePath):
        return shlex.quote(value.as_posix())
    return shlex.quote(str(value))


def _remote_words(value: Any) -> str:
    return " ".join(shlex.quote(part) for part in shlex.split(str(value), posix=True))


def _remote_dask_worker_command(
    *,
    cmd_prefix: str,
    dask_env: str,
    uv_cmd: str,
    wenv_rel: Path | str,
    scheduler: str,
    pid_file: str,
    worker_port: str | None = None,
) -> str:
    uv_parts = " ".join(shlex.quote(part) for part in shlex.split(str(uv_cmd), posix=True))
    worker_path = wenv_rel if isinstance(wenv_rel, PurePath) else Path(wenv_rel)
    port_clause = f"--worker-port {shlex.quote(worker_port)} " if worker_port else ""
    return (
        f"{_remote_prefix(cmd_prefix)}"
        f"{_remote_prefix(dask_env)}"
        f"{uv_parts} --project {_remote_path(worker_path)} run --no-sync "
        f"dask worker {shlex.quote(f'tcp://{scheduler}')} --no-nanny "
        f"{port_clause}"
        f"--pid-file {_remote_path(worker_path / pid_file)}"
    )


def _record_phase_timing(agi_cls: Any, phase: str, seconds: float) -> None:
    timings = getattr(agi_cls, "_phase_timings", None)
    if not isinstance(timings, list):
        timings = []
        setattr(agi_cls, "_phase_timings", timings)
    timings.append({"phase": phase, "seconds": round(float(seconds), 6)})


async def _run_timed_phase(
    agi_cls: Any,
    phase: str,
    awaitable_factory: Callable[[], Any],
    *,
    time_fn: Callable[[], float] = time.time,
) -> Any:
    started_at = time_fn()
    try:
        return await awaitable_factory()
    finally:
        _record_phase_timing(agi_cls, phase, time_fn() - started_at)


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


async def _call_client_blocking(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a (potentially blocking) sync Dask client call off the event loop.

    The production client is a synchronous ``distributed.Client`` whose
    ``gather``/``scheduler_info`` block the calling thread for the entire
    compute; offloading keeps the loop servicing the asyncssh worker channels.
    """
    result = await asyncio.to_thread(fn, *args, **kwargs)
    return await _maybe_await(result)


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
    # Normalize the persisted per-IP capability sentinel ("hw_rapids_capable"
    # / "no_rapids_hw") to a boolean; both sentinel strings are truthy, and an
    # unprobed host must not be treated as RAPIDS-capable.
    local_capability = str(env.envars.get("127.0.0.1", "") or "").strip().lower()
    env.hw_rapids_capable = local_capability in {"1", "true", "yes", "on", "hw_rapids_capable"}

    if not (env.wenv_abs / ".venv").exists():
        log.info("Worker installation not found")
        raise FileNotFoundError("Worker installation (.venv) not found")
    validate_worker_uv_sources_fn(env.wenv_abs / "pyproject.toml")

    # Keep ownership evidence inside the exact worker runtime so concurrent
    # managers cannot consume another target's shared-parent PID record.
    pid_file = Path(env.wenv_abs) / "dask_worker_0.pid"
    current_pid = os.getpid()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    with open(pid_file, "w", encoding="utf-8") as stream:
        stream.write(str(current_pid))

    try:
        return await _run_local_worker(
            agi_cls,
            env,
            base_worker_cls=base_worker_cls,
            run_async_fn=run_async_fn,
            log=log,
        )
    finally:
        with contextlib.suppress(OSError):
            pid_file.unlink()


async def _run_local_worker(
    agi_cls: Any,
    env: Any,
    *,
    base_worker_cls: Any,
    run_async_fn: Callable[[str, Path], Any],
    log: Any = logger,
) -> Any:
    current_pid = os.getpid()
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
        pyvers_worker_uv_spec = (
            getattr(env, "pyvers_worker_uv_spec", None)
            or getattr(env, "python_uv_spec", None)
            or pyvers_worker
        )
        python_selector = f" --python {_remote_path(str(pyvers_worker_uv_spec))}" if pyvers_worker_uv_spec else ""
        manager_apps_path = _manager_apps_path(env)
        manager_app = _manager_app_name(env)
        # Use POSIX-style separators so the embedded ``Path(...)`` literal stays
        # portable when the spawned worker decodes the script on either OS.
        manager_apps_expr = (
            f"Path({repr(manager_apps_path.as_posix())})"
            if manager_apps_path is not None
            else "None"
        )
        manager_app_expr = repr(manager_app)
        worker_args = _worker_startup_args(agi_cls)
        worker_script = "\n".join(
            [
                "from pathlib import Path",
                "from agi_env import AgiEnv",
                "from agi_node.agi_dispatcher import  BaseWorker",
                "import asyncio",
                "async def main():",
                f"  env = AgiEnv(apps_path={manager_apps_expr}, app={manager_app_expr}, verbose={env.verbose})",
                f"  BaseWorker._new(env=env, mode={agi_cls._mode}, verbose={env.verbose}, args={worker_args})",
                f"  res = await BaseWorker._run(env=env, mode={agi_cls._mode}, workers={agi_cls._workers}, args={agi_cls._args})",
                "  print(res)",
                "if __name__ == '__main__':",
                "  asyncio.run(main())",
            ]
        )
        cmd = (
            f"{_remote_words(uv_worker)} run --preview-features python-upgrade --no-sync "
            f"--project {_remote_path(env.wenv_abs)}"
            f"{python_selector} python -c {shlex.quote(worker_script)}"
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

    # Establish task ownership before any scheduler/worker process is spawned
    # so partial startup can always cancel and await every launch operation.
    agi_cls._scheduler_launch_tasks = set()
    agi_cls._scheduler_launch_errors = []
    agi_cls._worker_launch_tasks = set()
    agi_cls._worker_launch_errors = []

    acquire_remote_lease = getattr(agi_cls, "_acquire_remote_target_lease", None)
    if callable(acquire_remote_lease) and getattr(
        agi_cls, "_lifecycle_call_token", None
    ):
        target_ips = set(agi_cls._workers)
        target_ips.add(agi_cls._get_scheduler(scheduler)[0])
        for ip in sorted(target_ips):
            if not env.is_local(ip):
                await acquire_remote_lease(ip)

    if not await agi_cls._start_scheduler(scheduler):
        return False

    scheduler_errors = getattr(agi_cls, "_scheduler_launch_errors", None) or []
    if scheduler_errors:
        raise scheduler_errors[0]

    await ensure_remote_cluster_shares(agi_cls)

    # Keep strong references to the remote-launch tasks (asyncio only holds
    # weak ones) and record their failures so sync() can fail fast with the
    # real SSH root cause instead of a generic attach timeout.
    launch_tasks: set[Any] = set()
    launch_errors: list[BaseException] = []
    agi_cls._worker_launch_tasks = launch_tasks
    agi_cls._worker_launch_errors = launch_errors

    def _on_worker_launch_done(task: Any) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            launch_errors.append(exc)
            log.error(f"Remote worker launch failed: {exc}")

    worker_port = _worker_port_range(env)

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
                    local_cmd = _local_dask_worker_command(
                        str(env.uv),
                        wenv_abs,
                        agi_cls._scheduler,
                        pid_file,
                        worker_port=worker_port,
                    )
                    process_env = background_jobs_support.background_env_from_prefixes(cmd_prefix, dask_env)
                    agi_cls._exec_bg(local_cmd, str(wenv_abs), env=process_env)
                else:
                    wenv_rel = env.wenv_rel
                    remote_cmd = _remote_dask_worker_command(
                        cmd_prefix=cmd_prefix,
                        dask_env=dask_env,
                        uv_cmd=str(env.uv),
                        wenv_rel=wenv_rel,
                        scheduler=agi_cls._scheduler,
                        pid_file=pid_file,
                        worker_port=worker_port,
                    )
                    launch_task = create_task_fn(agi_cls.exec_ssh_async(ip, remote_cmd))
                    if hasattr(launch_task, "add_done_callback"):
                        launch_tasks.add(launch_task)
                        launch_task.add_done_callback(_on_worker_launch_done)
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
    poll_attempt = 0

    while True:
        launch_errors = getattr(agi_cls, "_worker_launch_errors", None)
        if launch_errors:
            # A background remote worker launch already failed; surface its
            # root cause instead of waiting for the generic attach timeout.
            raise launch_errors[0]
        try:
            info = await _scheduler_info_payload(agi_cls._dask_client)
            workers_info = info.get("workers")
            if workers_info is None:
                log.info("Scheduler info 'workers' not ready yet.")
                await sleep_fn(_sync_poll_delay(poll_attempt))
                poll_attempt += 1
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
                log.error("Timeout waiting for all workers. %s workers missing.", remaining)
                raise TimeoutError("Timed out waiting for all workers to attach")
            await sleep_fn(_sync_poll_delay(poll_attempt))
            poll_attempt += 1

        except _SYNC_RETRY_EXCEPTIONS as exc:
            log.info(f"Exception in _sync: {exc}")
            await sleep_fn(_sync_poll_delay(poll_attempt))
            poll_attempt += 1
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
    # Per-host preparation is independent (2 SSH round-trips each); run the
    # hosts concurrently like deploy_application does instead of serially.
    mounted = [
        ip
        for ip in sorted(getattr(agi_cls, "_workers", {}) or {})
        if not env.is_local(ip)
    ]
    if mounted:
        await asyncio.gather(
            *(
                prepare_remote_cluster_share_fn(
                    agi_cls,
                    ip,
                    env,
                    remote_share,
                    log=log,
                )
                for ip in mounted
            )
        )
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

    scheduler_info = await _call_client_blocking(agi_cls._dask_client.scheduler_info)
    agi_cls._dask_workers = [
        worker.split("/")[-1]
        for worker in list(scheduler_info["workers"].keys())
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

    await _call_client_blocking(
        agi_cls._dask_client.gather,
        [
            client.submit(
                base_worker_cls._new,
                env=0 if env.debug else None,
                app=_manager_app_name(env),
                mode=agi_cls._mode,
                verbose=agi_cls.verbose,
                worker_id=worker_id,
                worker=worker,
                args=_worker_startup_args(agi_cls),
                workers=[worker],
            )
            for worker_id, worker in enumerate(dask_workers)
        ],
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

    gathered_logs = (
        await _call_client_blocking(client.gather, list(futures.values()))
        if futures
        else []
    )
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
    agi_cls._phase_timings = []

    if (agi_cls._mode & agi_cls._DEPLOYEMENT_MASK) == agi_cls._SIMULATE_MODE:
        res = await agi_cls._run()
    elif agi_cls._mode >= agi_cls._INSTALL_MODE:
        started_at = time_fn()
        agi_cls._clean_dirs_local()
        await _run_timed_phase(
            agi_cls,
            "prepare-local-env",
            lambda: agi_cls._prepare_local_env(),
            time_fn=time_fn,
        )
        if agi_cls._mode & agi_cls.DASK_MODE:
            await _run_timed_phase(
                agi_cls,
                "prepare-cluster-env",
                lambda: agi_cls._prepare_cluster_env(scheduler),
                time_fn=time_fn,
            )
        await _run_timed_phase(
            agi_cls,
            "deploy-application",
            lambda: agi_cls._deploy_application(scheduler),
            time_fn=time_fn,
        )
        res = time_fn() - started_at
    elif agi_cls._mode & agi_cls.DASK_MODE:
        agi_cls._startup_in_progress = True
        try:
            started = await _run_timed_phase(
                agi_cls,
                "start-dask",
                lambda: agi_cls._start(scheduler),
                time_fn=time_fn,
            )
            if started is False:
                raise RuntimeError("Dask startup did not complete")
            agi_cls._startup_in_progress = False
            res = await _run_timed_phase(
                agi_cls,
                "distribute",
                lambda: agi_cls._distribute(),
                time_fn=time_fn,
            )
            agi_cls._update_capacity()
        finally:
            # Always tear the cluster down (dask client shutdown, worker
            # retirement, SSH/connection cleanup) even when _distribute or
            # _update_capacity raise; otherwise scheduler/workers/ports and
            # SSH connections leak. _stop() still honors the _mode_auto
            # benchmark skip internally.
            try:
                await _run_timed_phase(
                    agi_cls,
                    "stop-dask",
                    lambda: agi_cls._stop(),
                    time_fn=time_fn,
                )
            finally:
                agi_cls._startup_in_progress = False
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
    cleanup_timeout: float = RUNTIME_CLEANUP_TIMEOUT_SECONDS,
) -> None:
    """Stop owned runtime resources without letting caller cancellation strand them.

    Dask shutdown contains several cancellation points.  Run that cleanup in a
    separately owned task and keep draining it when the caller is cancelled
    again, but only for a finite interval.  A timed-out task remains attached to
    ``agi_cls`` so an explicit lifecycle stop can finish that exact cleanup
    before any lease or runtime ownership is released.
    """

    try:
        timeout = float(cleanup_timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("runtime cleanup timeout must be a positive number") from exc
    if timeout <= 0:
        raise ValueError("runtime cleanup timeout must be a positive number")

    agi_cls._service_cleanup_unproven = True
    cleanup_task = _reusable_runtime_cleanup_task(agi_cls, log=log)
    if cleanup_task is None:
        cleanup_task = asyncio.create_task(
            _stop_runtime_resources(
                agi_cls,
                sleep_fn=sleep_fn,
                log=log,
            ),
            name="agilab-stop-owned-runtime",
        )
        agi_cls._runtime_cleanup_task = cleanup_task

    try:
        await _drain_owned_cleanup_task(cleanup_task, timeout=timeout)
    except TimeoutError as exc:
        phase = str(getattr(agi_cls, "_runtime_cleanup_phase", None) or "unknown")
        raise RuntimeCleanupRequiredError(
            f"AGI runtime cleanup remains unproven after {timeout:.1f}s "
            f"(phase={phase}). The owned cleanup task and lifecycle lease were "
            "retained. Call AGI.serve(..., action='stop') to retry cleanup before "
            "starting another runtime operation."
        ) from exc
    finally:
        cleanup_proven = (
            cleanup_task.done()
            and not cleanup_task.cancelled()
            and cleanup_task.exception() is None
        )
        agi_cls._service_cleanup_unproven = not cleanup_proven
        if cleanup_task.done() and getattr(agi_cls, "_runtime_cleanup_task", None) is cleanup_task:
            # A completed failure is retryable by a fresh explicit stop.  Only a
            # still-running task must remain attached so cleanup cannot overlap.
            agi_cls._runtime_cleanup_task = None
        if cleanup_proven:
            agi_cls._runtime_cleanup_phase = None


def _reusable_runtime_cleanup_task(
    agi_cls: Any,
    *,
    log: Any,
) -> asyncio.Task[Any] | None:
    """Return an in-flight cleanup task, or consume a prior terminal result."""

    cleanup_task = getattr(agi_cls, "_runtime_cleanup_task", None)
    if not isinstance(cleanup_task, asyncio.Task):
        return None
    if cleanup_task.done():
        if not cleanup_task.cancelled() and cleanup_task.exception() is None:
            agi_cls._service_cleanup_unproven = False
            agi_cls._runtime_cleanup_phase = None
            agi_cls._runtime_cleanup_task = None
            return cleanup_task
        if cleanup_task.cancelled():
            log.warning("Prior owned AGI runtime cleanup task was cancelled; retrying cleanup")
        else:
            log.warning(
                "Prior owned AGI runtime cleanup failed; retrying cleanup: %s",
                cleanup_task.exception(),
            )
        agi_cls._runtime_cleanup_task = None
        return None

    current_loop = asyncio.get_running_loop()
    task_loop = cleanup_task.get_loop()
    if task_loop is not current_loop:
        raise RuntimeCleanupRequiredError(
            "AGI runtime cleanup remains active in another event loop. The owned "
            "cleanup task and lifecycle lease were retained; finish the original "
            "session or restart the AGILAB process before retrying."
        )
    return cleanup_task


async def _drain_owned_cleanup_task(
    cleanup_task: asyncio.Task[Any],
    *,
    timeout: float,
) -> Any:
    """Drain ``cleanup_task`` through repeated caller cancellation, with a bound."""

    cancellation: asyncio.CancelledError | None = None
    completion_waiter = asyncio.create_task(
        asyncio.wait({cleanup_task}, timeout=timeout),
        name="agilab-stop-cleanup-deadline",
    )
    while not completion_waiter.done():
        try:
            await asyncio.shield(completion_waiter)
        except asyncio.CancelledError as exc:
            if completion_waiter.cancelled():
                raise
            cancellation = cancellation or exc

    completed, _pending = completion_waiter.result()
    if cleanup_task not in completed:
        raise TimeoutError("owned AGI runtime cleanup exceeded its deadline")

    result = cleanup_task.result()
    if cancellation is not None:
        raise cancellation
    return result


def _record_runtime_cleanup_failure(
    failures: list[tuple[str, BaseException]],
    phase: str,
    exc: BaseException,
    *,
    log: Any,
) -> None:
    failures.append((phase, exc))
    log.warning("AGI runtime cleanup could not prove %s: %s", phase, exc)


def _raise_runtime_cleanup_failures(
    failures: list[tuple[str, BaseException]],
) -> None:
    if not failures:
        return
    details = "; ".join(f"{phase}: {exc}" for phase, exc in failures)
    error = RuntimeCleanupRequiredError(
        "AGI runtime cleanup remains unproven ("
        f"{details}). The lifecycle lease must remain retained; call "
        "AGI.serve(..., action='stop') to retry cleanup before another operation."
    )
    for phase, exc in failures[1:]:
        error.add_note(f"Additional cleanup failure in {phase}: {exc}")
    raise error from failures[0][1]


async def _stop_runtime_resources(
    agi_cls: Any,
    *,
    sleep_fn: Callable[[float], Any],
    log: Any,
) -> None:
    log.info("stop Agi core")

    failures: list[tuple[str, BaseException]] = []
    fatal_error: BaseException | None = None
    client = getattr(agi_cls, "_dask_client", None)
    shutdown_owned_runtime = not bool(getattr(agi_cls, "_mode_auto", False)) or bool(
        getattr(agi_cls, "_startup_in_progress", False)
    )
    proven_shutdown_client = getattr(agi_cls, "_runtime_shutdown_client", None)
    if proven_shutdown_client is not None and proven_shutdown_client is not client:
        agi_cls._runtime_shutdown_client = None
        proven_shutdown_client = None
    client_shutdown_proven = client is None or proven_shutdown_client is client
    if client is not None and not client_shutdown_proven:
        retire_attempts = 0
        try:
            retire_limit = max(int(getattr(agi_cls, "_TIMEOUT", 0)), 0)
        except (TypeError, ValueError):
            retire_limit = 0
        while fatal_error is None:
            agi_cls._runtime_cleanup_phase = "scheduler-inspection"
            try:
                scheduler_info = await _scheduler_info_payload(client)
            except _STOP_RETRY_EXCEPTIONS as exc:
                _record_runtime_cleanup_failure(
                    failures,
                    "scheduler inspection",
                    exc,
                    log=log,
                )
                break
            except BaseException as exc:
                fatal_error = exc
                break

            workers = scheduler_info.get("workers") or {}
            if not workers:
                break
            if retire_attempts >= retire_limit:
                _record_runtime_cleanup_failure(
                    failures,
                    "worker retirement",
                    RuntimeError(
                        f"{len(workers)} scheduler worker(s) remained after "
                        f"{retire_attempts} retirement attempt(s)"
                    ),
                    log=log,
                )
                break

            agi_cls._runtime_cleanup_phase = "worker-retirement"
            try:
                await _maybe_await(
                    client.retire_workers(
                        workers=list(workers.keys()),
                        close_workers=True,
                        remove=True,
                    )
                )
                retire_attempts += 1
                await sleep_fn(1)
            except _STOP_RETRY_EXCEPTIONS as exc:
                _record_runtime_cleanup_failure(
                    failures,
                    "worker retirement",
                    exc,
                    log=log,
                )
                break
            except BaseException as exc:
                fatal_error = exc
                break

        # A partial startup owns whatever scheduler it managed to create, even
        # during benchmark mode, and must tear it down.
        if shutdown_owned_runtime:
            agi_cls._runtime_cleanup_phase = "client-shutdown"
            try:
                await _maybe_await(client.shutdown())
                agi_cls._runtime_shutdown_client = client
                client_shutdown_proven = True
            except _STOP_RETRY_EXCEPTIONS as exc:
                _record_runtime_cleanup_failure(
                    failures,
                    "Dask client shutdown",
                    exc,
                    log=log,
                )
            except BaseException as exc:
                fatal_error = fatal_error or exc

    agi_cls._runtime_cleanup_phase = "launch-tasks"
    try:
        launch_tasks: list[Any] = []
        for field in ("_worker_launch_tasks", "_scheduler_launch_tasks"):
            tasks = getattr(agi_cls, field, None)
            if tasks:
                launch_tasks.extend(list(tasks))
        for task in launch_tasks:
            if hasattr(task, "done") and task.done():
                continue
            if hasattr(task, "cancel"):
                task.cancel()
        awaitables = [task for task in launch_tasks if inspect.isawaitable(task)]
        if awaitables:
            await asyncio.gather(*awaitables, return_exceptions=True)
        for field in ("_worker_launch_tasks", "_scheduler_launch_tasks"):
            tasks = getattr(agi_cls, field, None)
            if hasattr(tasks, "clear"):
                tasks.clear()
    except BaseException as exc:
        fatal_error = fatal_error or exc

    background_cleanup_proven = not shutdown_owned_runtime
    if shutdown_owned_runtime:
        agi_cls._runtime_cleanup_phase = "background-processes"
        try:
            await _terminate_owned_background_jobs(agi_cls, log=log)
            background_cleanup_proven = True
        except RuntimeCleanupRequiredError as exc:
            _record_runtime_cleanup_failure(
                failures,
                "owned background processes",
                exc,
                log=log,
            )
        except BaseException as exc:
            fatal_error = fatal_error or exc

    if shutdown_owned_runtime and client_shutdown_proven and background_cleanup_proven:
        # Do not retain a successfully closed client across a lifecycle retry.
        # A service-state unlink may fail after runtime cleanup and keep the
        # ownership lease; the next stop must not query the already-closed
        # client before retrying the remaining lifecycle work.
        if getattr(agi_cls, "_dask_client", None) is client:
            agi_cls._dask_client = None
        if getattr(agi_cls, "_runtime_shutdown_client", None) is client:
            agi_cls._runtime_shutdown_client = None

    agi_cls._runtime_cleanup_phase = "connections"
    try:
        await agi_cls._close_all_connections()
    except _STOP_RETRY_EXCEPTIONS as exc:
        _record_runtime_cleanup_failure(
            failures,
            "connection shutdown",
            exc,
            log=log,
        )
    except BaseException as exc:
        fatal_error = fatal_error or exc

    if fatal_error is not None:
        agi_cls._runtime_cleanup_phase = "recovery-required"
        for phase, exc in failures:
            fatal_error.add_note(f"Additional cleanup failure in {phase}: {exc}")
        raise fatal_error
    if failures:
        agi_cls._runtime_cleanup_phase = "recovery-required"
        _raise_runtime_cleanup_failures(failures)
    agi_cls._runtime_cleanup_phase = None


def _background_job_ownership_token(job: Any) -> str | None:
    token = getattr(job, "ownership_token", None)
    return token if isinstance(token, str) and token else None


def _owned_token_processes(job: Any) -> tuple[list[psutil.Process], list[int]]:
    """Return token matches and inaccessible plausible owned candidates."""

    token = _background_job_ownership_token(job)
    if token is None:
        return [], []
    matches: list[psutil.Process] = []
    uncertain_candidates: list[int] = []
    current_pid = os.getpid()
    started_at = getattr(job, "ownership_started_at", None)
    try:
        username = psutil.Process(current_pid).username()
    except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
        username = None
    for process in psutil.process_iter(attrs=["pid"]):
        if process.pid == current_pid:
            continue
        try:
            if isinstance(started_at, (int, float)) and (
                process.create_time() < float(started_at) - 1.0
            ):
                continue
            if username is not None and process.username() != username:
                continue
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess, OSError):
            # Identity-inaccessible protected processes cannot yet be narrowed
            # to this recent same-user launch and remain unrelated.
            continue
        try:
            if process.environ().get(background_jobs_support.BACKGROUND_JOB_TOKEN_ENV) == token:
                matches.append(process)
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except (psutil.AccessDenied, OSError):
            uncertain_candidates.append(process.pid)
    return matches, uncertain_candidates


def _known_process_tree(process: Any) -> list[psutil.Process]:
    """Return the still-addressable tree rooted at a known Popen handle."""

    try:
        if process.poll() is not None:
            return []
        pid = int(process.pid)
        root = psutil.Process(pid)
        return [*root.children(recursive=True), root]
    except (
        AttributeError,
        ProcessLookupError,
        TypeError,
        ValueError,
        psutil.AccessDenied,
        psutil.NoSuchProcess,
        psutil.ZombieProcess,
    ):
        return []


def _unique_processes(processes: list[psutil.Process]) -> list[psutil.Process]:
    unique: list[psutil.Process] = []
    seen: set[int] = set()
    for process in processes:
        if process.pid in seen:
            continue
        seen.add(process.pid)
        unique.append(process)
    return unique


def _terminate_token_process_tree(job: Any, *, timeout: float) -> None:
    """Terminate token-owned descendants, including a reparented Windows child."""

    token = _background_job_ownership_token(job)
    if token is None:
        raise RuntimeError("owned background job has no ownership token")
    process = getattr(job, "process", None)
    token_processes, _token_uncertainties = _owned_token_processes(job)
    processes = _unique_processes(
        [*token_processes, *_known_process_tree(process)]
    )

    signal_failures: list[str] = []
    terminated: list[psutil.Process] = []
    for owned_process in processes:
        try:
            owned_process.terminate()
            terminated.append(owned_process)
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except (psutil.AccessDenied, OSError) as exc:
            signal_failures.append(f"pid {owned_process.pid}: {exc}")

    _gone, alive = psutil.wait_procs(terminated, timeout=timeout)
    killed: list[psutil.Process] = []
    for owned_process in alive:
        try:
            owned_process.kill()
            killed.append(owned_process)
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except (psutil.AccessDenied, OSError) as exc:
            signal_failures.append(f"pid {owned_process.pid}: {exc}")
    _gone, alive = psutil.wait_procs(killed, timeout=timeout)

    remaining_token_processes, token_uncertainties = _owned_token_processes(job)
    remaining = _unique_processes([*alive, *remaining_token_processes])
    if signal_failures or remaining or token_uncertainties:
        details = "; ".join(signal_failures)
        if remaining:
            live_pids = ", ".join(str(process.pid) for process in remaining)
            details = f"{details}; " if details else ""
            details += f"owned pid(s) still alive: {live_pids}"
        if token_uncertainties:
            details = f"{details}; " if details else ""
            details += (
                "ownership token unavailable for recent same-user candidate pid(s): "
                + ", ".join(str(pid) for pid in token_uncertainties)
            )
        raise RuntimeError(f"owned process-tree termination remains unproven ({details})")


def _posix_process_group_has_live_member(process_group_id: int) -> bool:
    getpgid = getattr(os, "getpgid", None)
    if not callable(getpgid):
        return True
    for process in psutil.process_iter(attrs=["pid", "status"]):
        try:
            if getpgid(process.pid) != process_group_id:
                continue
            if process.info.get("status") != psutil.STATUS_ZOMBIE:
                return True
        except (ProcessLookupError, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except (PermissionError, OSError, psutil.AccessDenied):
            return True
    return False


def _posix_process_group_exists(process_group_id: int) -> bool:
    killpg = getattr(os, "killpg", None)
    if not callable(killpg):
        raise RuntimeError("POSIX process-group signaling is unavailable")
    try:
        killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError as exc:
        # macOS may report EPERM while a terminated orphan remains briefly as
        # a zombie. A zombie is already dead and cannot keep runtime work alive.
        if not _posix_process_group_has_live_member(process_group_id):
            return False
        raise RuntimeError(
            f"cannot inspect owned process group {process_group_id}: {exc}"
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            f"cannot inspect owned process group {process_group_id}: {exc}"
        ) from exc
    return True


def _posix_leader_owns_group(process: Any, process_group_id: int) -> bool:
    getpgid = getattr(os, "getpgid", None)
    if not callable(getpgid):
        return False
    try:
        if process.poll() is not None:
            return False
        return getpgid(int(process.pid)) == process_group_id
    except (AttributeError, ProcessLookupError, TypeError, ValueError, OSError):
        return False


def _posix_group_has_ownership_token(process_group_id: int, token: str) -> bool:
    getpgid = getattr(os, "getpgid", None)
    if not callable(getpgid):
        return False
    inaccessible_members: list[int] = []
    for process in psutil.process_iter(attrs=["pid"]):
        try:
            if getpgid(process.pid) != process_group_id:
                continue
        except (ProcessLookupError, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except (PermissionError, OSError) as exc:
            raise RuntimeError(
                f"cannot inspect member {process.pid} of process group {process_group_id}: {exc}"
            ) from exc
        try:
            if process.environ().get(background_jobs_support.BACKGROUND_JOB_TOKEN_ENV) == token:
                return True
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except (psutil.AccessDenied, PermissionError, OSError):
            inaccessible_members.append(process.pid)
    if inaccessible_members:
        pids = ", ".join(str(pid) for pid in inaccessible_members)
        raise RuntimeError(
            f"cannot prove ownership of process group {process_group_id}; "
            f"member environment unavailable for pid(s) {pids}"
        )
    return False


def _prove_posix_process_group_ownership(job: Any, process_group_id: int) -> bool:
    """Prove a still-existing group is ours before sending a group signal."""

    if not _posix_process_group_exists(process_group_id):
        return False
    process = getattr(job, "process", None)
    if _posix_leader_owns_group(process, process_group_id):
        return True
    token = _background_job_ownership_token(job)
    if token is not None and _posix_group_has_ownership_token(process_group_id, token):
        return True
    if not _posix_process_group_exists(process_group_id):
        return False
    raise RuntimeError(
        f"cannot prove ownership of live process group {process_group_id}; refusing to signal it"
    )


def _signal_posix_process_group(job: Any, process_group_id: int, sig: int) -> bool:
    if not _prove_posix_process_group_ownership(job, process_group_id):
        return False
    killpg = getattr(os, "killpg", None)
    if not callable(killpg):
        raise RuntimeError("POSIX process-group signaling is unavailable")
    try:
        killpg(process_group_id, sig)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError) as exc:
        raise RuntimeError(
            f"cannot signal owned process group {process_group_id}: {exc}"
        ) from exc
    return True


def _wait_for_posix_process_group(
    process: Any,
    process_group_id: int,
    *,
    timeout: float,
) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            process.poll()
        except (AttributeError, ProcessLookupError, OSError):
            pass
        if not _posix_process_group_exists(process_group_id):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.05, remaining))


def _terminate_posix_owned_process_tree(job: Any, *, timeout: float) -> None:
    process_group_id = getattr(job, "process_group_id", None)
    if not isinstance(process_group_id, int) or process_group_id <= 0:
        _terminate_token_process_tree(job, timeout=timeout)
        return
    getpgrp = getattr(os, "getpgrp", None)
    if callable(getpgrp) and getpgrp() == process_group_id:
        raise RuntimeError("refusing to signal the AGILAB process group")

    process = getattr(job, "process", None)
    if _signal_posix_process_group(job, process_group_id, signal.SIGTERM):
        if not _wait_for_posix_process_group(
            process,
            process_group_id,
            timeout=timeout,
        ):
            _signal_posix_process_group(job, process_group_id, signal.SIGKILL)
            if not _wait_for_posix_process_group(
                process,
                process_group_id,
                timeout=timeout,
            ):
                raise subprocess.TimeoutExpired(
                    f"owned process group {process_group_id}",
                    timeout,
                )

    # The random token also finds descendants that escaped the original group,
    # and is the safe Windows ownership boundary when killpg is unavailable.
    _terminate_token_process_tree(job, timeout=timeout)


async def _terminate_legacy_background_process(
    process: Any,
    *,
    timeout: float,
) -> tuple[str, BaseException] | None:
    process_label = str(getattr(process, "pid", "unknown"))
    try:
        if process.poll() is not None:
            return None
        process.terminate()
    except ProcessLookupError:
        return None
    except (AttributeError, OSError) as exc:
        return f"background process {process_label} termination", exc
    try:
        await asyncio.to_thread(process.wait, timeout=timeout)
        return None
    except subprocess.TimeoutExpired:
        pass
    except ProcessLookupError:
        return None
    except (AttributeError, OSError) as exc:
        return f"background process {process_label} wait", exc
    try:
        process.kill()
        await asyncio.to_thread(process.wait, timeout=timeout)
        return None
    except ProcessLookupError:
        return None
    except (AttributeError, OSError, subprocess.TimeoutExpired) as exc:
        return f"background process {process_label} kill/wait", exc


def _forget_owned_background_job(manager: Any, job: Any) -> None:
    for field in ("owned", "running", "completed", "dead"):
        jobs = getattr(manager, field, None)
        if not isinstance(jobs, list):
            continue
        while job in jobs:
            jobs.remove(job)
    job_num = getattr(job, "num", None)
    all_jobs = getattr(manager, "all", None)
    if isinstance(all_jobs, dict) and all_jobs.get(job_num) is job:
        all_jobs.pop(job_num, None)


async def _terminate_owned_background_jobs(
    agi_cls: Any,
    *,
    timeout: float = 3.0,
    log: Any = logger,
) -> None:
    """Terminate complete process groups/trees owned by this runtime operation."""

    manager = getattr(agi_cls, "_jobs", None)
    jobs: list[Any] = []
    seen_jobs: set[int] = set()
    for field in ("owned", "running"):
        for job in list(getattr(manager, field, None) or []):
            if id(job) in seen_jobs:
                continue
            seen_jobs.add(id(job))
            jobs.append(job)

    failures: list[tuple[str, BaseException]] = []
    seen_processes: set[int] = set()
    for index, job in enumerate(jobs):
        process = getattr(job, "process", None)
        if process is None:
            _record_runtime_cleanup_failure(
                failures,
                f"background job {index}",
                RuntimeError("owned job has no process handle"),
                log=log,
            )
            continue
        if id(process) in seen_processes:
            continue
        seen_processes.add(id(process))

        token = _background_job_ownership_token(job)
        if token is None:
            result = await _terminate_legacy_background_process(process, timeout=timeout)
            if result is not None:
                phase, exc = result
                _record_runtime_cleanup_failure(failures, phase, exc, log=log)
                continue
        else:
            process_label = str(getattr(process, "pid", index))
            try:
                if os.name == "posix":
                    await asyncio.to_thread(
                        _terminate_posix_owned_process_tree,
                        job,
                        timeout=timeout,
                    )
                else:
                    await asyncio.to_thread(
                        _terminate_token_process_tree,
                        job,
                        timeout=timeout,
                    )
            except _BACKGROUND_TREE_CLEANUP_EXCEPTIONS as exc:
                _record_runtime_cleanup_failure(
                    failures,
                    f"background process group/tree {process_label}",
                    exc,
                    log=log,
                )
                continue
        _forget_owned_background_job(manager, job)

    _raise_runtime_cleanup_failures(failures)


def exec_bg(agi_cls: Any, cmd: Any, cwd: str, *, env: Optional[Dict[str, str]] = None) -> None:
    if env is None:
        job = agi_cls._jobs.new(cmd, cwd=cwd)
    else:
        job = agi_cls._jobs.new(cmd, cwd=cwd, env=env)
    job_id = getattr(job, "num", 0)
    if not agi_cls._jobs.result(job_id):
        raise RuntimeError(f"running {cmd} at {cwd}")
