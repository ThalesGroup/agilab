from __future__ import annotations

import json
import os
import re
import time
import traceback
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable

SERVICE_TASK_SCHEMA = "agi.service.task.v1"
SERVICE_TASK_SUFFIX = ".task.json"
LEGACY_SERVICE_TASK_SUFFIX = ".task.pkl"


def resolve_service_queue_root(
    worker_args: Any,
    *,
    path_cls: type[Path] = Path,
) -> Path | None:
    if worker_args is None:
        return None

    service_queue_dir = getattr(worker_args, "_agi_service_queue_dir", None)
    if service_queue_dir is None and hasattr(worker_args, "get"):
        service_queue_dir = worker_args.get("_agi_service_queue_dir")
    if not service_queue_dir:
        return None

    return path_cls(str(service_queue_dir)).expanduser().resolve(strict=False)


def make_heartbeat_writer(
    queue_root: Path,
    *,
    worker_id: int,
    worker_name: str | None,
    logger_obj: Any,
    path_cls: type[Path] = Path,
    open_fn: Callable[..., Any] = open,
    json_module: Any = json,
    os_module: Any = os,
    time_module: Any = time,
    pid_factory: Callable[[], int] = os.getpid,
) -> Callable[[str], None]:
    heartbeat_dir = queue_root / "heartbeats"
    heartbeat_dir.mkdir(parents=True, exist_ok=True)
    safe_worker = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(worker_name or worker_id)).strip("-")
    heartbeat_file = heartbeat_dir / f"{worker_id:03d}-{safe_worker or 'worker'}.json"

    def _write_heartbeat(state: str) -> None:
        payload = {
            "worker_id": worker_id,
            "worker": str(worker_name),
            "pid": pid_factory(),
            "timestamp": time_module.time(),
            "state": state,
        }
        tmp = heartbeat_file.with_suffix(heartbeat_file.suffix + ".tmp")
        try:
            with open_fn(tmp, "w", encoding="utf-8") as stream:
                json_module.dump(payload, stream)
            os_module.replace(tmp, heartbeat_file)
        except OSError:
            with suppress(FileNotFoundError):
                tmp.unlink()
            logger_obj.debug(
                "worker #%s: failed to write service heartbeat",
                worker_id,
                exc_info=True,
            )

    return _write_heartbeat


def _ensure_service_queue_dirs(
    queue_root: Path,
    *,
    path_cls: type[Path] = Path,
) -> dict[str, Path]:
    queue_dirs = {
        "pending": queue_root / "pending",
        "running": queue_root / "running",
        "done": queue_root / "done",
        "failed": queue_root / "failed",
        "heartbeats": queue_root / "heartbeats",
    }
    for path in queue_dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return queue_dirs


def _dump_service_payload(
    path: Path,
    payload: dict[str, Any],
    *,
    open_fn: Callable[..., Any] = open,
    json_module: Any = json,
    pickle_module: Any | None = None,
    os_module: Any = os,
) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload.setdefault("schema", SERVICE_TASK_SCHEMA)
    with open_fn(tmp, "w", encoding="utf-8") as stream:
        json_module.dump(payload, stream, sort_keys=True)
    os_module.replace(tmp, path)


def _load_service_payload(
    path: Path,
    *,
    open_fn: Callable[..., Any] = open,
    json_module: Any = json,
) -> dict[str, Any]:
    with open_fn(path, "r", encoding="utf-8") as stream:
        payload = json_module.load(stream)
    if not isinstance(payload, dict):
        raise ValueError("service task payload must be a JSON object")
    if payload.get("schema") != SERVICE_TASK_SCHEMA:
        raise ValueError(f"unsupported service task schema: {payload.get('schema')!r}")
    return payload


def _reject_legacy_service_task(
    pending_path: Path,
    *,
    failed_dir: Path,
    worker_id: int,
    logger_obj: Any,
) -> None:
    logger_obj.error(
        "worker #%s: rejecting legacy pickle service task %s; service tasks must use %s",
        worker_id,
        pending_path,
        SERVICE_TASK_SUFFIX,
    )
    failed_path = failed_dir / pending_path.name
    with suppress(FileNotFoundError):
        pending_path.replace(failed_path)


