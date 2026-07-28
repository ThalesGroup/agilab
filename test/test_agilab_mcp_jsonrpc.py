"""JSON-RPC conformance contract for the AGILAB MCP server.

Two distinctions matter to a calling agent:

* a malformed request must be told apart from a server fault, via the standard
  JSON-RPC error codes rather than a single catch-all;
* a tool that *ran and failed* must come back as a tool result flagged
  ``isError``, not as a JSON-RPC error. A JSON-RPC error says the request never
  executed, which a client may treat as a transport fault and hide from the
  model, costing it the chance to correct itself.
"""

from __future__ import annotations

import json

import pytest

from agilab_mcp import server


def _request(method: str, params: object | None = None, request_id: object = 1):
    payload: dict[str, object] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    return server.handle_jsonrpc(payload)


@pytest.mark.parametrize(
    "method, params, expected_code",
    [
        ("nope", None, server.JSONRPC_METHOD_NOT_FOUND),
        (
            "tools/call",
            {"name": "ghost", "arguments": {}},
            server.JSONRPC_INVALID_PARAMS,
        ),
        (
            "tools/call",
            {"name": "list_runs", "arguments": {"bogus": 1}},
            server.JSONRPC_INVALID_PARAMS,
        ),
        (
            "tools/call",
            {"name": "list_runs", "arguments": {}},
            server.JSONRPC_INVALID_PARAMS,
        ),
        ("tools/call", [1, 2], server.JSONRPC_INVALID_PARAMS),
        (
            "tools/call",
            {"name": "list_runs", "arguments": [1, 2]},
            server.JSONRPC_INVALID_PARAMS,
        ),
    ],
)
def test_protocol_faults_use_standard_codes(method, params, expected_code):
    response = _request(method, params)

    assert response is not None
    assert response["error"]["code"] == expected_code
    # The catch-all must no longer stand in for request-shape problems.
    assert response["error"]["code"] != server.JSONRPC_SERVER_ERROR


def test_tool_failure_is_a_tool_result_not_a_protocol_error(tmp_path, monkeypatch):
    """A tool that runs and raises reports isError so the model can react."""

    monkeypatch.setenv("AGILAB_MCP_ALLOWED_ROOTS", str(tmp_path))
    response = _request(
        "tools/call",
        {"name": "read_manifest", "arguments": {"manifest_path": "/etc/passwd"}},
    )

    assert response is not None
    assert "error" not in response
    result = response["result"]
    assert result["isError"] is True
    assert "outside configured read roots" in result["content"][0]["text"]


def test_successful_tool_call_has_no_error_flag():
    response = _request("tools/call", {"name": "agent_quickstart", "arguments": {}})

    assert response is not None
    result = response["result"]
    assert "isError" not in result
    payload = json.loads(result["content"][0]["text"])
    assert payload["mcp_tools"]


def test_parse_and_invalid_request_codes_are_distinct():
    assert server.JSONRPC_PARSE_ERROR == -32700
    assert server.JSONRPC_INVALID_REQUEST == -32600
    assert server.JSONRPC_METHOD_NOT_FOUND == -32601
    assert server.JSONRPC_INVALID_PARAMS == -32602
    assert server.JSONRPC_INTERNAL_ERROR == -32603


def test_notifications_still_receive_no_response():
    assert server.handle_jsonrpc({"jsonrpc": "2.0", "method": "tools/list"}) is None
    assert (
        server.handle_jsonrpc(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "id": 9}
        )
        is None
    )


def test_tools_list_and_initialize_remain_plain_results():
    listed = _request("tools/list")
    assert listed is not None and "error" not in listed
    assert listed["result"]["tools"]

    initialized = _request("initialize")
    assert initialized is not None and "error" not in initialized
    assert initialized["result"]["serverInfo"]["name"] == "agilab-mcp"
