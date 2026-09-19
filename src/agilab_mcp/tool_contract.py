"""The bounded JSON Schema subset emitted by AGILAB's dependency-free MCP server."""

from __future__ import annotations

from typing import Any


def validate_schema(
    value: Any, schema: dict[str, Any], path: str = "arguments"
) -> None:
    """Validate our own schemas; this is not a general JSON Schema engine."""
    kind = schema.get("type")
    expected = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "boolean": bool,
        "null": type(None),
    }
    kinds = kind if isinstance(kind, list) else [kind]
    if kind is not None and not any(type(value) is expected.get(k) for k in kinds):
        raise ValueError(f"{path} must have type {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} is not an allowed value")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                raise ValueError(f"{path}.{key} is required")
        for key, item in value.items():
            if key in properties:
                validate_schema(item, properties[key], f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                raise ValueError(f"{path}.{key} is not supported")
            elif isinstance(schema.get("additionalProperties"), dict):
                validate_schema(item, schema["additionalProperties"], f"{path}.{key}")
    if isinstance(value, list):
        if len(value) > schema.get("maxItems", len(value)):
            raise ValueError(f"{path} exceeds maxItems")
        for index, item in enumerate(value):
            validate_schema(item, schema.get("items", {}), f"{path}[{index}]")
    if isinstance(value, str):
        if (
            not schema.get("minLength", 0)
            <= len(value)
            <= schema.get("maxLength", len(value))
        ):
            raise ValueError(f"{path} has an invalid length")
    if type(value) is int:
        if not schema.get("minimum", value) <= value <= schema.get("maximum", value):
            raise ValueError(f"{path} is outside its allowed range")


def complete_descriptors(descriptors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = {
        "list_projects": ("projects", "array"),
        "list_runs": ("runs", "array"),
        "list_agent_runs": ("runs", "array"),
        "read_agent_run": ("manifest", "object"),
        "summarize_agent_run": ("summary", "object"),
        "agent_handoff": ("handoff", "object"),
        "agent_next_actions": ("next_actions", "object"),
        "read_agent_trace": ("events", "array"),
    }
    for descriptor in descriptors:
        schema = descriptor["inputSchema"]
        schema.setdefault("additionalProperties", False)
        for key, prop in schema.get("properties", {}).items():
            if prop.get("type") == "string":
                prop.setdefault("maxLength", 4096)
            if key in {"limit", "max_items"}:
                prop.setdefault("minimum", 0)
                prop.setdefault("maximum", 100)
        properties = {"schema": {"type": "string"}}
        required = ["schema"]
        if descriptor["name"] in fields:
            name, kind = fields[descriptor["name"]]
            properties[name] = {"type": kind}
            required.append(name)
        descriptor["outputSchema"] = {
            "type": "object",
            "properties": properties,
            "required": required,
        }
        descriptor["annotations"] = {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    return descriptors
