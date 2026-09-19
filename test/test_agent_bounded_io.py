"""Real-process and large-trace regressions for bounded agent evidence."""

import json
import os
import sys
import subprocess

import pytest

from agilab.agent_runtime.agent_trace import AgentTraceStore, trace_page, trace_tail
from agilab.agent_runtime.process_capture import capture_command
from agilab.agent_runtime import agent_run
from agilab_mcp.server import ProtocolSession, handle_jsonrpc, tool_descriptors


def test_trace_pages_bound_output_and_resume_without_duplicates(tmp_path):
    store = AgentTraceStore(tmp_path, run_id="paged")
    for i in range(125):
        store.append("tool_output", message=("x" * 4000 if i == 0 else str(i)))
    cursor = ""
    sequences = []
    while True:
        page = trace_page(tmp_path, cursor=cursor, limit=7, max_bytes=2048)
        assert len(json.dumps(page).encode()) <= 2048
        sequences.extend(e["sequence"] for e in page["events"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert sequences == list(range(1, 126))
    tail = trace_tail(tmp_path)
    assert tail["event_count"] == 125
    assert tail["omitted_events"] == 105
    assert tail["events"][-1]["sequence"] == 125


def test_trace_cursor_rejects_replaced_or_truncated_file(tmp_path):
    store = AgentTraceStore(tmp_path, run_id="paged")
    store.append("session_start")
    store.append("session_end")
    cursor = trace_page(tmp_path, limit=1)["next_cursor"]
    store.events_path.write_text("")
    with pytest.raises(ValueError, match="Stale or invalid"):
        trace_page(tmp_path, cursor=cursor)


def test_trace_page_budget_counts_escaped_unicode(tmp_path):
    store = AgentTraceStore(tmp_path, run_id="unicode")
    store.append("tool_output", message="😀" * 10000, status="😀" * 10000)
    page = trace_page(tmp_path, max_bytes=2048)
    assert len(json.dumps(page).encode()) <= 2048
    assert page["truncated"]
    assert len(json.dumps(trace_tail(tmp_path)).encode()) < 2048


def test_truncated_trace_event_keeps_status_redacted(tmp_path):
    store = AgentTraceStore(tmp_path, run_id="status-secret")
    store.append(
        "tool_output", message="x" * 10000, status="OPENAI_API_KEY=private-value"
    )
    assert "private-value" not in json.dumps(trace_page(tmp_path, max_bytes=2048))


def test_mcp_expands_directory_events_before_boundary_check(tmp_path, monkeypatch):
    from agilab_mcp import manifest_tools

    root, external = tmp_path / "allowed", tmp_path / "external"
    root.mkdir()
    external.mkdir()
    run = agent_run.trace_agent_run(
        [sys.executable, "-c", "print('safe')"],
        cwd=root,
        output_dir=root / "run",
        permission_level="standard",
    )
    events = root / "nested"
    events.mkdir()
    (external / "agent_events.ndjson").write_text("external sentinel")
    (events / "agent_events.ndjson").symlink_to(external / "agent_events.ndjson")
    run.manifest["artifacts"]["agent_trace"]["events"] = str(events)
    manifest = root / "run" / agent_run.MANIFEST_FILENAME
    manifest.write_text(json.dumps(run.manifest))
    monkeypatch.setenv("AGILAB_MCP_ALLOWED_ROOTS", str(root))
    for tool in (
        manifest_tools.read_agent_trace,
        manifest_tools.agent_handoff,
        manifest_tools.validate_agent_run,
    ):
        with pytest.raises(ValueError, match="outside configured read roots"):
            tool(str(manifest))


def test_inherited_descendant_pipe_cannot_be_reported_as_complete_success(tmp_path):
    script = "import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(.5)'])"
    result = capture_command(
        [sys.executable, "-c", script],
        cwd=str(tmp_path),
        env=os.environ.copy(),
        timeout=0.1,
        stdout_path=tmp_path / "out",
        stderr_path=tmp_path / "err",
    )
    assert result["returncode"] == 124
    assert result["termination"] == "timeout"


def test_trace_crash_tail_does_not_produce_an_endless_next_cursor(tmp_path):
    store = AgentTraceStore(tmp_path, run_id="partial")
    store.append("session_start")
    with store.events_path.open("ab") as stream:
        stream.write(b'{"schema":')
    page = trace_page(tmp_path)
    assert page["incomplete_tail"]
    assert page["next_cursor"] is None
    assert not page["has_more"]
    assert page["resume_cursor"]


def test_capture_redacts_multiline_bearer(tmp_path):
    secret = "abcdefghij01234567890123456789"
    result = capture_command(
        [sys.executable, "-c", f"print('Authorization: Bearer\\n\\n{secret}')"],
        cwd=str(tmp_path),
        env=os.environ.copy(),
        timeout=5,
        stdout_path=tmp_path / "out",
        stderr_path=tmp_path / "err",
    )
    assert result["returncode"] == 0
    assert secret not in (tmp_path / "out").read_text()


def test_capture_redacts_split_secret_and_caps_noisy_streams(tmp_path):
    script = """import os, time
os.write(1, b'OPENAI_API_KEY=sk-')
time.sleep(.05)
os.write(1, b'secret-value-12345678901234567890\\n')
os.write(2, b'z' * 100000 + b'\\n')
for _ in range(10000): os.write(1, b'ordinary line\\n')
"""
    result = capture_command(
        [sys.executable, "-c", script],
        cwd=str(tmp_path),
        env=os.environ.copy(),
        timeout=5,
        stdout_path=tmp_path / "out",
        stderr_path=tmp_path / "err",
        max_log_bytes=2048,
    )
    assert result["returncode"] == 0
    assert (tmp_path / "out").stat().st_size <= 2048
    assert "secret-value" not in (tmp_path / "out").read_text()
    assert "oversized output line omitted" in (tmp_path / "err").read_text()
    assert result["streams"]["stdout"]["truncated"]
    assert result["streams"]["stderr"]["oversized_lines"] == 1


def test_capture_timeout_keeps_partial_evidence(tmp_path):
    result = capture_command(
        [
            sys.executable,
            "-c",
            "import time; print('before timeout', flush=True); time.sleep(10)",
        ],
        cwd=str(tmp_path),
        env=os.environ.copy(),
        timeout=0.2,
        stdout_path=tmp_path / "out",
        stderr_path=tmp_path / "err",
    )
    assert result["returncode"] == 124
    assert "before timeout" in (tmp_path / "out").read_text()


def test_capture_inherits_piped_input(tmp_path):
    script = f"""import os, sys
from pathlib import Path
from agilab.agent_runtime.process_capture import capture_command
root = Path({str(tmp_path)!r})
result = capture_command([sys.executable, '-c', 'print(input())'], cwd=str(root),
    env=os.environ.copy(), timeout=5, stdout_path=root/'out', stderr_path=root/'err')
sys.exit(result['returncode'])
"""
    env = os.environ.copy()
    from pathlib import Path

    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run(
        [sys.executable, "-c", script],
        input="piped value\n",
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "piped value" in (tmp_path / "out").read_text()


def test_late_publication_failure_keeps_stream_omission_metadata(tmp_path, monkeypatch):
    original_capture = agent_run.capture_command
    monkeypatch.setattr(
        agent_run,
        "capture_command",
        lambda *args, **kwargs: original_capture(*args, **kwargs, max_log_bytes=1024),
    )
    original_write = agent_run._atomic_write_text
    failed = False

    def fail_once(path, text):
        nonlocal failed
        if path.name == agent_run.MANIFEST_FILENAME and not failed:
            failed = True
            raise OSError("injected publication error")
        return original_write(path, text)

    monkeypatch.setattr(agent_run, "_atomic_write_text", fail_once)
    result = agent_run.trace_agent_run(
        [sys.executable, "-c", "print('row\\n' * 1000)"],
        cwd=tmp_path,
        output_dir=tmp_path / "run",
        permission_level="standard",
    )
    assert result.returncode == 125
    assert result.manifest["output_capture"]["stdout"]["truncated"]
    assert (tmp_path / "run" / "stdout.txt").stat().st_size > 0
    assert agent_run.validate_agent_run(tmp_path / "run")["ok"]


def _request(session, method, params):
    return handle_jsonrpc(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, session=session
    )


def test_mcp_negotiation_is_connection_local():
    legacy, modern = ProtocolSession(), ProtocolSession()
    response = _request(modern, "initialize", {"protocolVersion": "2025-11-25"})
    assert response["result"]["protocolVersion"] == "2025-11-25"
    for session, expected in [(legacy, False), (modern, True)]:
        result = _request(session, "tools/call", {"name": "agent_quickstart"})["result"]
        assert ("structuredContent" in result) is expected
        if expected:
            assert result["structuredContent"] == json.loads(
                result["content"][0]["text"]
            )
        descriptors = _request(session, "tools/list", {})["result"]["tools"]
        assert all(("outputSchema" in d) is expected for d in descriptors)
    assert all(d["annotations"]["readOnlyHint"] for d in tool_descriptors())


@pytest.mark.parametrize(
    "arguments",
    [
        {"limit": True},
        {"limit": -1},
        {"limit": 101},
        {"log_root": []},
        {"metadata": {"k": 3}},
        False,
        [],
    ],
)
def test_mcp_checks_schema_before_tool_execution(arguments):
    response = _request(
        ProtocolSession(),
        "tools/call",
        {"name": "list_agent_runs", "arguments": arguments},
    )
    assert response["error"]["code"] == -32602


def test_mcp_schema_errors_redact_and_bound_untrusted_keys():
    key = "OPENAI_API_KEY=private-value " + "x" * 10000
    response = _request(
        ProtocolSession(),
        "tools/call",
        {"name": "list_agent_runs", "arguments": {"metadata": {key: 1}}},
    )
    text = response["error"]["message"]
    assert "private-value" not in text
    assert len(text) < 1100
    assert text.endswith("[truncated]")
