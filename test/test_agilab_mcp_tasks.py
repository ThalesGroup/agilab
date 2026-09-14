"""MCP selects registered tasks but cannot register, approve or replay commands."""

import io
import json
import shutil
import time

import pytest

from agilab.agent_runtime.experiment_demo import demo_source
from agilab.agent_runtime.experiment import prepare_experiment
from agilab.agent_runtime.tasks import TaskStore
from agilab_mcp import server


def setup(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(demo_source(), source)
    root = tmp_path / "store"
    prepare_experiment(
        source_root=source,
        output_dir=root / "experiments/demo",
        files=["candidate.py", "grader.py", "inputs.json"],
        entrypoint="candidate.py",
        grader="grader.py",
        outputs=["result.json"],
        checks=["finite_mean", "missing_values_excluded"],
    )
    store = TaskStore(root)
    store.register("demo", "experiments/demo")
    return store


def call(session, name, **arguments):
    return server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        session=session,
    )


def test_opt_in_session_does_not_leak_to_default_tools(tmp_path):
    store = setup(tmp_path)
    enabled = server.ProtocolSession(task_store=store)
    default = server.ProtocolSession()
    enabled.version = "2025-11-25"
    names = {d["name"] for d in enabled.descriptors()}
    assert {"submit_agent_task", "start_agent_task", "cancel_agent_task"} <= names
    assert not any(
        name in names
        for name in (
            "approve_agent_task",
            "register_action",
            "retry_agent_task",
            "shell",
        )
    )
    assert "submit_agent_task" not in {d["name"] for d in default.descriptors()}
    assert "submit_agent_task" not in server.TOOLS
    assert (
        call(default, "submit_agent_task", action_id="demo", idempotency_key="key")[
            "error"
        ]["code"]
        == -32602
    )
    quickstart = call(enabled, "agent_quickstart")["result"]["structuredContent"]
    assert quickstart["task_boundary"]["approval_tools_enabled"] is False
    assert quickstart["task_boundary"]["execution_tools_enabled"] is True
    assert call(default, "agent_quickstart")["result"]["content"]
    assert server.server_manifest()["policy"]["read_only"]
    assert not server.server_manifest(store)["policy"]["read_only"]
    for d in enabled.descriptors():
        if d["name"] in {"submit_agent_task", "start_agent_task", "cancel_agent_task"}:
            assert d["annotations"]["readOnlyHint"] is False
            assert d["inputSchema"]["additionalProperties"] is False


def test_selected_task_round_trip_requires_local_digest_approval(tmp_path):
    store = setup(tmp_path)
    session = server.ProtocolSession(task_store=store)
    session.version = "2025-11-25"
    for action in ("missing", "../source/candidate.py"):
        assert call(
            session, "submit_agent_task", action_id=action, idempotency_key="key"
        )["result"]["isError"]
    invalid = call(
        session,
        "submit_agent_task",
        action_id="demo",
        idempotency_key="key",
        command="touch arbitrary",
    )
    assert invalid["error"]["code"] == -32602
    response = call(
        session, "submit_agent_task", action_id="demo", idempotency_key="key"
    )["result"]
    state = response["structuredContent"]
    assert json.loads(response["content"][0]["text"]) == state
    assert call(session, "start_agent_task", task_id=state["task_id"], attempt=1)[
        "result"
    ]["isError"]
    assert not (
        store.root / f"experiments/demo/attempts/{state['attempt_id']}"
    ).exists()
    store.decide(
        state["task_id"],
        plan_sha256=state["plan_sha256"],
        attempt=state["attempt"],
        approve=True,
    )
    assert (
        "isError"
        not in call(session, "start_agent_task", task_id=state["task_id"], attempt=1)[
            "result"
        ]
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        current = call(session, "read_agent_task", task_id=state["task_id"])["result"][
            "structuredContent"
        ]
        if current["status"] != "queued" and current["status"] != "running":
            break
        time.sleep(0.02)
    assert current["status"] == "completed"
    assert current["receipt"]["sha256"]
    again = call(session, "submit_agent_task", action_id="demo", idempotency_key="key")[
        "result"
    ]["structuredContent"]
    assert again == current


def test_stdio_and_cli_enabling_are_explicit(tmp_path, capsys):
    store = setup(tmp_path)
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
    output = io.StringIO()
    server.serve_stdio(
        stdin=io.StringIO(request),
        stdout=output,
        stderr=io.StringIO(),
        task_store=store,
    )
    names = {t["name"] for t in json.loads(output.getvalue())["result"]["tools"]}
    assert "submit_agent_task" in names
    assert server.main(["serve", "--task-root", str(store.root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "registered-experiments"
    with pytest.raises(ValueError, match="cannot be combined"):
        server.main(["serve", "--task-root", str(store.root), "--read-only", "--json"])
