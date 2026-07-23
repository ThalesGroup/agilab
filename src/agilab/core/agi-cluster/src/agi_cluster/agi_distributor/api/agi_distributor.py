# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
# 3. Neither the name of Jean-Pierre Morard nor the names of its contributors, or THALES SIX GTS France SAS, may be used to endorse or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""Cluster workplan utilities for distributing AGILab workloads."""
from __future__ import annotations

import traceback
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple, Union
import asyncio
import inspect
import getpass
import logging
import os
import random
import shutil
import socket
import sys
import time
from pathlib import Path
from tempfile import gettempdir, mkdtemp

from agi_cluster.agi_distributor import cli as distributor_cli
from agi_cluster.agi_distributor import (
    background_jobs_support,
    capacity_support,
    cleanup_support,
    deployment_build_support,
    deployment_local_support,
    deployment_orchestration_support,
    deployment_prepare_support,
    deployment_remote_support,
    entrypoint_support,
    lifecycle_guard_support,
    runtime_distribution_support,
    runtime_misc_support,
    scheduler_io_support,
    service_runtime_support,
    transport_support,
    uv_source_support,
)
from agi_cluster.agi_distributor.run_request_support import RunRequest


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Asyncio compatibility helpers (PyCharm debugger patches asyncio.run)
# ---------------------------------------------------------------------------
runtime_misc_support.ensure_asyncio_run_signature(
    asyncio_module=asyncio,
    inspect_signature_fn=inspect.signature,
)


# External Libraries
from asyncssh.process import ProcessError
from contextlib import asynccontextmanager
import psutil
import runpy

if TYPE_CHECKING:
    from dask.distributed import Client


def wait(*args: Any, **kwargs: Any) -> Any:
    """Lazy proxy for ``dask.distributed.wait``.

    Importing dask.distributed eagerly slows every ``import AGI`` even for
    non-Dask local runs; the real ``wait`` is loaded on first use.
    """
    from dask.distributed import wait as _wait

    return _wait(*args, **kwargs)

# Project Libraries:
from agi_env import AgiEnv
from agi_node.agi_dispatcher.bootstrap_source_paths import resolve_node_source_path

def _resolve_node_src(
    sys_prefix: str | os.PathLike[str] | None = None,
    source_file: str | os.PathLike[str] | None = None,
) -> str | None:
    """Return the best ``agi-node/src`` path for the current runtime layout."""
    node_src = resolve_node_source_path(
        sys_prefix=sys_prefix,
        source_file=source_file or __file__,
    )
    return str(node_src) if node_src is not None else None


def _bootstrap_node_src(
    *,
    sys_path: list[str] | None = None,
    sys_prefix: str | os.PathLike[str] | None = None,
    source_file: str | os.PathLike[str] | None = None,
) -> str | None:
    """Prepend the best repo-local ``agi-node/src`` path to ``sys.path``."""

    target_sys_path = sys.path if sys_path is None else sys_path
    node_src = _resolve_node_src(sys_prefix=sys_prefix, source_file=source_file)
    if node_src and node_src not in target_sys_path:
        target_sys_path.insert(0, node_src)
    return node_src


_node_src = _bootstrap_node_src()
from agi_node.agi_dispatcher import WorkDispatcher, BaseWorker

# os.environ["DASK_DISTRIBUTED__LOGGING__DISTRIBUTED__LEVEL"] = "INFO"
_workers_default = {"127.0.0.1": 1}

from agi_env.agi_logger import AgiLogger

logger = AgiLogger.get_logger(__name__)

_BackgroundProcessJob = background_jobs_support.BackgroundProcessJob
_BackgroundProcessManager = background_jobs_support.BackgroundProcessManager
bg = background_jobs_support.bg

