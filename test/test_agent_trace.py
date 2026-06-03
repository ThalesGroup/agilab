from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SECRET_MODULE_PATH = ROOT / "src" / "agilab" / "secret_uri.py"
MODULE_PATH = ROOT / "src" / "agilab" / "agent_trace.py"


def _load_secret_module() -> object:
    spec = importlib.util.spec_from_file_location("agilab.secret_uri", SECRET_MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_module():
    previous_package = sys.modules.get("agilab")
    previous_secret = sys.modules.get("agilab.secret_uri")
    sys.modules.pop("agilab.agent_trace", None)
    package = types.ModuleType("agilab")
    package.__path__ = [str(ROOT / "src" / "agilab")]  # type: ignore[attr-defined]
    package.__file__ = str(ROOT / "src" / "agilab" / "__init__.py")
    package.__package__ = "agilab"
    sys.modules["agilab"] = package
    _load_secret_module()
    spec = importlib.util.spec_from_file_location("agilab.agent_trace", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous_secret is None:
            sys.modules.pop("agilab.secret_uri", None)
        else:
            sys.modules["agilab.secret_uri"] = previous_secret
        if previous_package is None:
            sys.modules.pop("agilab", None)
        else:
            sys.modules["agilab"] = previous_package
    return module


def test_agent_trace_store_writes_redacted_append_only_events(tmp_path: Path) -> None:
    module = _load_module()
    store = module.AgentTraceStore(
        tmp_path,
        run_id="agent-run",
        agent="codex",
        label="Review",
        provider="openai",
        model="gpt-5",
    )

    meta = store.initialize({"OPENAI_API_KEY": "sk-secret", "safe": "visible"})
    start = store.append("session_start", message="using env://OPENAI_API_KEY")
    done = store.append(
        "tool_done",
        status="pass",
        message="OPENAI_API_KEY=sk-secret",
        metadata={"token": "sk-secret", "safe": "ok"},
    )

    raw = store.events_path.read_text(encoding="utf-8")
    loaded = module.load_trace_events(tmp_path)
    summary = module.summarize_trace(tmp_path)
    artifact = module.trace_artifact_payload(tmp_path)

    assert meta["schema"] == module.TRACE_SCHEMA
    assert meta["metadata"]["OPENAI_API_KEY"] == "<redacted>"
    assert start.sequence == 1
    assert done.sequence == 2
    assert [event.event for event in loaded] == ["session_start", "tool_done"]
    assert loaded[0].message == "using <secret-ref>"
    assert loaded[1].metadata["token"] == "<redacted>"
    assert "sk-secret" not in raw
    assert summary.event_count == 2
    assert summary.last_event == "tool_done"
    assert artifact["event_count"] == 2
    assert artifact["event_types"] == ["session_start", "tool_done"]


def test_agent_trace_store_reuses_existing_meta_and_auto_initializes(tmp_path: Path) -> None:
    module = _load_module()
    store = module.AgentTraceStore(tmp_path, run_id="agent-run", agent="codex")

    first_meta = store.initialize({"safe": "visible"})
    second_meta = store.initialize({"ignored": "after-create"})
    event = store.append("session_start", status="pass")

    assert second_meta == first_meta
    assert second_meta["metadata"] == {"safe": "visible"}
    assert event.sequence == 1

    lazy_root = tmp_path / "lazy"
    lazy_store = module.AgentTraceStore(lazy_root, run_id="lazy-run")
    lazy_event = lazy_store.append("session_start")

    assert lazy_event.sequence == 1
    assert lazy_store.meta_path.exists()


def test_agent_trace_store_clears_stale_append_lock(tmp_path: Path) -> None:
    module = _load_module()
    store = module.AgentTraceStore(tmp_path, run_id="agent-run", agent="codex")
    store.initialize()
    lock_path = store.events_path.with_name(store.events_path.name + ".lock")
    lock_path.write_text('{"host": "stale", "pid": -1}', encoding="utf-8")
    old_timestamp = 1.0
    lock_path.touch()
    lock_path.chmod(0o600)

    os.utime(lock_path, (old_timestamp, old_timestamp))

    event = store.append("session_start", message="after stale lock")

    assert event.sequence == 1
    assert not lock_path.exists()
    assert module.load_trace_events(tmp_path)[0].message == "after stale lock"


def test_agent_trace_rejects_unknown_events_and_validates_sequence(tmp_path: Path) -> None:
    module = _load_module()
    store = module.AgentTraceStore(tmp_path, run_id="run")

    try:
        store.append("not-real")
    except ValueError as exc:
        assert "Unsupported agent trace event" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unknown event should fail")

    broken = [
        module.AgentTraceEvent(
            schema=module.TRACE_SCHEMA,
            event="session_start",
            run_id="run",
            sequence=1,
            created_at="now",
            status="running",
            message="",
            metadata={},
        ),
        module.AgentTraceEvent(
            schema="other",
            event="unknown",
            run_id="run",
            sequence=3,
            created_at="now",
            status="running",
            message="",
            metadata={},
        ),
    ]

    issues = module.validate_event_sequence(broken)

    assert any("unsupported schema" in issue for issue in issues)
    assert any("unsupported event" in issue for issue in issues)
    assert any("expected sequence 2" in issue for issue in issues)


def test_load_trace_events_ignores_invalid_lines(tmp_path: Path) -> None:
    module = _load_module()
    events_path = tmp_path / module.EVENTS_FILENAME
    events_path.write_text(
        "\n".join(
            [
                "",
                "{not-json",
                json.dumps(["not", "an", "event"]),
                json.dumps(
                    {
                        "schema": module.TRACE_SCHEMA,
                        "event": "session_start",
                        "run_id": "run",
                        "sequence": 1,
                        "created_at": "now",
                        "status": "running",
                        "message": "",
                        "metadata": {},
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    assert [event.sequence for event in module.load_trace_events(tmp_path)] == [1]


def test_agent_trace_summaries_tolerate_missing_or_invalid_files(tmp_path: Path) -> None:
    module = _load_module()
    trace_root = tmp_path / "trace"
    trace_root.mkdir()
    (trace_root / module.META_FILENAME).write_text("{not json", encoding="utf-8")

    summary = module.summarize_trace(trace_root)
    artifact = module.trace_artifact_payload(trace_root)

    assert summary.run_id == ""
    assert summary.event_count == 0
    assert summary.first_event == ""
    assert summary.status == ""
    assert artifact["event_count"] == 0
    assert artifact["event_types"] == []
    assert artifact["exists"] is False


def test_agent_trace_lock_and_sequence_edge_cases(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    events_path = tmp_path / module.EVENTS_FILENAME
    events_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "schema": module.TRACE_SCHEMA,
                        "event": "session_start",
                        "run_id": "run",
                        "sequence": 4,
                        "created_at": "now",
                        "status": "running",
                        "message": "",
                        "metadata": {},
                    }
                ),
                "{not-json",
            ]
        ),
        encoding="utf-8",
    )
    assert module._last_event_sequence(events_path) == 4

    events_path.write_text(json.dumps({"sequence": "bad"}) + "\n", encoding="utf-8")
    assert module._last_event_sequence(events_path) == 0
    events_path.write_text(json.dumps(["not", "mapping"]) + "\n", encoding="utf-8")
    assert module._last_event_sequence(events_path) == 0

    same_host = {"host": module.socket.gethostname(), "pid": str(os.getpid())}
    assert module._lock_owner_alive({"host": "other", "pid": os.getpid()}) is None
    assert module._lock_owner_alive({"host": module.socket.gethostname(), "pid": "bad"}) is None
    assert module._lock_owner_alive({"host": module.socket.gethostname(), "pid": 0}) is None
    assert module._lock_owner_alive(same_host) is True

    def process_missing(_pid, _signal):
        raise ProcessLookupError

    monkeypatch.setattr(module.os, "kill", process_missing)
    assert module._lock_owner_alive(same_host) is False

    def process_forbidden(_pid, _signal):
        raise PermissionError

    monkeypatch.setattr(module.os, "kill", process_forbidden)
    assert module._lock_owner_alive(same_host) is True

    def process_unknown(_pid, _signal):
        raise OSError

    monkeypatch.setattr(module.os, "kill", process_unknown)
    assert module._lock_owner_alive(same_host) is None

    lock_path = tmp_path / "events.lock"
    lock_path.write_text("{not-json", encoding="utf-8")
    assert module._read_lock_payload(lock_path) == {}
    assert module._lock_is_stale(lock_path, now=lock_path.stat().st_mtime + module.LOCK_STALE_SECONDS) is True

    monkeypatch.setattr(module, "_lock_owner_alive", lambda _payload: True)
    assert module._lock_is_stale(lock_path, now=lock_path.stat().st_mtime + 999) is False
    assert module._clear_stale_lock(lock_path) is False


def test_agent_trace_event_lock_timeout_and_finally_edges(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    events_path = tmp_path / module.EVENTS_FILENAME
    events_path.touch()
    lock_path = events_path.with_name(events_path.name + ".lock")
    lock_path.write_text("{}", encoding="utf-8")

    monotonic_values = iter([0.0, module.LOCK_TIMEOUT_SECONDS + 1.0])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(module, "_clear_stale_lock", lambda _path: False)

    with pytest.raises(TimeoutError, match="Timed out waiting"):
        with module._event_file_lock(events_path):
            pass

    lock_path.unlink()
    monkeypatch.setattr(module.time, "monotonic", lambda: 0.0)
    original_unlink = module.Path.unlink

    def unlink_missing(self):
        if self == lock_path:
            raise FileNotFoundError
        return original_unlink(self)

    monkeypatch.setattr(module.Path, "unlink", unlink_missing)
    with module._event_file_lock(events_path):
        assert lock_path.exists()
