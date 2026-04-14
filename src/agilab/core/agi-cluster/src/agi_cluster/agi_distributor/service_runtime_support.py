from __future__ import annotations

import logging
import os
import pickle
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from dask.distributed import Client, wait

from agi_env import AgiEnv
from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher
from agi_cluster.agi_distributor.service_state_support import (
    init_service_queue,
    reset_service_queue_state,
    service_apply_queue_root,
    service_apply_runtime_config,
    service_cleanup_artifacts,
    service_clear_state,
    service_connected_workers,
    service_finalize_response,
    service_health_path,
    service_health_payload,
    service_heartbeat_timeout_value,
    service_public_args,
    service_queue_counts,
    service_queue_paths,
    service_read_heartbeat_payloads,
    service_read_heartbeats,
    service_read_state,
    service_safe_worker_name,
    service_state_path,
    service_state_payload,
    service_unhealthy_workers,
    service_worker_health,
    service_write_health_payload,
    service_write_state,
)

logger = logging.getLogger(__name__)


def wrap_worker_chunk(payload: Any, worker_index: int) -> Any:
    """Wrap one worker chunk so BaseWorker can reconstruct legacy payloads."""
    if not isinstance(payload, list):
        return payload
    chunk = payload[worker_index] if worker_index < len(payload) else []
    return {
        "__agi_worker_chunk__": True,
        "chunk": chunk,
        "total_workers": len(payload),
        "worker_idx": worker_index,
    }


async def service_recover(
    agi_cls: Any,
    env: AgiEnv,
    *,
    allow_stale_cleanup: bool = False,
    log: Any = logger,
) -> bool:
    state = agi_cls._service_read_state(env)
    if not state:
        return False

    try:
        agi_cls.env = env
        agi_cls.target_path = env.manager_path
        agi_cls._target = env.target
        agi_cls._mode = int(state.get("mode", agi_cls.DASK_MODE))
        agi_cls._mode_auto = False
        agi_cls._run_types = ["run --no-sync", "sync --dev", "sync --upgrade --dev", "simulate"]
        agi_cls._run_type = str(state.get("run_type", agi_cls._run_types[0]))

        workers_state = state.get("workers")
        agi_cls._workers = (
            workers_state
            if isinstance(workers_state, dict)
            else (agi_cls._workers or agi_cls._worker_default)
        )

        args_state = state.get("args")
        if isinstance(args_state, dict):
            agi_cls._args = agi_cls._service_public_args(args_state)

        agi_cls._scheduler = state.get("scheduler")
        agi_cls._scheduler_ip = state.get("scheduler_ip")
        agi_cls._scheduler_port = state.get("scheduler_port")
        agi_cls._service_poll_interval = state.get("poll_interval", agi_cls._service_poll_interval)
        agi_cls._service_stop_timeout = state.get("stop_timeout", agi_cls._service_stop_timeout)
        agi_cls._service_shutdown_on_stop = state.get(
            "shutdown_on_stop",
            agi_cls._service_shutdown_on_stop,
        )
        agi_cls._service_heartbeat_timeout = state.get(
            "heartbeat_timeout",
            agi_cls._service_heartbeat_timeout,
        )
        agi_cls._service_cleanup_done_ttl_sec = state.get(
            "cleanup_done_ttl_sec",
            agi_cls._service_cleanup_done_ttl_sec,
        )
        agi_cls._service_cleanup_failed_ttl_sec = state.get(
            "cleanup_failed_ttl_sec",
            agi_cls._service_cleanup_failed_ttl_sec,
        )
        agi_cls._service_cleanup_heartbeat_ttl_sec = state.get(
            "cleanup_heartbeat_ttl_sec",
            agi_cls._service_cleanup_heartbeat_ttl_sec,
        )
        agi_cls._service_cleanup_done_max_files = state.get(
            "cleanup_done_max_files",
            agi_cls._service_cleanup_done_max_files,
        )
        agi_cls._service_cleanup_failed_max_files = state.get(
            "cleanup_failed_max_files",
            agi_cls._service_cleanup_failed_max_files,
        )
        agi_cls._service_cleanup_heartbeat_max_files = state.get(
            "cleanup_heartbeat_max_files",
            agi_cls._service_cleanup_heartbeat_max_files,
        )
        started_at = state.get("started_at")
        agi_cls._service_started_at = (
            float(started_at)
            if started_at not in (None, "")
            else (agi_cls._service_started_at or time.time())
        )

        queue_dir = state.get("queue_dir")
        if queue_dir:
            agi_cls._service_apply_queue_root(Path(queue_dir), create=True)
        else:
            agi_cls._init_service_queue(env)
        agi_cls._service_worker_args = {
            **(agi_cls._args or {}),
            "_agi_service_mode": True,
            "_agi_service_queue_dir": str(agi_cls._service_queue_root),
        }

        scheduler_addr = state.get("scheduler") or agi_cls._scheduler
        if not scheduler_addr:
            raise RuntimeError("Missing scheduler address in persisted service state.")

        if agi_cls._dask_client is None or getattr(agi_cls._dask_client, "status", "") in {
            "closed",
            "closing",
        }:
            agi_cls._dask_client = await agi_cls._connect_scheduler_with_retry(
                scheduler_addr,
                timeout=max(agi_cls._TIMEOUT, 5),
                heartbeat_interval=5000,
            )

        agi_cls._scheduler = scheduler_addr
        agi_cls._dask_workers = await agi_cls._service_connected_workers(agi_cls._dask_client)
        agi_cls._service_workers = (
            agi_cls._dask_workers
            if agi_cls._dask_workers
            else [str(w) for w in state.get("service_workers", []) if w]
        )
        agi_cls._service_futures = {}

        if not agi_cls._service_workers:
            raise RuntimeError("Recovered service scheduler has no attached workers.")

        return True

    except Exception as exc:
        log.warning("Failed to recover persistent AGI service: %s", exc)
        if allow_stale_cleanup:
            agi_cls._service_clear_state(env)
            agi_cls._service_futures = {}
            agi_cls._service_workers = []
            agi_cls._reset_service_queue_state()
        return False