class AGI:
    """Coordinate installation, scheduling, and execution of AGILab workloads."""

    # Constants as class attributes
    _TIMEOUT = 10
    PYTHON_MODE = 1
    CYTHON_MODE = 2
    DASK_MODE = 4
    _INSTALL_MASK = 0b11 << DASK_MODE
    _INSTALL_MODE = 0b01 << DASK_MODE
    _UPDATE_MODE = 0b10 << DASK_MODE
    _SIMULATE_MODE = 0b11 << DASK_MODE
    _DEPLOYEMENT_MASK = 0b110000
    _RUN_MASK = 0b001111
    _RAPIDS_SET = 0b111111
    _RAPIDS_RESET = 0b110111
    # Rapids run-mode bit (8). Derived from the rapids set/reset masks so it can
    # never drift back into the install-mode range (0b01 << DASK_MODE == 16);
    # AGI.DASK_MODE | AGI.RAPIDS_MODE must resolve to a rapids RUN, not an install.
    RAPIDS_MODE = _RAPIDS_SET ^ _RAPIDS_RESET
    _DASK_RESET = 0b111011
    _args: Optional[Dict[str, Any]] = None
    _worker_args: Optional[Dict[str, Any]] = None
    _dask_client: Optional[Client] = None
    _dask_scheduler: Optional[Any] = None
    _dask_workers: Optional[List[str]] = None
    _jobs: Optional[Any] = None
    _local_ip: List[str] = []
    _install_done_local: bool = False
    _mode: Optional[int] = None
    _mode_auto: bool = False
    _remote_ip: List[str] = []
    _install_done: bool = False
    _install_todo: Optional[int] = 0
    _scheduler: Optional[str] = None
    _scheduler_ip: Optional[str] = None
    _scheduler_port: Optional[int] = None
    _target: Optional[str] = None
    verbose: Optional[int] = None
    _worker_init_error: bool = False
    _worker_launch_tasks: Set[Any] = set()
    _worker_launch_errors: List[BaseException] = []
    _scheduler_launch_tasks: Set[Any] = set()
    _scheduler_launch_errors: List[BaseException] = []
    _startup_in_progress: bool = False
    _workers: Optional[Dict[str, int]] = None
    _workers_data_path: Optional[str] = None
    _capacity: Optional[Dict[str, float]] = None
    _capacity_data_file: Optional[Path] = None
    _capacity_model_file: Optional[Path] = None
    _capacity_predictor: Optional[Any] = None
    _worker_default: Dict[str, int] = _workers_default
    _run_time: Dict[str, Any] = {}
    _run_type: Optional[str] = None
    _run_types: List[str] = []
    _target_built: Optional[Any] = None
    _module_to_clean: List[str] = []
    _ssh_connections = {}
    _best_mode: Dict[str, Any] = {}
    _work_plan: Optional[Any] = None
    _work_plan_metadata: Optional[Any] = None
    debug: Optional[bool] = None  # Cache with default local IPs
    _dask_log_level: str = os.environ.get("AGI_DASK_LOG_LEVEL", "critical").strip()
    env: Optional[AgiEnv] = None
    _service_futures: Dict[str, Any] = {}
    _service_workers: List[str] = []
    _service_shutdown_on_stop: bool = True
    _service_stop_timeout: Optional[float] = 30.0
    _service_poll_interval: Optional[float] = None
    _service_queue_root: Optional[Path] = None
    _service_queue_pending: Optional[Path] = None
    _service_queue_running: Optional[Path] = None
    _service_queue_done: Optional[Path] = None
    _service_queue_failed: Optional[Path] = None
    _service_queue_heartbeats: Optional[Path] = None
    _service_heartbeat_timeout: Optional[float] = None
    _service_started_at: Optional[float] = None
    _service_cleanup_done_ttl_sec: float = 7 * 24 * 3600
    _service_cleanup_failed_ttl_sec: float = 14 * 24 * 3600
    _service_cleanup_heartbeat_ttl_sec: float = 24 * 3600
    _service_cleanup_done_max_files: int = 2000
    _service_cleanup_failed_max_files: int = 2000
    _service_cleanup_heartbeat_max_files: int = 1000
    _service_submit_counter: int = 0
    _service_worker_args: Dict[str, Any] = {}
    _service_cleanup_unproven: bool = False
    _service_runtime_shutdown_proven: bool = False
    # ``AGI`` keeps a class-based compatibility surface.  These fields are
    # managed by lifecycle_guard_support so concurrent event loops/threads and
    # separate processes cannot cross-wire that shared mutable state.
    _lifecycle_state_lock: Any = None
    _lifecycle_call_token: Optional[str] = None
    _lifecycle_call_owner: Any = None
    _lifecycle_call_target: Optional[Path] = None
    _lifecycle_call_operation: Optional[str] = None
    _lifecycle_call_depth: int = 0
    _lifecycle_remote_token: Optional[str] = None
    _lifecycle_remote_recovery_tokens: tuple[str, ...] = ()
    _lifecycle_pending_release_lease: Any = None
    _lifecycle_service_token: Optional[str] = None
    _lifecycle_service_target: Optional[Path] = None
    _lifecycle_service_operation: Optional[str] = None
    _lifecycle_service_lease: Any = None
    _remote_target_leases: Dict[str, cleanup_support.RemoteTargetLease] = {}

    def __init__(self, target: str, verbose: int = 1):
        """
        Initialize a Agi object with a target and verbosity level.

        Args:
            target (str): The target for the env object.
            verbose (int): Verbosity level (0-3).

        Returns:
            None

        Raises:
            None
        """
        # At the top of __init__:
        if hasattr(AGI, "_instantiated") and AGI._instantiated:
            raise RuntimeError("AGI class is a singleton. Only one instance allowed per process.")
        AGI._instantiated = True  # ty: ignore[unresolved-attribute]

    @staticmethod
    async def run(
            env: AgiEnv,  # some_default_value must be defined
            request: RunRequest,
    ) -> Any:
        """
        Compiles the target module in Cython and runs it on the cluster.

        Args:
            env: AGILAB environment to execute.
            request: Typed execution request. App params and workflow stages are kept separate.

        Returns:
            Any: Result of the execution.

        Raises:
            ValueError: If `mode` is invalid.
            RuntimeError: If the target module fails to load.
        """
        async with lifecycle_guard_support.LifecycleOperation(AGI, env, "run"):
            return await entrypoint_support.run(
                AGI,
                env=env,
                request=request,
                workers_default=_workers_default,
                process_error_type=ProcessError,
                format_exception_chain_fn=_format_exception_chain,
                traceback_format_exc_fn=traceback.format_exc,
                log=logger,
            )

    @staticmethod
    def _wrap_worker_chunk(payload: Any, worker_index: int) -> Any:
        return service_runtime_support.wrap_worker_chunk(payload, worker_index)

    @staticmethod
    def _service_queue_paths(queue_root: Path) -> Dict[str, Path]:
        return service_runtime_support.service_queue_paths(queue_root)

    @staticmethod
    def _service_apply_queue_root(
            queue_root: Union[str, Path],
            *,
            create: bool = False,
    ) -> Dict[str, Path]:
        return service_runtime_support.service_apply_queue_root(AGI, queue_root, create=create)

    @staticmethod
    def _service_state_path(env: AgiEnv) -> Path:
        return service_runtime_support.service_state_path(env)

    @staticmethod
    def _service_read_state(env: AgiEnv) -> Optional[Dict[str, Any]]:
        return service_runtime_support.service_read_state(AGI, env, log=logger)

    @staticmethod
    def _service_write_state(env: AgiEnv, payload: Dict[str, Any]) -> None:
        service_runtime_support.service_write_state(AGI, env, payload)

    @staticmethod
    def _service_clear_state(env: AgiEnv) -> None:
        service_runtime_support.service_clear_state(AGI, env, log=logger)

    @staticmethod
    def _service_health_path(
            env: AgiEnv,
            health_output_path: Optional[Union[str, Path]] = None,
    ) -> Path:
        return service_runtime_support.service_health_path(
            env,
            health_output_path=health_output_path,
        )

    @staticmethod
    def _service_health_payload(env: AgiEnv, result_payload: Dict[str, Any]) -> Dict[str, Any]:
        return service_runtime_support.service_health_payload(env, result_payload)

    @staticmethod
    def _service_write_health_payload(
            env: AgiEnv,
            health_payload: Dict[str, Any],
            *,
            health_output_path: Optional[Union[str, Path]] = None,
    ) -> Optional[str]:
        return service_runtime_support.service_write_health_payload(
            AGI,
            env,
            health_payload,
            health_output_path=health_output_path,
            log=logger,
        )

    @staticmethod
    def _service_finalize_response(
            env: AgiEnv,
            result_payload: Dict[str, Any],
            *,
            health_output_path: Optional[Union[str, Path]] = None,
            health_only: bool = False,
    ) -> Dict[str, Any]:
        return service_runtime_support.service_finalize_response(
            AGI,
            env,
            result_payload,
            health_output_path=health_output_path,
            health_only=health_only,
        )

    @staticmethod
    async def _service_connected_workers(client: Client) -> List[str]:
        return await service_runtime_support.service_connected_workers(client)

    @staticmethod
    async def _service_recover(
            env: AgiEnv,
            *,
            allow_stale_cleanup: bool = False,
    ) -> bool:
        return await service_runtime_support.service_recover(
            AGI,
            env,
            allow_stale_cleanup=allow_stale_cleanup,
            log=logger,
        )

    @staticmethod
    def _reset_service_queue_state() -> None:
        service_runtime_support.reset_service_queue_state(AGI)

    @staticmethod
    def _init_service_queue(
            env: AgiEnv,
            service_queue_dir: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Path]:
        return service_runtime_support.init_service_queue(
            AGI,
            env,
            service_queue_dir=service_queue_dir,
        )

    @staticmethod
    def _service_queue_counts() -> Dict[str, int]:
        return service_runtime_support.service_queue_counts(AGI)

    @staticmethod
    def _recover_orphaned_service_tasks() -> Dict[str, int]:
        return service_runtime_support.recover_orphaned_service_tasks(AGI)

    @staticmethod
    def _service_cleanup_artifacts() -> Dict[str, int]:
        return service_runtime_support.service_cleanup_artifacts(AGI)

    @staticmethod
    def _service_public_args(args: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return service_runtime_support.service_public_args(args)

    @staticmethod
    def _service_safe_worker_name(worker: str) -> str:
        return service_runtime_support.service_safe_worker_name(worker)

    @staticmethod
    def _service_heartbeat_timeout_value() -> float:
        return service_runtime_support.service_heartbeat_timeout_value(AGI)

    @staticmethod
    def _service_apply_runtime_config(
            *,
            heartbeat_timeout: Optional[float] = None,
            cleanup_done_ttl_sec: Optional[float] = None,
            cleanup_failed_ttl_sec: Optional[float] = None,
            cleanup_heartbeat_ttl_sec: Optional[float] = None,
            cleanup_done_max_files: Optional[int] = None,
            cleanup_failed_max_files: Optional[int] = None,
            cleanup_heartbeat_max_files: Optional[int] = None,
    ) -> None:
        service_runtime_support.service_apply_runtime_config(
            AGI,
            heartbeat_timeout=heartbeat_timeout,
            cleanup_done_ttl_sec=cleanup_done_ttl_sec,
            cleanup_failed_ttl_sec=cleanup_failed_ttl_sec,
            cleanup_heartbeat_ttl_sec=cleanup_heartbeat_ttl_sec,
            cleanup_done_max_files=cleanup_done_max_files,
            cleanup_failed_max_files=cleanup_failed_max_files,
            cleanup_heartbeat_max_files=cleanup_heartbeat_max_files,
        )

    @staticmethod
    def _service_state_payload(env: AgiEnv) -> Dict[str, Any]:
        return service_runtime_support.service_state_payload(AGI, env)

    @staticmethod
    def _service_read_heartbeats() -> Dict[str, float]:
        return service_runtime_support.service_read_heartbeats(AGI)

    @staticmethod
    def _service_read_heartbeat_payloads() -> Dict[str, Dict[str, Any]]:
        return service_runtime_support.service_read_heartbeat_payloads(AGI)

    @staticmethod
    def _service_worker_health(workers: List[str]) -> List[Dict[str, Any]]:
        return service_runtime_support.service_worker_health(AGI, workers)

    @staticmethod
    def _service_unhealthy_workers(workers: List[str]) -> Dict[str, str]:
        return service_runtime_support.service_unhealthy_workers(AGI, workers)

    @staticmethod
    async def _service_restart_workers(
            env: AgiEnv,
            client: Client,
            workers_to_restart: List[str],
    ) -> List[str]:
        return await service_runtime_support.service_restart_workers(
            AGI,
            env,
            client,
            workers_to_restart,
            log=logger,
        )

    @staticmethod
    async def _service_auto_restart_unhealthy(
            env: AgiEnv,
            client: Client,
    ) -> Dict[str, Any]:
        return await service_runtime_support.service_auto_restart_unhealthy(
            AGI,
            env,
            client,
        )

    @staticmethod
    async def serve(
            env: AgiEnv,
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
            **args: Any,
    ) -> Dict[str, Any]:
        command = (action or "start").lower()
        operation = lifecycle_guard_support.LifecycleOperation(
            AGI,
            env,
            f"serve:{command}",
            service_command=True,
        )
        async with operation:
            try:
                result = await service_runtime_support.serve(
                    AGI,
                    env,
                    scheduler=scheduler,
                    workers=workers,
                    verbose=verbose,
                    mode=mode,
                    rapids_enabled=rapids_enabled,
                    action=action,
                    poll_interval=poll_interval,
                    shutdown_on_stop=shutdown_on_stop,
                    stop_timeout=stop_timeout,
                    service_queue_dir=service_queue_dir,
                    heartbeat_timeout=heartbeat_timeout,
                    cleanup_done_ttl_sec=cleanup_done_ttl_sec,
                    cleanup_failed_ttl_sec=cleanup_failed_ttl_sec,
                    cleanup_heartbeat_ttl_sec=cleanup_heartbeat_ttl_sec,
                    cleanup_done_max_files=cleanup_done_max_files,
                    cleanup_failed_max_files=cleanup_failed_max_files,
                    cleanup_heartbeat_max_files=cleanup_heartbeat_max_files,
                    health_output_path=health_output_path,
                    background_job_manager_factory=bg.BackgroundJobManager,
                    wait_fn=wait,
                    log=logger,
                    **args,
                )
            except BaseException:
                if (
                    AGI._service_cleanup_unproven
                    or AGI._service_runtime_shutdown_proven
                    or AGI._service_futures
                    or AGI._service_workers
                    or AGI._dask_client is not None
                    or bool(getattr(getattr(AGI, "_jobs", None), "running", None))
                ):
                    operation.retain_for_service_on_error()
                raise
            status = str(result.get("status", "")).lower()
            if command == "stop":
                jobs = getattr(getattr(AGI, "_jobs", None), "running", None) or []
                runtime_retained = AGI._dask_client is not None or bool(jobs)
                stop_unproven = (
                    status not in {"idle", "stopped"}
                    or AGI._service_cleanup_unproven
                    or AGI._service_runtime_shutdown_proven
                    or bool(AGI._service_futures)
                    or bool(AGI._service_workers)
                )
                if stop_unproven:
                    operation.retain_for_service()
                elif shutdown_on_stop or not runtime_retained:
                    operation.release_service()
                    AGI._service_cleanup_unproven = False
                else:
                    # A stopped service may intentionally retain its Dask
                    # runtime. Keep serialization until a later stop requests
                    # shutdown; otherwise a normal run can cross-wire it.
                    operation.retain_for_service()
            elif status in {"running", "degraded"} or AGI._service_futures or AGI._service_workers:
                operation.retain_for_service()
            return result

    @staticmethod
    async def submit(
            env: Optional[AgiEnv] = None,
            workers: Optional[Dict[str, int]] = None,
            work_plan: Optional[Any] = None,
            work_plan_metadata: Optional[Any] = None,
            task_id: Optional[str] = None,
            task_name: Optional[str] = None,
            **args: Any,
    ) -> Dict[str, Any]:
        effective_env = env or AGI.env
        if effective_env is None:
            raise ValueError("env is required when AGI has not been initialised yet")
        operation = lifecycle_guard_support.LifecycleOperation(
            AGI,
            effective_env,
            "submit",
            service_command=True,
        )
        async with operation:
            try:
                result = await service_runtime_support.submit(
                    AGI,
                    env=env,
                    workers=workers,
                    work_plan=work_plan,
                    work_plan_metadata=work_plan_metadata,
                    task_id=task_id,
                    task_name=task_name,
                    **args,
                )
            except BaseException:
                if (
                    AGI._service_cleanup_unproven
                    or AGI._service_futures
                    or AGI._service_workers
                    or AGI._dask_client is not None
                    or bool(getattr(getattr(AGI, "_jobs", None), "running", None))
                ):
                    operation.retain_for_service_on_error()
                raise
            operation.retain_for_service()
            return result

    @staticmethod
    async def _benchmark(
            env: AgiEnv,
            request: RunRequest,
    ) -> str:
        return await capacity_support.benchmark(
            AGI,
            env,
            request=request,
        )

    @staticmethod
    async def _benchmark_dask_modes(
        env: AgiEnv,
        request: RunRequest,
        mode_range: List[int],
        rapids_mode_mask: int,
        runs: Dict[int | str, Dict[str, Any]],
        *,
        include_best_single_node: bool = False,
    ) -> None:
        await capacity_support.benchmark_dask_modes(
            AGI,
            env,
            request,
            mode_range,
            rapids_mode_mask,
            runs,
            include_best_single_node=include_best_single_node,
        )

    @staticmethod
    def get_default_local_ip() -> str:
        return scheduler_io_support.get_default_local_ip(
            socket_factory=socket.socket,
        )

    @staticmethod
    def find_free_port(start: int = 5000, end: int = 10000, attempts: int = 100) -> int:
        return scheduler_io_support.find_free_port(
            start=start,
            end=end,
            attempts=attempts,
            randint_fn=random.randint,
            socket_factory=socket.socket,
        )

    @staticmethod
    def _get_scheduler(ip_sched: Optional[Union[str, Dict[str, int]]] = None) -> Tuple[str, int]:
        return scheduler_io_support.get_scheduler(
            AGI,
            ip_sched,
            gethostbyname_fn=socket.gethostbyname,
        )

    @staticmethod
    def _get_stdout(func: Any, *args: Any, **kwargs: Any) -> Tuple[str, Any]:
        return scheduler_io_support.get_stdout(func, *args, **kwargs)

    @staticmethod
    def _read_stderr(output_stream: Any) -> None:
        scheduler_io_support.read_stderr(
            AGI,
            output_stream,
            sleep_fn=time.sleep,
            log=logger,
        )

    @staticmethod
    async def send_file(
            env: AgiEnv,
            ip: str,
            local_path: Path,
            remote_path: Path,
            user: str = None,  # ty: ignore[invalid-parameter-default]
            password: str = None  # ty: ignore[invalid-parameter-default]
    ):
        await transport_support.send_file(
            env,
            ip,
            local_path,
            remote_path,
            user=user,
            password=password,
            log=logger,
        )

    @staticmethod
    async def send_files(env: AgiEnv, ip: str, files: list[Path], remote_dir: Path, user: str = None):  # ty: ignore[invalid-parameter-default]
        await transport_support.send_files(
            AGI,
            env,
            ip,
            files,
            remote_dir,
            user=user,
        )

    @staticmethod
    def _remove_dir_forcefully(path):
        cleanup_support.remove_dir_forcefully(
            path,
            rmtree_fn=shutil.rmtree,
            sleep_fn=time.sleep,
            access_fn=os.access,
            chmod_fn=os.chmod,
            log=logger,
        )

    @staticmethod
    async def _kill(
            ip: Optional[str] = None,
            current_pid: Optional[int] = None,
            force: bool = True,
            *,
            force_scan: bool = False,
    ) -> Optional[Any]:
        return await cleanup_support.kill_processes(
            AGI,
            ip=ip,
            current_pid=current_pid,
            force=force,
            force_scan=force_scan,
            gethostbyname_fn=socket.gethostbyname,
            run_fn=AgiEnv.run,
            copy_fn=shutil.copy,
            run_path_fn=runpy.run_path,
            sys_module=sys,
            path_cls=Path,
            detect_export_cmd_fn=AGI._detect_export_cmd,  # ty: ignore[invalid-argument-type]
            log=logger,
        )

    @staticmethod
    async def _wait_for_port_release(ip: str, port: int, timeout: float = 5.0, interval: float = 0.2) -> bool:
        return await cleanup_support.wait_for_port_release(
            ip,
            port,
            timeout=timeout,
            interval=interval,
            gethostbyname_fn=socket.gethostbyname,
            socket_factory=socket.socket,
            sleep_fn=asyncio.sleep,
            monotonic_fn=time.monotonic,
        )

    @staticmethod
    def _clean_dirs_local() -> None:
        cleanup_support.clean_dirs_local(
            AGI,
            process_iter_fn=psutil.process_iter,
            getuser_fn=getpass.getuser,
            getpid_fn=os.getpid,
            rmtree_fn=shutil.rmtree,
        )

    @staticmethod
    def _force_clean_dirs_local() -> None:
        """Explicit operator recovery; ordinary deploy cleanup is target-scoped."""

        cleanup_support.force_clean_dirs_local(
            AGI,
            process_iter_fn=psutil.process_iter,
            getuser_fn=getpass.getuser,
            getpid_fn=os.getpid,
            rmtree_fn=shutil.rmtree,
            gettempdir_fn=gettempdir,
        )

    @staticmethod
    async def _clean_dirs(ip: str) -> None:
        await cleanup_support.clean_dirs(
            AGI,
            ip,
            makedirs_fn=os.makedirs,
            remove_dir_forcefully_fn=AGI._remove_dir_forcefully,
        )

    @staticmethod
    async def _acquire_remote_target_lease(
            ip: str,
            *,
            cmd_prefix: Optional[str] = None,
    ) -> cleanup_support.RemoteTargetLease:
        return await cleanup_support.acquire_remote_target_lease(
            AGI,
            ip,
            cmd_prefix=cmd_prefix,
            detect_export_cmd_fn=AGI._detect_export_cmd,  # ty: ignore[invalid-argument-type]
        )

    @staticmethod
    async def _release_remote_target_leases() -> None:
        await cleanup_support.release_remote_target_leases(AGI)

    @staticmethod
    async def _clean_nodes(scheduler_addr: Optional[str], force: bool = True) -> Set[str]:
        return await deployment_orchestration_support.clean_nodes(
            AGI,
            scheduler_addr,
            force=force,
            is_local_fn=AgiEnv.is_local,
            gethostbyname_fn=socket.gethostbyname,
        )

    @staticmethod
    async def _clean_remote_procs(list_ip: Set[str], force: bool = True) -> None:
        await deployment_orchestration_support.clean_remote_procs(
            AGI,
            list_ip,
            force=force,
            is_local_fn=AgiEnv.is_local,
        )

    @staticmethod
    async def _clean_remote_dirs(list_ip: Set[str]) -> None:
        await deployment_orchestration_support.clean_remote_dirs(AGI, list_ip)

    @staticmethod
    async def _prepare_local_env() -> None:
        await deployment_prepare_support.prepare_local_env(
            AGI,
            envar_truthy_fn=uv_source_support.envar_truthy,
            detect_export_cmd_fn=AGI._detect_export_cmd,
            set_env_var_fn=AgiEnv.set_env_var,
            run_fn=AgiEnv.run,
            python_version_fn=distributor_cli.python_version,
            log=logger,
        )

    @staticmethod
    async def _prepare_cluster_env(scheduler_addr: Optional[str]) -> None:
        await deployment_prepare_support.prepare_cluster_env(
            AGI,
            scheduler_addr,
            envar_truthy_fn=uv_source_support.envar_truthy,
            detect_export_cmd_fn=AGI._detect_export_cmd,
            ensure_optional_extras_fn=uv_source_support.ensure_optional_extras,
            stage_uv_sources_fn=uv_source_support.stage_uv_sources_for_copied_pyproject,
            run_exec_ssh_fn=AGI.exec_ssh,
            send_files_fn=AGI.send_files,
            kill_fn=AGI._kill,
            clean_dirs_fn=AGI._clean_dirs,
            acquire_remote_target_lease_fn=AGI._acquire_remote_target_lease,
            mkdtemp_fn=mkdtemp,
            process_error_type=ProcessError,
            set_env_var_fn=AgiEnv.set_env_var,
            log=logger,
        )

    @staticmethod
    async def _deploy_application(scheduler_addr: Optional[str]) -> None:
        await deployment_orchestration_support.deploy_application(
            AGI,
            scheduler_addr,
            time_fn=time.time,
            log=logger,
        )

    @staticmethod
    def _reset_deploy_state() -> None:
        """Initialize installation flags and run type."""
        deployment_orchestration_support.reset_deploy_state(AGI)

    @staticmethod
    def _hardware_supports_rapids() -> bool:
        return runtime_misc_support.hardware_supports_rapids()

    @staticmethod
    async def _deploy_local_worker(options_worker: str) -> None:
        await deployment_local_support.deploy_local_worker(
            AGI,
            options_worker,
            agi_version_missing_on_pypi_fn=runtime_misc_support.agi_version_missing_on_pypi,
            worker_site_packages_dir_fn=uv_source_support.worker_site_packages_dir,  # ty: ignore[invalid-argument-type]
            write_staged_uv_sources_pth_fn=uv_source_support.write_staged_uv_sources_pth,
            runtime_file=__file__,
            run_fn=AgiEnv.run,
            set_env_var_fn=AgiEnv.set_env_var,
            log=logger,
        )

    @staticmethod
    async def _deploy_remote_worker(ip: str, env: AgiEnv) -> None:
        await deployment_remote_support.deploy_remote_worker(
            AGI,
            ip,
            env,
            worker_site_packages_dir_fn=uv_source_support.worker_site_packages_dir,
            staged_uv_sources_pth_content_fn=uv_source_support.staged_uv_sources_pth_content,
            set_env_var_fn=AgiEnv.set_env_var,
            log=logger,
        )

    @staticmethod
    def _should_install_pip() -> bool:
        return runtime_misc_support.should_install_pip()

    @staticmethod
    async def _uninstall_modules() -> None:
        await deployment_prepare_support.uninstall_modules(
            AGI,
            AGI.env,  # ty: ignore[invalid-argument-type]
            run_fn=AgiEnv.run,
            log=logger,
        )

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        return runtime_misc_support.format_elapsed(seconds)

    @staticmethod
    def _venv_todo(list_ip: Set[str]) -> None:
        deployment_prepare_support.venv_todo(AGI, list_ip, log=logger)

    @staticmethod
    async def install(
            env: AgiEnv,
            scheduler: Optional[str] = None,
            workers: Optional[Dict[str, int]] = None,
            workers_data_path: Optional[str] = None,
            modes_enabled: int = _RUN_MASK,
            verbose: Optional[int] = None,
            **args: Any,
    ) -> Any:
        async with lifecycle_guard_support.LifecycleOperation(AGI, env, "install"):
            return await entrypoint_support.install(
                AGI,
                env=env,
                scheduler=scheduler,
                workers=workers,
                workers_data_path=workers_data_path,
                modes_enabled=modes_enabled,
                verbose=verbose,
                args=args,
            )

    @staticmethod
    async def update(
            env: Optional[AgiEnv] = None,
            scheduler: Optional[str] = None,
            workers: Optional[Dict[str, int]] = None,
            modes_enabled: int = _RUN_MASK,
            verbose: Optional[int] = None,
            **args: Any,
    ) -> Any:
        effective_env = env or AGI.env
        if effective_env is None:
            raise ValueError("env is required when AGI has not been initialised yet")
        async with lifecycle_guard_support.LifecycleOperation(AGI, effective_env, "update"):
            return await entrypoint_support.update(
                AGI,
                env=env,
                scheduler=scheduler,
                workers=workers,
                modes_enabled=modes_enabled,
                verbose=verbose,
                args=args,
            )

    @staticmethod
    async def get_distrib(
            env: AgiEnv,
            scheduler: Optional[str] = None,
            workers: Optional[Dict[str, int]] = None,
            verbose: int = 0,
            **args: Any,
    ) -> Any:
        async with lifecycle_guard_support.LifecycleOperation(AGI, env, "get-distrib"):
            return await entrypoint_support.get_distrib(
                AGI,
                env=env,
                scheduler=scheduler,
                workers=workers,
                verbose=verbose,
                args=args,
            )

    # Backward compatibility alias
    @staticmethod
    async def distribute(
            env: AgiEnv,
            scheduler: Optional[str] = None,
            workers: Optional[Dict[str, int]] = None,
            verbose: int = 0,
            **args: Any,
    ) -> Any:
        async with lifecycle_guard_support.LifecycleOperation(AGI, env, "distribute"):
            return await entrypoint_support.distribute(
                AGI,
                env=env,
                scheduler=scheduler,
                workers=workers,
                verbose=verbose,
                args=args,
            )

    @staticmethod
    async def _start_scheduler(scheduler: Optional[str]) -> bool:
        return await entrypoint_support.start_scheduler(
            AGI,
            scheduler,
            set_env_var_fn=AgiEnv.set_env_var,
            create_task_fn=asyncio.create_task,
            sleep_fn=asyncio.sleep,
            log=logger,
        )

    @staticmethod
    async def _connect_scheduler_with_retry(
        address: str,
        *,
        timeout: float,
        heartbeat_interval: int = 5000,
    ) -> Client:
        from dask.distributed import Client as _Client

        return await entrypoint_support.connect_scheduler_with_retry(
            address,
            timeout=timeout,
            heartbeat_interval=heartbeat_interval,
            client_factory=_Client,
            sleep_fn=asyncio.sleep,
            monotonic_fn=time.monotonic,
            log=logger,
        )

    @staticmethod
    async def _detect_export_cmd(ip: str) -> Optional[str]:
        local_export_bin = getattr(
            AgiEnv,
            "export_local_bin",
            "" if os.name == "nt" else 'export PATH="~/.local/bin:$PATH";',
        )
        return await entrypoint_support.detect_export_cmd(
            AGI,
            ip,
            is_local_fn=AgiEnv.is_local,
            local_export_bin=local_export_bin,
        )

    @staticmethod
    def _dask_env_prefix() -> str:
        return runtime_distribution_support.dask_env_prefix(AGI)

    @staticmethod
    async def _start(scheduler: Optional[str]) -> bool:
        return await runtime_distribution_support.start(
            AGI,
            scheduler,
            set_env_var_fn=AgiEnv.set_env_var,
            create_task_fn=asyncio.create_task,
            log=logger,
        )

    @staticmethod
    async def _sync(timeout: int = 60) -> None:
        from dask.distributed import Client as _Client

        await runtime_distribution_support.sync(
            AGI,
            timeout=timeout,
            client_type=_Client,
            sleep_fn=asyncio.sleep,
            time_fn=time.time,
            log=logger,
        )

    @staticmethod
    async def _build_lib_local():
        await deployment_build_support.build_lib_local(
            AGI,
            ensure_optional_extras_fn=uv_source_support.ensure_optional_extras,
            stage_uv_sources_fn=uv_source_support.stage_uv_sources_for_copied_pyproject,
            validate_worker_uv_sources_fn=uv_source_support.validate_worker_uv_sources,
            run_fn=AgiEnv.run,
            log=logger,
        )

    @staticmethod
    async def _build_lib_remote() -> None:
        await deployment_build_support.build_lib_remote(AGI, log=logger)

    @staticmethod
    async def _run() -> Any:
        return await runtime_distribution_support.run_local(
            AGI,
            base_worker_cls=BaseWorker,
            validate_worker_uv_sources_fn=uv_source_support.validate_worker_uv_sources,
            run_async_fn=AgiEnv.run_async,
            log=logger,
        )

    @staticmethod
    async def _distribute() -> str:
        return await runtime_distribution_support.distribute(
            AGI,
            work_dispatcher_cls=WorkDispatcher,
            base_worker_cls=BaseWorker,
            time_fn=time.time,
            log=logger,
        )

    @staticmethod
    async def _main(scheduler: Optional[str]) -> Any:
        return await runtime_distribution_support.main(
            AGI,
            scheduler,
            background_job_manager_factory=bg.BackgroundJobManager,
            time_fn=time.time,
        )

    @staticmethod
    def _clean_job(cond_clean: bool) -> None:
        runtime_distribution_support.clean_job(AGI, cond_clean)

    @staticmethod
    def _scale_cluster() -> None:
        runtime_distribution_support.scale_cluster(AGI, log=logger)

    @staticmethod
    async def _stop() -> None:
        await runtime_distribution_support.stop(
            AGI,
            sleep_fn=asyncio.sleep,
            log=logger,
        )

    @staticmethod
    async def _calibration() -> None:
        await capacity_support.calibration(AGI, log=logger)

    @staticmethod
    def _train_capacity(train_home: Path) -> None:
        capacity_support.train_capacity(AGI, train_home, log=logger)

    @staticmethod
    def _update_capacity() -> None:
        capacity_support.update_capacity(AGI)

    @staticmethod
    def _exec_bg(cmd: Any, cwd: str, **kwargs: Any) -> None:
        runtime_distribution_support.exec_bg(AGI, cmd, cwd, **kwargs)

    @asynccontextmanager
    async def get_ssh_connection(ip: str, timeout_sec: int = 5):
        async with transport_support.get_ssh_connection(
            AGI,
            ip,
            timeout_sec=timeout_sec,
            discover_private_keys_fn=transport_support.discover_private_ssh_keys,
            log=logger,
        ) as conn:
            yield conn

    @staticmethod
    async def exec_ssh(ip: str, cmd: str) -> str:
        return await transport_support.exec_ssh(
            AGI,
            ip,
            cmd,
            process_error_cls=ProcessError,
            log=logger,
        )

    @staticmethod
    async def exec_ssh_async(ip: str, cmd: str) -> str:
        return await transport_support.exec_ssh_async(AGI, ip, cmd)

    @staticmethod
    async def _close_all_connections():
        await transport_support.close_all_connections(AGI)


def _format_exception_chain(exc: BaseException) -> str:
    return runtime_misc_support.format_exception_chain(exc)
