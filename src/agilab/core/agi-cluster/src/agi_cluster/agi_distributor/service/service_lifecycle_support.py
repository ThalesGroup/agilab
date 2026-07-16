from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

if TYPE_CHECKING:
    # Annotation-only: defer the dask.distributed import so importing AGI
    # stays cheap for non-Dask runs.
    from dask.distributed import Client

from agi_cluster.agi_distributor import runtime_misc_support
from agi_env import AgiEnv
from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher

logger = logging.getLogger(__name__)

SERVICE_TASK_SCHEMA = "agi.service.task.v1"
SERVICE_TASK_SUFFIX = ".task.json"

_SERVICE_RECOVERABLE_EXCEPTIONS = (
    ConnectionError,
    OSError,
    RuntimeError,
    TimeoutError,
)
_SERVICE_BREAK_LOOP_EXCEPTIONS = (
    ConnectionError,
    OSError,
    RuntimeError,
    TimeoutError,
)


def _break_loop_gather_exceptions() -> tuple:
    """Exceptions to tolerate when gathering break_loop tasks.

    Includes ``KilledWorker`` (imported lazily) so stopping a service whose
    worker died after task assignment still reaches cleanup.
    """
    try:
        from dask.distributed import KilledWorker
    except ImportError:
        return _SERVICE_BREAK_LOOP_EXCEPTIONS
    return _SERVICE_BREAK_LOOP_EXCEPTIONS + (KilledWorker,)


def _service_launch_failures(agi_cls: Any) -> List[str]:
    failures: List[str] = []
    for field in ("_scheduler_launch_errors", "_worker_launch_errors"):
        failures.extend(str(exc) for exc in (getattr(agi_cls, field, None) or []))
    for label, field in (
        ("scheduler", "_scheduler_launch_tasks"),
        ("worker", "_worker_launch_tasks"),
    ):
        for task in list(getattr(agi_cls, field, None) or []):
            if not hasattr(task, "done") or not task.done() or task.cancelled():
                continue
            try:
                exc = task.exception()
            except (asyncio.CancelledError, RuntimeError):
                continue
            failures.append(str(exc) if exc is not None else f"{label} launch task exited")
    return list(dict.fromkeys(failure for failure in failures if failure))


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


def _service_task_json_default(obj: Any) -> Any:
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if callable(obj):
        return getattr(obj, "__name__", str(obj))
    raise TypeError(f"Type {type(obj)} is not JSON serializable for service task payload")


def _prepare_service_worker_args(agi_cls: Any, env: AgiEnv) -> Dict[str, Any]:
    if agi_cls._service_queue_root is None:
        agi_cls._init_service_queue(env)
    agi_cls._service_worker_args = {
        **(agi_cls._args or {}),
        "_agi_service_mode": True,
        "_agi_service_queue_dir": str(agi_cls._service_queue_root),
    }
    return dict(agi_cls._service_worker_args)


def _submit_service_worker_inits(
    agi_cls: Any,
    env: AgiEnv,
    client: Client,
    workers: List[str],
    *,
    key_prefix: str,
) -> List[str]:
    worker_args = _prepare_service_worker_args(agi_cls, env)
    init_futures: List[Any] = []
    initialized: List[str] = []
    for worker in workers:
        if worker not in agi_cls._service_workers:
            agi_cls._service_workers.append(worker)
        worker_id = agi_cls._service_workers.index(worker)
        init_futures.append(
            client.submit(
                BaseWorker._new,
                env=0 if getattr(env, "debug", False) else None,
                app=env.target_worker,  # ty: ignore[unresolved-attribute]
                mode=agi_cls._mode,
                verbose=agi_cls.verbose,
                worker_id=worker_id,
                worker=worker,
                args=worker_args,
                workers=[worker],
                allow_other_workers=False,
                pure=False,
                key=f"{key_prefix}-init-{env.target}-{agi_cls._service_safe_worker_name(worker)}",
            )
        )
        initialized.append(worker)
    if init_futures:
        try:
            client.gather(init_futures)
        except BaseException:
            if not _cancel_owned_futures(init_futures, log=logger):
                agi_cls._service_cleanup_unproven = True
            raise
    return initialized


