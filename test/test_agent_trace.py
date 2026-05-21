from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path


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
                "{not-json",
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
