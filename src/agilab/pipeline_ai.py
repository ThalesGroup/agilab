from __future__ import annotations

import ast
import importlib
import importlib.metadata as importlib_metadata
import importlib.util
import json
import logging
import os
import re
import sys
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from agi_env import AgiEnv, normalize_path
from agi_env.defaults import get_default_openai_model
from agi_env.pagelib import activate_gpt_oss

try:
    from agilab.env_file_utils import load_env_file_map as _load_env_file_map
except ModuleNotFoundError:
    _env_file_utils_path = Path(__file__).resolve().parent / "env_file_utils.py"
    _env_file_utils_spec = importlib.util.spec_from_file_location("agilab_env_file_utils_fallback", _env_file_utils_path)
    if _env_file_utils_spec is None or _env_file_utils_spec.loader is None:
        raise
    _env_file_utils_module = importlib.util.module_from_spec(_env_file_utils_spec)
    _env_file_utils_spec.loader.exec_module(_env_file_utils_module)
    _load_env_file_map = _env_file_utils_module.load_env_file_map

try:
    from agilab.pipeline_openai import (
        ensure_cached_api_key,
        is_placeholder_api_key,
        make_openai_client_and_model,
        prompt_for_openai_api_key,
    )
except ModuleNotFoundError:
    _pipeline_openai_path = Path(__file__).resolve().parent / "pipeline_openai.py"
    _pipeline_openai_spec = importlib.util.spec_from_file_location("agilab_pipeline_openai_fallback", _pipeline_openai_path)
    if _pipeline_openai_spec is None or _pipeline_openai_spec.loader is None:
        raise
    _pipeline_openai_module = importlib.util.module_from_spec(_pipeline_openai_spec)
    _pipeline_openai_spec.loader.exec_module(_pipeline_openai_module)
    ensure_cached_api_key = _pipeline_openai_module.ensure_cached_api_key
    is_placeholder_api_key = _pipeline_openai_module.is_placeholder_api_key
    make_openai_client_and_model = _pipeline_openai_module.make_openai_client_and_model
    prompt_for_openai_api_key = _pipeline_openai_module.prompt_for_openai_api_key

try:
    from agilab.pipeline_steps import pipeline_export_root as _pipeline_export_root
except ModuleNotFoundError:
    _pipeline_steps_path = Path(__file__).resolve().parent / "pipeline_steps.py"
    _pipeline_steps_spec = importlib.util.spec_from_file_location("agilab_pipeline_steps_fallback", _pipeline_steps_path)
    if _pipeline_steps_spec is None or _pipeline_steps_spec.loader is None:
        raise
    _pipeline_steps_module = importlib.util.module_from_spec(_pipeline_steps_spec)
    _pipeline_steps_spec.loader.exec_module(_pipeline_steps_module)
    _pipeline_export_root = _pipeline_steps_module.pipeline_export_root

logger = logging.getLogger(__name__)
JumpToMain = RuntimeError

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

        if language_hint in {"python", "py"}:
            code = code_content
        else:
            code = code_block

        detail_parts: List[str] = []
        if prefix:
            detail_parts.append(prefix)
        if suffix:
            detail_parts.append(suffix)

        detail = "\n\n".join(detail_parts).strip()
        return code.strip(), detail

    # Fallback: accept raw Python if it parses cleanly.
    try:
        ast.parse(text)
    except SyntaxError:
        return "", text
    return text, ""


def _normalize_ollama_endpoint(raw_endpoint: Optional[str]) -> str:
    endpoint = (raw_endpoint or "").strip()
    if not endpoint:
        endpoint = os.getenv("OLLAMA_HOST", "").strip() or "http://127.0.0.1:11434"
    endpoint = endpoint.rstrip("/")
    if endpoint.endswith("/api/generate"):
        endpoint = endpoint[: -len("/api/generate")]
    return endpoint


@st.cache_data(show_spinner=False)
def _ollama_available_models(endpoint: str) -> List[str]:
    """Return the list of models available on the Ollama server."""

    base = _normalize_ollama_endpoint(endpoint)
    url = f"{base}/api/tags"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (OSError, TimeoutError, urllib.error.URLError, ValueError):
        return []

    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []

    models: List[str] = []
    if isinstance(parsed, dict):
        for entry in parsed.get("models") or []:
            if isinstance(entry, dict):
                name = entry.get("name")
                if name:
                    models.append(str(name))
    # Preserve order but drop duplicates/empties
    deduped: List[str] = []
    seen: set[str] = set()
    for name in models:
        if name in seen:
            continue
        seen.add(name)
        deduped.append(name)
    return deduped


_OLLAMA_CODE_MODEL_RE = re.compile(r"(?:^|/|:|_)(?:code|coder|codestral|deepseek)(?:$|/|:|_)", re.IGNORECASE)


def _default_ollama_model(
    endpoint: str,
    *,
    preferred: str = "mistral:instruct",
    prefer_code: bool = False,
) -> str:
    models = _ollama_available_models(endpoint)
    if models and prefer_code:
        for name in models:
            if _OLLAMA_CODE_MODEL_RE.search(name):
                return name
    if preferred and preferred in models:
        return preferred
    if models:
        return models[0]
    return preferred


def _ollama_generate(
    *,
    endpoint: str,
    model: str,
    prompt: str,
    temperature: float = 0.1,
    top_p: float = 0.9,
    num_ctx: Optional[int] = None,
    num_predict: Optional[int] = None,
    seed: Optional[int] = None,
    timeout_s: float = 120.0,
) -> str:
    """Call Ollama's /api/generate endpoint and return the response text."""
    base = _normalize_ollama_endpoint(endpoint)
    url = f"{base}/api/generate"

    options: Dict[str, Any] = {
        "temperature": float(temperature),
        "top_p": float(top_p),
    }
    if num_ctx is not None:
        options["num_ctx"] = int(num_ctx)
    if num_predict is not None:
        options["num_predict"] = int(num_predict)
    if seed is not None:
        options["seed"] = int(seed)

    payload = {
        "model": str(model).strip(),
        "prompt": str(prompt),
        "stream": False,
        "options": options,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=float(timeout_s)) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except (OSError, ValueError):
            pass
        raise RuntimeError(f"Ollama error {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Unable to reach Ollama at {url}. Start Ollama or update {UOAIC_OLLAMA_ENDPOINT_ENV}."
        ) from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ollama returned invalid JSON: {raw[:2000]}") from exc

    if not isinstance(parsed, dict):
        raise RuntimeError(f"Ollama returned unexpected payload: {type(parsed).__name__}")
    return str(parsed.get("response") or "").strip()


def _prompt_to_plaintext(prompt: List[Dict[str, str]], question: str) -> str:
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


