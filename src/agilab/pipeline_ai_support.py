from __future__ import annotations

import ast
import importlib
import importlib.metadata as importlib_metadata
import sys
import os
import json
import re
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from contextlib import contextmanager, nullcontext
from typing import Any, Dict, List, Optional, Tuple, Callable

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


def _ollama_available_models(endpoint: str) -> List[str]:
    """Return the list of models available on the Ollama server."""

    base = normalize_ollama_endpoint(endpoint)
    url = f"{base}/api/tags"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (OSError, TimeoutError, urllib.error.URLError, ValueError, RuntimeError):
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
    endpoint_var_name: str = "UOAIC_OLLAMA_ENDPOINT_ENV",
) -> str:
    """Call Ollama's /api/generate endpoint and return the response text."""
    base = normalize_ollama_endpoint(endpoint)
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
            f"Unable to reach Ollama at {url}. Start Ollama or update {endpoint_var_name}."
        ) from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ollama returned invalid JSON: {raw[:2000]}") from exc

    if not isinstance(parsed, dict):
        raise RuntimeError(f"Ollama returned unexpected payload: {type(parsed).__name__}")
    return str(parsed.get("response") or "").strip()


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


def _resolve_uoaic_path(raw_path: str, base_dir: Optional[Path] = None) -> Path:
    """Resolve a path in relation to an optional base directory."""
    path_str = (raw_path or "").strip()
    if not path_str:
        raise ValueError("Path is empty.")

    candidate = Path(path_str).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()

    base = base_dir if base_dir is not None else Path.cwd()
    return (base / candidate).resolve()


def _load_uoaic_modules(
    *,
    distribution_fn: Callable[[str], Any] | None = None,
    import_module_fn: Callable[[str], Any] | None = None,
    spec_from_file_location_fn: Callable[[str, str], Any] | None = None,
    module_from_spec_fn: Callable[[Any], Any] | None = None,
) -> Tuple[Any, ...]:
    """Import Universal Offline AI Chatbot modules with detailed diagnostics."""
    if distribution_fn is None:
        distribution_fn = importlib_metadata.distribution
    if import_module_fn is None:
        import_module_fn = importlib.import_module
    if spec_from_file_location_fn is None:
        spec_from_file_location_fn = importlib.util.spec_from_file_location
    if module_from_spec_fn is None:
        module_from_spec_fn = importlib.util.module_from_spec

    try:
        dist = distribution_fn("universal-offline-ai-chatbot")
    except importlib_metadata.PackageNotFoundError as exc:
        raise RuntimeError(
            "Install `universal-offline-ai-chatbot` (e.g. `uv pip install \"agilab[offline]\"`) "
            "to enable the local (Ollama) assistant."
        ) from exc

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
            imported_modules.append(import_module_fn(name))
            continue
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
                    if line.startswith("src/") and line.endswith(".py") and line.split(",", 1)[0].endswith(f"src/{short}.py"):
                        rel = line.split(",", 1)[0]
                        file_path = Path(dist.locate_file(rel))
                        break

            if file_path and file_path.exists():
                alias = f"uoaic_{short}"
                try:
                    spec = spec_from_file_location_fn(alias, str(file_path))
                    if spec and spec.loader:
                        module = module_from_spec_fn(spec)
                        spec.loader.exec_module(module)
                        imported_modules.append(module)
                        continue
                except (ImportError, OSError, RuntimeError, AttributeError, TypeError, ValueError):
                    # Fall through to messaging below.
                    pass

            missing = getattr(exc, "name", "") or ""
            if missing and missing != name:
                raise RuntimeError(
                    f"Missing dependency `{missing}` required by universal-offline-ai-chatbot. "
                    "Install the offline extras with `uv pip install \"agilab[offline]\"` or "
                    "`uv pip install universal-offline-ai-chatbot`."
                ) from exc

            raise RuntimeError(
                "Failed to load Universal Offline AI Chatbot module files. Ensure the package is installed in "
                "the same environment running Streamlit. You can force a reinstall with "
                "`uv pip install --force-reinstall universal-offline-ai-chatbot`."
            ) from exc

    return tuple(imported_modules)


