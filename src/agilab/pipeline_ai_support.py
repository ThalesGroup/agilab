from __future__ import annotations

import ast
import os
import re
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from agi_env import normalize_path

DEFAULT_GPT_OSS_ENDPOINT = "http://127.0.0.1:8000/v1/responses"

CODE_STRICT_INSTRUCTIONS = (
    "Return ONLY Python code wrapped in ```python ...``` with no explanations.\n"
    "Assume there is a pandas DataFrame df and pandas is imported as pd.\n"
    "Do not use Streamlit. Do not read/write files or call the network.\n"
    "Keep the result in a DataFrame named df."
)

_OLLAMA_CODE_MODEL_RE = re.compile(r"(?:^|/|:|_)(?:code|coder|codestral|deepseek)(?:$|/|:|_)", re.IGNORECASE)
_API_KEY_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9]{6})([A-Za-z0-9\\-_]{8,})"),
    re.compile(r"(sk-proj)-[A-Za-z0-9\\-_]{4,}"),
]


def extract_code(gpt_message: str) -> Tuple[str, str]:
    """Extract Python code (if any) and supporting detail from a GPT message."""
    if not gpt_message:
        return "", ""

    text = str(gpt_message).strip()
    if not text:
        return "", ""

    parts = text.split("```")
    if len(parts) > 1:
        prefix = parts[0].strip()
        code_block = parts[1]
        suffix = "```".join(parts[2:]).strip()

        language_line, newline, body = code_block.partition("\n")
        lang = language_line.strip().lower()
        if newline:
            code_content = body
            language_hint = lang
        else:
            code_content = code_block
            language_hint = ""

        code = code_content if language_hint in {"python", "py"} else code_block

        detail_parts: List[str] = []
        if prefix:
            detail_parts.append(prefix)
        if suffix:
            detail_parts.append(suffix)

        detail = "\n\n".join(detail_parts).strip()
        return code.strip(), detail

    try:
        ast.parse(text)
    except SyntaxError:
        return "", text
    return text, ""


def normalize_ollama_endpoint(raw_endpoint: Optional[str]) -> str:
    endpoint = (raw_endpoint or "").strip()
    if not endpoint:
        endpoint = os.getenv("OLLAMA_HOST", "").strip() or "http://127.0.0.1:11434"
    endpoint = endpoint.rstrip("/")
    if endpoint.endswith("/api/generate"):
        endpoint = endpoint[: -len("/api/generate")]
    return endpoint


def prompt_to_plaintext(prompt: List[Dict[str, str]], question: str) -> str:
    """Flatten the conversation history into plaintext for local providers."""
    lines: List[str] = []
    for item in prompt or []:
        content = item.get("content", "")
        if isinstance(content, list):
            content = "\n".join(str(part) for part in content)
        text = str(content).strip()
        if not text:
            continue
        role = str(item.get("role", "")).lower()
        if role == "user":
            prefix = "User"
        elif role == "assistant":
            prefix = "Assistant"
        elif role == "system":
            prefix = "System"
        else:
            prefix = role.title() if role else "Assistant"
        lines.append(f"{prefix}: {text}")
    lines.append(f"User: {question}")
    return "\n".join(lines).strip()


def normalize_identifier(raw: str, fallback: str = "value") -> str:
    """Return a snake_case identifier safe for column names."""
    cleaned = re.sub(r"[^0-9a-zA-Z_]+", "_", raw or "")
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        return fallback
    if cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned.lower()