async def service_restart_workers(
    agi_cls: Any,
    env: AgiEnv,
    client: Client,
    workers_to_restart: List[str],
    *,
    log: Any = logger,
) -> List[str]:
    if not workers_to_restart:
        return []

    connected = await agi_cls._service_connected_workers(client)
    if connected:
        agi_cls._service_workers = list(connected)

    if agi_cls._service_queue_root is None:
        agi_cls._init_service_queue(env)

    agi_cls._service_worker_args = {
        **(agi_cls._args or {}),
        "_agi_service_mode": True,
        "_agi_service_queue_dir": str(agi_cls._service_queue_root),
    }

    break_tasks = [
        client.submit(
            BaseWorker.break_loop,
            workers=[worker],
            allow_other_workers=False,
            pure=False,
            key=f"agi-serve-restart-break-{env.target}-{agi_cls._service_safe_worker_name(worker)}",
        )
        for worker in workers_to_restart
    ]
    if break_tasks:
        try:
            client.gather(break_tasks)
        except Exception:
            log.debug("Ignoring break_loop error during service restart", exc_info=True)

    init_futures: List[Any] = []
    for worker in workers_to_restart:
        if worker not in agi_cls._service_workers:
            agi_cls._service_workers.append(worker)
        worker_id = agi_cls._service_workers.index(worker)
        init_futures.append(
            client.submit(
                BaseWorker._new,
                env=0 if getattr(env, "debug", False) else None,
                app=env.target_worker,
                mode=agi_cls._mode,
                verbose=agi_cls.verbose,
                worker_id=worker_id,
                worker=worker,
                args=agi_cls._service_worker_args,
                workers=[worker],
                allow_other_workers=False,
                pure=False,
                key=f"agi-serve-restart-init-{env.target}-{agi_cls._service_safe_worker_name(worker)}",
            )
        )
    if init_futures:
        client.gather(init_futures)

    restarted: List[str] = []
    for worker in workers_to_restart:
        future = client.submit(
            BaseWorker.loop,
            poll_interval=agi_cls._service_poll_interval,
            workers=[worker],
            allow_other_workers=False,
            pure=False,
            key=f"agi-serve-restart-loop-{env.target}-{agi_cls._service_safe_worker_name(worker)}",
        )
        agi_cls._service_futures[worker] = future
        restarted.append(worker)

    return restarted


