#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from export_chat_docx import write_docx


ROLE_MAP = {
    "human": "user",
    "model": "assistant",
    "ai": "assistant",
    "bot": "assistant",
    "function": "tool",
}


def _normalize_role(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return "unknown"
    return ROLE_MAP.get(text, text)


def _extract_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [_extract_content(item) for item in value]
        return "\n\n".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("text", "content", "parts"):
            if key in value:
                return _extract_content(value[key])
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value).strip()


def _extract_messages(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("messages", "conversation", "turns"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    raise ValueError("Unsupported chat payload shape")


def _message_role(message: dict[str, Any]) -> str:
    if "role" in message:
        return _normalize_role(message.get("role"))
    author = message.get("author")
    if isinstance(author, dict) and "role" in author:
        return _normalize_role(author.get("role"))
    for key in ("speaker", "type"):
        if key in message:
            return _normalize_role(message.get(key))
    return "unknown"


def _message_content(message: dict[str, Any]) -> str:
    if "content" in message:
        return _extract_content(message.get("content"))
    if "text" in message:
        return _extract_content(message.get("text"))
    nested = message.get("message")
    if isinstance(nested, dict) and "content" in nested:
        return _extract_content(nested.get("content"))
    if "parts" in message:
        return _extract_content(message.get("parts"))
    return ""


def normalize_messages(
    payload: Any,
    *,
    include_system: bool = False,
    include_empty: bool = False,
) -> list[dict[str, str]]:
    messages = []
    for raw_message in _extract_messages(payload):
        role = _message_role(raw_message)
        content = _message_content(raw_message)
        if not include_system and role == "system":
            continue
        if not include_empty and not content:
            continue
        messages.append({"role": role, "content": content})
    return messages


def render_markdown(messages: list[dict[str, str]], *, title: str | None = None) -> str:
    lines: list[str] = []
    if title:
        lines.extend([f"# {title}", ""])
    for message in messages:
        role = message["role"].capitalize()
        lines.extend([f"## {role}", "", message["content"], ""])
    return "\n".join(lines).rstrip() + "\n"


def render_text(messages: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for message in messages:
        lines.extend([f"{message['role'].upper()}:", message["content"], ""])
    return "\n".join(lines).rstrip() + "\n"


def render_json(messages: list[dict[str, str]], *, title: str | None = None) -> str:
    payload = {"messages": messages}
    if title:
        payload["title"] = title
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export chat JSON into markdown, json, or text.")
    parser.add_argument("input", type=Path, help="Input JSON file")
    parser.add_argument("--output", "-o", type=Path, required=True, help="Output file")
    parser.add_argument(
        "--format",
        choices=("markdown", "json", "text", "docx"),
        default="markdown",
        help="Output format",
    )
    parser.add_argument("--title", help="Optional export title")
    parser.add_argument("--include-system", action="store_true", help="Keep system messages")
    parser.add_argument("--include-empty", action="store_true", help="Keep empty messages")
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    messages = normalize_messages(
        payload,
        include_system=args.include_system,
        include_empty=args.include_empty,
    )

    if args.format == "markdown":
        output = render_markdown(messages, title=args.title)
    elif args.format == "json":
        output = render_json(messages, title=args.title)
    elif args.format == "docx":
        write_docx(args.output, messages, title=args.title)
        return
    else:
        output = render_text(messages)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
