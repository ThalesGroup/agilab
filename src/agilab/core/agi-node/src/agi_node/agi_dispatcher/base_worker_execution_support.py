from __future__ import annotations

import io
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Callable, cast

from . import worker_tracking_support

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
DISTRIBUTION_PLAN_WRAP_EXCEPTIONS = (
    ValueError,
    OSError,
    ImportError,
    ModuleNotFoundError,
)


def _resolve_primary_cython_dist_path(
    wenv_abs: Path,
    *,
    path_cls: type[Path] = Path,
) -> str | None:
    cython_libs = list((wenv_abs / "dist").glob("*cy*"))
    if not cython_libs:
        return None
    return str(path_cls(cython_libs[0].parent).resolve())


def _append_sibling_worker_dist_paths(
    sibling_root: Path,
    *,
    sys_path: list[str],
) -> None:
    if not sibling_root.is_dir():
        return
    for extra_dist in sibling_root.glob("*_worker/dist"):
        try:
            extra_path = str(extra_dist.resolve())
        except FileNotFoundError:
            continue
        if extra_path and extra_path not in sys_path:
            sys_path.append(extra_path)


def add_cython_dist_paths(
    env: Any,
    *,
    sys_path: list[str],
    logger_obj: Any,
    path_cls: type[Path] = Path,
) -> None:
    wenv_abs = env.wenv_abs
    lib_path = _resolve_primary_cython_dist_path(
        wenv_abs,
        path_cls=path_cls,
    )

    if lib_path:
        if lib_path not in sys_path:
            sys_path.insert(0, lib_path)
    else:
        logger_obj.info("warning: no cython library found at %s", lib_path)
        raise RuntimeError("Cython mode requested but no compiled library found")

    _append_sibling_worker_dist_paths(
        wenv_abs.parent,
        sys_path=sys_path,
    )


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

    workers, workers_plan, workers_plan_metadata = await _build_distribution_plan(
        env=env,
        workers=workers,
        args=args,
        dispatcher_loader=dispatcher_loader,
        logger_obj=logger_obj,
        traceback_module=traceback_module,
    )

    if mode == 48:
        return workers_plan

    worker_tracking_support.prepare_worker_tracking_environment(
        env,
        logger_obj=logger_obj,
        path_cls=path_cls,
    )

    started_at = time_module.time()
    do_works_fn(workers_plan, workers_plan_metadata)
    runtime = time_module.time() - started_at
    env._run_time = runtime

    return (
        f"{env.mode2str(mode)} "
        f"{humanize_module.precisedelta(datetime_module.timedelta(seconds=runtime))}"
    )


async def _build_distribution_plan(
    *,
    env: Any,
    workers: dict[str, Any],
    args: Any,
    dispatcher_loader: Callable[[], Any],
    logger_obj: Any,
    traceback_module: Any,
) -> tuple[Any, Any, Any]:
    dispatcher = dispatcher_loader()
    try:
        return cast(
            tuple[Any, Any, Any],
            await dispatcher._do_distrib(
                env,
                workers,
                args,
            ),
        )
    except DISTRIBUTION_PLAN_WRAP_EXCEPTIONS as err:
        logger_obj.error(traceback_module.format_exc())
        raise RuntimeError("Failed to build distribution plan") from err


def _log_worker_startup_context(
    *,
    worker_id: int,
    worker: str,
    file_path: str,
    logger_obj: Any,
    sys_module: Any,
    path_cls: type[Path] = Path,
) -> None:
    logger_obj.info("venv: %s", sys_module.prefix)
    logger_obj.info("worker #%s: %s from: %s", worker_id, worker, path_cls(file_path))


def _resolve_initialized_worker_env(
    *,
    env: Any,
    app: str | None,
    verbose: int,
    base_worker_cls: Any,
    agi_env_factory: Callable[..., Any],
    ensure_managed_pc_share_dir_fn: Callable[[Any], None],
) -> Any:
    resolved_env = env if env else agi_env_factory(app=app, verbose=verbose)
    base_worker_cls.env = resolved_env
    ensure_managed_pc_share_dir_fn(base_worker_cls.env)
    return resolved_env