async def service_auto_restart_unhealthy(
    agi_cls: Any,
    env: AgiEnv,
    client: Client,
) -> Dict[str, Any]:
    connected = await agi_cls._service_connected_workers(client)
    if connected:
        agi_cls._service_workers = list(connected)
    if not agi_cls._service_workers:
        return {"restarted": [], "reasons": {}}

    reasons = agi_cls._service_unhealthy_workers(agi_cls._service_workers)
    if not reasons:
        return {"restarted": [], "reasons": {}}

    workers_to_restart = list(reasons.keys())
    restarted = await agi_cls._service_restart_workers(env, client, workers_to_restart)
    if restarted:
        agi_cls._service_write_state(env, agi_cls._service_state_payload(env))
    return {"restarted": restarted, "reasons": reasons}


async def serve(
    agi_cls: Any,
    env: AgiEnv,
    *,
    scheduler: Optional[str] = None,
    workers: Optional[Dict[str, int]] = None,
    verbose: int = 0,
    mode: Optional[Union[int, str]] = None,
    rapids_enabled: bool = False,
    action: str = "start",
    poll_interval: Optional[float] = None,
    shutdown_on_stop: bool = True,
    stop_timeout: Optional[float] = 30.0,
    service_queue_dir: Optional[Union[str, Path]] = None,
    heartbeat_timeout: Optional[float] = None,
    cleanup_done_ttl_sec: Optional[float] = None,
    cleanup_failed_ttl_sec: Optional[float] = None,
    cleanup_heartbeat_ttl_sec: Optional[float] = None,
    cleanup_done_max_files: Optional[int] = None,
    cleanup_failed_max_files: Optional[int] = None,
    cleanup_heartbeat_max_files: Optional[int] = None,
    health_output_path: Optional[Union[str, Path]] = None,
    background_job_manager_factory: Any,
    wait_fn: Any = wait,
    log: Any = logger,
    **args: Any,
) -> Dict[str, Any]:
    command = (action or "start").lower()
    health_only = command == "health"
    if health_only:
        command = "status"
    if command not in {"start", "stop", "status"}:
        raise ValueError("action must be 'start', 'stop', 'status' or 'health'")

    agi_cls._service_shutdown_on_stop = shutdown_on_stop
    agi_cls._service_stop_timeout = stop_timeout
    agi_cls._service_poll_interval = poll_interval
    agi_cls._service_apply_runtime_config(
        heartbeat_timeout=heartbeat_timeout,
        cleanup_done_ttl_sec=cleanup_done_ttl_sec,
        cleanup_failed_ttl_sec=cleanup_failed_ttl_sec,
        cleanup_heartbeat_ttl_sec=cleanup_heartbeat_ttl_sec,
        cleanup_done_max_files=cleanup_done_max_files,
        cleanup_failed_max_files=cleanup_failed_max_files,
        cleanup_heartbeat_max_files=cleanup_heartbeat_max_files,
    )

    if command == "status":
        client = agi_cls._dask_client
        if not agi_cls._service_futures and not agi_cls._service_workers:
            recovered = await agi_cls._service_recover(env)
            if recovered:
                client = agi_cls._dask_client
        agi_cls._service_apply_runtime_config(
            heartbeat_timeout=heartbeat_timeout,
            cleanup_done_ttl_sec=cleanup_done_ttl_sec,
            cleanup_failed_ttl_sec=cleanup_failed_ttl_sec,
            cleanup_heartbeat_ttl_sec=cleanup_heartbeat_ttl_sec,
            cleanup_done_max_files=cleanup_done_max_files,
            cleanup_failed_max_files=cleanup_failed_max_files,
            cleanup_heartbeat_max_files=cleanup_heartbeat_max_files,
        )

        restart_info: Dict[str, Any] = {"restarted": [], "reasons": {}}
        if client is not None and agi_cls._service_workers:
            restart_info = await agi_cls._service_auto_restart_unhealthy(env, client)

        cleanup_info = agi_cls._service_cleanup_artifacts()
        queue_state = agi_cls._service_queue_counts()
        queue_dir = str(agi_cls._service_queue_root) if agi_cls._service_queue_root else None
        workers_snapshot = list(agi_cls._service_workers)
        worker_health = agi_cls._service_worker_health(workers_snapshot) if workers_snapshot else []

        if not agi_cls._service_futures and not workers_snapshot:
            client_status = getattr(client, "status", None) if client else None
            return agi_cls._service_finalize_response(
                env,
                {
                    "status": "idle",
                    "workers": [],
                    "pending": [],
                    "client_status": client_status,
                    "queue": queue_state,
                    "queue_dir": queue_dir,
                    "cleanup": cleanup_info,
                    "heartbeat_timeout_sec": agi_cls._service_heartbeat_timeout_value(),
                    "worker_health": worker_health,
                    "restarted_workers": restart_info["restarted"],
                    "restart_reasons": restart_info["reasons"],
                },
                health_output_path=health_output_path,
                health_only=health_only,
            )

        if client is None:
            pending = list(agi_cls._service_futures.keys())
            return agi_cls._service_finalize_response(
                env,
                {
                    "status": "error",
                    "workers": workers_snapshot,
                    "pending": pending,
                    "client_status": "missing",
                    "queue": queue_state,
                    "queue_dir": queue_dir,
                    "cleanup": cleanup_info,
                    "heartbeat_timeout_sec": agi_cls._service_heartbeat_timeout_value(),
                    "worker_health": worker_health,
                    "restarted_workers": restart_info["restarted"],
                    "restart_reasons": restart_info["reasons"],
                },
                health_output_path=health_output_path,
                health_only=health_only,
            )

        if agi_cls._service_futures:
            running_workers: List[str] = []
            pending_workers: List[str] = []
            for worker, future in agi_cls._service_futures.items():
                state = str(getattr(future, "status", "pending")).lower()
                if state in {"finished", "error", "cancelled"}:
                    pending_workers.append(worker)
                else:
                    running_workers.append(worker)

            if running_workers and not pending_workers:
                status = "running"
            elif running_workers:
                status = "degraded"
            else:
                status = "stopped"
        else:
            running_workers = workers_snapshot
            pending_workers = []
            status = "running" if running_workers else "stopped"

        return agi_cls._service_finalize_response(
            env,
            {
                "status": status,
                "workers": running_workers,
                "pending": pending_workers,
                "client_status": getattr(client, "status", None),
                "queue": queue_state,
                "queue_dir": queue_dir,
                "cleanup": cleanup_info,
                "heartbeat_timeout_sec": agi_cls._service_heartbeat_timeout_value(),
                "worker_health": worker_health,
                "restarted_workers": restart_info["restarted"],
                "restart_reasons": restart_info["reasons"],
            },
            health_output_path=health_output_path,
            health_only=health_only,
        )

    if command == "stop":
        client = agi_cls._dask_client

        if not agi_cls._service_futures and not agi_cls._service_workers:
            recovered = await agi_cls._service_recover(env, allow_stale_cleanup=True)
            client = agi_cls._dask_client
            agi_cls._service_apply_runtime_config(
                heartbeat_timeout=heartbeat_timeout,
                cleanup_done_ttl_sec=cleanup_done_ttl_sec,
                cleanup_failed_ttl_sec=cleanup_failed_ttl_sec,
                cleanup_heartbeat_ttl_sec=cleanup_heartbeat_ttl_sec,
                cleanup_done_max_files=cleanup_done_max_files,
                cleanup_failed_max_files=cleanup_failed_max_files,
                cleanup_heartbeat_max_files=cleanup_heartbeat_max_files,
            )
            if not recovered:
                log.info("AGI.serve(stop): no active service loops to stop.")
                if shutdown_on_stop and client:
                    await agi_cls._stop()
                if agi_cls._jobs:
                    agi_cls._clean_job(True)
                agi_cls._service_clear_state(env)
                agi_cls._reset_service_queue_state()
                return agi_cls._service_finalize_response(
                    env,
                    {"status": "idle", "workers": [], "pending": []},
                    health_output_path=health_output_path,
                )

        if client is None:
            log.error("AGI.serve(stop): service state exists but Dask client is unavailable")
            pending = list(agi_cls._service_futures.keys()) or list(agi_cls._service_workers)
            agi_cls._service_futures.clear()
            agi_cls._service_workers = []
            if agi_cls._jobs:
                agi_cls._clean_job(True)
            agi_cls._service_clear_state(env)
            agi_cls._reset_service_queue_state()
            return agi_cls._service_finalize_response(
                env,
                {"status": "error", "workers": [], "pending": pending},
                health_output_path=health_output_path,
            )

        future_map = {future: worker for worker, future in agi_cls._service_futures.items()}
        target_workers = list(agi_cls._service_futures.keys()) or list(agi_cls._service_workers)
        if not target_workers:
            target_workers = await agi_cls._service_connected_workers(client)
            agi_cls._service_workers = list(target_workers)

        if not target_workers:
            if shutdown_on_stop:
                await agi_cls._stop()
            agi_cls._service_futures.clear()
            agi_cls._service_workers = []
            agi_cls._service_clear_state(env)
            agi_cls._reset_service_queue_state()
            return agi_cls._service_finalize_response(
                env,
                {"status": "idle", "workers": [], "pending": []},
                health_output_path=health_output_path,
            )

        break_tasks = [
            client.submit(
                BaseWorker.break_loop,
                workers=[worker],
                allow_other_workers=False,
                pure=False,
                key=f"agi-serve-break-{env.target}-{worker.replace(':', '-')}",
            )
            for worker in target_workers
        ]
        client.gather(break_tasks)

        if future_map:
            wait_kwargs: Dict[str, Any] = {}
            if stop_timeout is not None:
                wait_kwargs["timeout"] = stop_timeout

            done, not_done = wait_fn(list(future_map.keys()), **wait_kwargs)

            stopped_workers = [future_map[f] for f in done]
            pending_workers = [future_map[f] for f in not_done]

            if done:
                client.gather(list(done), errors="raise")

            if pending_workers:
                log.warning("Service loop shutdown timed out on workers: %s", pending_workers)
        else:
            stopped_workers = list(target_workers)
            pending_workers = []

        agi_cls._service_futures.clear()
        agi_cls._service_workers = []
        agi_cls._service_clear_state(env)
        agi_cls._reset_service_queue_state()

        if shutdown_on_stop:
            await agi_cls._stop()

        if agi_cls._jobs:
            agi_cls._clean_job(True)

        status = "stopped" if not pending_workers else "partial"
        return agi_cls._service_finalize_response(
            env,
            {"status": status, "workers": stopped_workers, "pending": pending_workers},
            health_output_path=health_output_path,
        )

    if agi_cls._service_futures:
        raise RuntimeError(
            "Service loop already running. Please call AGI.serve(..., action='stop') first."
        )

    recovered = await agi_cls._service_recover(env, allow_stale_cleanup=True)
    agi_cls._service_apply_runtime_config(
        heartbeat_timeout=heartbeat_timeout,
        cleanup_done_ttl_sec=cleanup_done_ttl_sec,
        cleanup_failed_ttl_sec=cleanup_failed_ttl_sec,
        cleanup_heartbeat_ttl_sec=cleanup_heartbeat_ttl_sec,
        cleanup_done_max_files=cleanup_done_max_files,
        cleanup_failed_max_files=cleanup_failed_max_files,
        cleanup_heartbeat_max_files=cleanup_heartbeat_max_files,
    )
    if recovered:
        restart_info: Dict[str, Any] = {"restarted": [], "reasons": {}}
        if agi_cls._dask_client is not None:
            restart_info = await agi_cls._service_auto_restart_unhealthy(env, agi_cls._dask_client)
        cleanup_info = agi_cls._service_cleanup_artifacts()
        worker_health = agi_cls._service_worker_health(list(agi_cls._service_workers))
        return agi_cls._service_finalize_response(
            env,
            {
                "status": "running",
                "workers": list(agi_cls._service_workers),
                "pending": [],
                "queue": agi_cls._service_queue_counts(),
                "queue_dir": str(agi_cls._service_queue_root) if agi_cls._service_queue_root else None,
                "cleanup": cleanup_info,
                "heartbeat_timeout_sec": agi_cls._service_heartbeat_timeout_value(),
                "worker_health": worker_health,
                "restarted_workers": restart_info["restarted"],
                "restart_reasons": restart_info["reasons"],
                "recovered": True,
            },
            health_output_path=health_output_path,
            health_only=health_only,
        )

    if not workers:
        workers = agi_cls._worker_default
    elif not isinstance(workers, dict):
        raise ValueError("workers must be a dict. {'ip-address':nb-worker}")

    agi_cls._jobs = background_job_manager_factory()
    agi_cls.env = env
    agi_cls.target_path = env.manager_path
    agi_cls._target = env.target
    agi_cls._rapids_enabled = rapids_enabled

    if env.verbose > 0:
        log.info(
            "AGI service instance created for target %s with verbosity %s",
            env.target,
            env.verbose,
        )

    if mode is None:
        agi_cls._mode = agi_cls.DASK_MODE
    elif isinstance(mode, str):
        pattern = r"^[dcrp]+$"
        if not re.fullmatch(pattern, mode.lower()):
            raise ValueError("parameter <mode> must only contain the letters 'd', 'c', 'r', 'p'")
        agi_cls._mode = env.mode2int(mode)
    elif isinstance(mode, int):
        agi_cls._mode = int(mode)
    else:
        raise ValueError("parameter <mode> must be an int or a string")

    if not (agi_cls._mode & agi_cls.DASK_MODE):
        raise ValueError("AGI.serve requires Dask mode (include 'd' in mode)")

    if agi_cls._mode & agi_cls._RUN_MASK not in range(0, agi_cls.RAPIDS_MODE):
        raise ValueError(f"mode {agi_cls._mode} not implemented")

    agi_cls._mode_auto = False
    agi_cls._run_types = ["run --no-sync", "sync --dev", "sync --upgrade --dev", "simulate"]
    agi_cls._run_type = agi_cls._run_types[0]
    agi_cls._args = agi_cls._service_public_args(dict(args))
    agi_cls.verbose = verbose
    agi_cls._workers = workers
    agi_cls._run_time = {}

    agi_cls._capacity_data_file = env.resources_path / "balancer_df.csv"
    agi_cls._capacity_model_file = env.resources_path / "balancer_model.pkl"
    path = Path(agi_cls._capacity_model_file)

    if path.is_file():
        with open(path, "rb") as f:
            agi_cls._capacity_predictor = pickle.load(f)
    else:
        agi_cls._capacity_predictor = None
        log.info(
            "Capacity model not found at %s; skipping capacity bootstrap for service mode.",
            path,
        )

    agi_cls.agi_workers = {
        "AgiDataWorker": "pandas-worker",
        "PolarsWorker": "polars-worker",
        "PandasWorker": "pandas-worker",
        "FireducksWorker": "fireducks-worker",
        "DagWorker": "dag-worker",
    }
    base_worker_cls = getattr(env, "base_worker_cls", None)
    if not base_worker_cls:
        target_worker_class = getattr(env, "target_worker_class", None) or "<worker class>"
        worker_path = getattr(env, "worker_path", None) or "<worker path>"
        supported = ", ".join(sorted(agi_cls.agi_workers.keys()))
        raise ValueError(
            f"Missing {target_worker_class} definition; expected {worker_path}. "
            f"Ensure the app worker exists and inherits from a supported base worker ({supported})."
        )
    try:
        agi_cls.install_worker_group = [agi_cls.agi_workers[base_worker_cls]]
    except KeyError as exc:
        supported = ", ".join(sorted(agi_cls.agi_workers.keys()))
        raise ValueError(
            f"Unsupported base worker class '{base_worker_cls}'. Supported values: {supported}."
        ) from exc

    client = agi_cls._dask_client
    if client is None or getattr(client, "status", "") in {"closed", "closing"}:
        await agi_cls._start(scheduler)
        client = agi_cls._dask_client
    else:
        await agi_cls._sync()

    if client is None:
        raise RuntimeError("Failed to obtain Dask client for service start")

    agi_cls._dask_workers = [
        worker.split("/")[-1]
        for worker in list(client.scheduler_info()["workers"].keys())
    ]

    dask_workers = list(agi_cls._dask_workers)
    queue_paths = agi_cls._init_service_queue(env, service_queue_dir=service_queue_dir)
    cleanup_info = agi_cls._service_cleanup_artifacts()
    agi_cls._service_worker_args = {
        **(agi_cls._args or {}),
        "_agi_service_mode": True,
        "_agi_service_queue_dir": str(queue_paths["root"]),
    }

    init_futures = [
        client.submit(
            BaseWorker._new,
            env=0 if env.debug else None,
            app=env.target_worker,
            mode=agi_cls._mode,
            verbose=agi_cls.verbose,
            worker_id=index,
            worker=worker,
            args=agi_cls._service_worker_args,
            workers=[worker],
            allow_other_workers=False,
            pure=False,
            key=f"agi-worker-init-{env.target}-{worker.replace(':', '-')}",
        )
        for index, worker in enumerate(dask_workers)
    ]
    client.gather(init_futures)

    service_futures: Dict[str, Any] = {}
    for worker in dask_workers:
        future = client.submit(
            BaseWorker.loop,
            poll_interval=poll_interval,
            workers=[worker],
            allow_other_workers=False,
            pure=False,
            key=f"agi-serve-loop-{env.target}-{worker.replace(':', '-')}",
        )
        service_futures[worker] = future

    agi_cls._service_futures = service_futures
    agi_cls._service_workers = dask_workers
    agi_cls._service_started_at = time.time()
    agi_cls._service_heartbeat_timeout = agi_cls._service_heartbeat_timeout_value()
    agi_cls._service_write_state(env, agi_cls._service_state_payload(env))

    log.info("Service loops started for workers: %s", dask_workers)
    return agi_cls._service_finalize_response(
        env,
        {
            "status": "running",
            "workers": dask_workers,
            "pending": [],
            "queue_dir": str(queue_paths["root"]),
            "cleanup": cleanup_info,
            "heartbeat_timeout_sec": agi_cls._service_heartbeat_timeout_value(),
            "worker_health": agi_cls._service_worker_health(list(dask_workers)),
        },
        health_output_path=health_output_path,
        health_only=health_only,
    )