def _submit_service_loops(
    agi_cls: Any,
    env: AgiEnv,
    client: Client,
    workers: List[str],
    *,
    key_prefix: str,
    service_futures: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    cancel_on_failure = service_futures is None
    if service_futures is None:
        service_futures = {}
    loop_generation = uuid.uuid4().hex[:12]
    try:
        for worker in workers:
            service_futures[worker] = client.submit(
                BaseWorker.loop,
                poll_interval=agi_cls._service_poll_interval,
                workers=[worker],
                allow_other_workers=False,
                pure=False,
                key=(
                    f"{key_prefix}-loop-{env.target}-"
                    f"{agi_cls._service_safe_worker_name(worker)}-{loop_generation}"
                ),
            )
    except BaseException:
        # A caller-provided map preserves every submitted loop so an outer
        # startup transaction can request a graceful break and prove the loop
        # task actually exited. Cancelling here would discard that proof: a
        # Dask Future can report cancellation while its worker function keeps
        # running.
        if cancel_on_failure and not _cancel_owned_futures(
            service_futures.values(),
            log=logger,
        ):
            agi_cls._service_cleanup_unproven = True
        raise
    return service_futures


def _cancel_owned_futures(futures: Any, *, log: Any = logger) -> bool:
    """Request best-effort cancellation without treating it as stop proof."""

    cancellation_proven = True
    for future in list(futures):
        cancel = getattr(future, "cancel", None)
        if not callable(cancel):
            cancellation_proven = False
            continue
        try:
            cancel()
        except BaseException as cleanup_exc:
            cancellation_proven = False
            log.warning("Failed to cancel service startup future: %s", cleanup_exc)
    return cancellation_proven


def _future_execution_terminal(future: Any) -> bool:
    """Return whether a service-loop Future proves its function has exited."""

    # ``cancelled`` is deliberately excluded. Distributed cancellation can
    # detach the client-side Future while the worker function is still
    # executing, so only a natural completion or error proves loop exit.
    return str(getattr(future, "status", "")).lower() in {"finished", "error"}


def _reacquire_service_future(client: Any, key: str) -> Any:
    """Rebind one persisted Dask task key to the recovered client."""

    from dask.distributed import Future

    return Future(key, client=client)


def _wait_for_execution_terminal(
    futures: List[Any],
    *,
    wait_fn: Any,
    timeout: Optional[float],
    log: Any = logger,
    description: str,
) -> bool:
    """Wait for Futures and verify their worker-side executions terminated."""

    if not futures:
        return True
    if all(_future_execution_terminal(future) for future in futures):
        return True

    wait_kwargs: Dict[str, Any] = {}
    if timeout is not None:
        wait_kwargs["timeout"] = timeout
    try:
        _done, not_done = wait_fn(futures, **wait_kwargs)
    except TimeoutError:
        log.warning("Timed out waiting for %s to terminate", description)
        return False
    except BaseException as cleanup_exc:
        log.warning("Failed while waiting for %s to terminate: %s", description, cleanup_exc)
        return False

    if not_done:
        log.warning(
            "%s did not terminate for %s owned Future(s)",
            description,
            len(not_done),
        )
        return False
    if not all(_future_execution_terminal(future) for future in futures):
        log.warning(
            "%s wait completed without terminal execution status for every owned Future",
            description,
        )
        return False
    return True


async def _stop_owned_service_loops(
    agi_cls: Any,
    env: AgiEnv,
    owned_futures: Dict[str, Any],
    *,
    wait_fn: Any,
    client: Any = None,
    log: Any = logger,
) -> Dict[str, Any]:
    """Gracefully stop loops without tearing down a caller-owned Dask runtime."""

    if not owned_futures:
        return {}

    client = client or getattr(agi_cls, "_dask_client", None)
    if client is None:
        log.warning("Cannot prove service-loop cleanup without the reused Dask client")
        return dict(owned_futures)

    workers = list(owned_futures)
    try:
        connected_workers = await agi_cls._service_connected_workers(client)
    except BaseException as cleanup_exc:
        log.warning(
            "Failed to inspect connected workers during service-loop cleanup: %s",
            cleanup_exc,
        )
        connected_workers = []
    break_targets = (
        [worker for worker in workers if worker in connected_workers]
        if connected_workers
        else workers
    )

    break_tasks: List[Any] = []
    for worker in break_targets:
        try:
            break_tasks.append(
                client.submit(
                    BaseWorker.break_loop,
                    workers=[worker],
                    allow_other_workers=False,
                    pure=False,
                    key=(
                        "agi-serve-startup-cleanup-break-"
                        f"{env.target}-{agi_cls._service_safe_worker_name(worker)}-"
                        f"{uuid.uuid4().hex[:8]}"
                    ),
                )
            )
        except BaseException as cleanup_exc:
            log.warning(
                "Failed to submit service-loop break request for %s: %s",
                worker,
                cleanup_exc,
            )

    timeout = getattr(agi_cls, "_service_stop_timeout", 30.0)
    break_tasks_finished = _wait_for_execution_terminal(
        break_tasks,
        wait_fn=wait_fn,
        timeout=timeout,
        log=log,
        description="service-loop break request",
    )
    if break_tasks_finished and break_tasks:
        try:
            client.gather(break_tasks, errors="raise")
        except _break_loop_gather_exceptions():
            log.debug("Ignoring break_loop error during service cleanup", exc_info=True)
    else:
        # These control tasks are no longer useful after the bounded wait. Do
        # not count cancellation as evidence that they executed.
        _cancel_owned_futures(break_tasks, log=log)

    # The break request is only a signal. The original loop Futures remain the
    # authority for proving that worker execution ended.
    _wait_for_execution_terminal(
        list(owned_futures.values()),
        wait_fn=wait_fn,
        timeout=timeout,
        log=log,
        description="service loop",
    )
    return {
        worker: future
        for worker, future in owned_futures.items()
        if not _future_execution_terminal(future)
    }


async def _ensure_service_runtime_shutdown(agi_cls: Any) -> None:
    """Prove owned runtime shutdown once across post-shutdown cleanup retries."""

    if getattr(agi_cls, "_service_runtime_shutdown_proven", False):
        return
    await agi_cls._stop()
    agi_cls._service_runtime_shutdown_proven = True


async def _cleanup_failed_service_start(
    agi_cls: Any,
    env: AgiEnv,
    *,
    owned_futures: Any,
    runtime_started_here: bool,
    wait_fn: Any = None,
    log: Any = logger,
) -> bool:
    """Release only resources acquired by the failed service-start attempt."""

    prior_cleanup_unproven = bool(
        getattr(agi_cls, "_service_cleanup_unproven", False)
    )
    if isinstance(owned_futures, dict):
        owned_future_map = dict(owned_futures)
    else:
        # Keep compatibility with direct internal callers that predate the
        # worker-keyed ownership contract. Production startup now always
        # supplies the mapping so pinned break requests target exact workers.
        future_list = list(owned_futures)
        worker_list = list(getattr(agi_cls, "_service_workers", []) or [])
        owned_future_map = {
            (
                worker_list[index]
                if index < len(worker_list)
                else f"unknown-startup-worker-{index}"
            ): future
            for index, future in enumerate(future_list)
        }
    retained_futures = dict(getattr(agi_cls, "_service_futures", {}) or {})
    retained_futures.update(owned_future_map)
    retained_workers = list(
        dict.fromkeys(
            [*(getattr(agi_cls, "_service_workers", []) or []), *owned_future_map]
        )
    )

    cleanup_proven = False
    pending_futures: Dict[str, Any] = {}

    if runtime_started_here:
        # Cancellation is useful as a best-effort request before closing the
        # runtime, but only successful runtime teardown proves execution ended.
        _cancel_owned_futures(owned_future_map.values(), log=log)
        try:
            await _ensure_service_runtime_shutdown(agi_cls)
        except BaseException as cleanup_exc:
            log.warning("Service runtime cleanup failed after startup error: %s", cleanup_exc)
        else:
            cleanup_proven = True
    else:
        pending_futures = dict(owned_future_map)
        if wait_fn is None:
            try:
                from dask.distributed import wait as wait_fn
            except BaseException as cleanup_exc:
                log.warning(
                    "Cannot load the Dask wait helper for service-loop cleanup: %s",
                    cleanup_exc,
                )
        try:
            pending_futures = (
                await _stop_owned_service_loops(
                    agi_cls,
                    env,
                    owned_future_map,
                    wait_fn=wait_fn,
                    log=log,
                )
                if wait_fn
                else owned_future_map
            )
            cleanup_proven = not pending_futures
        except BaseException as cleanup_exc:
            cleanup_proven = False
            log.warning("Service-loop cleanup failed after startup error: %s", cleanup_exc)
        if not cleanup_proven:
            # Request cancellation only after the observable stop attempt, and
            # retain ownership regardless of whether cancel() returns.
            _cancel_owned_futures(owned_future_map.values(), log=log)

    if prior_cleanup_unproven and not runtime_started_here:
        cleanup_proven = False

    if (
        not cleanup_proven
        and not runtime_started_here
        and not prior_cleanup_unproven
        and pending_futures
    ):
        pending_ownership = {
            worker: future
            for worker, future in pending_futures.items()
            if not _future_execution_terminal(future)
        }
        if pending_ownership:
            # Initial service loops on a reused runtime have new scheduler keys
            # but no durable state yet. Publish an exact pending-only map first;
            # otherwise full runtime teardown is the only crash-safe proof.
            retained_futures = dict(pending_ownership)
            retained_workers = list(pending_ownership)
            agi_cls._service_futures = dict(pending_ownership)
            agi_cls._service_workers = list(pending_ownership)
            pending_keys_complete = all(
                getattr(future, "key", None) not in (None, "")
                for future in pending_ownership.values()
            )
            ownership_published = False
            if pending_keys_complete:
                try:
                    agi_cls._service_write_state(
                        env,
                        agi_cls._service_state_payload(env),
                    )
                except BaseException as publish_exc:
                    log.error(
                        "Failed to persist pending service-start ownership on "
                        "the reused runtime: %s",
                        publish_exc,
                    )
                else:
                    ownership_published = True
            if not ownership_published:
                try:
                    await _ensure_service_runtime_shutdown(agi_cls)
                except BaseException as shutdown_exc:
                    log.error(
                        "Full runtime shutdown failed after pending service-"
                        "start ownership could not be published: %s",
                        shutdown_exc,
                    )
                else:
                    cleanup_proven = True

    if agi_cls._jobs:
        try:
            agi_cls._clean_job(True)
        except BaseException as cleanup_exc:
            cleanup_proven = False
            log.warning("Service job cleanup failed after startup error: %s", cleanup_exc)

    if cleanup_proven:
        for cleanup_name, cleanup_call in (
            ("persisted service state", lambda: agi_cls._service_clear_state(env)),
            ("service queue state", agi_cls._reset_service_queue_state),
        ):
            try:
                cleanup_call()
            except BaseException as cleanup_exc:
                cleanup_proven = False
                log.warning(
                    "Failed to clear %s after service startup error: %s",
                    cleanup_name,
                    cleanup_exc,
                )

    if cleanup_proven:
        agi_cls._service_futures = {}
        agi_cls._service_workers = []
        agi_cls._service_runtime_shutdown_proven = False
    else:
        # Preserve every observable ownership handle so the lifecycle lease is
        # retained and a later explicit stop can finish cleanup safely.
        agi_cls._service_futures = retained_futures
        agi_cls._service_workers = retained_workers
    agi_cls._service_cleanup_unproven = not cleanup_proven
    return cleanup_proven


async def service_recover(
    agi_cls: Any,
    env: AgiEnv,
    *,
    allow_stale_cleanup: bool = False,
    log: Any = logger,
) -> bool:
    try:
        state = agi_cls._service_read_state(env)
    except _SERVICE_RECOVERABLE_EXCEPTIONS as exc:
        log.warning("Failed to inspect persisted AGI service ownership: %s", exc)
        agi_cls._service_cleanup_unproven = True
        return False
    if not state:
        return False

    try:
        agi_cls.env = env
        agi_cls.target_path = env.manager_path  # ty: ignore[unresolved-attribute]
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
        _prepare_service_worker_args(agi_cls, env)

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

        if not agi_cls._service_workers:
            raise RuntimeError("Recovered service scheduler has no attached workers.")

        loop_keys = state.get("service_loop_keys")
        if not isinstance(loop_keys, dict):
            raise RuntimeError(
                "Persisted service state does not contain loop Future ownership keys."
            )
        missing_loop_keys = [
            worker
            for worker in agi_cls._service_workers
            if not str(loop_keys.get(worker, "")).strip()
        ]
        if missing_loop_keys:
            raise RuntimeError(
                "Persisted service state is missing loop Future keys for workers: "
                + ", ".join(missing_loop_keys)
            )
        agi_cls._service_futures = {
            worker: _reacquire_service_future(
                agi_cls._dask_client,
                str(loop_keys[worker]),
            )
            for worker in agi_cls._service_workers
        }
        agi_cls._service_cleanup_unproven = False

        # Persisted recovery is also a controller handoff. Reconcile running
        # claims while holding the caller's lifecycle lease, just as a fresh
        # service start does.
        agi_cls._recover_orphaned_service_tasks()

        return True

    except _SERVICE_RECOVERABLE_EXCEPTIONS as exc:
        log.warning("Failed to recover persistent AGI service: %s", exc)
        # A transport or reconstruction failure is not evidence that the
        # persisted worker loops stopped. Preserve every available ownership
        # handle and require an explicit stop/recovery retry.
        persisted_workers = [
            str(worker) for worker in state.get("service_workers", []) if worker
        ]
        if not agi_cls._service_workers:
            agi_cls._service_workers = persisted_workers
        agi_cls._service_cleanup_unproven = True
        return False


async def service_restart_workers(
    agi_cls: Any,
    env: AgiEnv,
    client: Client,
    workers_to_restart: List[str],
    *,
    wait_fn: Any = None,
    log: Any = logger,
) -> List[str]:
    if not workers_to_restart:
        return []

    connected = await agi_cls._service_connected_workers(client)
    if connected:
        agi_cls._service_workers = list(connected)
    existing_workers = list(agi_cls._service_workers)

    if wait_fn is None:
        from dask.distributed import wait as wait_fn

    existing_futures = dict(agi_cls._service_futures)
    missing_futures = [
        worker for worker in workers_to_restart if worker not in existing_futures
    ]
    if missing_futures:
        agi_cls._service_cleanup_unproven = True
        raise RuntimeError(
            "Cannot restart service workers without their original loop Future "
            "ownership: " + ", ".join(missing_futures)
        )

    old_target_futures = {
        worker: existing_futures[worker] for worker in workers_to_restart
    }
    try:
        pending_old_futures = await _stop_owned_service_loops(
            agi_cls,
            env,
            old_target_futures,
            wait_fn=wait_fn,
            client=client,
            log=log,
        )
    except BaseException:
        agi_cls._service_cleanup_unproven = True
        agi_cls._service_futures = existing_futures
        raise
    if pending_old_futures:
        agi_cls._service_cleanup_unproven = True
        agi_cls._service_futures = {
            **{
                worker: future
                for worker, future in existing_futures.items()
                if worker not in workers_to_restart
            },
            **pending_old_futures,
        }
        agi_cls._service_workers = list(agi_cls._service_futures)
        raise RuntimeError(
            "Cannot restart service workers until their original loops terminate: "
            + ", ".join(pending_old_futures)
        )

    restarted: List[str] = []
    replacement_futures: Dict[str, Any] = {}
    try:
        restarted = _submit_service_worker_inits(
            agi_cls,
            env,
            client,
            workers_to_restart,
            key_prefix="agi-serve-restart",
        )
        _submit_service_loops(
            agi_cls,
            env,
            client,
            restarted,
            key_prefix="agi-serve-restart",
            service_futures=replacement_futures,
        )
    except BaseException as restart_exc:
        pending_replacements = dict(replacement_futures)
        if replacement_futures:
            try:
                pending_replacements = await _stop_owned_service_loops(
                    agi_cls,
                    env,
                    replacement_futures,
                    wait_fn=wait_fn,
                    client=client,
                    log=log,
                )
            except BaseException as cleanup_exc:
                log.warning(
                    "Replacement service-loop cleanup failed after restart error: %s",
                    cleanup_exc,
                )
        agi_cls._service_futures = {
            **{
                worker: future
                for worker, future in existing_futures.items()
                if worker not in workers_to_restart
            },
            **pending_replacements,
        }
        agi_cls._service_workers = list(agi_cls._service_futures)
        agi_cls._service_cleanup_unproven = bool(pending_replacements)
        if pending_replacements:
            try:
                agi_cls._service_write_state(env, agi_cls._service_state_payload(env))
            except BaseException as publish_exc:
                log.error(
                    "Failed to persist partial service-restart ownership; "
                    "forcing full runtime shutdown: %s",
                    publish_exc,
                )
                restart_exc.add_note(
                    "Partial replacement ownership publication also failed: "
                    f"{type(publish_exc).__name__}: {publish_exc}"
                )
                try:
                    # A replacement Future uses a new scheduler key. If that
                    # key cannot be published, only full runtime teardown can
                    # keep a controller crash from orphaning live replacement
                    # work behind the durable pre-restart ownership record.
                    await _ensure_service_runtime_shutdown(agi_cls)
                except BaseException as shutdown_exc:
                    log.error(
                        "Full runtime shutdown failed after partial service-"
                        "restart ownership publication failure: %s",
                        shutdown_exc,
                    )
                    restart_exc.add_note(
                        "Fail-safe runtime shutdown also failed: "
                        f"{type(shutdown_exc).__name__}: {shutdown_exc}"
                    )
                else:
                    # Runtime shutdown proves every replacement ended, so the
                    # durable pre-restart Future keys are authoritative again.
                    agi_cls._service_futures = existing_futures
                    agi_cls._service_workers = existing_workers
                agi_cls._service_cleanup_unproven = True
        raise

    agi_cls._service_futures = {
        **{
            worker: future
            for worker, future in existing_futures.items()
            if worker not in workers_to_restart
        },
        **replacement_futures,
    }
    agi_cls._service_cleanup_unproven = False
    return restarted


async def service_auto_restart_unhealthy(
    agi_cls: Any,
    env: AgiEnv,
    client: Client,
    *,
    wait_fn: Any = None,
    log: Any = logger,
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
    prior_futures = dict(agi_cls._service_futures)
    prior_workers = list(agi_cls._service_workers)
    prior_cleanup_unproven = bool(agi_cls._service_cleanup_unproven)
    restarted = await agi_cls._service_restart_workers(env, client, workers_to_restart)
    if restarted:
        replacement_futures = {
            worker: agi_cls._service_futures[worker]
            for worker in restarted
            if worker in agi_cls._service_futures
        }
        try:
            agi_cls._service_write_state(env, agi_cls._service_state_payload(env))
        except BaseException as publish_exc:
            pending_replacements = dict(replacement_futures)
            if replacement_futures:
                if wait_fn is None:
                    try:
                        from dask.distributed import wait as wait_fn
                    except BaseException as wait_import_exc:
                        log.warning(
                            "Cannot load Dask wait after service-restart state "
                            "publication failure: %s",
                            wait_import_exc,
                        )
                if wait_fn is not None:
                    try:
                        pending_replacements = await _stop_owned_service_loops(
                            agi_cls,
                            env,
                            replacement_futures,
                            wait_fn=wait_fn,
                            client=client,
                            log=log,
                        )
                    except BaseException as cleanup_exc:
                        log.warning(
                            "Replacement service-loop cleanup failed after state "
                            "publication error: %s",
                            cleanup_exc,
                        )
                        publish_exc.add_note(
                            "Replacement cleanup also failed: "
                            f"{type(cleanup_exc).__name__}: {cleanup_exc}"
                        )

            rollback_futures = dict(prior_futures)
            for worker in restarted:
                if worker in pending_replacements:
                    rollback_futures[worker] = pending_replacements[worker]
                elif worker not in prior_futures:
                    rollback_futures.pop(worker, None)
            agi_cls._service_futures = rollback_futures
            agi_cls._service_workers = list(
                dict.fromkeys([*prior_workers, *pending_replacements])
            )
            if pending_replacements:
                agi_cls._service_cleanup_unproven = True
                try:
                    # These replacements have new scheduler keys that could
                    # not be published. Full runtime shutdown is the only
                    # crash-safe ownership proof once bounded loop cleanup
                    # leaves any of them live.
                    await _ensure_service_runtime_shutdown(agi_cls)
                except BaseException as shutdown_exc:
                    log.error(
                        "Full runtime shutdown failed after service-restart "
                        "state publication failure: %s",
                        shutdown_exc,
                    )
                    publish_exc.add_note(
                        "Fail-safe runtime shutdown also failed: "
                        f"{type(shutdown_exc).__name__}: {shutdown_exc}"
                    )
                else:
                    # Runtime shutdown proves every replacement ended, making
                    # the durable pre-restart ownership record authoritative.
                    agi_cls._service_futures = prior_futures
                    agi_cls._service_workers = prior_workers
            else:
                agi_cls._service_cleanup_unproven = prior_cleanup_unproven
            raise
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
    wait_fn: Any = None,
    log: Any = logger,
    **args: Any,
) -> Dict[str, Any]:
    if wait_fn is None:
        # Deferred import: dask.distributed is only needed when a caller does
        # not inject its own wait function.
        from dask.distributed import wait as wait_fn

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

        if (
            agi_cls._service_cleanup_unproven
            or agi_cls._service_runtime_shutdown_proven
        ):
            workers_snapshot = list(agi_cls._service_workers)
            return agi_cls._service_finalize_response(
                env,
                {
                    "status": "error",
                    "workers": workers_snapshot,
                    "pending": list(
                        dict.fromkeys(
                            [*agi_cls._service_futures, *workers_snapshot]
                        )
                    ),
                    "client_status": (
                        str(getattr(client, "status", "missing") or "missing")
                        if client is not None
                        else "missing"
                    ),
                    "recovery_required": True,
                    "message": (
                        "Service-loop ownership is incomplete; call "
                        "AGI.serve(..., action='stop') to recover or fully "
                        "tear down the retained runtime."
                    ),
                },
                health_output_path=health_output_path,
                health_only=health_only,
            )

        launch_failures = _service_launch_failures(agi_cls)
        client_status = str(getattr(client, "status", "") or "").lower() if client else "missing"
        if (agi_cls._service_futures or agi_cls._service_workers) and (
            launch_failures or client_status in {"closed", "closing", "failed"}
        ):
            workers_snapshot = list(agi_cls._service_workers)
            return agi_cls._service_finalize_response(
                env,
                {
                    "status": "error",
                    "workers": workers_snapshot,
                    "pending": list(agi_cls._service_futures.keys()),
                    "client_status": client_status,
                    "launch_errors": launch_failures,
                    "message": (
                        "Persistent AGI service ownership is unhealthy; "
                        "call AGI.serve(..., action='stop') before restarting."
                    ),
                },
                health_output_path=health_output_path,
                health_only=health_only,
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
                if agi_cls._service_cleanup_unproven:
                    pending = list(
                        dict.fromkeys(
                            [
                                *agi_cls._service_futures,
                                *agi_cls._service_workers,
                            ]
                        )
                    )
                    if shutdown_on_stop and client is not None:
                        retained_futures = dict(agi_cls._service_futures)
                        retained_workers = list(agi_cls._service_workers)
                        try:
                            # Legacy v1 state has no Future keys to reacquire.
                            # A full connected-runtime shutdown is the only
                            # compatible proof that those loops cannot survive.
                            await _ensure_service_runtime_shutdown(agi_cls)
                            if agi_cls._jobs:
                                agi_cls._clean_job(True)
                            agi_cls._service_clear_state(env)
                            agi_cls._reset_service_queue_state()
                        except BaseException:
                            agi_cls._service_futures = retained_futures
                            agi_cls._service_workers = retained_workers
                            agi_cls._service_cleanup_unproven = True
                            raise
                        agi_cls._service_futures = {}
                        agi_cls._service_workers = []
                        agi_cls._service_cleanup_unproven = False
                        agi_cls._service_runtime_shutdown_proven = False
                        return agi_cls._service_finalize_response(
                            env,
                            {
                                "status": "stopped",
                                "workers": retained_workers,
                                "pending": [],
                                "legacy_full_shutdown": True,
                            },
                            health_output_path=health_output_path,
                        )
                    return agi_cls._service_finalize_response(
                        env,
                        {
                            "status": "error",
                            "workers": list(agi_cls._service_workers),
                            "pending": pending,
                            "recovery_required": True,
                            "message": (
                                "Service ownership could not be recovered; retry "
                                "AGI.serve(..., action='stop') after scheduler "
                                "connectivity is restored."
                            ),
                        },
                        health_output_path=health_output_path,
                    )
                log.info("AGI.serve(stop): no active service loops to stop.")
                try:
                    if shutdown_on_stop:
                        await _ensure_service_runtime_shutdown(agi_cls)
                    if agi_cls._jobs:
                        agi_cls._clean_job(True)
                    agi_cls._service_clear_state(env)
                    agi_cls._reset_service_queue_state()
                except BaseException:
                    agi_cls._service_cleanup_unproven = True
                    raise
                agi_cls._service_cleanup_unproven = False
                agi_cls._service_runtime_shutdown_proven = False
                return agi_cls._service_finalize_response(
                    env,
                    {"status": "idle", "workers": [], "pending": []},
                    health_output_path=health_output_path,
                )

        owned_futures = dict(agi_cls._service_futures)
        owned_workers = list(agi_cls._service_workers)

        if client is None:
            terminal_ownership_complete = bool(owned_futures) and all(
                _future_execution_terminal(future)
                for future in owned_futures.values()
            ) and set(owned_workers).issubset(owned_futures)
            runtime_shutdown_proven = bool(
                getattr(agi_cls, "_service_runtime_shutdown_proven", False)
            )
            if shutdown_on_stop and (
                terminal_ownership_complete or runtime_shutdown_proven
            ):
                stopped_workers = list(
                    dict.fromkeys([*owned_futures, *owned_workers])
                )
                try:
                    # A prior stop may have fully shut down the owned runtime
                    # before persisted-state deletion failed. Runtime cleanup
                    # is idempotent; retry it without requiring the now-cleared
                    # client reference, then finish the retained local cleanup.
                    await _ensure_service_runtime_shutdown(agi_cls)
                    if agi_cls._jobs:
                        agi_cls._clean_job(True)
                    agi_cls._service_clear_state(env)
                    agi_cls._reset_service_queue_state()
                except BaseException:
                    agi_cls._service_futures = owned_futures
                    agi_cls._service_workers = owned_workers
                    agi_cls._service_cleanup_unproven = True
                    raise
                agi_cls._service_futures = {}
                agi_cls._service_workers = []
                agi_cls._service_cleanup_unproven = False
                agi_cls._service_runtime_shutdown_proven = False
                return agi_cls._service_finalize_response(
                    env,
                    {
                        "status": "stopped",
                        "workers": stopped_workers,
                        "pending": [],
                        "runtime_cleanup_retry": True,
                    },
                    health_output_path=health_output_path,
                )

            log.error("AGI.serve(stop): service state exists but Dask client is unavailable")
            pending = list(
                dict.fromkeys(
                    [*agi_cls._service_futures, *agi_cls._service_workers]
                )
            )
            agi_cls._service_cleanup_unproven = True
            return agi_cls._service_finalize_response(
                env,
                {
                    "status": "error",
                    "workers": list(agi_cls._service_workers),
                    "pending": pending,
                    "recovery_required": True,
                    "message": (
                        "The Dask client is unavailable, so service-loop "
                        "termination cannot be proven. Restore connectivity "
                        "and retry AGI.serve(..., action='stop')."
                    ),
                },
                health_output_path=health_output_path,
            )

        target_workers = list(
            dict.fromkeys([*owned_futures, *owned_workers])
        )
        if not target_workers:
            target_workers = await agi_cls._service_connected_workers(client)
            agi_cls._service_workers = list(target_workers)

        if not target_workers:
            try:
                if shutdown_on_stop:
                    await _ensure_service_runtime_shutdown(agi_cls)
                agi_cls._service_clear_state(env)
                agi_cls._reset_service_queue_state()
            except BaseException:
                agi_cls._service_futures = owned_futures
                agi_cls._service_workers = owned_workers
                agi_cls._service_cleanup_unproven = True
                raise
            agi_cls._service_futures.clear()
            agi_cls._service_workers = []
            agi_cls._service_cleanup_unproven = False
            agi_cls._service_runtime_shutdown_proven = False
            return agi_cls._service_finalize_response(
                env,
                {"status": "idle", "workers": [], "pending": []},
                health_output_path=health_output_path,
            )

        missing_futures = [
            worker for worker in target_workers if worker not in owned_futures
        ]
        if missing_futures:
            agi_cls._service_cleanup_unproven = True
            if shutdown_on_stop:
                try:
                    await _ensure_service_runtime_shutdown(agi_cls)
                    if agi_cls._jobs:
                        agi_cls._clean_job(True)
                    agi_cls._service_clear_state(env)
                    agi_cls._reset_service_queue_state()
                except BaseException:
                    agi_cls._service_futures = owned_futures
                    agi_cls._service_workers = owned_workers
                    agi_cls._service_cleanup_unproven = True
                    raise
                agi_cls._service_futures = {}
                agi_cls._service_workers = []
                agi_cls._service_cleanup_unproven = False
                agi_cls._service_runtime_shutdown_proven = False
                return agi_cls._service_finalize_response(
                    env,
                    {
                        "status": "stopped",
                        "workers": target_workers,
                        "pending": [],
                        "ownership_full_shutdown": True,
                    },
                    health_output_path=health_output_path,
                )
            return agi_cls._service_finalize_response(
                env,
                {
                    "status": "partial",
                    "workers": [],
                    "pending": missing_futures,
                    "recovery_required": True,
                    "message": (
                        "Service-loop Future ownership is incomplete; recover "
                        "the persisted service state before retrying stop."
                    ),
                },
                health_output_path=health_output_path,
            )

        try:
            pending_futures = await _stop_owned_service_loops(
                agi_cls,
                env,
                owned_futures,
                wait_fn=wait_fn,
                log=log,
            )
        except BaseException:
            agi_cls._service_futures = owned_futures
            agi_cls._service_workers = owned_workers
            agi_cls._service_cleanup_unproven = True
            raise

        stopped_workers = [
            worker for worker in target_workers if worker not in pending_futures
        ]
        pending_workers = list(pending_futures)
        if pending_futures:
            agi_cls._service_futures = pending_futures
            agi_cls._service_workers = pending_workers
            agi_cls._service_cleanup_unproven = True
            try:
                agi_cls._service_write_state(env, agi_cls._service_state_payload(env))
            except BaseException as cleanup_exc:
                log.warning(
                    "Failed to persist partial service-stop ownership: %s",
                    cleanup_exc,
                )
            return agi_cls._service_finalize_response(
                env,
                {
                    "status": "partial",
                    "workers": stopped_workers,
                    "pending": pending_workers,
                    "recovery_required": True,
                },
                health_output_path=health_output_path,
            )

        try:
            if shutdown_on_stop:
                await _ensure_service_runtime_shutdown(agi_cls)
            if agi_cls._jobs:
                agi_cls._clean_job(True)
            agi_cls._service_clear_state(env)
            agi_cls._reset_service_queue_state()
        except BaseException:
            agi_cls._service_futures = owned_futures
            agi_cls._service_workers = owned_workers
            agi_cls._service_cleanup_unproven = True
            raise

        agi_cls._service_futures = {}
        agi_cls._service_workers = []
        agi_cls._service_cleanup_unproven = False
        agi_cls._service_runtime_shutdown_proven = False
        return agi_cls._service_finalize_response(
            env,
            {"status": "stopped", "workers": stopped_workers, "pending": []},
            health_output_path=health_output_path,
        )

    if agi_cls._service_futures:
        launch_failures = _service_launch_failures(agi_cls)
        if launch_failures:
            raise RuntimeError(
                "Service launch ownership is unhealthy ("
                + "; ".join(launch_failures)
                + "). Call AGI.serve(..., action='stop') before restarting."
            )
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

    if (
        agi_cls._service_cleanup_unproven
        or agi_cls._service_runtime_shutdown_proven
    ):
        raise RuntimeError(
            "Persisted service ownership could not be recovered. Restore "
            "scheduler connectivity and call AGI.serve(..., action='stop') "
            "before starting a new service runtime."
        )

    if not workers:
        workers = agi_cls._worker_default
    elif not isinstance(workers, dict):
        raise ValueError("workers must be a dict. {'ip-address':nb-worker}")

    agi_cls._jobs = background_job_manager_factory()
    runtime_misc_support.initialize_runtime_state(
        agi_cls,
        env,
        workers=workers,
        verbose=verbose,
        rapids_enabled=rapids_enabled,
        args=dict(args),
        args_transform_fn=agi_cls._service_public_args,
        log=log,
        log_message="AGI service instance created for target %s with verbosity %s",
    )
    runtime_misc_support.configure_runtime_mode(
        agi_cls,
        env,
        mode,
        default_mode=agi_cls.DASK_MODE,
        require_dask=True,
    )
    agi_cls._mode_auto = False
    agi_cls._run_type = agi_cls._run_types[0]

    runtime_misc_support.bootstrap_capacity_predictor(
        agi_cls,
        env,
        missing_log_message=(
            "Capacity model not found at %s; skipping capacity bootstrap for service mode."
        ),
        log=log,
    )
    runtime_misc_support.configure_install_worker_group(agi_cls, env)

    client = agi_cls._dask_client
    runtime_started_here = False
    owned_service_futures: Dict[str, Any] = {}
    agi_cls._service_cleanup_unproven = False
    agi_cls._service_runtime_shutdown_proven = False
    try:
        if client is None or getattr(client, "status", "") in {"closed", "closing"}:
            # This call owns the startup attempt even if _start raises after
            # constructing only part of the Dask runtime.
            runtime_started_here = True
            agi_cls._startup_in_progress = True
            try:
                await agi_cls._start(scheduler)
                client = agi_cls._dask_client
                if client is None:
                    raise RuntimeError("Failed to obtain Dask client for service start")
            finally:
                agi_cls._startup_in_progress = False
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
        recovery_info = agi_cls._recover_orphaned_service_tasks()
        cleanup_info = agi_cls._service_cleanup_artifacts()
        _prepare_service_worker_args(agi_cls, env)
        _submit_service_worker_inits(
            agi_cls,
            env,
            client,
            dask_workers,
            key_prefix="agi-worker",
        )
        owned_service_futures = _submit_service_loops(
            agi_cls,
            env,
            client,
            dask_workers,
            key_prefix="agi-serve",
            service_futures=owned_service_futures,
        )

        agi_cls._service_futures = owned_service_futures
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
                "recovery": recovery_info,
                "heartbeat_timeout_sec": agi_cls._service_heartbeat_timeout_value(),
                "worker_health": agi_cls._service_worker_health(list(dask_workers)),
            },
            health_output_path=health_output_path,
            health_only=health_only,
        )
    except BaseException:
        await _cleanup_failed_service_start(
            agi_cls,
            env,
            owned_futures=owned_service_futures,
            runtime_started_here=runtime_started_here,
            wait_fn=wait_fn,
            log=log,
        )
        # Cleanup failures are deliberately contained above; preserve the
        # original queue/startup/publication exception and traceback.
        raise


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

        filename = f"{submit_seq:06d}-{batch_id}-{worker_idx:03d}-{safe_worker}{SERVICE_TASK_SUFFIX}"
        task_path = pending_dir / filename
        tmp_path = task_path.with_suffix(task_path.suffix + ".tmp")

        payload = {
            "schema": SERVICE_TASK_SCHEMA,
            "task_id": batch_id,
            "task_name": batch_name,
            "created_at": time.time(),
            # Target tasks by worker name only: positional ids drift after
            # service_recover/restart reorders _service_workers, while the
            # worker process keeps the id frozen at init time. worker_idx=None
            # makes _task_matches_worker rely on the stable name match.
            "worker_idx": None,
            "worker": str(worker_addr),
            "plan": agi_cls._wrap_worker_chunk(
                WorkDispatcher._convert_functions_to_names(work_plan or []),
                worker_idx,
            ),
            "metadata": agi_cls._wrap_worker_chunk(work_plan_metadata or [], worker_idx),
            "args": effective_args,
        }

        with open(tmp_path, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, default=_service_task_json_default, sort_keys=True)
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
