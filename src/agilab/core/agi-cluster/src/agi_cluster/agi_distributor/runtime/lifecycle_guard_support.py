"""Fail-fast lifecycle serialization and shared-runtime deployment leases.

``AGI`` still exposes a class-based compatibility API whose mutable fields are
shared by every caller in the interpreter.  Worker targets under one runtime
parent also share scheduler and remote-worker PID files.  This module makes
that boundary explicit: one lifecycle operation may mutate the class at a
time, and one process may own that shared runtime parent at a time.  The
in-process guard uses a plain thread lock rather than an asyncio primitive so
it remains safe across event loops and worker threads.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import socket
import threading
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil


LEASE_SCHEMA = "agilab-target-operation-lease-v1"
_PROCESS_START_TOLERANCE_SECONDS = 1.0
_STATE_LOCK_CREATION_LOCK = threading.Lock()


class LifecycleBusyError(RuntimeError):
    """Raised when another lifecycle call owns shared AGI runtime state."""


def _process_start_time(
    pid: int,
    *,
    process_factory: Any = psutil.Process,
) -> float | None:
    try:
        return float(process_factory(pid).create_time())
    except (psutil.Error, OSError, TypeError, ValueError):
        return None


def _owner_is_live(
    payload: dict[str, Any],
    *,
    process_factory: Any = psutil.Process,
) -> bool:
    owner_host = str(payload.get("hostname") or "")
    if owner_host and owner_host != socket.gethostname():
        # A shared filesystem can expose a lease created on another host.
        # Local PID inspection says nothing about that remote owner, so fail
        # closed and require explicit operator recovery.
        return True
    try:
        pid = int(payload.get("pid"))
    except (TypeError, ValueError):
        # Corrupt or partially readable ownership is not evidence of staleness.
        return True
    if pid <= 0:
        return True

    try:
        process = process_factory(pid)
    except psutil.NoSuchProcess:
        return False
    except (psutil.Error, OSError):
        # AccessDenied and transient process-table failures cannot prove the
        # owner is gone. Fail closed so a live deployment is never reclaimed.
        return True

    try:
        if not process.is_running():
            return False
    except psutil.NoSuchProcess:
        return False
    except (psutil.Error, OSError):
        return True

    expected_start = payload.get("process_start_time")
    if expected_start in (None, ""):
        return True
    try:
        expected_start_value = float(expected_start)
    except (TypeError, ValueError):
        return True
    try:
        actual_start = float(process.create_time())
    except psutil.NoSuchProcess:
        return False
    except (psutil.Error, OSError, TypeError, ValueError):
        return True
    return (
        abs(actual_start - expected_start_value)
        <= _PROCESS_START_TOLERANCE_SECONDS
    )


def _target_path(env: Any) -> Path:
    raw_path = getattr(env, "wenv_abs", None)
    if raw_path in (None, ""):
        # Lightweight test doubles and compatibility callers may not expose a
        # worker path.  They still receive in-process serialization, with a
        # stable temp-root lease keyed by their declared target/identity.
        identity = str(
            getattr(env, "target", None)
            or getattr(env, "app", None)
            or f"object-{id(env)}"
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        return Path(tempfile.gettempdir()) / "agilab-operation-targets" / digest
    return Path(raw_path).expanduser().resolve(strict=False)


def _normalized_target_key(
    target: Path,
    *,
    normcase_fn: Any = os.path.normcase,
) -> str:
    """Return a filesystem-identity key (including Windows case folding)."""

    normalized = os.path.normpath(str(target.expanduser().resolve(strict=False)))
    return str(normcase_fn(normalized)).replace("\\", "/")


def target_lease_path(env: Any) -> Path:
    """Return the stable lease for all targets sharing one runtime parent.

    Scheduler and remote-worker PID files live beside target environments, so
    a target-specific lease would let cleanup for one target unlink or stop a
    sibling target's live runtime.
    """

    target = _target_path(env)
    parent_key = _normalized_target_key(target.parent)
    digest = hashlib.sha256(parent_key.encode("utf-8")).hexdigest()[:16]
    return target.parent / ".agilab-operation-leases" / f"runtime-{digest}.lock"


def _read_owner(lock_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads((lock_path / "owner.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _busy_message(operation: str, target: Path, owner: dict[str, Any]) -> str:
    owner_operation = str(owner.get("operation") or "unknown")
    owner_pid = owner.get("pid", "unknown")
    owner_host = str(owner.get("hostname") or "unknown")
    return (
        f"Cannot start AGI {operation!r} for {target}: lifecycle operation "
        f"{owner_operation!r} is already active (pid={owner_pid}, host={owner_host}). "
        "Wait for it to finish or stop the active AGI service before retrying."
    )


@dataclass(frozen=True)
class TargetLease:
    path: Path
    token: str
    operation: str
    target: Path
    remote_token: str
    recovered_remote_tokens: tuple[str, ...]


def _valid_lease_token(value: Any) -> bool:
    token = str(value or "")
    if len(token) != 32:
        return False
    try:
        int(token, 16)
    except ValueError:
        return False
    return True


def _owner_remote_tokens(owner: dict[str, Any]) -> tuple[str, ...]:
    """Return capabilities belonging to one identity-proven stale owner."""

    candidates = [owner.get("remote_token")]
    inherited = owner.get("recovered_remote_tokens", ())
    if isinstance(inherited, list):
        candidates.extend(inherited)
    tokens: list[str] = []
    for candidate in candidates:
        token = str(candidate or "")
        if _valid_lease_token(token) and token not in tokens:
            tokens.append(token)
    return tuple(tokens)


def _target_release_tombstone(lock_path: Path, token: str) -> Path:
    return lock_path.with_name(f".{lock_path.name}.released-{token}")


def _target_generation_owned(lock_path: Path, token: str) -> bool:
    owner = _read_owner(lock_path)
    return (
        lock_path.exists()
        and owner.get("schema") == LEASE_SCHEMA
        and str(owner.get("token") or "") == token
    )


def _target_generation_released(lock_path: Path, token: str) -> bool:
    """Return true only when absence or a valid successor proves release."""

    if not lock_path.exists():
        return True
    owner = _read_owner(lock_path)
    owner_token = str(owner.get("token") or "")
    return (
        owner.get("schema") == LEASE_SCHEMA
        and _valid_lease_token(owner_token)
        and owner_token != token
    )


def _discard_target_claim(claim: Path) -> None:
    try:
        claim.rmdir()
    except OSError:
        pass


def _retire_claimed_target_generation(
    lock_path: Path,
    token: str,
    claim: Path,
) -> bool:
    """Move one exact claimed generation behind a durable no-replace fence."""

    if not _target_generation_owned(lock_path, token):
        released = _target_generation_released(lock_path, token)
        if released:
            _discard_target_claim(claim)
        return released

    tombstone = _target_release_tombstone(lock_path, token)
    if tombstone.exists():
        if not _target_generation_owned(tombstone, token):
            return False
        # Another resumer already retired this token. Re-read the public path:
        # the old generation may have disappeared or a successor may now own it.
        released = _target_generation_released(lock_path, token)
        if released:
            _discard_target_claim(claim)
        return released

    try:
        lock_path.rename(tombstone)
    except OSError:
        # The deterministic destination retains the old non-empty owner
        # generation. Therefore an arbitrarily delayed rename cannot replace a
        # successor: it fails against the existing tombstone and lands here.
        if tombstone.exists() and not _target_generation_owned(tombstone, token):
            return False
        released = _target_generation_released(lock_path, token)
        if released:
            _discard_target_claim(claim)
        return released

    # Keep the non-empty deterministic tombstone indefinitely. It is the
    # generation fence that makes delayed release/recovery safe for successors.
    _discard_target_claim(claim)
    _fsync_directory(lock_path.parent)
    return True


def _remove_stale_lock(lock_path: Path, observed_token: str) -> bool:
    """Reclaim only the exact lease generation previously observed as stale.

    Moving the observed token marker out of the lock directory is the CAS.
    A delayed reclaimer cannot claim a replacement generation because its
    marker has a different token. Competing resumers share the exact claim;
    the retained deterministic tombstone fences their delayed directory moves.
    """

    if len(observed_token) != 32:
        return False
    try:
        int(observed_token, 16)
    except ValueError:
        return False

    marker = lock_path / f"token-{observed_token}"
    claim = lock_path.parent / (
        f".{lock_path.name}.reclaim-{observed_token}-{uuid.uuid4().hex}"
    )
    try:
        marker.rename(claim)
    except FileNotFoundError:
        # A prior releaser/reclaimer may have crashed after moving the token
        # marker but before moving the generation directory. Resume only a
        # claim for this exact observed token and owner generation.
        claim_candidates = sorted(
            [
                *lock_path.parent.glob(
                    f".{lock_path.name}.reclaim-{observed_token}-*"
                ),
                lock_path.parent / f".release-{observed_token}",
            ],
            key=lambda path: path.name,
        )
        resumed_claim = next(
            (candidate for candidate in claim_candidates if candidate.is_dir()),
            None,
        )
        if resumed_claim is None:
            tombstone = _target_release_tombstone(lock_path, observed_token)
            return (
                _target_generation_owned(tombstone, observed_token)
                and _target_generation_released(lock_path, observed_token)
            )
        claim = resumed_claim
    except OSError:
        return False

    return _retire_claimed_target_generation(lock_path, observed_token, claim)


def acquire_target_lease(
    env: Any,
    operation: str,
    *,
    remote_token: str | None = None,
    process_factory: Any = psutil.Process,
    getpid_fn: Any = os.getpid,
    time_fn: Any = time.time,
) -> TargetLease:
    """Atomically claim one shared worker-runtime parent or fail closed."""

    target = _target_path(env)
    lock_path = target_lease_path(env)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    requested_remote_token = str(remote_token or "")
    if remote_token is not None and not _valid_lease_token(requested_remote_token):
        raise ValueError("Remote lifecycle token must be exactly 32 hexadecimal characters")
    recovered_remote_tokens: list[str] = []

    def _reclaim_observed_owner() -> None:
        owner = _read_owner(lock_path)
        if not owner and not lock_path.exists():
            return
        if _owner_is_live(owner, process_factory=process_factory):
            raise LifecycleBusyError(_busy_message(operation, target, owner))
        observed_token = str(owner.get("token") or "")
        # Whether this succeeds or loses the CAS, retry from a fresh owner
        # observation. The next iteration will either acquire the empty path or
        # report the replacement live owner without touching its generation.
        if _remove_stale_lock(lock_path, observed_token):
            for token in _owner_remote_tokens(owner):
                if token not in recovered_remote_tokens:
                    recovered_remote_tokens.append(token)

    for _attempt in range(3):
        token = uuid.uuid4().hex
        effective_remote_token = requested_remote_token or token
        staging = lock_path.with_name(
            f".{lock_path.name}.claim-{getpid_fn()}-{token}"
        )
        marker_name = f"token-{token}"
        staging.mkdir()
        (staging / marker_name).mkdir()
        pid = int(getpid_fn())
        payload = {
            "schema": LEASE_SCHEMA,
            "token": token,
            "pid": pid,
            "process_start_time": _process_start_time(
                pid,
                process_factory=process_factory,
            ),
            "hostname": socket.gethostname(),
            "operation": str(operation),
            "target": target.as_posix(),
            # The worker-side lifecycle lease uses a separate generation. Keep
            # its capability beside the manager PID incarnation so only an
            # identity-proven stale local owner can authorize remote recovery.
            "remote_token": effective_remote_token,
            "recovered_remote_tokens": list(recovered_remote_tokens),
            "created_at": float(time_fn()),
        }
        with (staging / "owner.json").open("x", encoding="utf-8") as owner_file:
            owner_file.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            owner_file.flush()
            os.fsync(owner_file.fileno())
        _fsync_directory(staging)
        try:
            staging.rename(lock_path)
        except FileExistsError:
            shutil.rmtree(staging, ignore_errors=True)
            _reclaim_observed_owner()
            continue
        except OSError:
            shutil.rmtree(staging, ignore_errors=True)
            if lock_path.exists():
                _reclaim_observed_owner()
                continue
            raise
        _fsync_directory(lock_path.parent)
        return TargetLease(
            path=lock_path,
            token=token,
            operation=str(operation),
            target=target,
            remote_token=effective_remote_token,
            recovered_remote_tokens=tuple(recovered_remote_tokens),
        )

    owner = _read_owner(lock_path)
    raise LifecycleBusyError(_busy_message(operation, target, owner))


def _target_lease_still_owned(lease: TargetLease) -> bool:
    return _target_generation_owned(lease.path, lease.token)


def release_target_lease(lease: TargetLease) -> bool:
    """Release only this generation and report whether ownership is gone."""

    marker = lease.path / f"token-{lease.token}"
    claim = lease.path.parent / f".release-{lease.token}"
    try:
        marker.rename(claim)
    except FileNotFoundError:
        if not claim.is_dir():
            return _target_generation_released(lease.path, lease.token)
    except OSError:
        return False

    return _retire_claimed_target_generation(lease.path, lease.token, claim)


def _caller_identity() -> tuple[int, int | None]:
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return threading.get_ident(), id(task) if task is not None else None


def _state_lock(agi_cls: Any) -> threading.Lock:
    lock = getattr(agi_cls, "_lifecycle_state_lock", None)
    if lock is None:
        # First use can itself be concurrent.  Serialize creation so no caller
        # ever enters lifecycle state under a private, losing lock instance.
        with _STATE_LOCK_CREATION_LOCK:
            lock = getattr(agi_cls, "_lifecycle_state_lock", None)
            if lock is None:
                lock = threading.Lock()
                setattr(agi_cls, "_lifecycle_state_lock", lock)
    return lock


@dataclass
class LifecycleOperation:
    agi_cls: Any
    env: Any
    operation: str
    service_command: bool = False
    token: str | None = None
    owner: tuple[int, int | None] | None = None
    lease: TargetLease | None = None
    target: Path | None = None
    reentrant: bool = False
    reused_service: bool = False
    _retain_service: bool = False
    _retain_service_on_error: bool = False
    _release_service: bool = False

    def _clear_call_state(self) -> None:
        if getattr(self.agi_cls, "_lifecycle_call_token", None) != self.token:
            return
        setattr(self.agi_cls, "_lifecycle_call_token", None)
        setattr(self.agi_cls, "_lifecycle_call_owner", None)
        setattr(self.agi_cls, "_lifecycle_call_target", None)
        setattr(self.agi_cls, "_lifecycle_call_operation", None)
        setattr(self.agi_cls, "_lifecycle_call_depth", 0)
        setattr(self.agi_cls, "_lifecycle_remote_token", None)
        setattr(self.agi_cls, "_lifecycle_remote_recovery_tokens", ())

    async def _finish_pending_release(self) -> None:
        """Prove a prior remote release before allowing a new lifecycle call."""

        lock = _state_lock(self.agi_cls)
        with lock:
            pending = getattr(
                self.agi_cls,
                "_lifecycle_pending_release_lease",
                None,
            )
            if pending is None:
                return
            if not isinstance(pending, TargetLease):
                raise LifecycleBusyError(
                    "Cannot start a new AGI lifecycle operation: pending remote "
                    "lease evidence is invalid"
                )
            active_token = getattr(self.agi_cls, "_lifecycle_call_token", None)
            if active_token is not None:
                raise LifecycleBusyError(
                    "Cannot start a new AGI lifecycle operation while a prior "
                    "remote lease release is still active"
                )
            setattr(self.agi_cls, "_lifecycle_call_token", self.token)
            setattr(self.agi_cls, "_lifecycle_call_owner", self.owner)
            setattr(self.agi_cls, "_lifecycle_call_target", pending.target)
            setattr(
                self.agi_cls,
                "_lifecycle_call_operation",
                f"release-pending:{pending.operation}",
            )
            setattr(self.agi_cls, "_lifecycle_call_depth", 1)
            setattr(self.agi_cls, "_lifecycle_remote_token", pending.remote_token)
            setattr(
                self.agi_cls,
                "_lifecycle_remote_recovery_tokens",
                pending.recovered_remote_tokens,
            )

        release_remote_leases = getattr(
            self.agi_cls,
            "_release_remote_target_leases",
            None,
        )
        try:
            if not callable(release_remote_leases):
                raise RuntimeError("remote lease release callback is unavailable")
            await release_remote_leases()
        except BaseException as exc:
            with lock:
                self._clear_call_state()
            if not isinstance(exc, Exception):
                raise
            raise LifecycleBusyError(
                "Cannot start a new AGI lifecycle operation: the prior remote "
                "target lease release is still unproven"
            ) from exc

        if not release_target_lease(pending):
            with lock:
                self._clear_call_state()
            raise LifecycleBusyError(
                "Cannot start a new AGI lifecycle operation: the prior local "
                "target lease release is still unproven"
            )
        with lock:
            if (
                getattr(self.agi_cls, "_lifecycle_pending_release_lease", None)
                == pending
            ):
                setattr(self.agi_cls, "_lifecycle_pending_release_lease", None)
            self._clear_call_state()

    async def __aenter__(self) -> "LifecycleOperation":
        self.target = _target_path(self.env)
        self.owner = _caller_identity()
        self.token = uuid.uuid4().hex
        await self._finish_pending_release()
        lock = _state_lock(self.agi_cls)
        with lock:
            active_token = getattr(self.agi_cls, "_lifecycle_call_token", None)
            if active_token is not None:
                active_owner = getattr(self.agi_cls, "_lifecycle_call_owner", None)
                active_target = getattr(self.agi_cls, "_lifecycle_call_target", None)
                if active_owner == self.owner and active_target == self.target:
                    self.reentrant = True
                    setattr(
                        self.agi_cls,
                        "_lifecycle_call_depth",
                        int(getattr(self.agi_cls, "_lifecycle_call_depth", 1)) + 1,
                    )
                    return self
                active_operation = getattr(
                    self.agi_cls,
                    "_lifecycle_call_operation",
                    "unknown",
                )
                raise LifecycleBusyError(
                    f"Cannot start AGI {self.operation!r}: lifecycle operation "
                    f"{active_operation!r} is already active in this process. "
                    "Wait for it to finish before retrying."
                )

            service_token = getattr(self.agi_cls, "_lifecycle_service_token", None)
            if service_token is not None:
                service_target = getattr(self.agi_cls, "_lifecycle_service_target", None)
                if (
                    getattr(self.agi_cls, "_service_cleanup_unproven", False)
                    and self.operation != "serve:stop"
                ):
                    raise LifecycleBusyError(
                        f"Cannot start AGI {self.operation!r}: the prior service "
                        "runtime cleanup could not be proven. Call "
                        "AGI.serve(..., action='stop') before any other operation."
                    )
                if not self.service_command or service_target != self.target:
                    service_operation = getattr(
                        self.agi_cls,
                        "_lifecycle_service_operation",
                        "service",
                    )
                    raise LifecycleBusyError(
                        f"Cannot start AGI {self.operation!r}: persistent "
                        f"{service_operation!r} owns runtime state for {service_target}. "
                        "Call AGI.serve(..., action='stop') first."
                    )
                self.reused_service = True
                self.lease = getattr(self.agi_cls, "_lifecycle_service_lease", None)
            else:
                self.lease = acquire_target_lease(
                    self.env,
                    self.operation,
                    remote_token=self.token,
                )

            setattr(self.agi_cls, "_lifecycle_call_token", self.token)
            setattr(self.agi_cls, "_lifecycle_call_owner", self.owner)
            setattr(self.agi_cls, "_lifecycle_call_target", self.target)
            setattr(self.agi_cls, "_lifecycle_call_operation", self.operation)
            setattr(self.agi_cls, "_lifecycle_call_depth", 1)
            setattr(
                self.agi_cls,
                "_lifecycle_remote_token",
                self.lease.remote_token if self.lease is not None else self.token,
            )
            setattr(
                self.agi_cls,
                "_lifecycle_remote_recovery_tokens",
                self.lease.recovered_remote_tokens if self.lease is not None else (),
            )
        return self

    def retain_for_service(self) -> None:
        self._retain_service = True

    def retain_for_service_on_error(self) -> None:
        """Retain ownership when an exception leaves runtime state live/uncertain."""

        self._retain_service = True
        self._retain_service_on_error = True

    def release_service(self) -> None:
        self._release_service = True

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        lock = _state_lock(self.agi_cls)
        lease_to_release: TargetLease | None = None
        with lock:
            if self.reentrant:
                depth = int(getattr(self.agi_cls, "_lifecycle_call_depth", 1)) - 1
                setattr(self.agi_cls, "_lifecycle_call_depth", max(depth, 1))
                return

            self._clear_call_state()

            persistent_lease = getattr(self.agi_cls, "_lifecycle_service_lease", None)
            if self._release_service:
                lease_to_release = persistent_lease or self.lease
                setattr(self.agi_cls, "_lifecycle_service_token", None)
                setattr(self.agi_cls, "_lifecycle_service_target", None)
                setattr(self.agi_cls, "_lifecycle_service_operation", None)
                setattr(self.agi_cls, "_lifecycle_service_lease", None)
            elif getattr(self.agi_cls, "_service_cleanup_unproven", False):
                # Runtime shutdown may have been interrupted or failed after
                # work was already cancelled.  Keep the exact local/remote
                # authority so only an explicit ``serve:stop`` recovery can
                # prove cleanup and release it.
                setattr(
                    self.agi_cls,
                    "_lifecycle_service_token",
                    getattr(self.agi_cls, "_lifecycle_service_token", None)
                    or self.token,
                )
                setattr(self.agi_cls, "_lifecycle_service_target", self.target)
                setattr(
                    self.agi_cls,
                    "_lifecycle_service_operation",
                    "cleanup-recovery",
                )
                setattr(
                    self.agi_cls,
                    "_lifecycle_service_lease",
                    persistent_lease or self.lease,
                )
            elif self._retain_service and (
                exc_type is None or self._retain_service_on_error
            ):
                setattr(
                    self.agi_cls,
                    "_lifecycle_service_token",
                    getattr(self.agi_cls, "_lifecycle_service_token", None) or self.token,
                )
                setattr(self.agi_cls, "_lifecycle_service_target", self.target)
                setattr(self.agi_cls, "_lifecycle_service_operation", "service")
                setattr(self.agi_cls, "_lifecycle_service_lease", persistent_lease or self.lease)
            elif not self.reused_service:
                lease_to_release = self.lease
            if lease_to_release is not None:
                setattr(
                    self.agi_cls,
                    "_lifecycle_pending_release_lease",
                    lease_to_release,
                )

        if lease_to_release is not None:
            release_remote_leases = getattr(
                self.agi_cls,
                "_release_remote_target_leases",
                None,
            )
            if callable(release_remote_leases):
                await release_remote_leases()
            if not release_target_lease(lease_to_release):
                raise RuntimeError(
                    "Could not prove local lifecycle lease release after remote "
                    "target leases were released"
                )
            with lock:
                if (
                    getattr(
                        self.agi_cls,
                        "_lifecycle_pending_release_lease",
                        None,
                    )
                    == lease_to_release
                ):
                    setattr(
                        self.agi_cls,
                        "_lifecycle_pending_release_lease",
                        None,
                    )


def reset_lifecycle_state(agi_cls: Any) -> None:
    """Best-effort reset for tests and process teardown."""

    lock = _state_lock(agi_cls)
    with lock:
        cleanup_task = getattr(agi_cls, "_runtime_cleanup_task", None)
        leases = {
            lease
            for lease in (
                getattr(agi_cls, "_lifecycle_service_lease", None),
                getattr(agi_cls, "_lifecycle_pending_release_lease", None),
            )
            if isinstance(lease, TargetLease)
        }
        for name in (
            "_lifecycle_call_token",
            "_lifecycle_call_owner",
            "_lifecycle_call_target",
            "_lifecycle_call_operation",
            "_lifecycle_remote_token",
            "_lifecycle_pending_release_lease",
            "_lifecycle_service_token",
            "_lifecycle_service_target",
            "_lifecycle_service_operation",
            "_lifecycle_service_lease",
        ):
            setattr(agi_cls, name, None)
        setattr(agi_cls, "_lifecycle_remote_recovery_tokens", ())
        setattr(agi_cls, "_lifecycle_call_depth", 0)
        setattr(agi_cls, "_service_cleanup_unproven", False)
        setattr(agi_cls, "_service_runtime_shutdown_proven", False)
        setattr(agi_cls, "_runtime_cleanup_task", None)
        setattr(agi_cls, "_runtime_cleanup_phase", None)
    if isinstance(cleanup_task, asyncio.Task) and not cleanup_task.done():
        cleanup_task.cancel()
    for lease in leases:
        release_target_lease(lease)


__all__ = [
    "LifecycleBusyError",
    "LifecycleOperation",
    "TargetLease",
    "acquire_target_lease",
    "release_target_lease",
    "reset_lifecycle_state",
    "target_lease_path",
]