def _start_initialized_worker(
    *,
    mode: int,
    worker_id: int,
    worker: str,
    args: dict[str, Any] | None,
    verbose: int,
    base_worker_cls: Any,
    load_worker_fn: Callable[[int], Any],
    start_fn: Callable[[Any], None],
    args_namespace_cls: type,
    logger_obj: Any,
    time_module: Any,
    path_cls: type[Path] = Path,
) -> Any:
    worker_inst = _configure_initialized_worker(
        mode=mode,
        worker_id=worker_id,
        args=args,
        verbose=verbose,
        load_worker_fn=load_worker_fn,
        args_namespace_cls=args_namespace_cls,
    )
    _register_initialized_worker(
        base_worker_cls=base_worker_cls,
        worker_id=worker_id,
        worker=worker,
        worker_inst=worker_inst,
        verbose=verbose,
        started_at=time_module.time(),
        path_cls=path_cls,
    )
    logger_obj.info("worker #%s: %s starting...", worker_id, worker)
    start_fn(worker_inst)
    return worker_inst


def _initialize_worker_runtime(
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
    sys_module: Any,
    file_path: str,
    path_cls: type[Path] = Path,
) -> Any:
    _log_worker_startup_context(
        worker_id=worker_id,
        worker=worker,
        file_path=file_path,
        logger_obj=logger_obj,
        sys_module=sys_module,
        path_cls=path_cls,
    )
    _resolve_initialized_worker_env(
        env=env,
        app=app,
        verbose=verbose,
        base_worker_cls=base_worker_cls,
        agi_env_factory=agi_env_factory,
        ensure_managed_pc_share_dir_fn=ensure_managed_pc_share_dir_fn,
    )
    return _start_initialized_worker(
        mode=mode,
        worker_id=worker_id,
        worker=worker,
        args=args,
        verbose=verbose,
        base_worker_cls=base_worker_cls,
        load_worker_fn=load_worker_fn,
        start_fn=start_fn,
        args_namespace_cls=args_namespace_cls,
        logger_obj=logger_obj,
        time_module=time_module,
        path_cls=path_cls,
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
        _initialize_worker_runtime(
            env=env,
            app=app,
            mode=mode,
            verbose=verbose,
            worker_id=worker_id,
            worker=worker,
            args=args,
            base_worker_cls=base_worker_cls,
            agi_env_factory=agi_env_factory,
            ensure_managed_pc_share_dir_fn=ensure_managed_pc_share_dir_fn,
            load_worker_fn=load_worker_fn,
            start_fn=start_fn,
            args_namespace_cls=args_namespace_cls,
            logger_obj=logger_obj,
            time_module=time_module,
            sys_module=sys_module,
            file_path=file_path,
            path_cls=path_cls,
        )
    except Exception:
        # Worker loading/constructor/startup executes app code; keep one logging boundary here.
        logger_obj.error(traceback_module.format_exc())
        raise


def _configure_initialized_worker(
    *,
    mode: int,
    worker_id: int,
    args: dict[str, Any] | None,
    verbose: int,
    load_worker_fn: Callable[[int], Any],
    args_namespace_cls: type,
) -> Any:
    worker_class = load_worker_fn(mode)
    worker_inst = worker_class()
    worker_inst._mode = mode
    worker_inst.worker_id = worker_id
    worker_inst._worker_id = worker_id
    worker_inst.args = args_namespace_cls(**(args or {}))
    worker_inst.verbose = verbose
    return worker_inst


def _register_initialized_worker(
    *,
    base_worker_cls: Any,
    worker_id: int,
    worker: str,
    worker_inst: Any,
    verbose: int,
    started_at: float,
    path_cls: type[Path] = Path,
) -> None:
    base_worker_cls.verbose = verbose
    base_worker_cls._insts[worker_id] = worker_inst
    base_worker_cls._built = False
    base_worker_cls._worker = path_cls(worker).name
    base_worker_cls._worker_id = worker_id
    base_worker_cls._t0 = started_at


def _resolve_worker_info_path(
    *,
    share_path: str | Path | None,
    normalize_path_fn: Callable[[str | Path], str],
    logger_obj: Any,
    tempfile_module: Any,
    os_module: Any,
) -> str:
    if not share_path:
        path = tempfile_module.gettempdir()
    else:
        path = normalize_path_fn(share_path)
    if not os_module.path.exists(path):
        logger_obj.info("mkdir %s", path)
        os_module.makedirs(path, exist_ok=True)
    return str(path)


def _measure_worker_write_speed(
    *,
    path: str,
    worker: str,
    time_module: Any,
    os_module: Any,
    open_fn: Callable[..., Any] = open,
    size: int = 10 * 1024 * 1024,
) -> list[float]:
    file_path = os_module.path.join(path, str(worker).replace(":", "_"))
    start = time_module.time()
    with open_fn(file_path, "w") as stream:
        stream.write("\x00" * size)

    elapsed = time_module.time() - start
    time_module.sleep(1)
    os_module.remove(file_path)
    return [size / elapsed]


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

    path = _resolve_worker_info_path(
        share_path=share_path,
        normalize_path_fn=normalize_path_fn,
        logger_obj=logger_obj,
        tempfile_module=tempfile_module,
        os_module=os_module,
    )
    write_speed = _measure_worker_write_speed(
        path=path,
        worker=worker,
        time_module=time_module,
        os_module=os_module,
        open_fn=open_fn,
    )

    return {
        "ram_total": ram_total,
        "ram_available": ram_available,
        "cpu_count": cpu_count,
        "cpu_frequency": cpu_frequency,
        "network_speed": write_speed,
    }


def _log_build_worker_context(
    *,
    home_dir: Path,
    target_worker: str,
    dask_home: str,
    mode: int,
    verbose: int,
    worker: str,
    logger_obj: Any,
    path_cls: type[Path] = Path,
) -> None:
    if verbose <= 2:
        return
    logger_obj.info("home_dir: %s", home_dir)
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


def _resolve_worker_home_dir(
    *,
    getuser_fn: Callable[[], str],
    path_cls: type[Path] = Path,
) -> Path:
    prefix = "~/MyApp/" if str(getuser_fn()).startswith("T0") else "~/"
    return path_cls(prefix).expanduser().absolute()


def _configure_build_worker_state(
    *,
    target_worker: str,
    dask_home: str,
    worker: str,
    base_worker_cls: Any,
    getuser_fn: Callable[[], str],
    path_cls: type[Path] = Path,
) -> Path:
    home_dir = _resolve_worker_home_dir(
        getuser_fn=getuser_fn,
        path_cls=path_cls,
    )
    base_worker_cls._home_dir = home_dir
    base_worker_cls._logs = home_dir / f"{target_worker}_trace.txt"
    base_worker_cls._dask_home = dask_home
    base_worker_cls._worker = worker
    return home_dir


def _resolve_worker_egg_install_paths(
    *,
    home_dir: Path,
    target_worker: str,
    dask_home: str,
    path_cls: type[Path] = Path,
) -> tuple[str, Path]:
    egg_src = dask_home + "/some_egg_file"
    extract_path = path_cls(home_dir) / "wenv" / target_worker
    return egg_src, extract_path


def _install_worker_egg(
    *,
    egg_src: str,
    extract_path: Path,
    sys_path: list[str],
    logger_obj: Any,
    os_module: Any = os,
    shutil_module: Any = shutil,
) -> Path:
    egg_name = f"{str(os_module.path.basename(egg_src))}.egg"
    egg_dest = extract_path / egg_name

    logger_obj.info("copy: %s to %s", egg_src, egg_dest)
    shutil_module.copyfile(egg_src, egg_dest)

    egg_dest_str = str(egg_dest)
    if egg_dest_str in sys_path:
        sys_path.remove(egg_dest_str)
    sys_path.insert(0, egg_dest_str)

    logger_obj.info("sys.path:")
    for entry in sys_path:
        logger_obj.info("%s", entry)

    logger_obj.info("done!")
    return egg_dest


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
    home_dir = _configure_build_worker_state(
        target_worker=target_worker,
        dask_home=dask_home,
        worker=worker,
        base_worker_cls=base_worker_cls,
        getuser_fn=getuser_fn,
        path_cls=path_cls,
    )

    logger_obj.info(
        "worker #%s: %s from: %s",
        base_worker_cls._worker_id,
        worker,
        path_cls(file_path),
    )

    try:
        logger_obj.info("set verbose=3 to see something in this trace file ...")
        _log_build_worker_context(
            home_dir=base_worker_cls._home_dir,
            target_worker=target_worker,
            dask_home=dask_home,
            mode=mode,
            verbose=verbose,
            worker=worker,
            logger_obj=logger_obj,
            path_cls=path_cls,
        )

        egg_src, extract_path = _resolve_worker_egg_install_paths(
            home_dir=home_dir,
            target_worker=target_worker,
            dask_home=dask_home,
            path_cls=path_cls,
        )

        if not mode & 2:
            _install_worker_egg(
                egg_src=egg_src,
                extract_path=extract_path,
                sys_path=sys_path,
                logger_obj=logger_obj,
                os_module=os_module,
                shutil_module=shutil_module,
            )
    except BUILD_ARTIFACT_EXCEPTIONS:
        logger_obj.error(
            "worker<%s> - fail to build %s from %s, see %s for details",
            worker,
            target_worker,
            dask_home,
            base_worker_cls._logs,
        )
        raise


def _expand_worker_payload(
    payload: Any,
    worker_id: int,
    *,
    expand_chunk_fn: Callable[[Any, int | None], tuple[Any, Any, Any]],
) -> tuple[Any, Any, Any]:
    expanded_payload, chunk_len, total_workers = expand_chunk_fn(
        payload,
        worker_id,
    )
    if expanded_payload is None:
        expanded_payload = payload
    return expanded_payload, chunk_len, total_workers


def _select_worker_batch_entry(
    expanded_payload: Any,
    worker_id: int,
) -> Any:
    if isinstance(expanded_payload, list) and len(expanded_payload) > worker_id:
        return expanded_payload[worker_id]
    return []


def _count_worker_batches(
    chunk_len: int | None,
    batch_entry: Any,
) -> int:
    return chunk_len if chunk_len is not None else len(batch_entry)


def _resolve_total_workers(
    total_workers: int | None,
    expanded_plan: Any,
) -> int | str:
    if total_workers is not None:
        return total_workers
    if isinstance(expanded_plan, list):
        return len(expanded_plan)
    return "?"


def _log_worker_plan_progress(
    *,
    worker_id: int,
    worker_name: str | None,
    file_path: str,
    expanded_plan: Any,
    plan_total_workers: int | None,
    plan_chunk_len: int | None,
    plan_entry: Any,
    meta_chunk_len: int | None,
    metadata_entry: Any,
    logger_obj: Any,
    path_cls: type[Path] = Path,
) -> int:
    plan_batch_count = _count_worker_batches(plan_chunk_len, plan_entry)
    metadata_batch_count = _count_worker_batches(meta_chunk_len, metadata_entry)
    logger_obj.info(
        "worker #%s: %s from %s",
        worker_id,
        worker_name,
        path_cls(file_path),
    )
    logger_obj.info(
        "work #%s / %s - plan batches=%s metadata batches=%s",
        worker_id + 1,
        _resolve_total_workers(plan_total_workers, expanded_plan),
        plan_batch_count,
        metadata_batch_count,
    )
    return plan_batch_count


def _attach_worker_log_capture(
    *,
    logging_module: Any = logging,
    io_module: Any = io,
    root_logger: logging.Logger | None = None,
) -> tuple[Any, Any, Any]:
    log_stream = cast(io.StringIO, io_module.StringIO())
    handler = cast(logging.Handler, logging_module.StreamHandler(log_stream))
    active_root_logger = cast(logging.Logger, root_logger or logging_module.getLogger())
    active_root_logger.addHandler(handler)
    return log_stream, handler, active_root_logger


def _detach_worker_log_capture(
    *,
    active_root_logger: Any,
    handler: Any,
) -> None:
    active_root_logger.removeHandler(handler)
    handler.close()


def _execute_initialized_worker_plan(
    *,
    workers_plan: Any,
    workers_plan_metadata: Any,
    worker_id: int,
    worker_name: str | None,
    insts: dict[int, Any],
    expand_chunk_fn: Callable[[Any, int | None], tuple[Any, Any, Any]],
    logger_obj: Any,
    file_path: str,
    path_cls: type[Path] = Path,
) -> int:
    expanded_plan, plan_chunk_len, plan_total_workers = _expand_worker_payload(
        workers_plan,
        worker_id,
        expand_chunk_fn=expand_chunk_fn,
    )
    expanded_meta, meta_chunk_len, _ = _expand_worker_payload(
        workers_plan_metadata,
        worker_id,
        expand_chunk_fn=expand_chunk_fn,
    )

    plan_entry = _select_worker_batch_entry(expanded_plan, worker_id)
    metadata_entry = _select_worker_batch_entry(expanded_meta, worker_id)
    plan_batch_count = _log_worker_plan_progress(
        worker_id=worker_id,
        worker_name=worker_name,
        file_path=file_path,
        expanded_plan=expanded_plan,
        plan_total_workers=plan_total_workers,
        plan_chunk_len=plan_chunk_len,
        plan_entry=plan_entry,
        meta_chunk_len=meta_chunk_len,
        metadata_entry=metadata_entry,
        logger_obj=logger_obj,
        path_cls=path_cls,
    )

    with worker_tracking_support.worker_tracking_run(
        worker_id=worker_id,
        worker_name=worker_name,
        plan_batch_count=plan_batch_count,
        plan_chunk_len=plan_chunk_len,
        metadata_chunk_len=meta_chunk_len,
        logger_obj=logger_obj,
    ):
        insts[worker_id].works(expanded_plan, expanded_meta)

    logger_obj.info(
        "worker #%s completed %s plan batches",
        worker_id,
        plan_batch_count,
    )
    return plan_batch_count


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
    log_stream, handler, active_root_logger = _attach_worker_log_capture(
        logging_module=logging_module,
        io_module=io_module,
        root_logger=root_logger,
    )

    try:
        if worker_id is not None:
            _execute_initialized_worker_plan(
                workers_plan=workers_plan,
                workers_plan_metadata=workers_plan_metadata,
                worker_id=worker_id,
                worker_name=worker_name,
                insts=insts,
                expand_chunk_fn=expand_chunk_fn,
                logger_obj=logger_obj,
                file_path=file_path,
                path_cls=path_cls,
            )
        else:
            logger_obj.error("this worker is not initialized")
            raise RuntimeError("failed to do_works")
    except Exception:
        # ``works(...)`` executes arbitrary worker code; keep the runtime logging boundary here.
        logger_obj.error(traceback_module.format_exc())
        raise
    finally:
        _detach_worker_log_capture(
            active_root_logger=active_root_logger,
            handler=handler,
        )

    return cast(str, log_stream.getvalue())


__all__ = [
    "add_cython_dist_paths",
    "build_worker_artifacts",
    "collect_worker_info",
    "execute_worker_plan",
    "initialize_worker",
    "run_worker",
]
