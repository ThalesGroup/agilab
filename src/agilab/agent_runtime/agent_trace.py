# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Append-only evidence traces for AGILAB agent and tool runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import tempfile
import time
from typing import Any, Mapping, Sequence

from agilab.security.secret_uri import redact_mapping, redact_text


TRACE_SCHEMA = "agilab.agent_trace.v1"
META_FILENAME = "agent_trace_meta.json"
EVENTS_FILENAME = "agent_events.ndjson"
TOOL_OUTPUT_DIRNAME = "tool-output"
LOCK_TIMEOUT_SECONDS = 5.0
LOCK_STALE_SECONDS = 30.0
VALID_EVENT_TYPES = frozenset(
    {
        "session_start",
        "session_end",
        "user_message",
        "assistant_message",
        "reasoning",
        "tool_start",
        "tool_output",
        "tool_done",
        "permission_request",
        "permission_resolved",
        "compact",
        "rewind",
        "command_start",
        "command_done",
        "error",
    }
)


@dataclass(frozen=True)
class AgentTraceEvent:
    """One redacted append-only trace event."""

    schema: str
    event: str
    run_id: str
    sequence: int
    created_at: str
    status: str
    message: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class AgentTraceSummary:
    """Compact read-side summary for an agent trace directory."""

    run_id: str
    agent: str
    label: str
    event_count: int
    events_path: Path
    meta_path: Path
    first_event: str
    last_event: str
    status: str


