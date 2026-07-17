"""Verified process ownership for local UI sidecars and background services."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Iterator
from urllib.parse import urlparse

import psutil


class SidecarRegistryError(RuntimeError):
    """Base class for fail-closed sidecar ownership errors."""


class SidecarRegistryBusyError(SidecarRegistryError):
    """Raised when another process is updating the registry."""


class SidecarCollisionError(SidecarRegistryError):
    """Raised when a registered endpoint is owned by an unexpected process."""


class SidecarStartError(SidecarRegistryError):
    """Raised when a launched process cannot prove endpoint ownership."""


@dataclass(frozen=True, slots=True)
class SidecarLease:
    service_kind: str
    project: str
    key: str
    endpoint: str
    token: str
    pid: int
    process_started_at: float
    command_digest: str
    registered_at: float
    health_signature: str

    @property
    def host(self) -> str:
        parsed = urlparse(self.endpoint)
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise SidecarRegistryError(f"Invalid loopback sidecar endpoint: {self.endpoint!r}")
        # Ports are allocated on IPv4 loopback, so ``localhost`` leases must
        # prove ownership of that same concrete bind address rather than any
        # address returned by host-name resolution.
        return "127.0.0.1"

    @property
    def port(self) -> int:
        parsed = urlparse(self.endpoint)
        if self.host != "127.0.0.1" or parsed.port is None:
            raise SidecarRegistryError(f"Invalid loopback sidecar endpoint: {self.endpoint!r}")
        return int(parsed.port)


_THREAD_GUARD = threading.RLock()
_ENSURE_THREAD_GUARDS_LOCK = threading.Lock()
_ENSURE_THREAD_GUARDS: dict[str, threading.RLock] = {}
_PORT_RESERVATIONS_LOCK = threading.Lock()
_PORT_RESERVATIONS: set[str] = set()
_PREPARATION_THREAD_GUARDS_LOCK = threading.Lock()
_PREPARATION_THREAD_GUARDS: dict[str, threading.RLock] = {}
HOSTED_INLINE_RENDER_LEASE = threading.RLock()
HOSTED_INLINE_RENDER_SESSION_LEASE = threading.Lock()
_HOSTED_INLINE_RENDER_LOCK_TIMEOUT_SECONDS = 5.0


@contextmanager
def _bounded_thread_guard(
    lock: Any,
    *,
    timeout: float,
    purpose: str,
) -> Iterator[None]:
    """Acquire a process-local guard without freezing every peer session."""

    acquired = lock.acquire(timeout=max(float(timeout), 0.0))
    if not acquired:
        raise SidecarRegistryBusyError(
            f"Timed out waiting for {purpose}; another AGILAB session is still using it"
        )
    try:
        yield
    finally:
        lock.release()


@contextmanager
def hosted_inline_render_guard(
    *,
    timeout: float | None = None,
) -> Iterator[None]:
    """Bound process-global mutations shared by hosted inline render paths."""

    effective_timeout = (
        _HOSTED_INLINE_RENDER_LOCK_TIMEOUT_SECONDS
        if timeout is None
        else timeout
    )
    with _bounded_thread_guard(
        HOSTED_INLINE_RENDER_LEASE,
        timeout=effective_timeout,
        purpose="hosted inline render lease",
    ):
        yield


def _importable_root_names(root: Path) -> set[str]:
    names: set[str] = set()
    try:
        children = sorted(root.iterdir(), key=lambda path: path.name)
    except OSError:
        return names
    for child in children:
        if child.is_file() and child.suffix == ".py" and child.stem != "__init__":
            names.add(child.stem)
        elif child.is_dir() and (child / "__init__.py").is_file():
            names.add(child.name)
    return names


def _module_is_below(module: Any, roots: tuple[Path, ...]) -> bool:
    raw_path = getattr(module, "__file__", None)
    if not raw_path:
        return False
    try:
        module_path = Path(raw_path).resolve(strict=False)
    except (OSError, TypeError, ValueError):
        return False
    for root in roots:
        try:
            module_path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


@contextmanager
def isolated_import_process_state(
    *,
    argv: list[str] | None = None,
    prepend_paths: tuple[Path, ...] = (),
    module_roots: tuple[Path, ...] = (),
    timeout: float = _HOSTED_INLINE_RENDER_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Serialize and restore temporary import globals used by hosted UI code.

    Importable names rooted in the temporary directories are evicted before the
    import so a helper from another app cannot be reused by name. Newly imported
    modules from those roots are removed afterwards, and prior modules are restored.
    """

    with hosted_inline_render_guard(timeout=timeout):
        original_argv = list(sys.argv)
        original_path = list(sys.path)
        roots = tuple(Path(root).resolve(strict=False) for root in module_roots)
        root_names: set[str] = set()
        for root in roots:
            root_names.update(_importable_root_names(root))
        saved_modules: dict[str, Any] = {}
        for module_name in tuple(sys.modules):
            top_level = module_name.partition(".")[0]
            if top_level in root_names:
                saved_modules[module_name] = sys.modules.pop(module_name)

        try:
            if argv is not None:
                sys.argv = list(argv)
            for path in reversed(prepend_paths):
                entry = str(Path(path).resolve(strict=False))
                sys.path[:] = [existing for existing in sys.path if existing != entry]
                sys.path.insert(0, entry)
            yield
        finally:
            for module_name, module in tuple(sys.modules.items()):
                if _module_is_below(module, roots):
                    sys.modules.pop(module_name, None)
            sys.modules.update(saved_modules)
            sys.argv = original_argv
            sys.path[:] = original_path


