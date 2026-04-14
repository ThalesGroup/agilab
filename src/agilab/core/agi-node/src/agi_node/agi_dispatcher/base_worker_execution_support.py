from __future__ import annotations

import io
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Callable

BUILD_ARTIFACT_EXCEPTIONS = (
    FileNotFoundError,
    IsADirectoryError,
    NotADirectoryError,
    PermissionError,
    RuntimeError,
    TypeError,
    ValueError,
    OSError,
)


def add_cython_dist_paths(
    env: Any,
    *,
    sys_path: list[str],
    logger_obj: Any,
    path_cls: type[Path] = Path,
) -> None:
    wenv_abs = env.wenv_abs
    cython_libs = list((wenv_abs / "dist").glob("*cy*"))
    lib_path = str(path_cls(cython_libs[0].parent).resolve()) if cython_libs else None

    if lib_path:
        if lib_path not in sys_path:
            sys_path.insert(0, lib_path)
    else:
        logger_obj.info("warning: no cython library found at %s", lib_path)
        raise RuntimeError("Cython mode requested but no compiled library found")

    sibling_root = wenv_abs.parent
    if sibling_root.is_dir():
        for extra_dist in sibling_root.glob("*_worker/dist"):
            try:
                extra_path = str(extra_dist.resolve())
            except FileNotFoundError:
                continue
            if extra_path and extra_path not in sys_path:
                sys_path.append(extra_path)


async def run_worker(
    *,
    env: Any,
    workers: dict[str, Any],
    mode: int,
    args: Any,
    do_works_fn: Callable[[Any, Any], Any],
    dispatcher_loader: Callable[[], Any],
    sys_path: list[str],
    logger_obj: Any,
    traceback_module: Any,
    time_module: Any,
    humanize_module: Any,
    datetime_module: Any,
    path_cls: type[Path] = Path,
) -> Any:
    if mode & 2:
        add_cython_dist_paths(
            env,
            sys_path=sys_path,
            logger_obj=logger_obj,
            path_cls=path_cls,
        )

    try:
        dispatcher = dispatcher_loader()
        workers, workers_plan, workers_plan_metadata = await dispatcher._do_distrib(
            env,
            workers,
            args,
        )
    except Exception as err:
        # Distribution planning crosses dispatcher/app code and can fail arbitrarily.
        logger_obj.error(traceback_module.format_exc())
        if isinstance(err, RuntimeError):
            raise
        raise RuntimeError("Failed to build distribution plan") from err

    if mode == 48:
        return workers_plan

    started_at = time_module.time()
    do_works_fn(workers_plan, workers_plan_metadata)
    runtime = time_module.time() - started_at
    env._run_time = runtime

    return (
        f"{env.mode2str(mode)} "
        f"{humanize_module.precisedelta(datetime_module.timedelta(seconds=runtime))}"
    )


def initialize_worker(
    *,
    env: Any,
    app: str | None,
    mode: int,
    verbose: int,
    worker_id: int,
    worker: str,
    args: dict[str, Any] | None,
    base_worker_cls: Any,
    agi_env_factory: Callable[..., Any],
    ensure_managed_pc_share_dir_fn: Callable[[Any], None],
    load_worker_fn: Callable[[int], Any],
    start_fn: Callable[[Any], None],
    args_namespace_cls: type,
    logger_obj: Any,
    time_module: Any,
    traceback_module: Any,
    sys_module: Any,
    file_path: str,
    path_cls: type[Path] = Path,
) -> None:
    try:
        logger_obj.info("venv: %s", sys_module.prefix)
        logger_obj.info("worker #%s: %s from: %s", worker_id, worker, path_cls(file_path))

        if env:
            base_worker_cls.env = env
        else:
            base_worker_cls.env = agi_env_factory(app=app, verbose=verbose)
        ensure_managed_pc_share_dir_fn(base_worker_cls.env)

        worker_class = load_worker_fn(mode)
        worker_inst = worker_class()
        worker_inst._mode = mode
        worker_inst.worker_id = worker_id
        worker_inst._worker_id = worker_id
        worker_inst.args = args_namespace_cls(**(args or {}))
        worker_inst.verbose = verbose

        base_worker_cls.verbose = verbose
        base_worker_cls._insts[worker_id] = worker_inst
        base_worker_cls._built = False
        base_worker_cls._worker = path_cls(worker).name
        base_worker_cls._worker_id = worker_id
        base_worker_cls._t0 = time_module.time()
        logger_obj.info("worker #%s: %s starting...", worker_id, worker)
        start_fn(worker_inst)
    except Exception:
        # Worker loading/constructor/startup executes app code; keep one logging boundary here.
        logger_obj.error(traceback_module.format_exc())
        raise


def collect_worker_info(
    *,
    share_path: str | Path | None,
    worker: str,
    normalize_path_fn: Callable[[str | Path], str],
    logger_obj: Any,
    psutil_module: Any,
    tempfile_module: Any,
    os_module: Any,
    time_module: Any,
    open_fn: Callable[..., Any] = open,
) -> dict[str, list[float]]:
    ram = psutil_module.virtual_memory()
    ram_total = [ram.total / 10 ** 9]
    ram_available = [ram.available / 10 ** 9]
    cpu_count = [psutil_module.cpu_count()]
    cpu_frequency = [psutil_module.cpu_freq().current / 10 ** 3]

    if not share_path:
        path = tempfile_module.gettempdir()
    else:
        path = normalize_path_fn(share_path)
    if not os_module.path.exists(path):
        logger_obj.info("mkdir %s", path)
        os_module.makedirs(path, exist_ok=True)

    size = 10 * 1024 * 1024
    file_path = os_module.path.join(path, str(worker).replace(":", "_"))
    start = time_module.time()
    with open_fn(file_path, "w") as stream:
        stream.write("\x00" * size)

    elapsed = time_module.time() - start
    time_module.sleep(1)
    write_speed = [size / elapsed]
    os_module.remove(file_path)

    return {
        "ram_total": ram_total,
        "ram_available": ram_available,
        "cpu_count": cpu_count,
        "cpu_frequency": cpu_frequency,
        "network_speed": write_speed,
    }