def _task_matches_worker(
    payload: dict[str, Any],
    *,
    worker_id: int,
    worker_name: str | None,
) -> bool:
    target_idx = payload.get("worker_idx")
    target_worker = str(payload.get("worker", "") or "").strip()
    if target_idx is not None and target_idx != worker_id:
        return False
    if target_worker and target_worker != str(worker_name):
        return False
    return True


def run_service_queue(
    *,
    stop_event: Any,
    queue_root: Path,
    worker_id: int,
    worker_name: str | None,
    poll: float,
    do_works_fn: Callable[[Any, Any], Any],
    write_heartbeat: Callable[[str], None],
    logger_obj: Any,
    path_cls: type[Path] = Path,
    open_fn: Callable[..., Any] = open,
    json_module: Any = json,
    pickle_module: Any | None = None,
    os_module: Any = os,
    time_module: Any = time,
    traceback_module: Any = traceback,
) -> dict[str, Any]:
    queue_dirs = _ensure_service_queue_dirs(queue_root, path_cls=path_cls)
    processed = 0
    failures = 0
    idle_wait = poll if poll > 0 else 0.05
    json_decode_error = getattr(json_module, "JSONDecodeError", ValueError)
    read_errors = (
        OSError,
        ValueError,
        TypeError,
        json_decode_error,
    )

    write_heartbeat("running")
    while not stop_event.is_set():
        write_heartbeat("running")
        claimed = False
        for legacy_path in sorted(queue_dirs["pending"].glob(f"*{LEGACY_SERVICE_TASK_SUFFIX}")):
            _reject_legacy_service_task(
                legacy_path,
                failed_dir=queue_dirs["failed"],
                worker_id=worker_id,
                logger_obj=logger_obj,
            )

        for pending_path in sorted(queue_dirs["pending"].glob(f"*{SERVICE_TASK_SUFFIX}")):
            try:
                payload = _load_service_payload(
                    pending_path,
                    open_fn=open_fn,
                    json_module=json_module,
                )
            except FileNotFoundError:
                continue
            except read_errors as exc:
                logger_obj.error(
                    "worker #%s: cannot read service task %s: %s",
                    worker_id,
                    pending_path,
                    exc,
                )
                failed_path = queue_dirs["failed"] / pending_path.name
                with suppress(FileNotFoundError):
                    pending_path.replace(failed_path)
                continue

            if not _task_matches_worker(
                payload,
                worker_id=worker_id,
                worker_name=worker_name,
            ):
                continue

            running_path = queue_dirs["running"] / pending_path.name
            try:
                pending_path.replace(running_path)
            except FileNotFoundError:
                continue

            claimed = True
            task_start = time_module.time()
            try:
                write_heartbeat("processing")
                logs = do_works_fn(
                    payload.get("plan", []),
                    payload.get("metadata", []),
                )
                payload["status"] = "done"
                payload["finished_at"] = time_module.time()
                payload["runtime"] = time_module.time() - task_start
                payload["worker_id"] = worker_id
                payload["worker_name"] = worker_name
                payload["logs"] = logs
                _dump_service_payload(
                    queue_dirs["done"] / pending_path.name,
                    payload,
                    open_fn=open_fn,
                    json_module=json_module,
                    pickle_module=pickle_module,
                    os_module=os_module,
                )
                processed += 1
            # Worker code can fail arbitrarily; persist the failure and keep the queue alive.
            except Exception as exc:
                payload["status"] = "failed"
                payload["finished_at"] = time_module.time()
                payload["runtime"] = time_module.time() - task_start
                payload["worker_id"] = worker_id
                payload["worker_name"] = worker_name
                payload["error"] = str(exc)
                payload["traceback"] = traceback_module.format_exc()
                _dump_service_payload(
                    queue_dirs["failed"] / pending_path.name,
                    payload,
                    open_fn=open_fn,
                    json_module=json_module,
                    pickle_module=pickle_module,
                    os_module=os_module,
                )
                failures += 1
                logger_obj.exception(
                    "worker #%s: service task failed (%s)",
                    worker_id,
                    pending_path.name,
                )
            finally:
                write_heartbeat("running")
                with suppress(FileNotFoundError):
                    running_path.unlink()
            break

        if not claimed:
            stop_event.wait(idle_wait)

    write_heartbeat("stopped")
    return {
        "status": "stopped",
        "processed": processed,
        "failed": failures,
    }


__all__ = [
    "make_heartbeat_writer",
    "resolve_service_queue_root",
    "run_service_queue",
]