async def submit(
    agi_cls: Any,
    env: Optional[AgiEnv] = None,
    *,
    workers: Optional[Dict[str, int]] = None,
    work_plan: Optional[Any] = None,
    work_plan_metadata: Optional[Any] = None,
    task_id: Optional[str] = None,
    task_name: Optional[str] = None,
    **args: Any,
) -> Dict[str, Any]:
    env = env or agi_cls.env
    if env is None:
        raise ValueError("env is required when AGI has not been initialised yet")

    if not agi_cls._service_futures and not agi_cls._service_workers:
        recovered = await agi_cls._service_recover(env)
        if not recovered:
            raise RuntimeError("Service is not running. Call AGI.serve(..., action='start') first.")

    if agi_cls._dask_client is None or getattr(agi_cls._dask_client, "status", "") in {
        "closed",
        "closing",
    }:
        raise RuntimeError("Dask client is unavailable while service loops are running.")

    if agi_cls._service_queue_pending is None:
        agi_cls._init_service_queue(env)

    if workers is None:
        workers = agi_cls._workers or agi_cls._worker_default
    elif not isinstance(workers, dict):
        raise ValueError("workers must be a dict. {'ip-address':nb-worker}")

    effective_args = agi_cls._service_public_args(dict(args) if args else dict(agi_cls._args or {}))

    if work_plan is None or work_plan_metadata is None:
        agi_cls._workers, generated_plan, generated_metadata = await WorkDispatcher._do_distrib(
            env,
            workers,
            effective_args,
        )
        if work_plan is None:
            work_plan = generated_plan
        if work_plan_metadata is None:
            work_plan_metadata = generated_metadata

    agi_cls._work_plan = work_plan
    agi_cls._work_plan_metadata = work_plan_metadata

    service_workers = list(agi_cls._service_workers or agi_cls._service_futures.keys())
    if not service_workers and agi_cls._dask_client is not None:
        service_workers = await agi_cls._service_connected_workers(agi_cls._dask_client)
        agi_cls._service_workers = list(service_workers)
    if not service_workers:
        raise RuntimeError("No active service workers available for submission.")

    agi_cls._service_submit_counter += 1
    submit_seq = agi_cls._service_submit_counter
    batch_id = task_id or f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
    batch_name = task_name or "service-workplan"
    cleanup_info = agi_cls._service_cleanup_artifacts()

    pending_dir = agi_cls._service_queue_pending
    queued_files: List[str] = []

    for worker_idx, worker_addr in enumerate(service_workers):
        safe_worker = agi_cls._service_safe_worker_name(worker_addr)

        filename = f"{submit_seq:06d}-{batch_id}-{worker_idx:03d}-{safe_worker}.task.pkl"
        task_path = pending_dir / filename
        tmp_path = task_path.with_suffix(task_path.suffix + ".tmp")

        payload = {
            "schema": "agi.service.task.v1",
            "task_id": batch_id,
            "task_name": batch_name,
            "created_at": time.time(),
            "worker_idx": worker_idx,
            "worker": str(worker_addr),
            "plan": agi_cls._wrap_worker_chunk(work_plan or [], worker_idx),
            "metadata": agi_cls._wrap_worker_chunk(work_plan_metadata or [], worker_idx),
            "args": effective_args,
        }

        with open(tmp_path, "wb") as stream:
            pickle.dump(payload, stream, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp_path, task_path)
        queued_files.append(str(task_path))

    logger.info(
        "Queued service batch %s (%s) for %s workers in %s",
        batch_id,
        batch_name,
        len(service_workers),
        pending_dir,
    )

    return {
        "status": "queued",
        "task_id": batch_id,
        "task_name": batch_name,
        "workers": service_workers,
        "queued_files": queued_files,
        "queue_dir": str(agi_cls._service_queue_root) if agi_cls._service_queue_root else str(pending_dir.parent),
        "cleanup": cleanup_info,
    }
