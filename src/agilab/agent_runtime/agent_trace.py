# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Append-only evidence traces for AGILAB agent and tool runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import base64
import hashlib
from collections import deque
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


MAX_TRACE_RECORD_BYTES = 1024 * 1024


def _events_path(path: Path | str) -> Path:
    candidate = Path(path).expanduser()
    return candidate / EVENTS_FILENAME if candidate.is_dir() else candidate


def _read_event(handle, path: Path):
    raw = handle.readline(MAX_TRACE_RECORD_BYTES + 1)
    if not raw:
        return None
    if len(raw) > MAX_TRACE_RECORD_BYTES:
        raise ValueError(f"Agent trace record exceeds {MAX_TRACE_RECORD_BYTES} bytes: {path}")
    if not raw.strip():
        return False
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        if not raw.endswith(b"\n"):
            return None  # Only an unterminated crash tail is tolerated.
        raise ValueError(f"Invalid agent trace JSONL record: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Agent trace JSONL record must be an object: {path}")
    try:
        return _event_from_mapping(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid agent trace event record: {path}") from exc


def iter_trace_events(path: Path | str):
    """Stream records with a 1 MiB per-record memory limit."""
    events_path = _events_path(path)
    if not events_path.exists():
        return
    with events_path.open("rb") as handle:
        index = 0
        while True:
            index += 1
            try:
                event = _read_event(handle, events_path)
            except ValueError as exc:
                raise ValueError(f"Invalid agent trace record {index}: {exc}") from exc
            if event is None:
                break
            if event is not False:
                yield event


def load_trace_events(path: Path | str) -> list[AgentTraceEvent]:
    """Compatibility reader; use trace pages for agent-facing requests."""
    return list(iter_trace_events(path))


def trace_tail(path: Path | str, *, limit: int = 20) -> dict[str, Any]:
    """Return bounded recent messages while counting the complete trace."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")
    events = deque(maxlen=limit)
    count = 0
    for event in iter_trace_events(path):
        count += 1
        message = redact_text(event.message)
        item = {"sequence": event.sequence, "event": redact_text(event.event),
                "status": redact_text(event.status), "message": message,
                "message_truncated": False}
        for key, budget in (("event", 128), ("status", 128), ("message", 512)):
            while len(json.dumps(item[key]).encode()) > budget:
                item[key] = item[key][:len(item[key]) // 2]
                item["message_truncated"] = True
        events.append(item)
    return {"event_count": count, "events": list(events),
            "omitted_events": count - len(events),
            "truncated": count > len(events) or any(e["message_truncated"] for e in events)}


def _cursor(handle, offset: int) -> str:
    handle.seek(max(0, offset - 64))
    anchor = hashlib.sha256(handle.read(min(offset, 64))).hexdigest()
    stat = os.fstat(handle.fileno())
    payload = [offset, stat.st_dev, stat.st_ino, anchor]
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def trace_page(path: Path | str, *, cursor: str = "", limit: int = 50,
               max_bytes: int = 32768) -> dict[str, Any]:
    """Read a byte-bounded page. Cursors detect replaced or truncated traces.

    The cursor is a continuation marker, not an authenticity credential.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")
    if type(max_bytes) is not int or not 2048 <= max_bytes <= 65536:
        raise ValueError("max_bytes must be an integer between 2048 and 65536")
    events_path = _events_path(path)
    events = []
    # Reserve space for the envelope and cursor, including JSON escaping.
    remaining = max_bytes - 768
    with events_path.open("rb") as handle:
        offset = 0
        incomplete_tail = False
        if cursor:
            try:
                fields = json.loads(base64.urlsafe_b64decode(cursor))
                offset = fields[0]
                if type(offset) is not int or offset < 0 or offset > os.fstat(handle.fileno()).st_size:
                    raise ValueError("offset")
                if _cursor(handle, offset) != cursor:
                    raise ValueError("identity or anchor")
                if offset:
                    handle.seek(offset - 1)
                    if handle.read(1) != b"\n":
                        raise ValueError("record boundary")
            except (ValueError, TypeError, IndexError, KeyError) as exc:
                raise ValueError("Stale or invalid trace cursor; restart pagination") from exc
        handle.seek(offset)
        for _ in range(limit):
            before = handle.tell()
            event = _read_event(handle, events_path)
            if event is None:
                handle.seek(before)  # An append can complete a crash tail later.
                incomplete_tail = bool(handle.read(1))
                handle.seek(before)
                break
            if event is False:
                continue
            item = redact_mapping(asdict(event))
            encoded = json.dumps(item, ensure_ascii=True).encode()
            if len(encoded) > remaining and events:
                handle.seek(before)
                break
            if len(encoded) > remaining:
                item = {"sequence": event.sequence, "event": item["event"],
                        "status": item["status"], "message": item["message"][:128],
                        "truncated": True, "omitted_bytes": len(encoded)}
                encoded = json.dumps(item, ensure_ascii=True).encode()
                while len(encoded) > remaining:
                    key = max(("event", "status", "message"), key=lambda k: len(item[k]))
                    if not item[key]:
                        raise ValueError("Trace event identifier exceeds the response budget")
                    item[key] = item[key][:len(item[key]) // 2]
                    encoded = json.dumps(item, ensure_ascii=True).encode()
            events.append(item)
            remaining -= len(encoded) + 2
            if remaining < 1024:
                break
        offset = handle.tell()
        has_more = bool(handle.read(1)) and not incomplete_tail
        next_cursor = _cursor(handle, offset) if has_more else None
        resume_cursor = _cursor(handle, offset) if incomplete_tail else None
    return {"schema": "agilab.agent_trace_page.v1", "events": events,
            "returned_events": len(events), "next_cursor": next_cursor,
            "has_more": has_more, "max_bytes": max_bytes,
            "incomplete_tail": incomplete_tail, "resume_cursor": resume_cursor,
            "truncated": any(e.get("truncated", False) for e in events)}


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
    first = last = None
    count = 0
    for event in iter_trace_events(candidate):
        first = first or event
        last = event
        count += 1
    return AgentTraceSummary(
        run_id=str(meta.get("run_id") or (first.run_id if first else "")),
        agent=str(meta.get("agent") or ""),
        label=str(meta.get("label") or ""),
        event_count=count,
        events_path=root / EVENTS_FILENAME,
        meta_path=root / META_FILENAME,
        first_event=first.event if first else "",
        last_event=last.event if last else "",
        status=last.status if last else "",
    )


def trace_artifact_payload(root: Path | str) -> dict[str, Any]:
    """Return manifest-ready metadata for a trace directory."""

    root_path = Path(root).expanduser()
    events_path = root_path / EVENTS_FILENAME
    meta_path = root_path / META_FILENAME
    event_types = []
    count = 0
    for event in iter_trace_events(events_path):
        count += 1
        if len(event_types) < 128:
            event_types.append(event.event)
    return {
        "schema": TRACE_SCHEMA,
        "meta": str(meta_path),
        "events": str(events_path),
        "tool_output_dir": str(root_path / TOOL_OUTPUT_DIRNAME),
        "event_count": count,
        "event_types": event_types,
        "omitted_event_types": max(0, count - len(event_types)),
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
