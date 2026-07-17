from __future__ import annotations

import inspect
import json
import logging
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union, cast

if TYPE_CHECKING:
    # Annotation-only: defer the dask.distributed import so importing AGI
    # stays cheap for non-Dask runs.
    from dask.distributed import Client

from agi_env import AgiEnv
from agi_env.runtime.atomic_write_support import run_with_windows_file_sharing_retry

logger = logging.getLogger(__name__)

_SERVICE_IO_EXCEPTIONS = (OSError, ValueError, TypeError, json.JSONDecodeError)
_SERVICE_FALLBACK_EXCEPTIONS = (AttributeError, OSError, RuntimeError)
_SERVICE_EXPORT_EXCEPTIONS = _SERVICE_IO_EXCEPTIONS + (RuntimeError,)
SERVICE_TASK_SCHEMA = "agi.service.task.v1"
SERVICE_TASK_SUFFIX = ".task.json"
LEGACY_SERVICE_TASK_SUFFIX = ".task.pkl"


class ServiceStateUnavailableError(RuntimeError):
    """Raised when persisted service ownership exists but cannot be verified."""


def _fallback_service_path(env: AgiEnv, relative_path: Path) -> Path:
    fallback_home = Path(getattr(env, "home_abs", Path.home()) or Path.home())
    return (
        fallback_home
        / ".agilab_service"
        / _service_target_name(env)
        / relative_path
    ).resolve(strict=False)


def _service_target_name(env: AgiEnv) -> str:
    return str(getattr(env, "target", "") or "")


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
        share_relative_path=Path("service") / _service_target_name(env) / "service_state.json",
        fallback_relative_path=Path("service_state.json"),
    )


def service_read_state(agi_cls: Any, env: AgiEnv, *, log: Any = logger) -> Optional[Dict[str, Any]]:
    state_path = agi_cls._service_state_path(env)

    def _read_payload() -> Any:
        with open(state_path, "r", encoding="utf-8") as stream:
            return json.load(stream)

    try:
        payload = run_with_windows_file_sharing_retry(_read_payload)
    except FileNotFoundError:
        return None
    except _SERVICE_IO_EXCEPTIONS as exc:
        log.warning("Failed to read service state from %s: %s", state_path, exc)
        raise ServiceStateUnavailableError(
            f"Persisted service state at {state_path} is unreadable"
        ) from exc
    if not isinstance(payload, dict):
        raise ServiceStateUnavailableError(
            f"Persisted service state at {state_path} is not a JSON object"
        )
    return payload