def build_worker_artifacts(
    *,
    target_worker: str,
    dask_home: str,
    worker: str,
    mode: int,
    verbose: int,
    base_worker_cls: Any,
    logger_obj: Any,
    getuser_fn: Callable[[], str],
    file_path: str,
    sys_path: list[str],
    path_cls: type[Path] = Path,
    os_module: Any = os,
    shutil_module: Any = shutil,
) -> None:
    prefix = "~/MyApp/" if str(getuser_fn()).startswith("T0") else "~/"
    base_worker_cls._home_dir = path_cls(prefix).expanduser().absolute()
    base_worker_cls._logs = base_worker_cls._home_dir / f"{target_worker}_trace.txt"
    base_worker_cls._dask_home = dask_home
    base_worker_cls._worker = worker

    logger_obj.info(
        "worker #%s: %s from: %s",
        base_worker_cls._worker_id,
        worker,
        path_cls(file_path),
    )

    try:
        logger_obj.info("set verbose=3 to see something in this trace file ...")

        if verbose > 2:
            logger_obj.info("home_dir: %s", base_worker_cls._home_dir)
            logger_obj.info(
                "target_worker=%s, dask_home=%s, mode=%s, verbose=%s, worker=%s)",
                target_worker,
                dask_home,
                mode,
                verbose,
                worker,
            )
            for entry in path_cls(dask_home).glob("*"):
                logger_obj.info("%s", entry)

        egg_src = dask_home + "/some_egg_file"
        extract_path = base_worker_cls._home_dir / "wenv" / target_worker

        if not mode & 2:
            egg_dest = extract_path / (os_module.path.basename(egg_src) + ".egg")

            logger_obj.info("copy: %s to %s", egg_src, egg_dest)
            shutil_module.copyfile(egg_src, egg_dest)

            if str(egg_dest) in sys_path:
                sys_path.remove(str(egg_dest))
            sys_path.insert(0, str(egg_dest))

            logger_obj.info("sys.path:")
            for entry in sys_path:
                logger_obj.info("%s", entry)

            logger_obj.info("done!")
    except BUILD_ARTIFACT_EXCEPTIONS:
        logger_obj.error(
            "worker<%s> - fail to build %s from %s, see %s for details",
            worker,
            target_worker,
            dask_home,
            base_worker_cls._logs,
        )
        raise


def execute_worker_plan(
    *,
    workers_plan: Any,
    workers_plan_metadata: Any,
    worker_id: int | None,
    worker_name: str | None,
    insts: dict[int, Any],
    expand_chunk_fn: Callable[[Any, int | None], tuple[Any, Any, Any]],
    logger_obj: Any,
    traceback_module: Any,
    file_path: str,
    logging_module: Any = logging,
    io_module: Any = io,
    path_cls: type[Path] = Path,
    root_logger: logging.Logger | None = None,
) -> str:
    log_stream = io_module.StringIO()
    handler = logging_module.StreamHandler(log_stream)
    active_root_logger = root_logger or logging_module.getLogger()
    active_root_logger.addHandler(handler)

    try:
        if worker_id is not None:
            expanded_plan, plan_chunk_len, plan_total_workers = expand_chunk_fn(
                workers_plan,
                worker_id,
            )
            expanded_meta, meta_chunk_len, _ = expand_chunk_fn(
                workers_plan_metadata,
                worker_id,
            )

            if expanded_plan is None:
                expanded_plan = workers_plan
            if expanded_meta is None:
                expanded_meta = workers_plan_metadata

            plan_entry = (
                expanded_plan[worker_id]
                if isinstance(expanded_plan, list) and len(expanded_plan) > worker_id
                else []
            )
            metadata_entry = (
                expanded_meta[worker_id]
                if isinstance(expanded_meta, list) and len(expanded_meta) > worker_id
                else []
            )

            logger_obj.info(
                "worker #%s: %s from %s",
                worker_id,
                worker_name,
                path_cls(file_path),
            )
            logger_obj.info(
                "work #%s / %s - plan batches=%s metadata batches=%s",
                worker_id + 1,
                plan_total_workers
                if plan_total_workers is not None
                else (len(expanded_plan) if isinstance(expanded_plan, list) else "?"),
                plan_chunk_len if plan_chunk_len is not None else len(plan_entry),
                meta_chunk_len if meta_chunk_len is not None else len(metadata_entry),
            )

            insts[worker_id].works(expanded_plan, expanded_meta)

            logger_obj.info(
                "worker #%s completed %s plan batches",
                worker_id,
                plan_chunk_len if plan_chunk_len is not None else len(plan_entry),
            )
        else:
            logger_obj.error("this worker is not initialized")
            raise RuntimeError("failed to do_works")
    except Exception:
        # ``works(...)`` executes arbitrary worker code; keep the runtime logging boundary here.
        logger_obj.error(traceback_module.format_exc())
        raise
    finally:
        active_root_logger.removeHandler(handler)
        handler.close()

    return log_stream.getvalue()


__all__ = [
    "add_cython_dist_paths",
    "build_worker_artifacts",
    "collect_worker_info",
    "execute_worker_plan",
    "initialize_worker",
    "run_worker",
]
