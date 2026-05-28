"""Minimal read-only MCP-style stdio server for AGILAB evidence."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable, Mapping

from agilab_mcp import manifest_tools


ToolFn = Callable[..., dict[str, Any]]

TOOLS: dict[str, ToolFn] = {
    "list_projects": manifest_tools.list_projects,
    "list_runs": manifest_tools.list_runs,
    "list_agent_runs": manifest_tools.list_agent_runs,
    "read_agent_run": manifest_tools.read_agent_run,
    "summarize_agent_run": manifest_tools.summarize_agent_run,
    "agent_handoff": manifest_tools.agent_handoff,
    "agent_next_actions": manifest_tools.agent_next_actions,
    "agent_context": manifest_tools.agent_context,
    "agent_lineage": manifest_tools.agent_lineage,
    "compare_agent_runs": manifest_tools.compare_agent_runs,
    "validate_agent_run": manifest_tools.validate_agent_run,
    "read_manifest": manifest_tools.read_manifest,
    "summarize_run": manifest_tools.summarize_run,
    "list_artifacts": manifest_tools.list_artifacts,
    "compare_runs": manifest_tools.compare_runs,
    "export_quarto_report": manifest_tools.export_quarto_report,
}


def tool_descriptors() -> list[dict[str, Any]]:
    return [
        {
            "name": "list_projects",
            "description": "List AGILAB project directories under an apps root.",
            "inputSchema": {
                "type": "object",
                "properties": {"apps_root": {"type": "string"}},
                "required": ["apps_root"],
            },
        },
        {
            "name": "list_runs",
            "description": "List AGILAB run_manifest.json files under a log root.",
            "inputSchema": {
                "type": "object",
                "properties": {"log_root": {"type": "string"}},
                "required": ["log_root"],
            },
        },
        {
            "name": "list_agent_runs",
            "description": "List redacted AGILAB agent-run evidence manifests.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "log_root": {"type": "string"},
                    "agent": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["", "planned", "pass", "fail", "timeout", "denied"],
                    },
                    "tag": {"type": "string"},
                    "metadata": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                    },
                    "protocol_adapter": {"type": "string"},
                    "capability": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 0},
                },
            },
        },
        {
            "name": "read_agent_run",
            "description": "Read and redact one AGILAB agent-run manifest.",
            "inputSchema": {
                "type": "object",
                "properties": {"manifest_path": {"type": "string"}},
                "required": ["manifest_path"],
            },
        },
        {
            "name": "summarize_agent_run",
            "description": "Summarize one AGILAB agent-run manifest.",
            "inputSchema": {
                "type": "object",
                "properties": {"manifest_path": {"type": "string"}},
                "required": ["manifest_path"],
            },
        },
        {
            "name": "agent_handoff",
            "description": "Render a compact AGILAB agent-run continuation card.",
            "inputSchema": {
                "type": "object",
                "properties": {"manifest_path": {"type": "string"}},
                "required": ["manifest_path"],
            },
        },
        {
            "name": "agent_next_actions",
            "description": "Render deterministic next-action guidance from AGILAB agent-run evidence.",
            "inputSchema": {
                "type": "object",
                "properties": {"manifest_path": {"type": "string"}},
                "required": ["manifest_path"],
            },
        },
        {
            "name": "agent_context",
            "description": "Build a safe AGILAB agent context pack from matching agent-run evidence.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "log_root": {"type": "string"},
                    "agent": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["", "planned", "pass", "fail", "timeout", "denied"],
                    },
                    "tag": {"type": "string"},
                    "metadata": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                    },
                    "protocol_adapter": {"type": "string"},
                    "capability": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 0},
                },
            },
        },
        {
            "name": "agent_lineage",
            "description": "Build a follow-up lineage graph from AGILAB agent-run evidence.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "log_root": {"type": "string"},
                    "run_id": {"type": "string"},
                },
                "required": ["run_id"],
            },
        },
        {
            "name": "compare_agent_runs",
            "description": "Compare two AGILAB agent-run manifests without reading output contents.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "left_manifest": {"type": "string"},
                    "right_manifest": {"type": "string"},
                },
                "required": ["left_manifest", "right_manifest"],
            },
        },
        {
            "name": "validate_agent_run",
            "description": "Validate an AGILAB agent-run manifest for safe read-side reuse.",
            "inputSchema": {
                "type": "object",
                "properties": {"manifest_path": {"type": "string"}},
                "required": ["manifest_path"],
            },
        },
        {
            "name": "read_manifest",
            "description": "Read and redact one AGILAB run manifest.",
            "inputSchema": {
                "type": "object",
                "properties": {"manifest_path": {"type": "string"}},
                "required": ["manifest_path"],
            },
        },
        {
            "name": "summarize_run",
            "description": "Summarize one AGILAB run manifest.",
            "inputSchema": {
                "type": "object",
                "properties": {"manifest_path": {"type": "string"}},
                "required": ["manifest_path"],
            },
        },
        {
            "name": "list_artifacts",
            "description": "List artifacts recorded by one AGILAB run manifest.",
            "inputSchema": {
                "type": "object",
                "properties": {"manifest_path": {"type": "string"}},
                "required": ["manifest_path"],
            },
        },
        {
            "name": "compare_runs",
            "description": "Compare two AGILAB run manifests.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "left_manifest": {"type": "string"},
                    "right_manifest": {"type": "string"},
                },
                "required": ["left_manifest", "right_manifest"],
            },
        },
        {
            "name": "export_quarto_report",
            "description": "Export a Quarto report from one AGILAB run manifest.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "manifest_path": {"type": "string"},
                    "output_path": {"type": "string"},
                },
                "required": ["manifest_path", "output_path"],
            },
        },
    ]


def server_manifest() -> dict[str, Any]:
    return {
        "schema": "agilab.mcp.server.v1",
        "name": "agilab-mcp",
        "mode": "read-only",
        "tools": tool_descriptors(),
        "dangerous_tools": [],
        "policy": {
            "read_only": True,
            "local_files_only": True,
            "execution_tools_enabled": False,
            "shell_enabled": False,
        },
    }


def call_tool(name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    if name not in TOOLS:
        raise ValueError(f"Unknown AGILAB MCP tool: {name}")
    return TOOLS[name](**dict(arguments))


def _jsonrpc_response(
    request_id: Any, result: Any = None, error: Any = None, error_code: int = -32000
) -> dict[str, Any]:
    response = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        response["error"] = {"code": error_code, "message": str(error)}
    else:
        response["result"] = result
    return response


def handle_jsonrpc(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    method = payload.get("method")
    if "id" not in payload:
        # JSON-RPC notifications never receive responses. The server currently
        # has no notification side effects to perform.
        return None
    request_id = payload.get("id")
    try:
        if method == "initialize":
            return _jsonrpc_response(
                request_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "agilab-mcp", "version": "0.1.0"},
                },
            )
        if method == "tools/list":
            return _jsonrpc_response(request_id, {"tools": tool_descriptors()})
        if method == "tools/call":
            params = payload.get("params") or {}
            if not isinstance(params, Mapping):
                raise ValueError("tools/call params must be an object")
            result = call_tool(
                str(params.get("name", "")), params.get("arguments") or {}
            )
            return _jsonrpc_response(
                request_id,
                {
                    "content": [
                        {"type": "text", "text": json.dumps(result, sort_keys=True)}
                    ]
                },
            )
        if method == "notifications/initialized":
            return None
        raise ValueError(f"Unsupported method: {method}")
    except Exception as exc:
        return _jsonrpc_response(request_id, error=exc)


def serve_stdio(stdin: Any = sys.stdin, stdout: Any = sys.stdout) -> int:
    for line in stdin:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            response = _jsonrpc_response(
                None,
                error=f"Parse error: {exc.msg}",
                error_code=-32700,
            )
        else:
            if not isinstance(payload, Mapping):
                response = _jsonrpc_response(
                    None,
                    error="Invalid request",
                    error_code=-32600,
                )
            else:
                response = handle_jsonrpc(payload)
        if response is not None:
            stdout.write(json.dumps(response, sort_keys=True) + "\n")
            stdout.flush()
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Serve read-only AGILAB evidence tools."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve")
    serve.add_argument("--read-only", action="store_true", default=True)
    serve.add_argument(
        "--json",
        action="store_true",
        help="Print server metadata instead of serving stdio.",
    )
    serve.add_argument(
        "--once", action="store_true", help="Alias for --json for smoke tests."
    )
    tools = subparsers.add_parser("list-tools")
    tools.add_argument("--json", action="store_true")
    call = subparsers.add_parser("call-tool")
    call.add_argument("name")
    call.add_argument("--arguments", default="{}")
    call.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "serve":
        if args.json or args.once:
            print(json.dumps(server_manifest(), indent=2, sort_keys=True))
            return 0
        return serve_stdio()
    if args.command == "list-tools":
        payload = {"tools": tool_descriptors()}
        print(json.dumps(payload, indent=2 if args.json else None, sort_keys=True))
        return 0
    if args.command == "call-tool":
        payload = call_tool(args.name, json.loads(args.arguments))
        print(json.dumps(payload, indent=2 if args.json else None, sort_keys=True))
        return 0
    raise SystemExit(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
