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
import time
from typing import Any, Mapping, Sequence

from agilab.secret_uri import redact_mapping, redact_text


TRACE_SCHEMA = "agilab.agent_trace.v1"
META_FILENAME = "agent_trace_meta.json"
EVENTS_FILENAME = "agent_events.ndjson"
TOOL_OUTPUT_DIRNAME = "tool-output"
LOCK_TIMEOUT_SECONDS = 5.0
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


@contextmanager
def _event_file_lock(path: Path):
    lock_path = path.with_name(path.name + ".lock")
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for agent trace lock: {lock_path}")
            time.sleep(0.01)
    try:
        yield
    finally:
        os.close(fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def load_trace_events(path: Path | str) -> list[AgentTraceEvent]:
    """Load events from an ``agent_events.ndjson`` file or a trace directory."""

    candidate = Path(path).expanduser()
    events_path = candidate / EVENTS_FILENAME if candidate.is_dir() else candidate
    if not events_path.exists():
        return []

    events: list[AgentTraceEvent] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict):
            events.append(_event_from_mapping(payload))
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
        if self.meta_path.exists():
            return _read_json(self.meta_path)

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
        self.meta_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