def synthesize_stub_response(question: str) -> str:
    """Generate a deterministic response when the GPT-OSS stub backend is active."""
    normalized = (question or "").lower()
    if not normalized:
        return (
            "The GPT-OSS stub backend only confirms connectivity. Set the backend to 'transformers' or "
            "point the endpoint to a real GPT-OSS deployment for code completions."
        )

    if "savgol" in normalized or "savitzky" in normalized:
        match = re.search(r"(?:col(?:umn)?|field|series)\s+([\w-]+)", normalized)
        column_raw = match.group(1) if match else "value"
        column = normalize_identifier(column_raw)
        window_match = re.search(r"(?:window|kernel)(?:\s+(?:length|size))?\s+(\d+)", normalized)
        window_length = max(int(window_match.group(1)), 5) if window_match else 7
        if window_length % 2 == 0:
            window_length += 1
        return (
            f"Apply a Savitzky-Golay filter to the `{column}` column and store the result in a new series.\n"
            "```python\n"
            "from scipy.signal import savgol_filter\n\n"
            f"column = '{column}'\n"
            "if column not in df.columns:\n"
            "    raise KeyError(f\"Column '{column}' not found in dataframe\")\n\n"
            f"window_length = {window_length}  # must be odd and >= 5\n"
            "polyorder = 2\n"
            "if window_length >= len(df):\n"
            "    window_length = len(df) - 1 if len(df) % 2 == 0 else len(df)\n"
            "    window_length = max(window_length, 5)\n"
            "    if window_length % 2 == 0:\n"
            "        window_length -= 1\n\n"
            "df[f\"{column}_smooth\"] = savgol_filter(\n"
            "    df[column].to_numpy(),\n"
            "    window_length=window_length,\n"
            "    polyorder=polyorder,\n"
            "    mode='interp',\n"
            ")\n"
            "```\n"
            "Adjust `polyorder` or `window_length` to control the amount of smoothing. Install SciPy with "
            "`pip install scipy` if the import fails."
        )

    return (
        "The GPT-OSS stub backend is only for smoke tests and responds with canned data. Use the sidebar to "
        "select a real backend (e.g. transformers) and provide a model checkpoint for usable completions."
    )