def _atomic_write(
    output_path: Path,
    write_fn: Any,
    *,
    mode: str,
    encoding: Optional[str] = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        dir=str(output_path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        open_kwargs: Dict[str, Any] = {}
        if encoding is not None:
            open_kwargs["encoding"] = encoding
        with os.fdopen(fd, mode, **open_kwargs) as stream:
            write_fn(stream)
        run_with_windows_file_sharing_retry(
            lambda: os.replace(tmp_path, output_path)
        )
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def service_write_state(agi_cls: Any, env: AgiEnv, payload: Dict[str, Any]) -> None:
    state_path = agi_cls._service_state_path(env)
    _atomic_write(
        state_path,
        lambda stream: json.dump(payload, stream, indent=2),
        mode="w",
        encoding="utf-8",
    )


def service_clear_state(agi_cls: Any, env: AgiEnv, *, log: Any = logger) -> None:
    state_path = agi_cls._service_state_path(env)

    def _unlink_state() -> None:
        state_path.unlink()

    try:
        run_with_windows_file_sharing_retry(_unlink_state)
    except FileNotFoundError:
        return
    except OSError as exc:
        log.warning("Failed to remove service state file %s: %s", state_path, exc)
        raise ServiceStateUnavailableError(
            f"Persisted service state at {state_path} could not be removed"
        ) from exc


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
        share_relative_path=Path("service") / _service_target_name(env) / "health.json",
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
        _atomic_write(
            output_path,
            lambda stream: json.dump(health_payload, stream, indent=2),
            mode="w",
            encoding="utf-8",
        )
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
    info_payload = cast(Dict[str, Any], info or {})
    workers = cast(Dict[str, Any], info_payload.get("workers") or {})
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
        queue_root = (
            Path(str(agi_cls._workers_data_path)).expanduser()
            / "service"
            / _service_target_name(env)
            / "queue"
        )
    else:
        queue_root = _resolve_service_path(
            env,
            share_relative_path=Path("service") / _service_target_name(env) / "queue",
            fallback_relative_path=Path("queue"),
        )

    queue_paths = cast(
        Dict[str, Path],
        agi_cls._service_apply_queue_root(queue_root, create=True),
    )

    # Initialization is intentionally non-destructive.  Pending tasks may
    # have been accepted by another controller, running tasks need heartbeat-
    # aware reconciliation, and heartbeats are ownership evidence.  Recovery
    # is an explicit, conservative step below.
    return queue_paths


def recover_orphaned_service_tasks(
    agi_cls: Any,
    *,
    now: Optional[float] = None,
    heartbeat_timeout: Optional[float] = None,
) -> Dict[str, int]:
    """Move only expired running claims to failed evidence.

    A missing heartbeat alone is not sufficient: a new worker can claim a task
    just before its next beat.  The running file must also be older than the
    configured timeout.  For an old claim, a heartbeat preserves it only when
    its worker-incarnation token matches the claim; a replacement worker using
    the same scheduler name cannot adopt stale work.  Pending tasks and fresh
    claims are always preserved. Legacy pickle claims are moved as opaque
    failed artifacts and are never deserialized.
    """

    running_dir = agi_cls._service_queue_running
    failed_dir = agi_cls._service_queue_failed
    if running_dir is None or failed_dir is None or not running_dir.exists():
        return {"recovered": 0, "preserved": 0}

    current_time = time.time() if now is None else float(now)
    timeout = (
        float(heartbeat_timeout)
        if heartbeat_timeout is not None
        else float(agi_cls._service_heartbeat_timeout_value())
    )
    timeout = max(timeout, 0.1)
    heartbeat_payloads = agi_cls._service_read_heartbeat_payloads()
    failed_dir.mkdir(parents=True, exist_ok=True)
    recovered = 0
    preserved = 0

    # A previous controller can crash after atomically renaming a running task
    # to its hidden recovery claim. Reconcile those claims before scanning the
    # canonical names: finish an already-published terminal move, or restore an
    # uncontested claim so normal age/incarnation checks decide its fate.
    hidden_claim_pattern = re.compile(
        rf"^\.(?P<name>.+{re.escape(SERVICE_TASK_SUFFIX)})\.recovery-[^.]+\.tmp$"
    )
    done_dir = getattr(agi_cls, "_service_queue_done", None)
    for hidden_claim in sorted(
        running_dir.glob(".*.recovery-*.tmp"),
        key=lambda candidate: candidate.name,
    ):
        match = hidden_claim_pattern.match(hidden_claim.name)
        if match is None:
            continue
        canonical = running_dir / match.group("name")
        if canonical.exists():
            # Never overwrite competing evidence. A later recovery pass can
            # reconcile this claim after the canonical owner reaches terminal
            # state.
            preserved += 1
            continue
        try:
            os.replace(hidden_claim, canonical)
        except FileNotFoundError:
            continue

    def _heartbeat_is_live_for_claim(
        task_payload: Dict[str, Any],
        heartbeat_payload: Dict[str, Any],
    ) -> tuple[bool, Optional[float]]:
        try:
            heartbeat_age_value = current_time - float(heartbeat_payload.get("timestamp"))
        except (TypeError, ValueError):
            heartbeat_age_value = None
        heartbeat_state_value = str(heartbeat_payload.get("state", "") or "").lower()
        claim = task_payload.get("claim")
        claim_payload = claim if isinstance(claim, dict) else {}
        claim_incarnation = str(claim_payload.get("worker_incarnation", "") or "")
        heartbeat_incarnation = str(
            heartbeat_payload.get("worker_incarnation", "") or ""
        )
        heartbeat_live_value = (
            heartbeat_age_value is not None
            and heartbeat_age_value <= timeout
            and heartbeat_state_value not in {"stopped", "failed"}
            and bool(claim_incarnation)
            and claim_incarnation == heartbeat_incarnation
        )
        return heartbeat_live_value, heartbeat_age_value

    def _terminal_task_filename(task_payload: Dict[str, Any], fallback: str) -> str:
        claim = task_payload.get("claim")
        claim_payload = claim if isinstance(claim, dict) else {}
        candidate = str(claim_payload.get("task_filename", "") or "")
        if (
            candidate
            and Path(candidate).name == candidate
            and candidate.endswith(SERVICE_TASK_SUFFIX)
        ):
            return candidate
        return fallback

    def _terminal_matches_claim(
        terminal_path: Path,
        task_payload: Dict[str, Any],
        *,
        expected_status: str,
    ) -> bool:
        try:
            terminal_payload = json.loads(terminal_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return False
        if not isinstance(terminal_payload, dict):
            return False
        if terminal_payload.get("schema") != SERVICE_TASK_SCHEMA:
            return False
        if str(terminal_payload.get("status", "") or "") != expected_status:
            return False

        task_claim = task_payload.get("claim")
        terminal_claim = terminal_payload.get("claim")
        task_claim_payload = task_claim if isinstance(task_claim, dict) else {}
        terminal_claim_payload = terminal_claim if isinstance(terminal_claim, dict) else {}
        task_incarnation = str(
            task_claim_payload.get("worker_incarnation", "") or ""
        )
        terminal_incarnation = str(
            terminal_claim_payload.get("worker_incarnation", "") or ""
        )
        task_id = str(task_payload.get("task_id", "") or "")
        terminal_task_id = str(terminal_payload.get("task_id", "") or "")
        task_worker = str(task_payload.get("worker", "") or "")
        terminal_worker = str(terminal_payload.get("worker", "") or "")

        # A filename alone is not enough to discard evidence: require at least
        # one durable task identity and require every available identity to
        # match the already-published terminal payload.
        if not task_incarnation and not task_id:
            return False
        if task_incarnation and task_incarnation != terminal_incarnation:
            return False
        if task_id and task_id != terminal_task_id:
            return False
        if task_worker and task_worker != terminal_worker:
            return False
        return True

    for running_path in sorted(
        running_dir.glob(f"*{SERVICE_TASK_SUFFIX}"),
        key=lambda candidate: candidate.name,
    ):
        try:
            mtime = running_path.stat().st_mtime
            payload = json.loads(running_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue

        terminal_filename = _terminal_task_filename(payload, running_path.name)
        terminal_candidates = (
            (
                done_dir / terminal_filename if done_dir is not None else None,
                "done",
            ),
            (failed_dir / terminal_filename, "failed"),
        )
        terminal_duplicate = False
        for terminal_path, expected_status in terminal_candidates:
            if terminal_path is None or not _terminal_matches_claim(
                terminal_path,
                payload,
                expected_status=expected_status,
            ):
                continue
            try:
                running_path.unlink()
            except FileNotFoundError:
                pass
            else:
                recovered += 1
            terminal_duplicate = True
            break
        if terminal_duplicate:
            continue

        task_age = max(0.0, current_time - float(mtime))
        worker = str(payload.get("worker", "") or "")
        heartbeat = heartbeat_payloads.get(worker, {})
        heartbeat_live, heartbeat_age = _heartbeat_is_live_for_claim(payload, heartbeat)
        if task_age <= timeout or heartbeat_live:
            preserved += 1
            continue

        recovery_claim = running_dir / (
            f".{running_path.name}.recovery-{uuid.uuid4().hex}.tmp"
        )
        try:
            os.replace(running_path, recovery_claim)
        except FileNotFoundError:
            # The worker completed or another recovery owner claimed it.
            continue

        # A heartbeat can race the directory scan. Re-read it after atomically
        # claiming the task, and restore the claim if the worker is live.
        latest_heartbeat = agi_cls._service_read_heartbeat_payloads().get(worker, {})
        latest_live, _ = _heartbeat_is_live_for_claim(payload, latest_heartbeat)
        if latest_live:
            try:
                os.replace(recovery_claim, running_path)
            except FileNotFoundError:
                pass
            preserved += 1
            continue

        payload.update(
            {
                "status": "failed",
                "finished_at": current_time,
                "error": "orphaned service task recovered after worker heartbeat expired",
                "recovery": {
                    "reason": "expired-worker-heartbeat",
                    "task_age_sec": round(task_age, 3),
                    "heartbeat_age_sec": (
                        round(heartbeat_age, 3) if heartbeat_age is not None else None
                    ),
                },
            }
        )
        terminal_filename = _terminal_task_filename(payload, running_path.name)
        failed_path = failed_dir / terminal_filename
        if failed_path.exists():
            base_name = terminal_filename[: -len(SERVICE_TASK_SUFFIX)]
            failed_path = failed_dir / (
                f"{base_name}.orphaned-{uuid.uuid4().hex[:8]}{SERVICE_TASK_SUFFIX}"
            )
        try:
            _atomic_write(
                failed_path,
                lambda stream, data=payload: json.dump(data, stream, sort_keys=True),
                mode="w",
                encoding="utf-8",
            )
        except BaseException:
            # Never strand the only task evidence under a hidden claim name.
            try:
                os.replace(recovery_claim, running_path)
            except FileNotFoundError:
                pass
            raise
        try:
            recovery_claim.unlink()
        except FileNotFoundError:
            pass
        recovered += 1

    for legacy_path in sorted(
        running_dir.glob(f"*{LEGACY_SERVICE_TASK_SUFFIX}"),
        key=lambda candidate: candidate.name,
    ):
        try:
            if current_time - legacy_path.stat().st_mtime <= timeout:
                preserved += 1
                continue
            destination = failed_dir / legacy_path.name
            if destination.exists():
                base_name = legacy_path.name[: -len(LEGACY_SERVICE_TASK_SUFFIX)]
                destination = failed_dir / (
                    f"{base_name}.orphaned-{uuid.uuid4().hex[:8]}{LEGACY_SERVICE_TASK_SUFFIX}"
                )
            os.replace(legacy_path, destination)
            recovered += 1
        except FileNotFoundError:
            continue

    return {"recovered": recovered, "preserved": preserved}


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
            counts[name] = sum(
                1
                for pattern in (f"*{SERVICE_TASK_SUFFIX}", f"*{LEGACY_SERVICE_TASK_SUFFIX}")
                for _ in path.glob(pattern)
            )
    return counts


def service_cleanup_artifacts(agi_cls: Any) -> Dict[str, int]:
    def _cleanup_dir(
        path: Optional[Path],
        *,
        pattern: str | tuple[str, ...],
        ttl_sec: float,
        max_files: int,
    ) -> int:
        if path is None or not path.exists():
            return 0

        now = time.time()
        kept: List[Tuple[float, Path]] = []
        removed = 0

        patterns = (pattern,) if isinstance(pattern, str) else tuple(pattern)
        for file_path in sorted(
            (
                candidate
                for item_pattern in patterns
                for candidate in path.glob(item_pattern)
            ),
            key=lambda candidate: candidate.name,
        ):
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
            pattern=(f"*{SERVICE_TASK_SUFFIX}", f"*{LEGACY_SERVICE_TASK_SUFFIX}"),
            ttl_sec=max(float(agi_cls._service_cleanup_done_ttl_sec), 0.0),
            max_files=max(int(agi_cls._service_cleanup_done_max_files), 0),
        ),
        "failed": _cleanup_dir(
            agi_cls._service_queue_failed,
            pattern=(f"*{SERVICE_TASK_SUFFIX}", f"*{LEGACY_SERVICE_TASK_SUFFIX}"),
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
    service_loop_keys = {
        worker: str(key)
        for worker, future in agi_cls._service_futures.items()
        if (key := getattr(future, "key", None)) not in (None, "")
    }
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
        "service_loop_keys": service_loop_keys,
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
    for beat_file in sorted(heartbeat_dir.glob("*.json"), key=lambda candidate: candidate.name):
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
    for beat_file in sorted(heartbeat_dir.glob("*.json"), key=lambda candidate: candidate.name):
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