def chat_ollama_local(
    input_request: str,
    prompt: List[Dict[str, str]],
    envars: Dict[str, str],
) -> Tuple[str, str]:
    """Call a local Ollama model for code generation."""
    endpoint = _normalize_ollama_endpoint(
        envars.get(UOAIC_OLLAMA_ENDPOINT_ENV)
        or os.getenv(UOAIC_OLLAMA_ENDPOINT_ENV)
        or os.getenv("OLLAMA_HOST")
    )
    fallback_model = _default_ollama_model(endpoint, prefer_code=True)
    model = (envars.get(UOAIC_MODEL_ENV) or os.getenv(UOAIC_MODEL_ENV) or fallback_model).strip()
    if not model:
        st.error("Set an Ollama model name to use the local assistant (see `ollama list`).")
        raise JumpToMain(ValueError("Missing Ollama model"))

    def _float_env(name: str, default: float) -> float:
        raw = envars.get(name) or os.getenv(name)
        try:
            return float(raw) if raw is not None and str(raw).strip() else float(default)
        except (TypeError, ValueError):
            return float(default)

    def _int_env(name: str) -> Optional[int]:
        raw = envars.get(name) or os.getenv(name)
        if raw is None or not str(raw).strip():
            return None
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return None

    temperature = _float_env(UOAIC_TEMPERATURE_ENV, 0.1)
    top_p = _float_env(UOAIC_TOP_P_ENV, 0.9)
    num_ctx = _int_env(UOAIC_NUM_CTX_ENV)
    num_predict = _int_env(UOAIC_NUM_PREDICT_ENV)
    seed = _int_env(UOAIC_SEED_ENV)

    history = _prompt_to_plaintext(prompt, input_request)
    full_prompt = f"{CODE_STRICT_INSTRUCTIONS}\n\n{history}"

    try:
        text = _ollama_generate(
            endpoint=endpoint,
            model=model,
            prompt=full_prompt,
            temperature=temperature,
            top_p=top_p,
            num_ctx=num_ctx,
            num_predict=num_predict,
            seed=seed,
        )
    except Exception as exc:
        st.error(str(exc))
        raise JumpToMain(exc)

    return text, model


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


def _normalize_identifier(raw: str, fallback: str = "value") -> str:
    """Return a snake_case identifier safe for column names."""

    cleaned = re.sub(r"[^0-9a-zA-Z_]+", "_", raw or "")
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        return fallback
    if cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned.lower()


def _synthesize_stub_response(question: str) -> str:
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
        column = _normalize_identifier(column_raw)
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