def utc_now() -> str:
    """Return an RFC3339-ish UTC timestamp used across trace records."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _event_from_mapping(payload: Mapping[str, Any]) -> AgentTraceEvent:
    metadata = payload.get("metadata")
    return AgentTraceEvent(
        schema=str(payload.get("schema") or ""),
        event=str(payload.get("event") or ""),
        run_id=str(payload.get("run_id") or ""),
        sequence=int(payload.get("sequence") or 0),
        created_at=str(payload.get("created_at") or ""),
        status=str(payload.get("status") or ""),
        message=str(payload.get("message") or ""),
        metadata=dict(metadata) if isinstance(metadata, dict) else {},
    )


def _last_nonempty_line(path: Path) -> str:
    if not path.exists() or path.stat().st_size == 0:
        return ""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        buffer = bytearray()
        while position > 0:
            position -= 1
            handle.seek(position)
            char = handle.read(1)
            if char == b"\n":
                if buffer:
                    break
                continue
            buffer.extend(char)
    return bytes(reversed(buffer)).decode("utf-8", "replace").strip()


def _last_event_sequence(path: Path) -> int:
    line = _last_nonempty_line(path)
    if not line:
        return 0
    try:
        payload = json.loads(line)
    except ValueError:
        events = load_trace_events(path)
        return events[-1].sequence if events else 0
    if isinstance(payload, dict):
        try:
            return int(payload.get("sequence") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def _lock_owner_alive(payload: Mapping[str, Any]) -> bool | None:
    if str(payload.get("host") or "") != socket.gethostname():
        return None
    try:
        pid = int(payload.get("pid") or 0)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


def _read_lock_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _lock_is_stale(path: Path, *, now: float | None = None) -> bool:
    payload = _read_lock_payload(path)
    if _lock_owner_alive(payload) is True:
        return False
    try:
        age_seconds = (time.time() if now is None else now) - path.stat().st_mtime
    except OSError:
        return False
    return age_seconds >= LOCK_STALE_SECONDS


def _clear_stale_lock(path: Path) -> bool:
    if not _lock_is_stale(path):
        return False
    handle = path.open("a+b")
    try:
        if not _try_lock_handle(handle):
            return False
        _rewrite_locked_handle(handle, {})
        return True
    except OSError:
        return False
    finally:
        _unlock_handle(handle)
        handle.close()


def _try_lock_handle(handle) -> bool:
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


def _unlock_handle(handle) -> None:
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


def _rewrite_locked_handle(handle, payload: Mapping[str, Any]) -> None:
    encoded = (json.dumps(dict(payload), sort_keys=True) + "\n").encode("utf-8")
    handle.seek(0)
    handle.truncate(0)
    handle.write(encoded)
    handle.flush()
    os.fsync(handle.fileno())


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, path)
        _fsync_directory(path.parent)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _validate_trace_run_identity(
    payload: Mapping[str, Any],
    *,
    expected_run_id: str,
    meta_path: Path,
) -> None:
    """Reject missing or mismatched ownership before reusing a trace."""

    existing_run_id = str(payload.get("run_id") or "")
    if not existing_run_id:
        raise FileExistsError(
            f"Agent trace metadata is invalid and cannot be resumed: {meta_path}"
        )
    if existing_run_id != expected_run_id:
        raise FileExistsError(
            f"Agent trace directory belongs to run {existing_run_id!r}, "
            f"not {expected_run_id!r}: {meta_path.parent}"
        )


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


@contextmanager
def _event_file_lock(path: Path):
    lock_path = path.with_name(path.name + ".lock")
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    while not _try_lock_handle(handle):
        if time.monotonic() >= deadline:
            handle.close()
            raise TimeoutError(f"Timed out waiting for agent trace lock: {lock_path}")
        time.sleep(0.01)
    try:
        _rewrite_locked_handle(
            handle,
            {
                "host": socket.gethostname(),
                "pid": os.getpid(),
                "created_at": utc_now(),
            },
        )
    except BaseException:
        _unlock_handle(handle)
        handle.close()
        raise
    try:
        yield
    finally:
        try:
            _rewrite_locked_handle(handle, {})
        finally:
            _unlock_handle(handle)
            handle.close()


trace_file_lock = _event_file_lock


def repair_jsonl_tail(path: Path | str) -> Path | None:
    """Repair only an unterminated JSONL tail while its file lock is held.

    A complete JSON value which merely lacks its final newline is preserved.
    An invalid suffix is copied to a unique quarantine artifact and removed
    from the live stream before a later append can be concatenated onto it.
    """

    candidate = Path(path).expanduser()
    if not candidate.exists() or candidate.stat().st_size == 0:
        return None
    with candidate.open("r+b") as handle:
        handle.seek(0, os.SEEK_END)
        end = handle.tell()
        handle.seek(end - 1)
        if handle.read(1) == b"\n":
            return None

        start = end
        while start > 0:
            start -= 1
            handle.seek(start)
            if handle.read(1) == b"\n":
                start += 1
                break
        handle.seek(start)
        tail = handle.read(end - start)
        try:
            decoded = tail.decode("utf-8")
            payload = json.loads(decoded)
            if not isinstance(payload, Mapping):
                raise ValueError("JSONL records must be objects")
        except (UnicodeDecodeError, ValueError):
            fd, quarantine_name = tempfile.mkstemp(
                prefix=f".{candidate.name}.partial.",
                suffix=".jsonl",
                dir=candidate.parent,
            )
            quarantine_path = Path(quarantine_name)
            try:
                with os.fdopen(fd, "wb") as quarantine:
                    quarantine.write(tail)
                    quarantine.flush()
                    os.fsync(quarantine.fileno())
            except BaseException:
                try:
                    quarantine_path.unlink()
                except FileNotFoundError:
                    pass
                raise
            handle.seek(start)
            handle.truncate()
            handle.flush()
            os.fsync(handle.fileno())
            _fsync_directory(candidate.parent)
            return quarantine_path

        handle.seek(0, os.SEEK_END)
        handle.write(b"\n")
        handle.flush()
        os.fsync(handle.fileno())
        return None


def load_trace_events(path: Path | str) -> list[AgentTraceEvent]:
    """Load trace events, tolerating only an unterminated crash tail."""

    candidate = Path(path).expanduser()
    events_path = candidate / EVENTS_FILENAME if candidate.is_dir() else candidate
    if not events_path.exists():
        return []

    raw = events_path.read_bytes()
    has_unterminated_tail = bool(raw) and not raw.endswith(b"\n")
    encoded_lines = raw.splitlines()
    events: list[AgentTraceEvent] = []
    for index, encoded_line in enumerate(encoded_lines):
        if not encoded_line.strip():
            continue
        try:
            payload = json.loads(encoded_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if has_unterminated_tail and index == len(encoded_lines) - 1:
                break
            raise ValueError(
                f"Invalid agent trace JSONL record {index + 1}: {events_path}"
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError(
                f"Agent trace JSONL record {index + 1} must be an object: {events_path}"
            )
        try:
            events.append(_event_from_mapping(payload))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid agent trace event record {index + 1}: {events_path}"
            ) from exc
    return events


class AgentTraceStore:
    """Directory-backed append-only event store for one AGILAB agent run."""

    def __init__(
        self,
        root: Path | str,
        *,
        run_id: str,
        agent: str = "",
        label: str = "",
        provider: str = "",
        model: str = "",
    ) -> None:
        self.root = Path(root).expanduser()
        self.run_id = run_id
        self.agent = agent
        self.label = label
        self.provider = provider
        self.model = model

    @property
    def meta_path(self) -> Path:
        return self.root / META_FILENAME

    @property
    def events_path(self) -> Path:
        return self.root / EVENTS_FILENAME

    @property
    def tool_output_dir(self) -> Path:
        return self.root / TOOL_OUTPUT_DIRNAME

    def initialize(self, metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Create the trace directory and meta file if missing."""

        self.root.mkdir(parents=True, exist_ok=True)
        self.tool_output_dir.mkdir(parents=True, exist_ok=True)
        with _event_file_lock(self.events_path):
            if self.meta_path.exists():
                existing = _read_json(self.meta_path)
                _validate_trace_run_identity(
                    existing,
                    expected_run_id=self.run_id,
                    meta_path=self.meta_path,
                )
                return existing

            if self.events_path.exists() and self.events_path.stat().st_size:
                raise FileExistsError(
                    f"Agent trace events exist without ownership metadata and cannot be resumed: {self.events_path}"
                )

            payload: dict[str, Any] = {
                "schema": TRACE_SCHEMA,
                "run_id": self.run_id,
                "agent": self.agent,
                "label": self.label,
                "provider": self.provider,
                "model": self.model,
                "created_at": utc_now(),
                "events": str(self.events_path),
                "tool_output_dir": str(self.tool_output_dir),
                "metadata": redact_mapping(metadata or {}),
            }
            _atomic_write_text(
                self.meta_path,
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
            )
            self.events_path.touch(exist_ok=True)
            return payload

    def append(
        self,
        event: str,
        *,
        status: str = "running",
        message: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> AgentTraceEvent:
        """Append one redacted event record and return it."""

        if event not in VALID_EVENT_TYPES:
            raise ValueError(f"Unsupported agent trace event {event!r}")
        if not self.meta_path.exists():
            self.initialize()

        with _event_file_lock(self.events_path):
            _validate_trace_run_identity(
                _read_json(self.meta_path),
                expected_run_id=self.run_id,
                meta_path=self.meta_path,
            )
            repair_jsonl_tail(self.events_path)
            sequence = _last_event_sequence(self.events_path) + 1
            record = AgentTraceEvent(
                schema=TRACE_SCHEMA,
                event=event,
                run_id=self.run_id,
                sequence=sequence,
                created_at=utc_now(),
                status=status,
                message=redact_text(message),
                metadata=redact_mapping(metadata or {}),
            )
            with self.events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        return record


def summarize_trace(path: Path | str) -> AgentTraceSummary:
    """Return a compact summary for a trace directory or events file."""

    candidate = Path(path).expanduser()
    root = candidate if candidate.is_dir() else candidate.parent
    meta = _read_json(root / META_FILENAME)
    events = load_trace_events(candidate)
    return AgentTraceSummary(
        run_id=str(meta.get("run_id") or (events[0].run_id if events else "")),
        agent=str(meta.get("agent") or ""),
        label=str(meta.get("label") or ""),
        event_count=len(events),
        events_path=root / EVENTS_FILENAME,
        meta_path=root / META_FILENAME,
        first_event=events[0].event if events else "",
        last_event=events[-1].event if events else "",
        status=events[-1].status if events else "",
    )


def trace_artifact_payload(root: Path | str) -> dict[str, Any]:
    """Return manifest-ready metadata for a trace directory."""

    root_path = Path(root).expanduser()
    events_path = root_path / EVENTS_FILENAME
    meta_path = root_path / META_FILENAME
    events = load_trace_events(events_path)
    return {
        "schema": TRACE_SCHEMA,
        "meta": str(meta_path),
        "events": str(events_path),
        "tool_output_dir": str(root_path / TOOL_OUTPUT_DIRNAME),
        "event_count": len(events),
        "event_types": [event.event for event in events],
        "exists": events_path.exists(),
    }


def validate_event_sequence(events: Sequence[AgentTraceEvent]) -> list[str]:
    """Return human-readable trace-sequence issues."""

    issues: list[str] = []
    expected = 1
    for event in events:
        if event.schema != TRACE_SCHEMA:
            issues.append(f"event {event.sequence}: unsupported schema {event.schema!r}")
        if event.event not in VALID_EVENT_TYPES:
            issues.append(f"event {event.sequence}: unsupported event {event.event!r}")
        if event.sequence != expected:
            issues.append(f"event {event.sequence}: expected sequence {expected}")
            expected = event.sequence
        expected += 1
    return issues
