from __future__ import annotations

import inspect
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from dask.distributed import Client

from agi_env import AgiEnv

logger = logging.getLogger(__name__)

_SERVICE_IO_EXCEPTIONS = (OSError, ValueError, TypeError, json.JSONDecodeError)
_SERVICE_FALLBACK_EXCEPTIONS = (AttributeError, OSError, RuntimeError)
_SERVICE_EXPORT_EXCEPTIONS = _SERVICE_IO_EXCEPTIONS + (RuntimeError,)


def _fallback_service_path(env: AgiEnv, relative_path: Path) -> Path:
    fallback_home = Path(getattr(env, "home_abs", Path.home()) or Path.home())
    return (fallback_home / ".agilab_service" / env.target / relative_path).resolve(strict=False)


def _resolve_service_path(
    env: AgiEnv,
    *,
    share_relative_path: Path,
    fallback_relative_path: Path,
) -> Path:
    try:
        path = Path(env.resolve_share_path(share_relative_path))
    except _SERVICE_FALLBACK_EXCEPTIONS:
        path = _fallback_service_path(env, fallback_relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def service_queue_paths(queue_root: Path) -> Dict[str, Path]:
    root = Path(queue_root)
    return {
        "root": root,
        "pending": root / "pending",
        "running": root / "running",
        "done": root / "done",
        "failed": root / "failed",
        "heartbeats": root / "heartbeats",
    }


def service_apply_queue_root(
    agi_cls: Any,
    queue_root: Union[str, Path],
    *,
    create: bool = False,
) -> Dict[str, Path]:
    queue_paths = service_queue_paths(Path(queue_root))
    if create:
        for path in queue_paths.values():
            path.mkdir(parents=True, exist_ok=True)
    agi_cls._service_queue_root = queue_paths["root"]
    agi_cls._service_queue_pending = queue_paths["pending"]
    agi_cls._service_queue_running = queue_paths["running"]
    agi_cls._service_queue_done = queue_paths["done"]
    agi_cls._service_queue_failed = queue_paths["failed"]
    agi_cls._service_queue_heartbeats = queue_paths["heartbeats"]
    return queue_paths


def service_state_path(env: AgiEnv) -> Path:
    return _resolve_service_path(
        env,
        share_relative_path=Path("service") / env.target / "service_state.json",
        fallback_relative_path=Path("service_state.json"),
    )


def service_read_state(agi_cls: Any, env: AgiEnv, *, log: Any = logger) -> Optional[Dict[str, Any]]:
    state_path = agi_cls._service_state_path(env)
    if not state_path.exists():
        return None
    try:
        with open(state_path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
        return payload if isinstance(payload, dict) else None
    except _SERVICE_IO_EXCEPTIONS as exc:
        log.warning("Failed to read service state from %s: %s", state_path, exc)
        return None


def service_write_state(agi_cls: Any, env: AgiEnv, payload: Dict[str, Any]) -> None:
    state_path = agi_cls._service_state_path(env)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_suffix(state_path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
    os.replace(tmp_path, state_path)


def service_clear_state(agi_cls: Any, env: AgiEnv, *, log: Any = logger) -> None:
    state_path = agi_cls._service_state_path(env)
    try:
        if state_path.exists():
            state_path.unlink()
    except OSError as exc:
        log.debug("Failed to remove service state file %s: %s", state_path, exc)


def service_health_path(
    env: AgiEnv,
    health_output_path: Optional[Union[str, Path]] = None,
) -> Path:
    if health_output_path:
        candidate = Path(str(health_output_path))
        if candidate.is_absolute():
            path = candidate
            path.parent.mkdir(parents=True, exist_ok=True)
            return path
        return _resolve_service_path(
            env,
            share_relative_path=candidate,
            fallback_relative_path=candidate,
        )

    return _resolve_service_path(
        env,
        share_relative_path=Path("service") / env.target / "health.json",
        fallback_relative_path=Path("health.json"),
    )


def service_health_payload(env: AgiEnv, result_payload: Dict[str, Any]) -> Dict[str, Any]:
    workers = [str(worker) for worker in (result_payload.get("workers") or []) if worker]
    pending = [str(worker) for worker in (result_payload.get("pending") or []) if worker]
    restarted = [str(worker) for worker in (result_payload.get("restarted_workers") or []) if worker]
    restart_reasons = result_payload.get("restart_reasons") or {}
    queue = result_payload.get("queue") or {}
    worker_health = result_payload.get("worker_health")
    worker_health_rows = worker_health if isinstance(worker_health, list) else []

    healthy_workers: List[str] = []
    unhealthy_workers: List[str] = []
    for row in worker_health_rows:
        if not isinstance(row, dict):
            continue
        worker_name = str(row.get("worker", "")).strip()
        if not worker_name:
            continue
        if bool(row.get("healthy", False)):
            healthy_workers.append(worker_name)
        else:
            unhealthy_workers.append(worker_name)

    health_payload: Dict[str, Any] = {
        "schema": "agi.service.health.v1",
        "timestamp": time.time(),
        "app": env.app,
        "target": env.target,
        "status": str(result_payload.get("status", "unknown") or "unknown"),
        "workers_running": workers,
        "workers_pending": pending,
        "workers_restarted": restarted,
        "workers_healthy": healthy_workers,
        "workers_unhealthy": unhealthy_workers,
        "workers_running_count": len(workers),
        "workers_pending_count": len(pending),
        "workers_restarted_count": len(restarted),
        "workers_healthy_count": len(healthy_workers),
        "workers_unhealthy_count": len(unhealthy_workers),
        "queue": queue if isinstance(queue, dict) else {},
    }

    if isinstance(restart_reasons, dict) and restart_reasons:
        health_payload["restart_reasons"] = {
            str(worker): str(reason)
            for worker, reason in restart_reasons.items()
        }
    client_status = result_payload.get("client_status")
    if client_status is not None:
        health_payload["client_status"] = str(client_status)
    heartbeat_timeout = result_payload.get("heartbeat_timeout_sec")
    if heartbeat_timeout is not None:
        try:
            health_payload["heartbeat_timeout_sec"] = float(heartbeat_timeout)
        except (TypeError, ValueError):
            pass
    queue_dir = result_payload.get("queue_dir")
    if queue_dir:
        health_payload["queue_dir"] = str(queue_dir)
    cleanup = result_payload.get("cleanup")
    if isinstance(cleanup, dict):
        health_payload["cleanup"] = cleanup
    if worker_health_rows:
        health_payload["worker_health"] = worker_health_rows

    return health_payload


def service_write_health_payload(
    agi_cls: Any,
    env: AgiEnv,
    health_payload: Dict[str, Any],
    *,
    health_output_path: Optional[Union[str, Path]] = None,
    log: Any = logger,
) -> Optional[str]:
    try:
        output_path = agi_cls._service_health_path(env, health_output_path=health_output_path)
        tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as stream:
            json.dump(health_payload, stream, indent=2)
        os.replace(tmp_path, output_path)
        return str(output_path)
    except _SERVICE_EXPORT_EXCEPTIONS as exc:
        log.warning("Failed to write service health payload: %s", exc)
        return None


def service_finalize_response(
    agi_cls: Any,
    env: AgiEnv,
    result_payload: Dict[str, Any],
    *,
    health_output_path: Optional[Union[str, Path]] = None,
    health_only: bool = False,
) -> Dict[str, Any]:
    payload = dict(result_payload)
    health_payload = agi_cls._service_health_payload(env, payload)
    health_path = agi_cls._service_write_health_payload(
        env,
        health_payload,
        health_output_path=health_output_path,
    )
    payload["health"] = health_payload
    if health_path:
        payload["health_path"] = health_path
    if health_only:
        exported = dict(health_payload)
        if health_path:
            exported["path"] = health_path
        return exported
    return payload


async def service_connected_workers(client: Client) -> List[str]:
    info = client.scheduler_info()
    if inspect.isawaitable(info):
        info = await info
    workers = (info or {}).get("workers") or {}
    return [worker.split("/")[-1] for worker in workers.keys()]


def reset_service_queue_state(agi_cls: Any) -> None:
    agi_cls._service_queue_root = None
    agi_cls._service_queue_pending = None
    agi_cls._service_queue_running = None
    agi_cls._service_queue_done = None
    agi_cls._service_queue_failed = None
    agi_cls._service_queue_heartbeats = None
    agi_cls._service_heartbeat_timeout = None
    agi_cls._service_started_at = None
    agi_cls._service_submit_counter = 0
    agi_cls._service_worker_args = {}


def init_service_queue(
    agi_cls: Any,
    env: AgiEnv,
    service_queue_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Path]:
    if service_queue_dir is not None:
        queue_root = Path(service_queue_dir).expanduser()
    elif agi_cls._workers_data_path:
        queue_root = Path(str(agi_cls._workers_data_path)).expanduser() / "service" / env.target / "queue"
    else:
        queue_root = _resolve_service_path(
            env,
            share_relative_path=Path("service") / env.target / "queue",
            fallback_relative_path=Path("queue"),
        )

    queue_paths = agi_cls._service_apply_queue_root(queue_root, create=True)

    for stale_dir in (queue_paths["pending"], queue_paths["running"]):
        for stale_task in stale_dir.glob("*.task.pkl"):
            try:
                stale_task.unlink()
            except FileNotFoundError:
                continue
    for heartbeat_file in queue_paths["heartbeats"].glob("*.json"):
        try:
            heartbeat_file.unlink()
        except FileNotFoundError:
            continue

    return queue_paths


def service_queue_counts(agi_cls: Any) -> Dict[str, int]:
    counts: Dict[str, int] = {"pending": 0, "running": 0, "done": 0, "failed": 0}
    mapping = {
        "pending": agi_cls._service_queue_pending,
        "running": agi_cls._service_queue_running,
        "done": agi_cls._service_queue_done,
        "failed": agi_cls._service_queue_failed,
    }

    for name, path in mapping.items():
        if path and path.exists():
            counts[name] = sum(1 for _ in path.glob("*.task.pkl"))
    return counts


def service_cleanup_artifacts(agi_cls: Any) -> Dict[str, int]:
    def _cleanup_dir(
        path: Optional[Path],
        *,
        pattern: str,
        ttl_sec: float,
        max_files: int,
    ) -> int:
        if path is None or not path.exists():
            return 0

        now = time.time()
        kept: List[Tuple[float, Path]] = []
        removed = 0

        for file_path in path.glob(pattern):
            try:
                mtime = file_path.stat().st_mtime
            except FileNotFoundError:
                continue

            if ttl_sec > 0 and (now - mtime) > ttl_sec:
                try:
                    file_path.unlink()
                    removed += 1
                except FileNotFoundError:
                    continue
                continue

            kept.append((mtime, file_path))

        if max_files >= 0 and len(kept) > max_files:
            kept.sort(key=lambda item: item[0], reverse=True)
            for _, stale in kept[max_files:]:
                try:
                    stale.unlink()
                    removed += 1
                except FileNotFoundError:
                    continue

        return removed

    return {
        "done": _cleanup_dir(
            agi_cls._service_queue_done,
            pattern="*.task.pkl",
            ttl_sec=max(float(agi_cls._service_cleanup_done_ttl_sec), 0.0),
            max_files=max(int(agi_cls._service_cleanup_done_max_files), 0),
        ),
        "failed": _cleanup_dir(
            agi_cls._service_queue_failed,
            pattern="*.task.pkl",
            ttl_sec=max(float(agi_cls._service_cleanup_failed_ttl_sec), 0.0),
            max_files=max(int(agi_cls._service_cleanup_failed_max_files), 0),
        ),
        "heartbeats": _cleanup_dir(
            agi_cls._service_queue_heartbeats,
            pattern="*.json",
            ttl_sec=max(float(agi_cls._service_cleanup_heartbeat_ttl_sec), 0.0),
            max_files=max(int(agi_cls._service_cleanup_heartbeat_max_files), 0),
        ),
    }


def service_public_args(args: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not args:
        return {}
    return {
        key: value
        for key, value in args.items()
        if not str(key).startswith("_agi_service_")
    }


def service_safe_worker_name(worker: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(worker)).strip("-")
    return safe or "worker"


def service_heartbeat_timeout_value(agi_cls: Any) -> float:
    if agi_cls._service_heartbeat_timeout and agi_cls._service_heartbeat_timeout > 0:
        return float(agi_cls._service_heartbeat_timeout)
    poll = agi_cls._service_poll_interval
    base = float(poll) if poll is not None else 1.0
    agi_cls._service_heartbeat_timeout = max(5.0, base * 4.0)
    return float(agi_cls._service_heartbeat_timeout)


def service_apply_runtime_config(
    agi_cls: Any,
    *,
    heartbeat_timeout: Optional[float] = None,
    cleanup_done_ttl_sec: Optional[float] = None,
    cleanup_failed_ttl_sec: Optional[float] = None,
    cleanup_heartbeat_ttl_sec: Optional[float] = None,
    cleanup_done_max_files: Optional[int] = None,
    cleanup_failed_max_files: Optional[int] = None,
    cleanup_heartbeat_max_files: Optional[int] = None,
) -> None:
    if heartbeat_timeout is not None:
        agi_cls._service_heartbeat_timeout = max(float(heartbeat_timeout), 0.1)
    if cleanup_done_ttl_sec is not None:
        agi_cls._service_cleanup_done_ttl_sec = max(float(cleanup_done_ttl_sec), 0.0)
    if cleanup_failed_ttl_sec is not None:
        agi_cls._service_cleanup_failed_ttl_sec = max(float(cleanup_failed_ttl_sec), 0.0)
    if cleanup_heartbeat_ttl_sec is not None:
        agi_cls._service_cleanup_heartbeat_ttl_sec = max(float(cleanup_heartbeat_ttl_sec), 0.0)
    if cleanup_done_max_files is not None:
        agi_cls._service_cleanup_done_max_files = max(int(cleanup_done_max_files), 0)
    if cleanup_failed_max_files is not None:
        agi_cls._service_cleanup_failed_max_files = max(int(cleanup_failed_max_files), 0)
    if cleanup_heartbeat_max_files is not None:
        agi_cls._service_cleanup_heartbeat_max_files = max(int(cleanup_heartbeat_max_files), 0)


def service_state_payload(agi_cls: Any, env: AgiEnv) -> Dict[str, Any]:
    return {
        "schema": "agi.service.state.v1",
        "target": env.target,
        "app": env.app,
        "mode": agi_cls._mode,
        "run_type": agi_cls._run_type,
        "scheduler": agi_cls._scheduler,
        "scheduler_ip": agi_cls._scheduler_ip,
        "scheduler_port": getattr(agi_cls, "_scheduler_port", None),
        "workers": agi_cls._workers,
        "service_workers": list(agi_cls._service_workers),
        "queue_dir": str(agi_cls._service_queue_root) if agi_cls._service_queue_root else None,
        "args": agi_cls._args or {},
        "poll_interval": agi_cls._service_poll_interval,
        "stop_timeout": agi_cls._service_stop_timeout,
        "shutdown_on_stop": agi_cls._service_shutdown_on_stop,
        "heartbeat_timeout": agi_cls._service_heartbeat_timeout_value(),
        "cleanup_done_ttl_sec": agi_cls._service_cleanup_done_ttl_sec,
        "cleanup_failed_ttl_sec": agi_cls._service_cleanup_failed_ttl_sec,
        "cleanup_heartbeat_ttl_sec": agi_cls._service_cleanup_heartbeat_ttl_sec,
        "cleanup_done_max_files": agi_cls._service_cleanup_done_max_files,
        "cleanup_failed_max_files": agi_cls._service_cleanup_failed_max_files,
        "cleanup_heartbeat_max_files": agi_cls._service_cleanup_heartbeat_max_files,
        "started_at": agi_cls._service_started_at or time.time(),
        "owner_pid": os.getpid(),
    }


def service_read_heartbeats(agi_cls: Any) -> Dict[str, float]:
    heartbeat_dir = agi_cls._service_queue_heartbeats
    if heartbeat_dir is None or not heartbeat_dir.exists():
        return {}

    beats: Dict[str, float] = {}
    for beat_file in heartbeat_dir.glob("*.json"):
        try:
            with open(beat_file, "r", encoding="utf-8") as stream:
                payload = json.load(stream)
            if not isinstance(payload, dict):
                continue
            worker = str(payload.get("worker", "")).strip()
            timestamp = float(payload.get("timestamp", 0.0) or 0.0)
            if not worker or timestamp <= 0:
                continue
            previous = beats.get(worker)
            beats[worker] = max(previous, timestamp) if previous else timestamp
        except _SERVICE_IO_EXCEPTIONS:
            continue
    return beats


def service_read_heartbeat_payloads(agi_cls: Any) -> Dict[str, Dict[str, Any]]:
    heartbeat_dir = agi_cls._service_queue_heartbeats
    if heartbeat_dir is None or not heartbeat_dir.exists():
        return {}

    payloads: Dict[str, Dict[str, Any]] = {}
    for beat_file in heartbeat_dir.glob("*.json"):
        try:
            with open(beat_file, "r", encoding="utf-8") as stream:
                payload = json.load(stream)
            if not isinstance(payload, dict):
                continue
            worker = str(payload.get("worker", "")).strip()
            timestamp = float(payload.get("timestamp", 0.0) or 0.0)
            if not worker or timestamp <= 0:
                continue
            previous = payloads.get(worker)
            if previous is None or float(previous.get("timestamp", 0.0) or 0.0) < timestamp:
                payloads[worker] = payload
        except _SERVICE_IO_EXCEPTIONS:
            continue
    return payloads


def service_worker_health(agi_cls: Any, workers: List[str]) -> List[Dict[str, Any]]:
    now = time.time()
    timeout = agi_cls._service_heartbeat_timeout_value()
    heartbeat_payloads = agi_cls._service_read_heartbeat_payloads()
    unhealthy = agi_cls._service_unhealthy_workers(workers)
    service_started_at = agi_cls._service_started_at or now
    warmup_done = (now - service_started_at) >= timeout

    report: List[Dict[str, Any]] = []
    for worker in workers:
        payload = heartbeat_payloads.get(worker, {})
        timestamp = float(payload.get("timestamp", 0.0) or 0.0)
        heartbeat_age = (now - timestamp) if timestamp > 0 else None
        heartbeat_state = str(payload.get("state", "missing")).strip() or "missing"
        future = agi_cls._service_futures.get(worker)
        future_state = (
            str(getattr(future, "status", "unknown")).lower()
            if future is not None
            else "detached"
        )
        reason = unhealthy.get(worker)
        if reason:
            healthy = False
        elif heartbeat_age is None:
            healthy = not warmup_done
        else:
            healthy = heartbeat_age <= timeout

        report.append(
            {
                "worker": worker,
                "future_state": future_state,
                "heartbeat_state": heartbeat_state,
                "heartbeat_age_sec": round(heartbeat_age, 3) if heartbeat_age is not None else None,
                "healthy": healthy,
                "reason": reason or "",
            }
        )

    return report


def service_unhealthy_workers(agi_cls: Any, workers: List[str]) -> Dict[str, str]:
    reasons: Dict[str, str] = {}
    if not workers:
        return reasons

    heartbeats = agi_cls._service_read_heartbeats()
    timeout = agi_cls._service_heartbeat_timeout_value()
    now = time.time()
    service_started_at = agi_cls._service_started_at or now
    warmup_done = (now - service_started_at) >= timeout

    for worker in workers:
        future = agi_cls._service_futures.get(worker)
        if future is not None:
            state = str(getattr(future, "status", "pending")).lower()
            if state in {"finished", "error", "cancelled"}:
                reasons[worker] = f"loop-{state}"
                continue

        beat_ts = heartbeats.get(worker)
        if beat_ts is None:
            if warmup_done:
                reasons[worker] = "missing-heartbeat"
            continue

        age = now - beat_ts
        if age > timeout and warmup_done:
            reasons[worker] = f"stale-heartbeat({age:.1f}s)"

    return reasons