class ProcessSidecarRegistry:
    """Cross-session registry backed by signed, process-verified leases."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else Path.home() / ".agilab" / "runtime" / "sidecars"
        self.registry_path = self.root / "registry.json"
        self.lock_path = self.root / "registry.lock"
        self.secret_path = self.root / "registry.secret"

    def ensure(
        self,
        *,
        service_kind: str,
        project: str,
        key: str,
        launcher: Callable[[int, str], Any],
        token: str | None = None,
        endpoint_builder: Callable[[int], str] | None = None,
        replace_existing_for_project: bool = False,
        exclusive_for_project: bool = False,
        timeout: float = 24.0,
    ) -> SidecarLease:
        """Reuse a verified process or launch and register a new owned service."""

        kind = self._nonempty(service_kind, "service kind")
        project_id = self._nonempty(project, "project")
        service_key = self._nonempty(key, "service key")
        entry_id = self._entry_id(kind, project_id, service_key)
        endpoint_builder = endpoint_builder or (lambda port: f"http://127.0.0.1:{port}")
        if replace_existing_for_project and exclusive_for_project:
            raise ValueError(
                "A sidecar cannot both replace and reject another project configuration."
            )

        lock_timeout = max(timeout, 5.0)
        with self._ensure_guard(
            service_kind=kind,
            project=project_id,
            timeout=lock_timeout,
        ):
            with _bounded_thread_guard(
                _THREAD_GUARD,
                timeout=lock_timeout,
                purpose="sidecar registry thread lock",
            ), self._file_guard(timeout=lock_timeout):
                entries = self._load_entries()
                if replace_existing_for_project:
                    self._retire_project_entries(
                        entries,
                        service_kind=kind,
                        project=project_id,
                        keep_entry_id=entry_id,
                    )
                if exclusive_for_project:
                    self._reject_project_entry_conflicts(
                        entries,
                        service_kind=kind,
                        project=project_id,
                        keep_entry_id=entry_id,
                    )
                raw_existing = entries.get(entry_id)
                if raw_existing is not None and not isinstance(raw_existing, dict):
                    raise SidecarRegistryError(
                        f"Invalid sidecar registry entry for {kind}/{project_id}"
                    )
                if isinstance(raw_existing, dict):
                    existing = self._verified_lease(raw_existing)
                    if self._lease_is_healthy(existing):
                        return existing
                    identity_status = self._process_identity_status(
                        existing.pid,
                        existing.process_started_at,
                    )
                    if identity_status is not False:
                        detail = (
                            "is still live"
                            if identity_status is True
                            else "cannot be verified"
                        )
                        raise SidecarCollisionError(
                            f"Registered sidecar process {existing.pid} {detail}, but endpoint "
                            f"health for {existing.endpoint} is not proven; refusing to launch a "
                            "replacement."
                        )
                    if self._port_is_open(existing.port):
                        raise SidecarCollisionError(
                            f"Sidecar endpoint {existing.endpoint} is listening without its "
                            "registered PID/start identity; refusing to reuse an unrelated process."
                        )
                    entries.pop(entry_id, None)
                    self._write_entries(entries)

            with self._reserved_loopback_port(timeout=lock_timeout) as port:
                service_token = token or secrets.token_urlsafe(32)
                endpoint = endpoint_builder(port)
                parsed = urlparse(endpoint)
                if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != port:
                    raise SidecarRegistryError(
                        "Sidecar endpoint builder must preserve the allocated loopback port: "
                        f"{endpoint!r}"
                    )

                try:
                    process = launcher(port, service_token)
                except BaseException as exc:
                    raise SidecarStartError(f"Failed to launch {kind} sidecar: {exc}") from exc

                pid: int | None = None
                started_at: float | None = None
                observed_processes: dict[int, float] = {}
                try:
                    raw_pid = getattr(process, "pid", None)
                    if not isinstance(raw_pid, int) or raw_pid <= 0:
                        raise SidecarStartError(
                            f"{kind} launcher did not return an owned process handle"
                        )
                    pid = raw_pid
                    try:
                        started_at = float(psutil.Process(pid).create_time())
                    except (psutil.Error, OSError, ValueError) as exc:
                        raise SidecarStartError(
                            f"Could not verify {kind} process identity for PID {pid}"
                        ) from exc

                    deadline = time.monotonic() + max(timeout, 0.1)
                    observed_processes[pid] = started_at
                    while time.monotonic() < deadline:
                        observed_processes.update(
                            self._process_tree_identities(pid, started_at)
                        )
                        poll = getattr(process, "poll", None)
                        if callable(poll) and poll() is not None:
                            break
                        endpoint_host = "127.0.0.1"
                        if self._process_owns_endpoint(
                            pid,
                            started_at,
                            endpoint_host,
                            port,
                        ):
                            command_digest = self._command_digest(pid, started_at)
                            unsigned = {
                                "service_kind": kind,
                                "project": project_id,
                                "key": service_key,
                                "endpoint": endpoint,
                                "token": service_token,
                                "pid": pid,
                                "process_started_at": started_at,
                                "command_digest": command_digest,
                                "registered_at": time.time(),
                            }
                            with _bounded_thread_guard(
                                _THREAD_GUARD,
                                timeout=lock_timeout,
                                purpose="sidecar registry thread lock",
                            ), self._file_guard(timeout=lock_timeout):
                                entries = self._load_entries()
                                if entry_id in entries:
                                    raise SidecarCollisionError(
                                        f"Sidecar registry entry for {kind}/{project_id} changed "
                                        "while its replacement was starting"
                                    )
                                lease = SidecarLease(
                                    **unsigned,
                                    health_signature=self._sign(unsigned),
                                )
                                entries[entry_id] = asdict(lease)
                                self._write_entries(entries)
                            return lease
                        time.sleep(0.1)

                    raise SidecarStartError(
                        f"{kind} process PID {pid} did not prove ownership of {endpoint} "
                        f"within {timeout:.1f}s"
                    )
                except BaseException:
                    try:
                        self._terminate_process(
                            process,
                            root_pid=pid,
                            root_started_at=started_at,
                            observed_processes=observed_processes,
                        )
                    except BaseException:
                        # Cleanup must never replace the failure that caused it.
                        pass
                    raise

    def _reject_project_entry_conflicts(
        self,
        entries: dict[str, Any],
        *,
        service_kind: str,
        project: str,
        keep_entry_id: str,
    ) -> None:
        """Refuse a different live project configuration without terminating it."""

        changed = False
        for candidate_id, raw_entry in tuple(entries.items()):
            if candidate_id == keep_entry_id or not isinstance(raw_entry, dict):
                continue
            if (
                raw_entry.get("service_kind") != service_kind
                or raw_entry.get("project") != project
            ):
                continue

            lease = self._verified_lease(raw_entry)
            if self._lease_is_healthy(lease):
                raise SidecarCollisionError(
                    f"A different {service_kind} configuration is already active for "
                    f"{project} at {lease.endpoint}; refusing to replace another session's service."
                )

            identity_status = self._process_identity_status(
                lease.pid,
                lease.process_started_at,
            )
            if identity_status is not False:
                detail = "is still live" if identity_status is True else "cannot be verified"
                raise SidecarCollisionError(
                    f"A different registered {service_kind} process {lease.pid} {detail} "
                    f"for {project}; refusing to replace another session's service."
                )
            if self._port_is_open(lease.port):
                raise SidecarCollisionError(
                    f"A different {service_kind} endpoint is listening on port {lease.port} "
                    f"for {project}; refusing to replace an unrelated process."
                )
            entries.pop(candidate_id, None)
            changed = True

        if changed:
            self._write_entries(entries)

    def get(self, *, service_kind: str, project: str, key: str) -> SidecarLease | None:
        """Return a verified lease, deleting dead entries without trusting the port alone."""

        entry_id = self._entry_id(service_kind, project, key)
        with _bounded_thread_guard(
            _THREAD_GUARD,
            timeout=5.0,
            purpose="sidecar registry thread lock",
        ), self._file_guard(timeout=5.0):
            entries = self._load_entries()
            raw = entries.get(entry_id)
            if raw is None:
                return None
            if not isinstance(raw, dict):
                raise SidecarRegistryError(
                    f"Invalid sidecar registry entry for {service_kind}/{project}"
                )
            lease = self._verified_lease(raw)
            if self._lease_is_healthy(lease):
                return lease
            identity_status = self._process_identity_status(
                lease.pid,
                lease.process_started_at,
            )
            if identity_status is not False:
                detail = "is still live" if identity_status is True else "cannot be verified"
                raise SidecarCollisionError(
                    f"Registered sidecar process {lease.pid} {detail}, but endpoint "
                    f"health for {lease.endpoint} is not proven"
                )
            if self._port_is_open(lease.port):
                raise SidecarCollisionError(
                    f"Registered sidecar endpoint {lease.endpoint} no longer matches its process identity"
                )
            entries.pop(entry_id, None)
            self._write_entries(entries)
            return None

    @contextmanager
    def _ensure_guard(
        self,
        *,
        service_kind: str,
        project: str,
        timeout: float,
    ) -> Iterator[None]:
        """Serialize one logical service without blocking unrelated launches."""

        scope_id = self._entry_id(service_kind, project, "sidecar-service")
        guard_key = f"{self.root.resolve(strict=False)}\0{scope_id}"
        with _ENSURE_THREAD_GUARDS_LOCK:
            thread_guard = _ENSURE_THREAD_GUARDS.setdefault(
                guard_key,
                threading.RLock(),
            )
        service_lock = self.root / f"service-{scope_id}.lock"
        with _bounded_thread_guard(
            thread_guard,
            timeout=timeout,
            purpose="sidecar service thread lock",
        ), self._locked_file_guard(
            service_lock,
            timeout=timeout,
            purpose="sidecar-service",
        ):
            yield

    @contextmanager
    def _reserved_loopback_port(self, *, timeout: float) -> Iterator[int]:
        """Reserve an allocated port across concurrent registry launchers."""

        deadline = time.monotonic() + timeout
        while True:
            if time.monotonic() >= deadline:
                raise SidecarRegistryBusyError(
                    "Timed out reserving a loopback port for sidecar launch"
                )
            port = self._allocate_loopback_port()
            lock_path = self.root / f"port-{port}.lock"
            reservation_key = str(lock_path.resolve(strict=False))
            with _PORT_RESERVATIONS_LOCK:
                if reservation_key in _PORT_RESERVATIONS:
                    claimed_in_process = False
                else:
                    _PORT_RESERVATIONS.add(reservation_key)
                    claimed_in_process = True
            if not claimed_in_process:
                time.sleep(0.01)
                continue

            handle = None
            locked = False
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                handle = lock_path.open("a+b")
                if not self._try_advisory_lock(handle):
                    time.sleep(0.01)
                    continue
                locked = True
                yield port
                return
            finally:
                if handle is not None:
                    if locked:
                        self._unlock_advisory_lock(handle)
                    handle.close()
                with _PORT_RESERVATIONS_LOCK:
                    _PORT_RESERVATIONS.discard(reservation_key)

    @contextmanager
    def preparation_guard(
        self,
        *,
        service_kind: str,
        project: str,
        key: str,
        timeout: float = 120.0,
    ) -> Iterator[None]:
        """Serialize destructive preparation for one shared sidecar resource."""

        entry_id = self._entry_id(
            self._nonempty(service_kind, "service kind"),
            self._nonempty(project, "project"),
            self._nonempty(key, "preparation key"),
        )
        with _PREPARATION_THREAD_GUARDS_LOCK:
            thread_guard = _PREPARATION_THREAD_GUARDS.setdefault(
                entry_id,
                threading.RLock(),
            )
        preparation_lock = self.root / f"prepare-{entry_id}.lock"
        with _bounded_thread_guard(
            thread_guard,
            timeout=timeout,
            purpose="sidecar preparation thread lock",
        ), self._locked_file_guard(
            preparation_lock,
            timeout=timeout,
            purpose="sidecar-preparation",
        ):
            yield

    @staticmethod
    def _nonempty(value: object, label: str) -> str:
        result = str(value or "").strip()
        if not result:
            raise ValueError(f"{label} must be non-empty")
        return result

    @staticmethod
    def _entry_id(service_kind: str, project: str, key: str) -> str:
        payload = "\0".join((str(service_kind), str(project), str(key)))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @contextmanager
    def _file_guard(self, *, timeout: float) -> Iterator[None]:
        with self._locked_file_guard(
            self.lock_path,
            timeout=timeout,
            purpose="sidecar-registry",
        ):
            yield

    @contextmanager
    def _locked_file_guard(
        self,
        lock_path: Path,
        *,
        timeout: float,
        purpose: str,
    ) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + timeout
        handle = lock_path.open("a+b")
        locked = False
        try:
            while not self._try_advisory_lock(handle):
                if time.monotonic() >= deadline:
                    raise SidecarRegistryBusyError(
                        f"Timed out waiting for {purpose} lock {lock_path}"
                    )
                time.sleep(0.05)
            locked = True
            payload = (
                json.dumps(
                    {
                        "purpose": purpose,
                        "pid": os.getpid(),
                        "started_at": self._current_process_start(),
                    },
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
            handle.seek(0)
            handle.truncate(0)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            yield
        finally:
            try:
                if locked:
                    self._unlock_advisory_lock(handle)
            finally:
                handle.close()

    @staticmethod
    def _try_advisory_lock(handle) -> bool:
        if os.name == "nt":  # pragma: no cover - exercised on Windows CI
            import msvcrt

            try:
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                return False
        import fcntl

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (BlockingIOError, OSError):
            return False

    @staticmethod
    def _unlock_advisory_lock(handle) -> None:
        try:
            if os.name == "nt":  # pragma: no cover - exercised on Windows CI
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass

    def _load_entries(self) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            raise SidecarRegistryError(f"Could not read sidecar registry {self.registry_path}: {exc}") from exc
        entries = payload.get("entries", {}) if isinstance(payload, dict) else {}
        if not isinstance(entries, dict):
            raise SidecarRegistryError(f"Invalid sidecar registry structure in {self.registry_path}")
        return entries

    def _write_entries(self, entries: dict[str, dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix="registry-", suffix=".tmp", dir=self.root)
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"version": 1, "entries": entries}, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, self.registry_path)
            self._fsync_directory(self.root)
        finally:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass

    def _load_secret(self) -> bytes:
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.secret_path.exists():
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{self.secret_path.name}.",
                suffix=".tmp",
                dir=self.root,
            )
            tmp_path = Path(tmp_name)
            try:
                os.chmod(tmp_path, 0o600)
                secret = secrets.token_bytes(32)
                offset = 0
                while offset < len(secret):
                    offset += os.write(fd, secret[offset:])
                os.fsync(fd)
                os.close(fd)
                fd = -1
                os.replace(tmp_path, self.secret_path)
                self._fsync_directory(self.root)
            finally:
                if fd >= 0:
                    os.close(fd)
                try:
                    tmp_path.unlink()
                except FileNotFoundError:
                    pass
        try:
            secret = self.secret_path.read_bytes()
        except OSError as exc:
            raise SidecarRegistryError(f"Could not read registry secret {self.secret_path}: {exc}") from exc
        if len(secret) < 32:
            raise SidecarRegistryError(f"Registry secret is invalid: {self.secret_path}")
        return secret

    def _sign(self, payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hmac.new(self._load_secret(), encoded, hashlib.sha256).hexdigest()

    def _lease_from_dict(self, raw: dict[str, Any]) -> SidecarLease | None:
        try:
            return SidecarLease(
                service_kind=str(raw["service_kind"]),
                project=str(raw["project"]),
                key=str(raw["key"]),
                endpoint=str(raw["endpoint"]),
                token=str(raw["token"]),
                pid=int(raw["pid"]),
                process_started_at=float(raw["process_started_at"]),
                command_digest=str(raw["command_digest"]),
                registered_at=float(raw["registered_at"]),
                health_signature=str(raw["health_signature"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _verified_lease(self, raw: dict[str, Any]) -> SidecarLease:
        lease = self._lease_from_dict(raw)
        if lease is None:
            raise SidecarRegistryError(f"Invalid sidecar registry entry in {self.registry_path}")
        unsigned = asdict(lease)
        signature = str(unsigned.pop("health_signature"))
        if not hmac.compare_digest(signature, self._sign(unsigned)):
            raise SidecarRegistryError(
                f"Sidecar registry signature validation failed for PID {lease.pid}"
            )
        return lease

    def _lease_is_healthy(self, lease: SidecarLease) -> bool:
        unsigned = asdict(lease)
        signature = str(unsigned.pop("health_signature"))
        if not hmac.compare_digest(signature, self._sign(unsigned)):
            return False
        if not self._process_matches(lease.pid, lease.process_started_at):
            return False
        if self._command_digest(lease.pid, lease.process_started_at) != lease.command_digest:
            return False
        return self._process_owns_endpoint(
            lease.pid,
            lease.process_started_at,
            lease.host,
            lease.port,
        )

    @staticmethod
    def _current_process_start() -> float:
        return float(psutil.Process(os.getpid()).create_time())

    @staticmethod
    def _process_identity_status(pid: int, started_at: float) -> bool | None:
        try:
            process = psutil.Process(pid)
            if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
                return False
            return abs(float(process.create_time()) - float(started_at)) < 0.01
        except psutil.NoSuchProcess:
            return False
        except (psutil.Error, OSError, ValueError):
            return None

    @classmethod
    def _process_matches(cls, pid: int, started_at: float) -> bool:
        return cls._process_identity_status(pid, started_at) is True

    def _retire_project_entries(
        self,
        entries: dict[str, dict[str, Any]],
        *,
        service_kind: str,
        project: str,
        keep_entry_id: str,
    ) -> None:
        changed = False
        for candidate_id in sorted(entries):
            if candidate_id == keep_entry_id:
                continue
            raw = entries.get(candidate_id)
            if not isinstance(raw, dict):
                continue
            if (
                str(raw.get("service_kind", "")) != service_kind
                or str(raw.get("project", "")) != project
            ):
                continue
            lease = self._verified_lease(raw)
            identity_status = self._process_identity_status(
                lease.pid,
                lease.process_started_at,
            )
            if identity_status is None:
                raise SidecarCollisionError(
                    f"Cannot verify obsolete {service_kind} sidecar PID {lease.pid}; "
                    "refusing configuration replacement."
                )
            if identity_status is True:
                try:
                    process = psutil.Process(lease.pid)
                except psutil.NoSuchProcess:
                    process = None
                except psutil.Error as exc:
                    raise SidecarCollisionError(
                        f"Cannot inspect obsolete {service_kind} sidecar PID {lease.pid}"
                    ) from exc
                if process is not None:
                    observed = self._process_tree_identities(
                        lease.pid,
                        lease.process_started_at,
                    )
                    self._terminate_process(
                        process,
                        root_pid=lease.pid,
                        root_started_at=lease.process_started_at,
                        observed_processes=observed,
                    )
                    if self._process_identity_status(
                        lease.pid,
                        lease.process_started_at,
                    ) is not False:
                        raise SidecarCollisionError(
                            f"Could not stop obsolete {service_kind} sidecar PID {lease.pid}"
                        )
            if self._port_is_open(lease.port):
                raise SidecarCollisionError(
                    f"Obsolete {service_kind} endpoint {lease.endpoint} is still listening"
                )
            entries.pop(candidate_id, None)
            changed = True
        if changed:
            self._write_entries(entries)

    @classmethod
    def _process_tree(cls, pid: int, started_at: float) -> list[psutil.Process]:
        if not cls._process_matches(pid, started_at):
            return []
        try:
            root = psutil.Process(pid)
            return [root, *root.children(recursive=True)]
        except (psutil.Error, OSError):
            return []

    @classmethod
    def _process_tree_identities(cls, pid: int, started_at: float) -> dict[int, float]:
        identities: dict[int, float] = {}
        for process in cls._process_tree(pid, started_at):
            try:
                identities[int(process.pid)] = float(process.create_time())
            except (psutil.Error, OSError, ValueError):
                continue
        return identities

    @classmethod
    def _process_owns_endpoint(
        cls,
        pid: int,
        started_at: float,
        host: str,
        port: int,
    ) -> bool:
        if host != "127.0.0.1":
            return False
        for process in cls._process_tree(pid, started_at):
            try:
                connections = process.net_connections(kind="tcp")
            except (psutil.Error, OSError):
                continue
            for connection in connections:
                local = getattr(connection, "laddr", None)
                local_ip = getattr(local, "ip", None) if local else None
                local_port = getattr(local, "port", None) if local else None
                if local and (local_ip is None or local_port is None):
                    try:
                        local_ip = local[0]
                        local_port = local[1]
                    except (IndexError, TypeError):
                        local_ip = None
                        local_port = None
                try:
                    family = int(getattr(connection, "family"))
                except (AttributeError, TypeError, ValueError):
                    continue
                if family != int(socket.AF_INET):
                    continue
                if str(local_ip) != host:
                    continue
                if local_port is None or int(local_port) != int(port):
                    continue
                status = str(getattr(connection, "status", ""))
                if status.upper() == "LISTEN":
                    return True
        return False

    @classmethod
    def _command_digest(cls, pid: int, started_at: float) -> str:
        if not cls._process_matches(pid, started_at):
            return ""
        try:
            command = "\0".join(psutil.Process(pid).cmdline())
        except (psutil.Error, OSError):
            return ""
        # The root process remains stable while launchers such as uv can turn
        # child processes over. Port ownership is still verified over the full
        # process tree, so child churn cannot invalidate a legitimate lease.
        return hashlib.sha256(command.encode("utf-8")).hexdigest()

    @staticmethod
    def _allocate_loopback_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    @staticmethod
    def _port_is_open(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            return sock.connect_ex(("127.0.0.1", int(port))) == 0

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        try:
            directory_fd = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(directory_fd)
        except OSError:
            pass
        finally:
            os.close(directory_fd)

    @classmethod
    def _terminate_process(
        cls,
        process: Any,
        *,
        root_pid: int | None = None,
        root_started_at: float | None = None,
        observed_processes: dict[int, float] | None = None,
    ) -> None:
        """Stop only the verified launcher tree, children first, with a bound."""

        identities = dict(observed_processes or {})
        if root_pid is not None and root_started_at is not None:
            identities.update(cls._process_tree_identities(root_pid, root_started_at))
            identities.setdefault(root_pid, root_started_at)

        owned: list[psutil.Process] = []
        for candidate_pid, candidate_started_at in identities.items():
            if not cls._process_matches(candidate_pid, candidate_started_at):
                continue
            try:
                owned.append(psutil.Process(candidate_pid))
            except (psutil.Error, OSError):
                continue

        if owned:
            owned.sort(key=lambda item: item.pid == root_pid)
            for owned_process in owned:
                try:
                    owned_process.terminate()
                except (psutil.Error, OSError):
                    pass
            _gone, alive = psutil.wait_procs(owned, timeout=2.0)
            for owned_process in alive:
                expected_start = identities.get(owned_process.pid)
                if expected_start is None or not cls._process_matches(
                    owned_process.pid, expected_start
                ):
                    continue
                try:
                    owned_process.kill()
                except (psutil.Error, OSError):
                    pass
            if alive:
                psutil.wait_procs(alive, timeout=1.0)
            return

        terminate = getattr(process, "terminate", None)
        if callable(terminate):
            try:
                terminate()
            except (OSError, ProcessLookupError):
                pass


DEFAULT_SIDECAR_REGISTRY = ProcessSidecarRegistry()