def format_for_responses(conversation: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert legacy message payload into Responses API format."""
    formatted: List[Dict[str, Any]] = []
    for message in conversation:
        role = message.get("role", "user")
        content = message.get("content", "")

        if isinstance(content, list):
            formatted.append({"role": role, "content": content})
            continue

        text_value = "" if content is None else str(content)
        formatted.append(
            {
                "role": role,
                "content": [{"type": "text", "text": text_value}],
            }
        )
    return formatted


def response_to_text(response: Any) -> str:
    """Extract plain text from a Responses API reply with graceful fallbacks."""
    if not response:
        return ""

    text_value = getattr(response, "output_text", None)
    if isinstance(text_value, str) and text_value.strip():
        return text_value.strip()

    collected: List[str] = []
    for item in getattr(response, "output", []) or []:
        item_type = getattr(item, "type", None)
        if item_type == "message":
            for part in getattr(item, "content", []) or []:
                part_type = getattr(part, "type", None)
                if part_type in {"text", "output_text"}:
                    part_text = getattr(part, "text", "")
                    if hasattr(part_text, "value"):
                        collected.append(str(part_text.value))
                    else:
                        collected.append(str(part_text))
        elif hasattr(item, "text"):
            chunk = getattr(item, "text")
            if hasattr(chunk, "value"):
                collected.append(str(chunk.value))
            else:
                collected.append(str(chunk))

    if collected:
        return "\n".join(piece for piece in collected if piece).strip()

    choices = getattr(response, "choices", None)
    if choices:
        try:
            return choices[0].message.content.strip()
        except (AttributeError, IndexError, KeyError):
            pass

    return ""


def redact_sensitive(text: str) -> str:
    """Mask API keys or similar secrets present in provider error messages."""
    if not text:
        return text
    redacted = str(text)
    for pattern in _API_KEY_PATTERNS:
        redacted = pattern.sub(lambda m: f"{m.group(1)}…", redacted)
    return redacted


def normalize_gpt_oss_endpoint(raw_endpoint: Optional[str]) -> str:
    endpoint = (raw_endpoint or "").strip()
    if not endpoint:
        return DEFAULT_GPT_OSS_ENDPOINT
    if endpoint.endswith("/responses"):
        return endpoint
    if endpoint.rstrip("/").endswith("/v1"):
        return endpoint.rstrip("/") + "/responses"
    if endpoint.endswith("/"):
        return endpoint + "v1/responses"
    return endpoint + "/v1/responses"


def prompt_to_gpt_oss_messages(prompt: List[Dict[str, str]], question: str) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    instructions: List[str] = []
    history: List[Dict[str, Any]] = []
    for item in prompt or []:
        role = str(item.get("role", "assistant")).lower()
        content = item.get("content", "")
        if isinstance(content, list):
            content = "\n".join(str(part) for part in content)
        text = str(content)
        if not text.strip():
            continue
        if role == "system":
            instructions.append(text)
            continue
        content_type = "input_text" if role == "user" else "output_text"
        if role not in {"assistant", "user"}:
            role = "assistant"
            content_type = "text"
        history.append(
            {
                "type": "message",
                "role": role,
                "content": [{"type": content_type, "text": text}],
            }
        )

    history.append(
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": question}],
        }
    )

    instructions_text = "\n\n".join(part for part in instructions if part.strip()) or None
    return instructions_text, history


def format_uoaic_question(prompt: List[Dict[str, str]], question: str) -> str:
    """Flatten the conversation history into a single query string."""
    lines: List[str] = []
    for item in prompt or []:
        content = item.get("content", "")
        if isinstance(content, list):
            content = "\n".join(str(part) for part in content)
        text = str(content).strip()
        if not text:
            continue
        role = str(item.get("role", "")).lower()
        if role == "user":
            prefix = "User"
        elif role == "assistant":
            prefix = "Assistant"
        elif role == "system":
            prefix = "System"
        else:
            prefix = role.title() if role else "Assistant"
        lines.append(f"{prefix}: {text}")
    lines.append(f"User: {question}")
    body = "\n".join(lines).strip()
    return f"{CODE_STRICT_INSTRUCTIONS}\n\n{body}" if body else CODE_STRICT_INSTRUCTIONS


def normalize_user_path(raw_path: str) -> str:
    """Return a normalised absolute path string for user provided input."""
    raw = (raw_path or "").strip()
    if not raw:
        return ""
    candidate = Path(raw).expanduser()
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError):
        resolved = candidate.absolute()
    return normalize_path(resolved)


_BLOCKED_BUILTINS = frozenset({
    "eval", "exec", "compile", "__import__", "open", "breakpoint",
    "globals", "locals", "vars", "dir", "getattr", "setattr", "delattr",
    "input", "memoryview", "exit", "quit",
})

_SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
    "enumerate": enumerate, "filter": filter, "float": float,
    "frozenset": frozenset, "hasattr": hasattr, "hash": hash,
    "int": int, "isinstance": isinstance, "issubclass": issubclass,
    "len": len, "list": list, "map": map, "max": max, "min": min,
    "print": print, "range": range, "repr": repr, "reversed": reversed,
    "round": round, "set": set, "slice": slice, "sorted": sorted,
    "str": str, "sum": sum, "tuple": tuple, "type": type, "zip": zip,
    "True": True, "False": False, "None": None,
    # Standard exception types so sandboxed code can raise/catch errors
    "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
    "KeyError": KeyError, "IndexError": IndexError, "RuntimeError": RuntimeError,
    "AttributeError": AttributeError, "ZeroDivisionError": ZeroDivisionError,
    "StopIteration": StopIteration, "NotImplementedError": NotImplementedError,
    "ArithmeticError": ArithmeticError, "LookupError": LookupError,
    "OverflowError": OverflowError,
}

_BLOCKED_DUNDER_ATTRS = frozenset({
    "__class__", "__subclasses__", "__bases__", "__mro__",
    "__globals__", "__code__", "__func__", "__self__",
    "__builtins__", "__import__", "__loader__", "__spec__",
})

_BLOCKED_MODULES = frozenset({
    "os", "sys", "subprocess", "shutil", "signal", "socket",
    "http", "urllib", "requests", "ftplib", "smtplib", "ctypes",
    "importlib", "pickle", "shelve", "marshal", "code", "codeop",
    "compileall", "py_compile", "io", "pathlib", "tempfile",
    "multiprocessing", "threading", "webbrowser",
})


class _UnsafeCodeError(Exception):
    """Raised when LLM-generated code fails the safety audit."""


def _validate_code_safety(code: str) -> None:
    """Parse *code* and reject patterns that could escape the sandbox.

    Raises ``_UnsafeCodeError`` with a human-readable explanation when a
    dangerous construct is detected.
    """
    try:
        tree = ast.parse(code, filename="<lab_step>")
    except SyntaxError as exc:
        raise _UnsafeCodeError(f"Syntax error in generated code: {exc}") from exc

    for node in ast.walk(tree):
        # Block all import statements
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                names = [node.module or ""]
            raise _UnsafeCodeError(
                f"Import statements are not allowed in pipeline code: {', '.join(names)}"
            )

        # Block calls to dangerous builtins
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _BLOCKED_BUILTINS:
                raise _UnsafeCodeError(
                    f"Call to blocked builtin '{func.id}' is not allowed."
                )

        # Block access to dangerous dunder attributes
        if isinstance(node, ast.Attribute):
            if node.attr in _BLOCKED_DUNDER_ATTRS:
                raise _UnsafeCodeError(
                    f"Access to '{node.attr}' is not allowed."
                )
            # Block access to known dangerous modules via attribute chains
            if isinstance(node.value, ast.Name) and node.value.id in _BLOCKED_MODULES:
                raise _UnsafeCodeError(
                    f"Access to module '{node.value.id}' is not allowed."
                )


def _exec_code_on_df(code: str, df: pd.DataFrame) -> Tuple[Optional[pd.DataFrame], str]:
    """Execute code against a copy of df. Returns (new_df, error).

    The code is first validated via AST inspection to reject dangerous
    constructs (imports, dunder access, blocked builtins) before execution.
    The runtime namespace is restricted to pandas, numpy, and a safe
    subset of Python builtins.
    """
    try:
        _validate_code_safety(code)
    except _UnsafeCodeError as exc:
        return None, f"Safety check failed: {exc}"

    import numpy as np  # local import to keep module-level namespace clean

    df_local = df.copy()
    restricted_globals: Dict[str, Any] = {
        "__builtins__": _SAFE_BUILTINS,
        "pd": pd,
        "np": np,
    }
    local_vars: Dict[str, Any] = {"df": df_local}
    try:
        compiled = compile(code, "<lab_step>", "exec")
        exec(compiled, restricted_globals, local_vars)
    except _UnsafeCodeError:
        raise
    except Exception:
        return None, traceback.format_exc()
    updated = local_vars.get("df")
    if isinstance(updated, pd.DataFrame):
        return updated, ""
    return None, "Code did not produce a DataFrame named `df`."


def _build_autofix_prompt(
    *,
    original_request: str,
    failing_code: str,
    traceback_text: str,
    attempt: int,
) -> str:
    clipped_trace = (traceback_text or "").strip()
    if len(clipped_trace) > 4000:
        clipped_trace = clipped_trace[-4000:]
    clipped_code = (failing_code or "").strip()
    if len(clipped_code) > 6000:
        clipped_code = clipped_code[:6000]
    return (
        f"{CODE_STRICT_INSTRUCTIONS}\n\n"
        f"You generated Python code for the following request:\n{original_request.strip()}\n\n"
        f"The code failed when executed (attempt {attempt}). Fix it.\n\n"
        f"Traceback:\n{clipped_trace}\n\n"
        f"Failing code:\n```python\n{clipped_code}\n```"
    )