def _ensure_uoaic_runtime(
    envars: Dict[str, str],
    *,
    session_state: Dict[str, Any],
    resolve_uoaic_path: Callable[[str, Optional[Path]], Path],
    load_uoaic_modules: Callable[[], Tuple[Any, ...]],
    runtime_state_key: str,
    data_state_key: str,
    db_state_key: str,
    rebuild_state_key: str,
    data_env_key: str,
    db_env_key: str,
    model_env_key: str,
    default_db_dirname: str,
    spinner: Callable[[str], Any] = nullcontext,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build or reuse Universal Offline AI Chatbot runtime artifacts."""
    data_path_raw = (
        session_state.get(data_state_key)
        or envars.get(data_env_key)
        or os.getenv(data_env_key, "")
    )
    if not data_path_raw:
        raise ValueError("Missing Universal Offline data directory")

    try:
        data_path = resolve_uoaic_path(data_path_raw, base_dir=base_dir)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid Universal Offline data directory: {exc}") from exc
    normalized_data = normalize_path(data_path)
    session_state[data_state_key] = normalized_data
    envars[data_env_key] = normalized_data

    db_path_raw = (
        session_state.get(db_state_key)
        or envars.get(db_env_key)
        or os.getenv(db_env_key, "")
    )
    if not db_path_raw:
        db_path_raw = normalize_path(Path(data_path) / default_db_dirname)

    try:
        db_path = resolve_uoaic_path(db_path_raw, base_dir=base_dir)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid Universal Offline vector store directory: {exc}") from exc
    normalized_db = normalize_path(db_path)
    session_state[db_state_key] = normalized_db
    envars[db_env_key] = normalized_db

    runtime = session_state.get(runtime_state_key)
    if runtime and runtime.get("data_path") == normalized_data and runtime.get("db_path") == normalized_db:
        return runtime

    rebuild_requested = bool(session_state.pop(rebuild_state_key, False))
    chunker, embedding, loader, model_loader, prompts, qa_chain, vectorstore = load_uoaic_modules()

    try:
        embedding_model = embedding.get_embedding_model()
    except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Failed to load the embedding model for Universal Offline AI Chatbot: {exc}") from exc
    db_directory = Path(db_path)
    if rebuild_requested or not db_directory.exists():
        with spinner("Building Universal Offline AI Chatbot knowledge base…"):
            try:
                documents = loader.load_pdf_files(str(data_path))
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
                raise RuntimeError(f"Unable to load PDF documents from {data_path}: {exc}") from exc

            if not documents:
                raise RuntimeError(f"No PDF documents found in {data_path}. Add PDFs and rebuild the index.")

            try:
                chunks = chunker.create_chunks(documents)
                db_directory.parent.mkdir(parents=True, exist_ok=True)
                vectorstore.build_vector_db(chunks, embedding_model, str(db_path))
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
                raise RuntimeError(f"Failed to build the Universal Offline vector store: {exc}") from exc

    with spinner("Loading Universal Offline AI Chatbot artifacts…"):
        try:
            db = vectorstore.load_vector_db(str(db_path), embedding_model)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise RuntimeError(f"Failed to load the Universal Offline vector store at {db_path}: {exc}") from exc
        try:
            llm = model_loader.load_llm()
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            raise RuntimeError(f"Failed to load the local Ollama model used by Universal Offline AI Chatbot: {exc}") from exc

        model_label = ""
        for attr in ("model_name", "model", "model_id", "model_path", "name"):
            value = getattr(llm, attr, None)
            if value:
                model_label = str(value)
                break
        if not model_label:
            model_label = str(envars.get(model_env_key) or "universal-offline")

        prompt_template = prompts.set_custom_prompt(prompts.CUSTOM_PROMPT_TEMPLATE)
        try:
            chain = qa_chain.setup_qa_chain(llm, db, prompt_template)
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            raise RuntimeError(f"Failed to initialise the Universal Offline AI Chatbot chain: {exc}") from exc

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
    session_state[runtime_state_key] = runtime
    return runtime


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
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError, NameError, KeyError, IndexError, ArithmeticError, OverflowError, LookupError):
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
