"""Bounded, measured source excerpts for agent_context_router (no execution)."""

from __future__ import annotations

import ast
import hashlib
import os
import re
import stat
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_SELECTORS = 256
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".rst",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".txt",
    ".sh",
    ".ps1",
}


def reference_counter() -> Callable[[str], int]:
    try:
        import tiktoken
    except ImportError as exc:
        raise ValueError(
            "Measured context requires tiktoken: uv run --with tiktoken python tools/agent_context_router.py --profile agilab --materialize ..."
        ) from exc
    encoding = tiktoken.get_encoding("o200k_base")
    return lambda text: len(encoding.encode(text, disallowed_special=()))


def _read_selector(root: Path, selector: str) -> tuple[str, str, list[str], int, int]:
    path_text, _, symbol = selector.partition("::")
    path_text, _, line_spec = path_text.partition("#L")
    path = (root / path_text).resolve()
    if not path.is_relative_to(root):
        raise ValueError("outside_repository")
    relative = path.relative_to(root)
    if path.is_dir():
        raise ValueError("directory_not_expanded")
    if ".git" in relative.parts or path.suffix not in TEXT_SUFFIXES:
        raise ValueError("unsupported_source_file")
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("not_regular_file")
    if metadata.st_size > MAX_FILE_BYTES:
        raise ValueError("file_too_large")
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("not_regular_file")
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("file_too_large")
    text = raw.decode("utf-8")
    if "\x00" in text:
        raise ValueError("binary_content")
    lines = text.splitlines(keepends=True)
    start, end = 1, len(lines)
    if symbol:
        tree: ast.AST = ast.parse(text)
        for part in symbol.split("."):
            matches = [
                node
                for node in getattr(tree, "body", [])
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                )
                and node.name == part
            ]
            if len(matches) != 1:
                raise ValueError("symbol_not_found_or_ambiguous")
            tree = matches[0]
        start = min([tree.lineno] + [d.lineno for d in tree.decorator_list])
        end = tree.end_lineno
    elif line_spec:
        match = re.fullmatch(r"(\d+)-L?(\d+)", line_spec)
        if not match:
            raise ValueError("invalid_line_selector")
        start, end = map(int, match.groups())
        if not 1 <= start <= end <= len(lines):
            raise ValueError("line_selector_out_of_range")
    return relative.as_posix(), hashlib.sha256(raw).hexdigest(), lines, start, end


def materialize_context(
    recommendation: Mapping[str, Any],
    *,
    root: Path,
    count_tokens: Callable[[str], int],
    selectors: Sequence[str] = (),
    max_tokens: int | None = None,
    reserve_tokens: int = 1000,
    counter_name: str = "caller-supplied",
) -> dict[str, Any]:
    """Count complete rendered context, keep mandatory policy intact, report omissions.

    Directory recommendations are never recursively expanded. The counter is
    injected for deterministic tests; the CLI uses the o200k_base reference
    encoding. Counts cover context_text, not protocol framing or billed usage.
    """
    root = root.resolve()
    profile = recommendation["context_profile"]
    limit = profile["max_total_tokens"] if max_tokens is None else max_tokens
    if limit <= 0 or reserve_tokens < 0 or reserve_tokens >= limit:
        raise ValueError("context allowance must be positive and exceed reserve tokens")
    budget = limit - reserve_tokens
    required = list(profile["baseline_files"])
    required.extend(profile.get("mandatory_files", []))
    required.extend(
        skill["path"]
        for skill in recommendation.get("recommended_skills", [])
        if skill.get("path")
    )
    optional = list(selectors)
    deferred: list[str] = []
    for pack in profile["matched_packs"]:
        for path in pack["files"]:
            if path.endswith("/SKILL.md") or Path(path).name in {
                "AGENTS.md",
                "AGENT_CONVENTIONS.md",
            }:
                required.append(path)
            else:
                (deferred if selectors else optional).append(path)
    required = list(dict.fromkeys(required))
    optional = [path for path in dict.fromkeys(optional) if path not in required]
    if len(required) + len(optional) > MAX_SELECTORS:
        raise ValueError(f"at most {MAX_SELECTORS} context selectors are allowed")
    chunks: list[str] = []
    selected: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = [
        {"selector": path, "reason": "not_selected", "required": False}
        for path in dict.fromkeys(deferred)
        if path not in required and path not in optional
    ]
    seen: set[str] = set()
    blocked = False
    for mandatory, candidates in ((True, required), (False, optional)):
        for selector in candidates:
            try:
                path, digest, lines, start, end = _read_selector(root, selector)
            except (OSError, ValueError, SyntaxError) as exc:
                omitted.append(
                    {"selector": selector, "reason": str(exc), "required": mandatory}
                )
                blocked |= mandatory
                continue
            content = "".join(lines[start - 1 : end])
            content_digest = hashlib.sha256(content.encode()).hexdigest()
            if content_digest in seen:
                omitted.append(
                    {
                        "selector": selector,
                        "reason": "duplicate_content",
                        "sha256": content_digest,
                        "required": mandatory,
                    }
                )
                continue

            def render(last: int) -> str:
                return f"{path}:{start}-{last} sha256={digest}\n" + "".join(
                    lines[start - 1 : last]
                )

            last = end
            if count_tokens("\n\n".join([*chunks, render(last)])) > budget:
                if mandatory:
                    omitted.append(
                        {
                            "selector": selector,
                            "reason": "mandatory_context_exceeds_budget",
                            "required": True,
                        }
                    )
                    blocked = True
                    continue
                # Bound by whole source lines; every omission is explicit.
                low, high = start - 1, end
                while low < high:
                    middle = (low + high + 1) // 2
                    if count_tokens("\n\n".join([*chunks, render(middle)])) <= budget:
                        low = middle
                    else:
                        high = middle - 1
                last = low
            if last < start:
                omitted.append(
                    {
                        "selector": selector,
                        "reason": "budget_exhausted",
                        "required": False,
                    }
                )
                continue
            chunks.append(render(last))
            seen.add(
                hashlib.sha256("".join(lines[start - 1 : last]).encode()).hexdigest()
            )
            selected.append(
                {
                    "selector": selector,
                    "path": path,
                    "sha256": digest,
                    "start_line": start,
                    "end_line": last,
                    "total_lines": len(lines),
                    "omitted_lines": len(lines) - (last - start + 1),
                    "required": mandatory,
                }
            )
            if last < end:
                omitted.append(
                    {
                        "selector": selector,
                        "reason": "excerpt_truncated",
                        "start_line": last + 1,
                        "end_line": end,
                        "required": False,
                    }
                )
    context_text = "\n\n".join(chunks)
    return {
        "schema": "agilab.agent_context_materialization.v1",
        "status": "mandatory-context-blocked" if blocked else "pass",
        "measurement_scope": "context_text_only; excludes framing and actual model usage",
        "counter": counter_name,
        "context_token_budget": budget,
        "reserve_tokens": reserve_tokens,
        "actual_tokens": count_tokens(context_text),
        "context_text": context_text,
        "selected": selected,
        "omissions": omitted,
        "complete": not blocked
        and not any(
            o["reason"] not in {"duplicate_content", "not_selected"} for o in omitted
        ),
    }
