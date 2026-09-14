"""Provider-neutral bounds for project examples and generated-code repair.

Budgets measure UTF-8 JSON bytes, not model tokens. Backend scaffolding,
retrieval and output have separate limits; no provider SDK is imported here.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Mapping, Sequence


class PromptContextError(ValueError):
    """Required task/instruction context cannot be safely assembled."""


@dataclass(frozen=True)
class PromptBudget:
    max_bytes: int = 32768
    reserve_bytes: int = 4096

    @property
    def input_bytes(self) -> int:
        if self.max_bytes <= self.reserve_bytes or self.reserve_bytes < 0:
            raise PromptContextError(
                "Prompt budget must exceed its nonnegative reserve."
            )
        return self.max_bytes - self.reserve_bytes


@dataclass(frozen=True)
class PromptContext:
    question: str
    messages: tuple[dict[str, str], ...]
    receipt: dict[str, object]


def _serialized(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def assemble_prompt_context(
    question: str,
    prompt: Sequence[Mapping[str, object]],
    *,
    instructions: str = "",
    budget: PromptBudget = PromptBudget(),
) -> PromptContext:
    """Keep instructions/task intact; select whole optional examples with a receipt."""
    limit = budget.input_bytes
    if not isinstance(question, str) or not isinstance(instructions, str):
        raise PromptContextError("Assistant request and instructions must be text.")
    if not isinstance(prompt, (list, tuple)) or len(prompt) > 256:
        raise PromptContextError(
            "Project pre-prompt must contain at most 256 messages."
        )
    normalized: list[dict[str, str]] = []
    for item in prompt:
        if not isinstance(item, Mapping):
            raise PromptContextError(
                "Each project pre-prompt message must be an object."
            )
        role = str(item.get("role", "assistant")).lower()
        if len(role) > 64:
            raise PromptContextError("Project pre-prompt role is too long.")
        content = item.get("content", "")
        if isinstance(content, list):
            content = "\n".join(str(part) for part in content)
        text = str(content).strip()
        if text:
            normalized.append({"role": role, "content": text})
    source_hash = hashlib.sha256(_serialized(normalized)).hexdigest()
    required = {
        index
        for index, item in enumerate(normalized)
        if item["role"] in {"system", "developer"}
    }
    selected = set(required)
    omitted: list[int] = []
    duplicates: list[int] = []

    def messages(indices: set[int], notice: bool = False) -> list[dict[str, str]]:
        result = [item for index, item in enumerate(normalized) if index in indices]
        if notice:
            result.append(
                {
                    "role": "user",
                    "content": f"[Project context: {len(omitted)} optional messages omitted; source sha256={source_hash}.]",
                }
            )
        return result

    def size(items: list[dict[str, str]]) -> int:
        return len(
            _serialized(
                [
                    {"role": "system", "content": instructions},
                    *items,
                    {"role": "user", "content": question},
                ]
            )
        )

    # Reserve the bounded omission notice before selecting optional examples.
    notice_reserve = 200
    if size(messages(required)) + notice_reserve > limit:
        raise PromptContextError(
            f"Required assistant request/instructions exceed the {limit}-byte input budget; shorten the request or required project instructions."
        )
    seen: set[bytes] = set()
    index = 0
    while index < len(normalized):
        if index in required:
            index += 1
            continue
        group = [index]
        if (
            normalized[index]["role"] == "user"
            and index + 1 < len(normalized)
            and normalized[index + 1]["role"] == "assistant"
        ):
            group.append(index + 1)
        signature = _serialized([normalized[i] for i in group])
        if signature in seen:
            duplicates.extend(group)
        elif size(messages(selected | set(group))) + notice_reserve <= limit:
            selected.update(group)
            seen.add(signature)
        else:
            omitted.extend(group)
        index = group[-1] + 1
    output = messages(selected, bool(omitted))
    actual = size(output)
    if actual > limit:
        raise PromptContextError("Prompt metadata cannot fit the input budget.")
    return PromptContext(
        question,
        tuple(output),
        {
            "schema": "agilab.prompt_context.v1",
            "measurement": "shared_context_json_utf8_bytes",
            "input_bytes": actual,
            "input_budget_bytes": limit,
            "reserve_bytes": budget.reserve_bytes,
            "source_sha256": source_hash,
            "selected_indices": sorted(selected),
            "omitted_indices": omitted,
            "duplicate_indices": duplicates,
            "raw_content_in_receipt": False,
        },
    )


def _byte_excerpt(text: str, limit: int, *, tail: bool = False) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    selected = raw[-limit:] if tail else raw[:limit]
    body = selected.decode("utf-8", errors="ignore")
    return f"[Omitted {len(raw) - len(body.encode())} UTF-8 bytes; sha256={hashlib.sha256(raw).hexdigest()}]\n{body}"


def build_repair_prompt(
    *,
    original_request: str,
    failing_code: str,
    traceback_text: str,
    attempt: int,
    instructions: str,
    budget: PromptBudget = PromptBudget(),
) -> str:
    """Select code around the failing generated line and expose omitted ranges."""
    trace = _byte_excerpt((traceback_text or "").strip(), 4000, tail=True)
    code = (failing_code or "").strip()
    lines = code.splitlines(keepends=True)
    references = re.findall(
        r'File "<(?:lab_step|string|generated)>", line (\d+)', traceback_text or ""
    )
    line_number = int(references[-1]) if references else len(lines)
    line_number = min(max(line_number, 1), max(len(lines), 1))
    if len(code.encode()) > 6000:
        start, end = line_number - 1, line_number
        used = len(lines[start].encode()) if lines else 0
        for _ in range(20):
            if start and used + len(lines[start - 1].encode()) <= 6000:
                start -= 1
                used += len(lines[start].encode())
            if end < len(lines) and used + len(lines[end].encode()) <= 6000:
                used += len(lines[end].encode())
                end += 1
        snippet = "".join(lines[start:end])
        if len(snippet.encode()) > 6000:
            # Preserve both ends of a long failing line; disclose the byte gap.
            raw = snippet.encode()
            head = raw[:2900].decode("utf-8", errors="ignore")
            tail = raw[-2900:].decode("utf-8", errors="ignore")
            snippet = f"{head}\n[Omitted {len(raw) - len((head + tail).encode())} bytes within the failing line]\n{tail}"
        code = f"[Code lines {start + 1}-{end} of {len(lines)}; {start + len(lines) - end} lines omitted; sha256={hashlib.sha256(code.encode()).hexdigest()}]\n{snippet}"
    request = (
        f"{instructions}\n\nYou generated Python code for the following request:\n{original_request.strip()}\n\n"
        f"The code failed when executed (attempt {attempt}). Fix it.\n\n"
        f"Traceback:\n{trace}\n\nFailing code:\n```python\n{code}\n```"
    )
    # The original request is never silently clipped.
    assemble_prompt_context(request, [], instructions=instructions, budget=budget)
    return request