def _format_for_responses(conversation: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert legacy message payload into Responses API format."""

    formatted: List[Dict[str, Any]] = []
    for message in conversation:
        role = message.get("role", "user")
        content = message.get("content", "")

        if isinstance(content, list):
            # Assume content already follows the new schema.
            formatted.append({"role": role, "content": content})
            continue

        text_value = "" if content is None else str(content)
        formatted.append(
            {
                "role": role,
                "content": [
                    {
                        "type": "text",
                        "text": text_value,
                    }
                ],
            }
        )

    return formatted


def _response_to_text(response: Any) -> str:
    """Extract plain text from a Responses API reply with graceful fallbacks."""

    if not response:
        return ""

    # New SDKs expose an `output_text` convenience attribute.
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

    # Fall back to legacy completions format if present.
    choices = getattr(response, "choices", None)
    if choices:
        try:
            return choices[0].message.content.strip()
        except (AttributeError, IndexError, KeyError):
            pass

    return ""


DEFAULT_GPT_OSS_ENDPOINT = "http://127.0.0.1:8000/v1/responses"
UOAIC_PROVIDER = "universal-offline-ai-chatbot"
UOAIC_DATA_ENV = "UOAIC_DATA_PATH"
UOAIC_DB_ENV = "UOAIC_DB_PATH"
UOAIC_DEFAULT_DB_DIRNAME = "vectorstore/db_faiss"
UOAIC_RUNTIME_KEY = "uoaic_runtime"
UOAIC_DATA_STATE_KEY = "uoaic_data_path"
UOAIC_DB_STATE_KEY = "uoaic_db_path"
UOAIC_REBUILD_FLAG_KEY = "uoaic_rebuild_requested"
UOAIC_MODE_ENV = "UOAIC_MODE"
UOAIC_MODE_STATE_KEY = "uoaic_mode"
UOAIC_MODE_OLLAMA = "ollama"
UOAIC_MODE_RAG = "rag"
UOAIC_OLLAMA_ENDPOINT_ENV = "UOAIC_OLLAMA_ENDPOINT"
UOAIC_MODEL_ENV = "UOAIC_MODEL"
UOAIC_TEMPERATURE_ENV = "UOAIC_TEMPERATURE"
UOAIC_TOP_P_ENV = "UOAIC_TOP_P"
UOAIC_NUM_CTX_ENV = "UOAIC_NUM_CTX"
UOAIC_NUM_PREDICT_ENV = "UOAIC_NUM_PREDICT"
UOAIC_SEED_ENV = "UOAIC_SEED"
UOAIC_AUTOFIX_ENV = "UOAIC_AUTOFIX"
UOAIC_AUTOFIX_MAX_ENV = "UOAIC_AUTOFIX_MAX_ATTEMPTS"
UOAIC_AUTOFIX_STATE_KEY = "uoaic_autofix_enabled"
UOAIC_AUTOFIX_MAX_STATE_KEY = "uoaic_autofix_max_attempts"
DEFAULT_UOAIC_BASE = Path.home() / ".agilab" / "mistral_offline"
_HF_TOKEN_ENV_KEYS = ("HF_TOKEN", "HUGGINGFACEHUB_API_TOKEN")
_API_KEY_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9]{4,})([A-Za-z0-9\-*_]{8,})"),
    re.compile(r"(sk-proj-[A-Za-z0-9]{4,})([A-Za-z0-9\-*_]{8,})"),
]

ENV_FILE_PATH = Path.home() / ".agilab/.env"


CODE_STRICT_INSTRUCTIONS = (
    "Return ONLY Python code wrapped in ```python ...``` with no explanations.\n"
    "Assume there is a pandas DataFrame df and pandas is imported as pd.\n"
    "Do not use Streamlit. Do not read/write files or call the network.\n"
    "Keep the result in a DataFrame named df."
)


def _redact_sensitive(text: str) -> str:
    """Mask API keys or similar secrets present in provider error messages."""
    if not text:
        return text
    redacted = str(text)
    for pattern in _API_KEY_PATTERNS:
        redacted = pattern.sub(lambda m: f"{m.group(1)}…", redacted)
    return redacted


def _normalize_gpt_oss_endpoint(raw_endpoint: Optional[str]) -> str:
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


def _prompt_to_gpt_oss_messages(prompt: List[Dict[str, str]], question: str) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    instructions: List[str] = []
    history: List[Dict[str, Any]] = []
    for item in prompt or []:
        role = str(item.get("role", "assistant")).lower()
        content = item.get("content", "")
        if isinstance(content, list):  # handle pre_prompt lists
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


def chat_offline(
    input_request: str,
    prompt: List[Dict[str, str]],
    envars: Dict[str, str],
) -> Tuple[str, str]:
    """Call the GPT-OSS Responses API endpoint configured for offline use."""

    try:
        import requests  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional dependency
        st.error("`requests` is required for GPT-OSS offline mode. Install it with `pip install requests`." )
        raise JumpToMain(exc)

    endpoint = _normalize_gpt_oss_endpoint(
        envars.get("GPT_OSS_ENDPOINT")
        or os.getenv("GPT_OSS_ENDPOINT")
        or st.session_state.get("gpt_oss_endpoint")
    )
    envars["GPT_OSS_ENDPOINT"] = endpoint

    instructions, items = _prompt_to_gpt_oss_messages(prompt, input_request)
    payload: Dict[str, Any] = {
        "model": envars.get("GPT_OSS_MODEL", "gpt-oss-120b"),
        "input": items,
        "temperature": float(envars.get("GPT_OSS_TEMPERATURE", 0.0) or 0.0),
        "stream": False,
        "reasoning": {"effort": envars.get("GPT_OSS_REASONING", "low")},
    }
    if instructions:
        payload["instructions"] = instructions

    timeout = float(envars.get("GPT_OSS_TIMEOUT", 60))
    model_name = str(payload.get("model", ""))
    try:
        response = requests.post(endpoint, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as exc:
        st.error(
            "Failed to reach GPT-OSS at {endpoint}. Start it with `python -m gpt_oss.responses_api.serve --inference-backend stub --port 8000` or configure `GPT_OSS_ENDPOINT`.".format(
                endpoint=endpoint
            )
        )
        raise JumpToMain(exc)
    except ValueError as exc:
        st.error("GPT-OSS returned an invalid JSON payload.")
        raise JumpToMain(exc)

    # The Responses API returns a dictionary; reuse helper to extract text.
    text = ""
    if isinstance(data, dict):
        try:
            from gpt_oss.responses_api.types import ResponseObject

            text = _response_to_text(ResponseObject.model_validate(data))
        except Exception:
            # Best-effort extraction for plain dicts.
            output = data.get("output", []) if isinstance(data, dict) else []
            chunks = []
            for item in output:
                if isinstance(item, dict) and item.get("type") == "message":
                    for part in item.get("content", []) or []:
                        if isinstance(part, dict) and part.get("text"):
                            chunks.append(str(part.get("text")))
            text = "\n".join(chunks).strip()

    text = text.strip()
    backend_hint = (
        st.session_state.get("gpt_oss_backend_active")
        or st.session_state.get("gpt_oss_backend")
        or envars.get("GPT_OSS_BACKEND")
        or os.getenv("GPT_OSS_BACKEND")
        or "stub"
    ).lower()
    if backend_hint == "stub" and (not text or "2 + 2 = 4" in text):
        return _synthesize_stub_response(input_request), model_name

    return text, model_name


def _format_uoaic_question(prompt: List[Dict[str, str]], question: str) -> str:
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


def _normalize_user_path(raw_path: str) -> str:
    """Return a normalised absolute path string for user provided input."""
    raw = (raw_path or "").strip()
    if not raw:
        return ""
    candidate = Path(raw).expanduser()
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError):
        # Fall back to absolute without resolving symlinks if the path is missing.
        resolved = candidate.absolute()
    return normalize_path(resolved)


def _resolve_uoaic_path(raw_path: str, env: Optional[AgiEnv]) -> Path:
    """Resolve user-supplied paths relative to AGILab export directory when needed."""
    path_str = (raw_path or "").strip()
    if not path_str:
        raise ValueError("Path is empty.")
    candidate = Path(path_str).expanduser()
    if not candidate.is_absolute():
        base: Optional[Path] = None
        if env is not None:
            try:
                base = _pipeline_export_root(env)
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError):  # pragma: no cover - defensive
                base = None
        if base is None:
            base = Path.cwd()
        candidate = (base / candidate).resolve()
    else:
        candidate = candidate.resolve()
    return candidate


def _load_uoaic_modules():
    """Import the Universal Offline AI Chatbot helpers with detailed diagnostics."""

    try:
        importlib_metadata.distribution("universal-offline-ai-chatbot")
    except importlib_metadata.PackageNotFoundError as exc:
        st.error(
            "Install `universal-offline-ai-chatbot` (e.g. `uv pip install \"agilab[offline]\"`) "
            "to enable the local (Ollama) assistant."
        )
        raise JumpToMain(exc)

    dist = importlib_metadata.distribution("universal-offline-ai-chatbot")
    site_root = Path(dist.locate_file(""))
    if site_root.is_file():
        site_root = site_root.parent
    candidate_dirs = {
        site_root,
        site_root.parent if site_root.name.endswith(".dist-info") else site_root,
        (site_root.parent if site_root.name.endswith(".dist-info") else site_root) / "src",
    }
    for path in candidate_dirs:
        if path and path.exists():
            str_path = str(path.resolve())
            if str_path not in sys.path:
                sys.path.append(str_path)

    module_names = (
        "src.chunker",
        "src.embedding",
        "src.loader",
        "src.model_loader",
        "src.prompts",
        "src.qa_chain",
        "src.vectorstore",
    )

    imported_modules: List[Any] = []
    for name in module_names:
        try:
            imported_modules.append(importlib.import_module(name))
        except ImportError as exc:
            # Fallback: load the module directly from files inside the wheel
            short = name.split(".")[-1]
            file_path: Optional[Path] = None
            files = getattr(dist, "files", None)
            if files:
                for entry in files:
                    if str(entry).replace("\\", "/").endswith(f"src/{short}.py"):
                        file_path = Path(dist.locate_file(entry))
                        break
            if not file_path:
                try:
                    rec = dist.read_text("RECORD") or ""
                except (OSError, RuntimeError):
                    rec = ""
                for line in rec.splitlines():
                    if line.startswith("src/") and line.endswith(".py") and line.split(",",1)[0].endswith(f"src/{short}.py"):
                        rel = line.split(",", 1)[0]
                        file_path = Path(dist.locate_file(rel))
                        break

            if file_path and file_path.exists():
                alias = f"uoaic_{short}"
                try:
                    spec = importlib.util.spec_from_file_location(alias, str(file_path))
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        imported_modules.append(module)
                        continue
                except Exception as ex2:
                    # Fall through to messaging below
                    pass

            missing = getattr(exc, "name", "") or ""
            if missing and missing != name:
                st.error(
                    f"Missing dependency `{missing}` required by universal-offline-ai-chatbot. "
                    "Install the offline extras with `uv pip install \"agilab[offline]\"` or "
                    "`uv pip install universal-offline-ai-chatbot`."
                )
            else:
                st.error(
                    "Failed to load Universal Offline AI Chatbot module files. Ensure the package is installed in "
                    "the same environment running Streamlit. You can force a reinstall with "
                    "`uv pip install --force-reinstall universal-offline-ai-chatbot`."
                )
            raise JumpToMain(exc) from exc

    return tuple(imported_modules)


def _ensure_uoaic_runtime(envars: Dict[str, str]) -> Dict[str, Any]:
    """Initialise or reuse the Universal Offline AI Chatbot QA chain."""
    env: Optional[AgiEnv] = st.session_state.get("env")

    data_path_raw = (
        st.session_state.get(UOAIC_DATA_STATE_KEY)
        or envars.get(UOAIC_DATA_ENV)
        or os.getenv(UOAIC_DATA_ENV, "")
    )
    if not data_path_raw:
        st.error("Configure the Universal Offline data directory in the sidebar to enable this provider.")
        raise JumpToMain(ValueError("Missing Universal Offline data directory"))

    try:
        data_path = _resolve_uoaic_path(data_path_raw, env)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        st.error(f"Invalid Universal Offline data directory: {exc}")
        raise JumpToMain(exc)

    normalized_data = normalize_path(data_path)
    st.session_state[UOAIC_DATA_STATE_KEY] = normalized_data
    envars[UOAIC_DATA_ENV] = normalized_data

    db_path_raw = (
        st.session_state.get(UOAIC_DB_STATE_KEY)
        or envars.get(UOAIC_DB_ENV)
        or os.getenv(UOAIC_DB_ENV, "")
    )
    if not db_path_raw:
        db_path_raw = normalize_path(Path(data_path) / UOAIC_DEFAULT_DB_DIRNAME)

    try:
        db_path = _resolve_uoaic_path(db_path_raw, env)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        st.error(f"Invalid Universal Offline vector store directory: {exc}")
        raise JumpToMain(exc)

    normalized_db = normalize_path(db_path)
    st.session_state[UOAIC_DB_STATE_KEY] = normalized_db
    envars[UOAIC_DB_ENV] = normalized_db

    runtime = st.session_state.get(UOAIC_RUNTIME_KEY)
    if runtime and runtime.get("data_path") == normalized_data and runtime.get("db_path") == normalized_db:
        return runtime

    rebuild_requested = bool(st.session_state.pop(UOAIC_REBUILD_FLAG_KEY, False))

    chunker, embedding, loader, model_loader, prompts, qa_chain, vectorstore = _load_uoaic_modules()

    try:
        embedding_model = embedding.get_embedding_model()
    except Exception as exc:
        st.error(f"Failed to load the embedding model for Universal Offline AI Chatbot: {exc}")
        raise JumpToMain(exc)

    db_directory = Path(db_path)
    if rebuild_requested or not db_directory.exists():
        with st.spinner("Building Universal Offline AI Chatbot knowledge base…"):
            try:
                documents = loader.load_pdf_files(str(data_path))
            except Exception as exc:
                st.error(f"Unable to load PDF documents from {data_path}: {exc}")
                raise JumpToMain(exc)

            if not documents:
                st.error(f"No PDF documents found in {data_path}. Add PDFs and rebuild the index.")
                raise JumpToMain(ValueError("Universal Offline data directory is empty"))

            try:
                chunks = chunker.create_chunks(documents)
                db_directory.parent.mkdir(parents=True, exist_ok=True)
                vectorstore.build_vector_db(chunks, embedding_model, str(db_path))
            except Exception as exc:
                st.error(f"Failed to build the Universal Offline vector store: {exc}")
                raise JumpToMain(exc)

    with st.spinner("Loading Universal Offline AI Chatbot artifacts…"):
        try:
            db = vectorstore.load_vector_db(str(db_path), embedding_model)
        except Exception as exc:
            st.error(f"Failed to load the Universal Offline vector store at {db_path}: {exc}")
            raise JumpToMain(exc)

        try:
            llm = model_loader.load_llm()
        except Exception as exc:
            st.error(f"Failed to load the local Ollama model used by Universal Offline AI Chatbot: {exc}")
            raise JumpToMain(exc)

        model_label = ""
        for attr in ("model_name", "model", "model_id", "model_path", "name"):
            value = getattr(llm, attr, None)
            if value:
                model_label = str(value)
                break
        if not model_label:
            model_label = str(envars.get("UOAIC_MODEL") or "universal-offline")

        prompt_template = prompts.set_custom_prompt(prompts.CUSTOM_PROMPT_TEMPLATE)
        try:
            chain = qa_chain.setup_qa_chain(llm, db, prompt_template)
        except Exception as exc:
            st.error(f"Failed to initialise the Universal Offline AI Chatbot chain: {exc}")
            raise JumpToMain(exc)

    runtime = {
        "data_path": normalized_data,
        "db_path": normalized_db,
        "chain": chain,
        "embedding_model": embedding_model,
        "vector_store": db,
        "llm": llm,
        "prompt": prompt_template,
        "model_label": model_label,
    }
    st.session_state[UOAIC_RUNTIME_KEY] = runtime
    return runtime


def chat_universal_offline(
    input_request: str,
    prompt: List[Dict[str, str]],
    envars: Dict[str, str],
) -> Tuple[str, str]:
    """Invoke the Universal Offline AI Chatbot pipeline for the current query."""
    runtime = _ensure_uoaic_runtime(envars)
    chain = runtime["chain"]
    model_label = runtime.get("model_label") or str(envars.get("UOAIC_MODEL") or "universal-offline")
    query_text = _format_uoaic_question(prompt, input_request) or input_request

    try:
        response = chain.invoke({"query": query_text})
    except Exception as exc:
        st.error(f"Universal Offline AI Chatbot invocation failed: {exc}")
        raise JumpToMain(exc)

    answer = ""
    sources: List[str] = []

    if isinstance(response, dict):
        answer = response.get("result") or response.get("answer") or ""
        source_documents = response.get("source_documents") or []
        for doc in source_documents:
            metadata = getattr(doc, "metadata", {}) if hasattr(doc, "metadata") else {}
            if isinstance(metadata, dict):
                source = metadata.get("source") or metadata.get("file") or metadata.get("path")
                page = metadata.get("page") or metadata.get("page_number")
                if source:
                    if page is not None:
                        sources.append(f"{source} (page {page})")
                    else:
                        sources.append(str(source))
    else:
        answer = str(response)

    answer_text = str(answer).strip()
    if sources:
        sources_block = "\n".join(f"- {entry}" for entry in sources)
        if answer_text:
            answer_text = f"{answer_text}\n\nSources:\n{sources_block}"
        else:
            answer_text = f"Sources:\n{sources_block}"

    return answer_text, model_label


def chat_online(
    input_request: str,
    prompt: List[Dict[str, str]],
    envars: Dict[str, str],
) -> Tuple[str, str]:
    """Robust Chat Completions call: OpenAI, Azure OpenAI, or proxy base_url."""
    import openai

    # Refresh envars from the latest .env so model/key changes take effect without restart.
    env_file_map = _load_env_file_map(ENV_FILE_PATH)
    if env_file_map:
        envars.update(env_file_map)

    api_key = ensure_cached_api_key(envars)
    if not api_key or is_placeholder_api_key(api_key):
        prompt_for_openai_api_key(
            "OpenAI API key appears missing or redacted. Supply a valid key to continue."
        )
        raise JumpToMain(ValueError("OpenAI API key unavailable"))

    # Persist to session + envars to survive reruns
    st.session_state["openai_api_key"] = api_key
    envars["OPENAI_API_KEY"] = api_key

    # Build messages
    system_msg = {
        "role": "system",
        "content": (
            "Return ONLY Python code wrapped in ```python ... ``` with no explanations. "
            "Assume there is a pandas DataFrame df and pandas is imported as pd."
        ),
    }
    messages: List[Dict[str, str]] = [system_msg]
    for item in prompt:
        role = item.get("role", "assistant")
        content = str(item.get("content", ""))
        if content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": input_request})

    # Create client (supports OpenAI/Azure/proxy)
    try:
        client, model_name, is_azure = make_openai_client_and_model(envars, api_key)
    except Exception as e:
        st.error("Failed to initialise OpenAI/Azure client. Check your SDK install and environment variables.")
        logger.error(f"Client init error: {_redact_sensitive(str(e))}")
        raise JumpToMain(e)

    # Call – support new and old SDKs
    try:
        # New-style client returns objects; old SDK returns dicts
        if hasattr(client, "chat") and hasattr(client.chat, "completions"):
            resp = client.chat.completions.create(model=model_name, messages=messages)
            content = resp.choices[0].message.content
        else:
            # Old SDK (module-style)
            resp = client.ChatCompletion.create(model=model_name, messages=messages)
            content = resp["choices"][0]["message"]["content"]

        return content or "", str(model_name)

    except openai.OpenAIError as e:
        # Don’t re-prompt for key here; surface the *actual* problem.
        msg = _redact_sensitive(str(e))
        status = getattr(e, "status_code", None) or getattr(e, "status", None)
        if status == 404 or "model_not_found" in msg or "does not exist" in msg:
            st.info(
                "The requested model is unavailable. Please select a different model in the LLM provider settings "
                "or update the model name in the Environment Variables expander (OPENAI_MODEL/AZURE deployment)."
            )
            logger.info(f"Model not found/unavailable: {msg}")
        elif status in (401, 403):
            # Most common causes:
            # - Azure key used without proper Azure endpoint/version/deployment
            # - Wrong org / no access to model
            # - Proxy/base_url misconfigured
            st.error(
                "Authentication/authorization failed.\n\n"
                "Common causes:\n"
                "• Using an **Azure OpenAI** key but missing `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_VERSION` / deployment name.\n"
                "• Using a **gateway/proxy** but missing `OPENAI_BASE_URL`.\n"
                "• The key doesn’t have access to the requested model/deployment.\n\n"
                f"Details: {msg}"
            )
        else:
            st.error(f"OpenAI/Azure error: {msg}")
        logger.error(f"OpenAI error: {msg}")
        raise JumpToMain(e)
    except Exception as e:
        msg = _redact_sensitive(str(e))
        st.error(f"Unexpected client error: {msg}")
        logger.error(f"General error in chat_online: {msg}")
        raise JumpToMain(e)


def ask_gpt(
    question: str,
    df_file: Path,
    index_page: str,
    envars: Dict[str, str],
) -> List[Any]:
    """Send a question to GPT and get the response."""
    prompt = st.session_state.get("lab_prompt", [])
    provider = st.session_state.get(
        "lab_llm_provider",
        envars.get("LAB_LLM_PROVIDER", "openai"),
    )
    model_label = ""
    if provider == "gpt-oss":
        result, model_label = chat_offline(question, prompt, envars)
    elif provider == UOAIC_PROVIDER:
        mode = (
            st.session_state.get(UOAIC_MODE_STATE_KEY)
            or envars.get(UOAIC_MODE_ENV)
            or os.getenv(UOAIC_MODE_ENV)
            or UOAIC_MODE_OLLAMA
        )
        if mode == UOAIC_MODE_RAG:
            result, model_label = chat_universal_offline(question, prompt, envars)
        else:
            result, model_label = chat_ollama_local(question, prompt, envars)
    else:
        result, model_label = chat_online(question, prompt, envars)

    model_label = str(model_label or "")
    if not result:
        return [df_file, question, model_label, "", ""]

    code, detail = extract_code(result)
    detail = detail or ("" if code else result.strip())
    return [
        df_file,
        question,
        model_label,
        code.strip() if code else "",
        detail,
    ]


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


def _maybe_autofix_generated_code(
    *,
    original_request: str,
    df_path: Path,
    index_page: str,
    env: AgiEnv,
    merged_code: str,
    model_label: str,
    detail: str,
    load_df_cached: Any,
    push_run_log: Any,
    get_run_placeholder: Any,
) -> Tuple[str, str, str]:
    """Optionally run + repair generated code using the active assistant."""
    provider = st.session_state.get("lab_llm_provider") or env.envars.get("LAB_LLM_PROVIDER", "openai")
    if provider != UOAIC_PROVIDER:
        return merged_code, model_label, detail

    enabled = bool(st.session_state.get(UOAIC_AUTOFIX_STATE_KEY, False))
    if not enabled:
        enabled_env = (env.envars.get(UOAIC_AUTOFIX_ENV) or os.getenv(UOAIC_AUTOFIX_ENV) or "").strip().lower()
        enabled = enabled_env in {"1", "true", "yes", "on"}
    if not enabled:
        return merged_code, model_label, detail

    try:
        max_attempts = int(st.session_state.get(UOAIC_AUTOFIX_MAX_STATE_KEY, 2))
    except (TypeError, ValueError):
        max_attempts = 2
    if max_attempts <= 0:
        return merged_code, model_label, detail

    df: Any = st.session_state.get("loaded_df")
    if not isinstance(df, pd.DataFrame) or df.empty:
        df_file = st.session_state.get("df_file")
        if df_file:
            df = load_df_cached(Path(df_file))

    if not isinstance(df, pd.DataFrame) or df.empty:
        push_run_log(index_page, "Auto-fix skipped: no dataframe is loaded.", get_run_placeholder(index_page))
        return merged_code, model_label, detail

    placeholder = get_run_placeholder(index_page)
    _, err = _exec_code_on_df(merged_code, df)
    if not err:
        push_run_log(index_page, "Auto-fix: generated code validated successfully.", placeholder)
        return merged_code, model_label, detail

    push_run_log(index_page, f"Auto-fix: initial execution failed.\n{err}", placeholder)
    current_code = merged_code
    current_model = model_label
    current_detail = detail
    current_err = err

    for attempt in range(1, max_attempts + 1):
        fix_question = _build_autofix_prompt(
            original_request=original_request,
            failing_code=current_code,
            traceback_text=current_err,
            attempt=attempt,
        )
        fix_answer = ask_gpt(fix_question, df_path, index_page, env.envars)
        fix_code = fix_answer[3] if len(fix_answer) > 3 else ""
        fix_detail = (fix_answer[4] or "").strip() if len(fix_answer) > 4 else ""
        fix_model = str(fix_answer[2] or "") if len(fix_answer) > 2 else current_model
        if not fix_code.strip():
            push_run_log(index_page, f"Auto-fix attempt {attempt}: model returned no code.", placeholder)
            break

        candidate = f"# {fix_detail}\n{fix_code}".strip() if fix_detail else fix_code.strip()
        _, candidate_err = _exec_code_on_df(candidate, df)
        if not candidate_err:
            push_run_log(index_page, f"Auto-fix: success on attempt {attempt}.", placeholder)
            return candidate, fix_model, fix_detail

        summary = candidate_err.strip().splitlines()[-1] if candidate_err.strip() else "Unknown error"
        push_run_log(index_page, f"Auto-fix attempt {attempt} failed: {summary}", placeholder)
        current_code = candidate
        current_model = fix_model
        current_detail = fix_detail
        current_err = candidate_err

    push_run_log(index_page, "Auto-fix failed; keeping the last generated code.", placeholder)
    return current_code, current_model, current_detail


def configure_assistant_engine(env: AgiEnv) -> str:
    """Render assistant-provider controls and persist provider-specific settings."""
    provider_options = {
        "OpenAI (online)": "openai",
        "GPT-OSS (local)": "gpt-oss",
        "Ollama (local)": UOAIC_PROVIDER,
    }
    stored_provider = st.session_state.get("lab_llm_provider")
    current_provider = stored_provider or env.envars.get("LAB_LLM_PROVIDER", "openai")
    provider_labels = list(provider_options.keys())
    provider_to_label = {v: k for k, v in provider_options.items()}
    current_label = provider_to_label.get(current_provider, provider_labels[0])
    current_index = provider_labels.index(current_label) if current_label in provider_labels else 0
    selected_label = st.sidebar.selectbox(
        "Assistant engine",
        provider_labels,
        index=current_index,
    )
    selected_provider = provider_options[selected_label]
    previous_provider = st.session_state.get("lab_llm_provider")
    st.session_state["lab_llm_provider"] = selected_provider
    env.envars["LAB_LLM_PROVIDER"] = selected_provider
    if previous_provider != selected_provider and previous_provider == UOAIC_PROVIDER:
        st.session_state.pop(UOAIC_RUNTIME_KEY, None)
    if previous_provider != selected_provider:
        index_page = st.session_state.get("index_page") or st.session_state.get("lab_dir")
        if index_page is not None:
            index_page_str = str(index_page)
            row = st.session_state.get(index_page_str)
            if isinstance(row, list) and len(row) > 3:
                row[3] = ""
        st.session_state.setdefault("_experiment_reload_required", True)

        if selected_provider == "openai":
            env.envars["OPENAI_MODEL"] = get_default_openai_model()
        elif selected_provider == "gpt-oss":
            oss_model = (
                st.session_state.get("gpt_oss_model")
                or env.envars.get("GPT_OSS_MODEL")
                or os.getenv("GPT_OSS_MODEL", "gpt-oss-120b")
            )
            env.envars["OPENAI_MODEL"] = oss_model
        else:
            env.envars.pop("OPENAI_MODEL", None)

    if selected_provider == "gpt-oss":
        default_endpoint = (
            st.session_state.get("gpt_oss_endpoint")
            or env.envars.get("GPT_OSS_ENDPOINT")
            or os.getenv("GPT_OSS_ENDPOINT", "http://127.0.0.1:8000")
        )
        endpoint = st.sidebar.text_input(
            "GPT-OSS endpoint",
            value=default_endpoint,
            help="Point to a running GPT-OSS responses API (e.g. start with `python -m gpt_oss.responses_api.serve --inference-backend stub --port 8000`).",
        ).strip() or default_endpoint
        st.session_state["gpt_oss_endpoint"] = endpoint
        env.envars["GPT_OSS_ENDPOINT"] = endpoint
    else:
        st.session_state.pop("gpt_oss_endpoint", None)

    return selected_provider



def gpt_oss_controls(env: AgiEnv) -> None:
    """Ensure GPT-OSS responses service is reachable and provide quick controls."""
    if st.session_state.get("lab_llm_provider") != "gpt-oss":
        return

    endpoint = (
        st.session_state.get("gpt_oss_endpoint")
        or env.envars.get("GPT_OSS_ENDPOINT")
        or os.getenv("GPT_OSS_ENDPOINT", "")
    )
    backend_choices = ["stub", "transformers", "metal", "triton", "ollama", "vllm"]
    backend_default = (
        st.session_state.get("gpt_oss_backend")
        or env.envars.get("GPT_OSS_BACKEND")
        or os.getenv("GPT_OSS_BACKEND")
        or "stub"
    )
    if backend_default not in backend_choices:
        backend_choices = [backend_default] + [opt for opt in backend_choices if opt != backend_default]
    backend = st.sidebar.selectbox(
        "GPT-OSS backend",
        backend_choices,
        index=backend_choices.index(backend_default if backend_default in backend_choices else backend_choices[0]),
        help="Select the inference backend for a local GPT-OSS server. "
             "Use 'transformers' for Hugging Face checkpoints or leave on 'stub' for a mock service.",
    )
    st.session_state["gpt_oss_backend"] = backend
    env.envars["GPT_OSS_BACKEND"] = backend
    if st.session_state.get("gpt_oss_server_started") and st.session_state.get("gpt_oss_backend_active") not in (None, backend):
        st.sidebar.warning("Restart GPT-OSS server to apply the new backend.")

    checkpoint_default = (
        st.session_state.get("gpt_oss_checkpoint")
        or env.envars.get("GPT_OSS_CHECKPOINT")
        or os.getenv("GPT_OSS_CHECKPOINT")
        or ("gpt2" if backend == "transformers" else "")
    )
    checkpoint = st.sidebar.text_input(
        "GPT-OSS checkpoint / model",
        value=checkpoint_default,
        help="Provide a Hugging Face model ID or local checkpoint path when using a local backend.",
    ).strip()
    if checkpoint:
        st.session_state["gpt_oss_checkpoint"] = checkpoint
        env.envars["GPT_OSS_CHECKPOINT"] = checkpoint
    else:
        st.session_state.pop("gpt_oss_checkpoint", None)
        env.envars.pop("GPT_OSS_CHECKPOINT", None)

    extra_args_default = (
        st.session_state.get("gpt_oss_extra_args")
        or env.envars.get("GPT_OSS_EXTRA_ARGS")
        or os.getenv("GPT_OSS_EXTRA_ARGS")
        or ""
    )
    extra_args = st.sidebar.text_input(
        "GPT-OSS extra flags",
        value=extra_args_default,
        help="Optional additional flags appended to the launch command (e.g. `--temperature 0.1`).",
    ).strip()
    if extra_args:
        st.session_state["gpt_oss_extra_args"] = extra_args
        env.envars["GPT_OSS_EXTRA_ARGS"] = extra_args
    else:
        st.session_state.pop("gpt_oss_extra_args", None)
        env.envars.pop("GPT_OSS_EXTRA_ARGS", None)

    if st.session_state.get("gpt_oss_server_started"):
        active_checkpoint = st.session_state.get("gpt_oss_checkpoint_active", "")
        active_extra = st.session_state.get("gpt_oss_extra_args_active", "")
        if checkpoint != active_checkpoint or extra_args != active_extra:
            st.sidebar.warning("Restart GPT-OSS server to apply updated checkpoint or flags.")

    auto_local = endpoint.startswith("http://127.0.0.1") or endpoint.startswith("http://localhost")

    autostart_failed = st.session_state.get("gpt_oss_autostart_failed")

    if auto_local and not st.session_state.get("gpt_oss_server_started") and not autostart_failed:
        if activate_gpt_oss(env):
            endpoint = st.session_state.get("gpt_oss_endpoint", endpoint)

    if st.session_state.get("gpt_oss_server_started"):
        endpoint = st.session_state.get("gpt_oss_endpoint", endpoint)
        backend_active = st.session_state.get("gpt_oss_backend_active", backend)
        st.sidebar.success(f"GPT-OSS server running ({backend_active}) at {endpoint}")
        return

    if st.sidebar.button("Start GPT-OSS server", key="gpt_oss_start_btn"):
        if activate_gpt_oss(env):
            endpoint = st.session_state.get("gpt_oss_endpoint", endpoint)
            backend_active = st.session_state.get("gpt_oss_backend_active", backend)
            st.sidebar.success(f"GPT-OSS server running ({backend_active}) at {endpoint}")
            return

    if endpoint:
        st.sidebar.info(f"Using GPT-OSS endpoint: {endpoint}")
    else:
        st.sidebar.warning(
            "Configure a GPT-OSS endpoint or install the package with `pip install gpt-oss` "
            "to start a local server."
        )


def universal_offline_controls(env: AgiEnv) -> None:
    """Provide configuration helpers for the Universal Offline AI Chatbot provider."""
    if st.session_state.get("lab_llm_provider") != UOAIC_PROVIDER:
        return

    mode_default = (
        st.session_state.get(UOAIC_MODE_STATE_KEY)
        or env.envars.get(UOAIC_MODE_ENV)
        or os.getenv(UOAIC_MODE_ENV)
        or UOAIC_MODE_OLLAMA
    )
    mode_options = {
        "Code (Ollama)": UOAIC_MODE_OLLAMA,
        "RAG (offline docs)": UOAIC_MODE_RAG,
    }
    mode_labels = list(mode_options.keys())
    current_mode_label = next(
        (label for label, val in mode_options.items() if val == mode_default),
        mode_labels[0],
    )
    selected_mode_label = st.sidebar.selectbox(
        "Local assistant mode",
        mode_labels,
        index=mode_labels.index(current_mode_label),
        help="Use direct Ollama generation for code correctness, or the Universal Offline RAG chain for doc Q&A.",
    )
    selected_mode = mode_options[selected_mode_label]
    previous_mode = st.session_state.get(UOAIC_MODE_STATE_KEY)
    st.session_state[UOAIC_MODE_STATE_KEY] = selected_mode
    env.envars[UOAIC_MODE_ENV] = selected_mode
    if previous_mode and previous_mode != selected_mode:
        st.session_state.pop(UOAIC_RUNTIME_KEY, None)

    with st.sidebar.expander("Ollama settings", expanded=True):
        endpoint_default = (
            st.session_state.get("uoaic_ollama_endpoint")
            or env.envars.get(UOAIC_OLLAMA_ENDPOINT_ENV)
            or os.getenv(UOAIC_OLLAMA_ENDPOINT_ENV)
            or os.getenv("OLLAMA_HOST", "")
            or "http://127.0.0.1:11434"
        )
        endpoint_input = st.text_input(
            "Ollama endpoint",
            value=str(endpoint_default),
            help="Base URL of the Ollama server (default: http://127.0.0.1:11434).",
        ).strip()
        normalized_endpoint = _normalize_ollama_endpoint(endpoint_input)
        st.session_state["uoaic_ollama_endpoint"] = normalized_endpoint
        env.envars[UOAIC_OLLAMA_ENDPOINT_ENV] = normalized_endpoint

        model_default = (
            st.session_state.get("uoaic_model")
            or env.envars.get(UOAIC_MODEL_ENV)
            or os.getenv(UOAIC_MODEL_ENV, "")
            or _default_ollama_model(
                normalized_endpoint,
                prefer_code=selected_mode == UOAIC_MODE_OLLAMA,
            )
        )
        model_input = st.text_input(
            "Ollama model",
            value=str(model_default),
            help="Model name (as shown by `ollama list`). For best code correctness, use a code-tuned model when available.",
        ).strip()
        st.session_state["uoaic_model"] = model_input
        if model_input:
            env.envars[UOAIC_MODEL_ENV] = model_input
        else:
            env.envars.pop(UOAIC_MODEL_ENV, None)

        def _float_default(name: str, fallback: float) -> float:
            raw = st.session_state.get(name) or env.envars.get(name) or os.getenv(name)
            try:
                return float(raw)
            except (TypeError, ValueError):
                return float(fallback)

        temperature_default = max(0.0, min(1.0, _float_default(UOAIC_TEMPERATURE_ENV, 0.1)))
        temperature = st.slider(
            "temperature",
            min_value=0.0,
            max_value=1.0,
            value=float(temperature_default),
            step=0.05,
            help="Lower values improve determinism for code generation.",
        )
        env.envars[UOAIC_TEMPERATURE_ENV] = str(float(temperature))

        top_p_default = max(0.0, min(1.0, _float_default(UOAIC_TOP_P_ENV, 0.9)))
        top_p = st.slider(
            "top_p",
            min_value=0.0,
            max_value=1.0,
            value=float(top_p_default),
            step=0.05,
            help="Nucleus sampling. Lower values can reduce hallucinations for code.",
        )
        env.envars[UOAIC_TOP_P_ENV] = str(float(top_p))

        def _int_default(name: str, fallback: int) -> int:
            raw = st.session_state.get(name) or env.envars.get(name) or os.getenv(name)
            try:
                return int(float(raw))
            except (TypeError, ValueError):
                return int(fallback)

        num_ctx = st.number_input(
            "num_ctx (0 = default)",
            min_value=0,
            max_value=262144,
            value=_int_default(UOAIC_NUM_CTX_ENV, 0),
            step=256,
            help="Context window. Increase if prompts are truncated (requires RAM).",
        )
        if int(num_ctx) > 0:
            env.envars[UOAIC_NUM_CTX_ENV] = str(int(num_ctx))
        else:
            env.envars.pop(UOAIC_NUM_CTX_ENV, None)

        num_predict = st.number_input(
            "num_predict (0 = default)",
            min_value=0,
            max_value=65536,
            value=_int_default(UOAIC_NUM_PREDICT_ENV, 0),
            step=128,
            help="Max tokens to generate. Set 0 to use Ollama defaults.",
        )
        if int(num_predict) > 0:
            env.envars[UOAIC_NUM_PREDICT_ENV] = str(int(num_predict))
        else:
            env.envars.pop(UOAIC_NUM_PREDICT_ENV, None)

        seed = st.number_input(
            "seed (0 = unset)",
            min_value=0,
            max_value=2**31 - 1,
            value=_int_default(UOAIC_SEED_ENV, 0),
            step=1,
            help="Optional deterministic seed for the local model.",
        )
        if int(seed) > 0:
            env.envars[UOAIC_SEED_ENV] = str(int(seed))
        else:
            env.envars.pop(UOAIC_SEED_ENV, None)

    with st.sidebar.expander("Code correctness", expanded=True):
        autofix_default = env.envars.get(UOAIC_AUTOFIX_ENV) or os.getenv(UOAIC_AUTOFIX_ENV) or "0"
        autofix_enabled = bool(st.session_state.get(UOAIC_AUTOFIX_STATE_KEY, autofix_default in {"1", "true", "True"}))
        autofix_enabled = st.checkbox(
            "Auto-run + auto-fix generated code",
            value=autofix_enabled,
            help="After generating code, run it against the loaded dataframe and ask the model to repair tracebacks.",
        )
        st.session_state[UOAIC_AUTOFIX_STATE_KEY] = autofix_enabled
        env.envars[UOAIC_AUTOFIX_ENV] = "1" if autofix_enabled else "0"

        max_default = env.envars.get(UOAIC_AUTOFIX_MAX_ENV) or os.getenv(UOAIC_AUTOFIX_MAX_ENV) or "2"
        try:
            max_default_int = max(0, int(max_default))
        except (TypeError, ValueError):
            max_default_int = 2
        max_attempts = st.number_input(
            "Max fix attempts",
            min_value=0,
            max_value=10,
            value=int(st.session_state.get(UOAIC_AUTOFIX_MAX_STATE_KEY, max_default_int)),
            step=1,
            help="0 disables iterative repairs; the first generated code is kept.",
        )
        st.session_state[UOAIC_AUTOFIX_MAX_STATE_KEY] = int(max_attempts)
        env.envars[UOAIC_AUTOFIX_MAX_ENV] = str(int(max_attempts))

    if selected_mode != UOAIC_MODE_RAG:
        st.sidebar.caption("RAG knowledge-base settings are hidden (switch mode to enable).")
        return

    default_data_path = DEFAULT_UOAIC_BASE / "data"
    data_default = (
        st.session_state.get(UOAIC_DATA_STATE_KEY)
        or env.envars.get(UOAIC_DATA_ENV)
        or os.getenv(UOAIC_DATA_ENV, "")
    )
    if not data_default:
        try:
            default_data_path.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        data_default = normalize_path(default_data_path)
    data_input = st.sidebar.text_input(
        "Universal Offline data directory",
        value=data_default,
        help="Path containing the PDF documents to index for the Universal Offline AI Chatbot.",
    ).strip()
    if not data_input:
        data_input = data_default
    if data_input:
        normalized_data = _normalize_user_path(data_input)
        if normalized_data:
            changed = normalized_data != st.session_state.get(UOAIC_DATA_STATE_KEY)
            st.session_state[UOAIC_DATA_STATE_KEY] = normalized_data
            env.envars[UOAIC_DATA_ENV] = normalized_data
            if changed:
                st.session_state.pop(UOAIC_RUNTIME_KEY, None)
        else:
            st.sidebar.warning("Provide a valid data directory for the Universal Offline AI Chatbot.")
    else:
        st.session_state.pop(UOAIC_DATA_STATE_KEY, None)
        env.envars.pop(UOAIC_DATA_ENV, None)

    default_db_path = DEFAULT_UOAIC_BASE / "vectorstore" / "db_faiss"
    db_default = (
        st.session_state.get(UOAIC_DB_STATE_KEY)
        or env.envars.get(UOAIC_DB_ENV)
        or os.getenv(UOAIC_DB_ENV, "")
    )
    if not db_default:
        try:
            default_db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        db_default = normalize_path(default_db_path)

    db_input = st.sidebar.text_input(
        "Universal Offline vector store directory",
        value=db_default,
        help="Location for the FAISS vector store (defaults to `<data>/vectorstore/db_faiss`).",
    ).strip()
    if not db_input:
        db_input = db_default
    if db_input:
        normalized_db = _normalize_user_path(db_input)
        if normalized_db:
            changed = normalized_db != st.session_state.get(UOAIC_DB_STATE_KEY)
            st.session_state[UOAIC_DB_STATE_KEY] = normalized_db
            env.envars[UOAIC_DB_ENV] = normalized_db
            if changed:
                st.session_state.pop(UOAIC_RUNTIME_KEY, None)
        else:
            st.sidebar.warning("Provide a valid directory for the Universal Offline vector store.")
    else:
        st.session_state.pop(UOAIC_DB_STATE_KEY, None)
        env.envars.pop(UOAIC_DB_ENV, None)

    if not any(os.getenv(k) for k in _HF_TOKEN_ENV_KEYS):
        st.sidebar.info(
            "Set `HF_TOKEN` (or `HUGGINGFACEHUB_API_TOKEN`) so the embedding model can download once."
        )

    if st.sidebar.button("Rebuild Universal Offline knowledge base", key="uoaic_rebuild_btn"):
        if not st.session_state.get(UOAIC_DATA_STATE_KEY):
            st.sidebar.error("Set the data directory before rebuilding the Universal Offline knowledge base.")
            return
        st.session_state[UOAIC_REBUILD_FLAG_KEY] = True
        try:
            with st.spinner("Rebuilding Universal Offline AI Chatbot knowledge base…"):
                _ensure_uoaic_runtime(env.envars)
        except JumpToMain:
            # Errors are already surfaced via st.error in the helper.
            return
        st.sidebar.success("Universal Offline knowledge base updated.")
