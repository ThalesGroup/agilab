import logging
import os
import json
import webbrowser
from pathlib import Path
import importlib
import importlib.metadata as importlib_metadata
import sys
import sysconfig
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd
import re
os.environ.setdefault("STREAMLIT_CONFIG_FILE", str(Path(__file__).resolve().parents[1] / "resources" / "config.toml"))
import streamlit as st
import tomli        # For reading TOML files
import tomli_w      # For writing TOML files

from code_editor import code_editor
from agi_env.pagelib import (
    activate_mlflow,
    activate_gpt_oss,
    find_files,
    run_lab,
    load_df,
    get_custom_buttons,
    get_info_bar,
    get_about_content,
    get_css_text,
    export_df,
    save_csv,
    scan_dir,
    on_df_change,
    render_logo,
    inject_theme,
)
from agi_env import AgiEnv, normalize_path

# Constants
STEPS_FILE_NAME = "lab_steps.toml"
DEFAULT_DF = "export.csv"
BUTTONS_PER_LINE = 20
JUPYTER_URL = "http://localhost:8888"

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class JumpToMain(Exception):
    """Custom exception to jump back to the main execution flow."""
    pass


def convert_paths_to_strings(obj: Any) -> Any:
    """Recursively convert pathlib.Path objects to strings for serialization."""
    if isinstance(obj, dict):
        return {k: convert_paths_to_strings(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_paths_to_strings(item) for item in obj]
    elif isinstance(obj, Path):
        return str(obj)
    else:
        return obj


def on_page_change() -> None:
    """Set the 'page_broken' flag in session state."""
    st.session_state.page_broken = True


def on_step_change(
    module_dir: Path,
    steps_file: Path,
    index_step: int,
    index_page: str,
) -> None:
    """Update session state when a step is selected."""
    st.session_state[index_page][0] = index_step
    st.session_state.step_checked = False
    # Schedule prompt clear and blank on next render; bump input revision to remount widget
    st.session_state[f"{index_page}__clear_q"] = True
    st.session_state[f"{index_page}__force_blank_q"] = True
    st.session_state[f"{index_page}__q_rev"] = st.session_state.get(f"{index_page}__q_rev", 0) + 1
    # Drop any existing editor instance state for this step (best-effort)
    st.session_state.pop(f"{index_page}_a_{index_step}", None)
    # Do not call st.rerun() here: callbacks automatically trigger a rerun
    # after returning. Rely on the updated session_state to refresh the UI.
    return


def load_last_step(
    module_dir: Path,
    steps_file: Path,
    index_page: str,
) -> None:
    """Load the last step for a module into session state."""
    details_store = st.session_state.setdefault(f"{index_page}__details", {})
    all_steps = load_all_steps(module_dir, steps_file, index_page)
    if all_steps:
        last_step = len(all_steps) - 1
        current_step = st.session_state[index_page][0]
        if current_step <= last_step:
            entry = all_steps[current_step] or {}
            d = entry.get("D", "")
            q = entry.get("Q", "")
            c = entry.get("C", "")
            detail = details_store.get(current_step, "")
            st.session_state[index_page][1:5] = [d, q, c, detail]
            # Drive the text area via session state, using a revisioned key to control remounts
            q_rev = st.session_state.get(f"{index_page}__q_rev", 0)
            prompt_key = f"{index_page}_q__{q_rev}"
            # Allow actions to force a blank prompt on the next run
            if st.session_state.pop(f"{index_page}__force_blank_q", False):
                st.session_state[prompt_key] = ""
            else:
                st.session_state[prompt_key] = q
        else:
            clean_query(index_page)


def clean_query(index_page: str) -> None:
    """Reset the query fields in session state."""
    df_value = st.session_state.get("df_file", "") or ""
    st.session_state[index_page][1:-1] = [df_value, "", "", ""]
    details_store = st.session_state.setdefault(f"{index_page}__details", {})
    current_step = st.session_state[index_page][0] if index_page in st.session_state else None
    if current_step is not None:
        details_store.pop(current_step, None)


@st.cache_data(show_spinner=False)
def _read_steps(steps_file: Path, module_key: str, mtime_ns: int) -> List[Dict[str, Any]]:
    """Read steps for a specific module key from a TOML file.

    Caches on (path, module_key, mtime_ns) so saves invalidate automatically.
    """
    with open(steps_file, "rb") as f:
        data = tomli.load(f)
    return list(data.get(module_key, []))


def load_all_steps(
    module_path: Path,
    steps_file: Path,
    index_page: str,
) -> Optional[List[Dict[str, Any]]]:
    """Load all steps for a module from a TOML file using str(module_path) as key.

    Uses a small cache keyed by file mtime to avoid re-parsing on every rerun.
    """
    try:
        module_key = str(Path(str(module_path)))
        mtime_ns = steps_file.stat().st_mtime_ns
        filtered_entries = _read_steps(steps_file, module_key, mtime_ns)
        if filtered_entries and not st.session_state[index_page][-1]:
            st.session_state[index_page][-1] = len(filtered_entries)
        # Lazily materialize a notebook if it's missing; read full TOML once
        if filtered_entries and not steps_file.with_suffix(".ipynb").exists():
            try:
                with open(steps_file, "rb") as f:
                    steps_full = tomli.load(f)
                toml_to_notebook(steps_full, steps_file)
            except Exception as e:
                logger.warning(f"Skipping notebook generation: {e}")
        return filtered_entries
    except FileNotFoundError:
        return []
    except tomli.TOMLDecodeError as e:
        st.error(f"Error decoding TOML: {e}")
        return []


def on_query_change(
    request_key: str,
    module: Path,
    step: int,
    steps_file: Path,
    df_file: Path,
    index_page: str,
    env: AgiEnv,
    provider_snapshot: str,
) -> None:
    """Handle the query action when user input changes."""
    current_provider = st.session_state.get(
        "lab_llm_provider",
        env.envars.get("LAB_LLM_PROVIDER", "openai"),
    )
    if provider_snapshot and provider_snapshot != current_provider:
        # Provider changed between the widget render and callback; skip the stale request.
        return

    try:
        if st.session_state.get(request_key):
            answer = ask_gpt(
                st.session_state[request_key], df_file, index_page, env.envars
            )
            detail = answer[3] if len(answer) > 3 else ""
            details_key = f"{index_page}__details"
            details_store = st.session_state.setdefault(details_key, {})
            if detail:
                details_store[step] = detail
            else:
                details_store.pop(step, None)
            nstep, entry = save_step(module, answer, step, 0, steps_file)
            st.session_state[index_page][0] = step
            # Deterministic mapping to D/Q/C slots
            d = entry.get("D", "")
            q = entry.get("Q", "")
            c = entry.get("C", "")
            st.session_state[index_page][1:5] = [d, q, c, detail or ""]
            st.session_state[f"{index_page}_q"] = q
            st.session_state[index_page][-1] = nstep
        st.session_state.pop(f"{index_page}_a_{step}", None)
        st.session_state.page_broken = True
    except JumpToMain:
        pass


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

    return "", text


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
DEFAULT_UOAIC_BASE = Path.home() / ".agilab" / "mistral_offline"
_HF_TOKEN_ENV_KEYS = ("HF_TOKEN", "HUGGINGFACEHUB_API_TOKEN")
_API_KEY_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9]{4,})([A-Za-z0-9\-*_]{8,})"),
    re.compile(r"(sk-proj-[A-Za-z0-9]{4,})([A-Za-z0-9\-*_]{8,})"),
]


def _redact_sensitive(text: str) -> str:
    """Mask API keys or similar secrets present in provider error messages."""
    if not text:
        return text
    redacted = str(text)
    for pattern in _API_KEY_PATTERNS:
        redacted = pattern.sub(lambda m: f"{m.group(1)}…", redacted)
    return redacted


def _is_placeholder_api_key(key: Optional[str]) -> bool:
    """Heuristic to detect missing or redacted API key strings."""
    if not key:
        return True
    value = key.strip()
    if not value:
        return True
    if len(value) < 20:
        return True
    CHECK_MARKERS = ("***", "…", "xxx", "xxxxx", "YOUR-API-KEY", "YOUR_API_KEY")
    upper_value = value.upper()
    for marker in CHECK_MARKERS:
        if marker in value or marker in upper_value:
            return True
    return False


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
) -> str:
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
        return _synthesize_stub_response(input_request)

    return text


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
    return "\n".join(lines).strip()


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
                base = Path(env.AGILAB_EXPORT_ABS)
            except Exception:  # pragma: no cover - defensive
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
            "to enable the mistral:instruct assistant."
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
                except Exception:
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
    except Exception as exc:
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
    except Exception as exc:
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
    }
    st.session_state[UOAIC_RUNTIME_KEY] = runtime
    return runtime


def chat_universal_offline(
    input_request: str,
    prompt: List[Dict[str, str]],
    envars: Dict[str, str],
) -> str:
    """Invoke the Universal Offline AI Chatbot pipeline for the current query."""
    runtime = _ensure_uoaic_runtime(envars)
    chain = runtime["chain"]
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

    return answer_text


def chat_online(
    input_request: str,
    prompt: List[Dict[str, str]],
    envars: Dict[str, str],
) -> str:
    """Minimal, robust Chat Completions call to get fenced Python code."""

    import openai

    api_key = envars.get("OPENAI_API_KEY", "")
    if not api_key:
        st.warning("OpenAI API key is required to use this page. Enter it below to continue.")
        entered = st.text_input("OpenAI API key", value="", type="password", key="experiment_openai_key")
        save_profile = st.checkbox("Save to profile (~/.agilab/.env)", value=True, key="experiment_save_openai_key")
        submit = st.button("Use API key", key="experiment_submit_openai_key")
        if not submit:
            st.stop()
        api_key = (entered or "").strip()
        if not api_key:
            st.error("Please enter a valid API key.")
            st.stop()
        # Persist for the current session/runtime
        envars["OPENAI_API_KEY"] = api_key
        try:
            from agi_env import AgiEnv
            AgiEnv.set_env_var("OPENAI_API_KEY", api_key)
        except Exception:
            pass
        # Optionally persist to ~/.agilab/.env
        if save_profile:
            try:
                from pathlib import Path
                env_dir = Path.home() / ".agilab"
                env_dir.mkdir(parents=True, exist_ok=True)
                env_file = env_dir / ".env"
                existing = []
                if env_file.exists():
                    existing = env_file.read_text().splitlines()
                    existing = [line for line in existing if not line.strip().startswith("OPENAI_API_KEY=")]
                existing.append(f'OPENAI_API_KEY="{api_key}"')
                env_file.write_text("\n".join(existing) + "\n", encoding="utf-8")
                st.success("API key saved to ~/.agilab/.env")
            except Exception as e:
                st.warning(f"Could not persist API key: {e}")
    if _is_placeholder_api_key(api_key):
        st.info(
            "OpenAI API key appears to be a placeholder or redacted. Update `OPENAI_API_KEY`"
            " in your environment or secrets, then rerun the request."
        )
        raise JumpToMain(ValueError("OpenAI API key unavailable"))

    model_name = envars.get("OPENAI_MODEL", "gpt-4o-mini")

    # Strict system to force fenced Python code
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

    try:
        client = openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(model=model_name, messages=messages)
        return resp.choices[0].message.content or ""
    except openai.OpenAIError as e:
        msg = _redact_sensitive(str(e))
        status = getattr(e, "status_code", None)
        if status == 401 or "invalid_api_key" in str(e):
            st.info("OpenAI API key invalid or missing. Update `OPENAI_API_KEY` and rerun.")
        else:
            st.error(f"OpenAI API error: {msg}")
        logger.error(f"OpenAI error: {msg}")
        raise JumpToMain(e)
    except Exception as e:
        msg = _redact_sensitive(str(e))
        st.error(f"Error: {msg}")
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
    if provider == "gpt-oss":
        result = chat_offline(question, prompt, envars)
    elif provider == UOAIC_PROVIDER:
        result = chat_universal_offline(question, prompt, envars)
    else:
        result = chat_online(question, prompt, envars)

    if not result:
        return [df_file, question, None, None]

    code, detail = extract_code(result)
    detail = detail or ("" if code else result.strip())
    return [df_file, question, code.strip() if code else "", detail]


def is_query_valid(query: Any) -> bool:
    """Check if a query is valid."""
    return isinstance(query, list) and bool(query[2])


def get_steps_list(module: Union[str, Path], steps_file: Path) -> List[Any]:
    """Get the list of steps for a module from a TOML file."""
    try:
        with open(steps_file, "rb") as f:
            steps = tomli.load(f)
    except (FileNotFoundError, tomli.TOMLDecodeError):
        steps = {}
    return steps.get(str(module), [])


def get_steps_dict(module: Union[str, Path], steps_file: Path) -> Dict[str, Any]:
    """Get the steps dictionary from a TOML file."""
    try:
        with open(steps_file, "rb") as f:
            steps = tomli.load(f)
    except (FileNotFoundError, tomli.TOMLDecodeError):
        steps = {}
    return steps


def remove_step(
    module: Union[str, Path],
    step: str,
    steps_file: Path,
    index_page: str,
) -> int:
    """Remove a step from the steps file."""
    steps = get_steps_dict(module, steps_file)
    nsteps = len(steps.get(str(module), []))
    index_step = int(step)
    details_key = f"{index_page}__details"
    details_store = st.session_state.setdefault(details_key, {})
    if 0 <= index_step < nsteps:
        del steps[str(module)][index_step]
        nsteps -= 1
        st.session_state[index_page][0] = max(0, nsteps - 1)
        st.session_state[index_page][-1] = nsteps
        shifted: Dict[int, str] = {}
        for idx, text in details_store.items():
            if idx < index_step:
                shifted[idx] = text
            elif idx > index_step:
                shifted[idx - 1] = text
        st.session_state[details_key] = shifted
    else:
        st.session_state[index_page][0] = 0

    serializable_steps = convert_paths_to_strings(steps)
    try:
        with open(steps_file, "wb") as f:
            tomli_w.dump(serializable_steps, f)
    except Exception as e:
        st.error(f"Failed to save steps file: {e}")
        logger.error(f"Error writing TOML in remove_step: {e}")

    return nsteps


def toml_to_notebook(toml_data: Dict[str, Any], toml_path: Path) -> None:
    """Convert TOML steps data to a Jupyter notebook file."""
    notebook_data = {"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    for module, steps in toml_data.items():
        for step in steps:
            code_cell = {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": (step.get("C", "").splitlines(keepends=True) if step.get("C") else []),
            }
            notebook_data["cells"].append(code_cell)
    notebook_path = toml_path.with_suffix(".ipynb")
    try:
        with open(notebook_path, "w", encoding="utf-8") as nb_file:
            json.dump(notebook_data, nb_file, indent=2)
    except Exception as e:
        st.error(f"Failed to save notebook: {e}")
        logger.error(f"Error saving notebook in toml_to_notebook: {e}")


def save_query(module: Union[str, Path], query: List[Any], steps_file: Path) -> None:
    """Save the query to the steps file if valid."""
    if is_query_valid(query):
        # Persist only D, Q, and C
        query[-1], _ = save_step(module, query[1:4], query[0], query[-1], steps_file)
    export_df()


def save_step(
    module: Union[str, Path],
    query: List[Any],
    current_step: int,
    nsteps: int,
    steps_file: Path,
) -> Tuple[int, Dict[str, Any]]:
    """Save a step in the steps file."""
    # Persist only D, Q, and C
    fields = ["D", "Q", "C"]
    entry = {field: (query[i] if i < len(query) else "") for i, field in enumerate(fields)}
    # Normalize types
    try:
        nsteps = int(nsteps)
    except Exception:
        nsteps = 0
    try:
        index_step = int(current_step)
    except Exception:
        index_step = 0
    if steps_file.exists():
        with open(steps_file, "rb") as f:
            steps = tomli.load(f)
    else:
        os.makedirs(steps_file.parent, exist_ok=True)
        steps = {}

    module_str = str(module)
    steps.setdefault(module_str, [])
    nsteps_saved = len(steps[module_str])
    nsteps = max(int(nsteps), nsteps_saved)

    if index_step < nsteps_saved:
        steps[module_str][index_step] = entry
    else:
        steps[module_str].append(entry)

    serializable_steps = convert_paths_to_strings(steps)
    try:
        with open(steps_file, "wb") as f:
            tomli_w.dump(serializable_steps, f)
    except Exception as e:
        st.error(f"Failed to save steps file: {e}")
        logger.error(f"Error writing TOML in save_step: {e}")

    toml_to_notebook(steps, steps_file)
    return nsteps, entry


def on_nb_change(
    module: Union[str, Path],
    query: List[Any],
    file_step_path: Path,
    project: str,
    notebook_file: Path,
    env: AgiEnv,
) -> None:
    """Handle notebook interaction and run notebook if possible."""
    save_step(module, query[1:4], query[0], query[-1], file_step_path)
    project_path = env.apps_dir / project
    if notebook_file.exists():
        cmd = f"uv -q run jupyter notebook {notebook_file}"
        output = run_lab(cmd, venv=project_path, wait=True)
        if output is None:
            open_notebook_in_browser()
        else:
            st.info(output)
    else:
        st.info(f"No file named {notebook_file} found!")


def notebook_to_toml(
    uploaded_file: Any,
    toml_file_name: str,
    module_dir: Path,
) -> int:
    """Convert uploaded Jupyter notebook file to a TOML file."""
    toml_path = module_dir / toml_file_name
    file_content = uploaded_file.read().decode("utf-8")
    notebook_content = json.loads(file_content)
    toml_content = {}
    module = module_dir.name
    toml_content[module] = []
    cell_count = 0
    for cell in notebook_content.get("cells", []):
        if cell.get("cell_type") == "code":
            step = {"D": "", "Q": "", "C": "".join(cell.get("source", [])), "M": ""}
            toml_content[module].append(step)
            cell_count += 1
    try:
        with open(toml_path, "wb") as toml_file:
            tomli_w.dump(toml_content, toml_file)
    except Exception as e:
        st.error(f"Failed to save TOML file: {e}")
        logger.error(f"Error writing TOML in notebook_to_toml: {e}")
    return cell_count


def on_import_notebook(
    key: str,
    module_dir: Path,
    steps_file: Path,
    index_page: str,
) -> None:
    """Handle notebook file import via sidebar uploader."""
    uploaded_file = st.session_state.get(key)
    if uploaded_file and "ipynb" in uploaded_file.type:
        cell_count = notebook_to_toml(uploaded_file, steps_file.name, module_dir)
        st.session_state[index_page][-1] = cell_count
        st.session_state.page_broken = True


def on_lab_change(new_index_page: str) -> None:
    """Handle lab directory change event."""
    st.session_state.pop("steps_file", None)
    st.session_state.pop("df_file", None)
    key = str(st.session_state.get("index_page", "")) + "df"
    st.session_state.pop(key, None)
    st.session_state["lab_dir"] = new_index_page
    st.session_state.page_broken = True


def open_notebook_in_browser() -> None:
    """Inject JS to open the Jupyter Notebook URL in a new tab."""
    js_code = f"""
    <script>
    window.open("{JUPYTER_URL}", "_blank");
    </script>
    """
    st.components.v1.html(js_code, height=0, width=0)


def sidebar_controls() -> None:
    """Create sidebar controls for selecting modules and DataFrames."""
    env: AgiEnv = st.session_state["env"]
    Agi_export_abs = Path(env.AGILAB_EXPORT_ABS)
    modules = st.session_state.get("modules", scan_dir(Agi_export_abs))

    provider_options = {
        "OpenAI (online)": "openai",
        "GPT-OSS (local)": "gpt-oss",
        "mistral:instruct (local)": UOAIC_PROVIDER,
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

    st.session_state["lab_dir"] = st.sidebar.selectbox(
        "Lab Directory",
        modules,
        index=modules.index(st.session_state.get("lab_dir", env.target)),
        on_change=lambda: on_lab_change(st.session_state.lab_dir_selectbox),
        key="lab_dir_selectbox",
    )

    steps_file_name = st.session_state["steps_file_name"]
    lab_dir = Agi_export_abs / st.session_state["lab_dir_selectbox"]
    st.session_state.df_dir = Agi_export_abs / lab_dir
    steps_file = env.active_app / steps_file_name
    st.session_state["steps_file"] = steps_file

    steps_files = find_files(lab_dir, ".toml")
    st.session_state.steps_files = steps_files
    steps_files_path = [Path(file) for file in steps_files]
    steps_files_rel = [file.relative_to(Agi_export_abs) for file in steps_files_path]
    steps_file_rel = sorted(
        [file for file in steps_files_rel if file.parts[0].startswith(st.session_state["lab_dir"])]
    )

    if "index_page" not in st.session_state:
        index_page = steps_file_rel[0] if steps_file_rel else env.target
        st.session_state["index_page"] = index_page
    else:
        index_page = st.session_state["index_page"]

    index_page_str = str(index_page)

    if steps_file_rel:
        st.sidebar.selectbox("Steps", steps_file_rel, key="index_page", on_change=on_page_change)

    df_files = find_files(lab_dir)
    st.session_state.df_files = df_files

    if not steps_file.parent.exists():
        steps_file.parent.mkdir(parents=True, exist_ok=True)

    df_files_rel = sorted((Path(file).relative_to(Agi_export_abs) for file in df_files), key=str)
    key_df = index_page_str + "df"
    index = next((i for i, f in enumerate(df_files_rel) if f.name == DEFAULT_DF), 0)

    module_path = lab_dir.relative_to(Agi_export_abs)
    st.session_state["module_path"] = module_path

    st.sidebar.selectbox(
        "DataFrame",
        df_files_rel,
        key=key_df,
        index=index,
        on_change=on_df_change,
        args=(module_path, st.session_state.df_file, index_page_str, steps_file),
    )

    if st.session_state.get(key_df):
        st.session_state["df_file"] = str(Agi_export_abs / st.session_state[key_df])
    else:
        st.session_state["df_file"] = None

    key = index_page_str + "import_notebook"
    st.sidebar.file_uploader(
        "Import Notebook",
        type="ipynb",
        key=key,
        on_change=on_import_notebook,
        args=(key, module_path, index_page_str, steps_file),
    )


def mlflow_controls() -> None:
    """Display MLflow UI controls in sidebar."""
    if st.session_state.get("server_started") and st.sidebar.button("Open MLflow UI"):
        mlflow_port = st.session_state.get("mlflow_port", 5000)
        st.sidebar.info(f"MLflow UI is running on port {mlflow_port}.")
        webbrowser.open_new_tab(f"http://localhost:{mlflow_port}")
        st.sidebar.success("MLflow UI has been opened in a new browser tab.")
        st.sidebar.markdown(
            """
            <style>
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100%;
            </style>
            <div class="centered">
                <h1 style='font-size:50px;'>😄</h1>
            </div>
            """,
            unsafe_allow_html=True,
        )
    elif not st.session_state.get("server_started"):
        st.sidebar.error("MLflow UI server is not running. Please start it from Edit.")


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

    default_data_path = DEFAULT_UOAIC_BASE / "data"
    data_default = (
        st.session_state.get(UOAIC_DATA_STATE_KEY)
        or env.envars.get(UOAIC_DATA_ENV)
        or os.getenv(UOAIC_DATA_ENV, "")
    )
    if not data_default:
        try:
            default_data_path.mkdir(parents=True, exist_ok=True)
        except Exception:
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
        except Exception:
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


def display_lab_tab(
    lab_dir: Path,
    index_page_str: str,
    steps_file: Path,
    module_path: Path,
    env: AgiEnv,
) -> None:
    """Display the ASSISTANT tab with steps and query input."""
    query = st.session_state[index_page_str]
    step = query[0]
    st.markdown(f"<h3 style='font-size:16px;'>Step {step + 1}</h3>", unsafe_allow_html=True)

    if query[-1]:
        cols = st.columns(BUTTONS_PER_LINE)
        for idx_button in range(query[-1]):
            col = cols[idx_button % BUTTONS_PER_LINE]
            str_button = str(idx_button + 1)
            col.button(
                str_button,
                use_container_width=True,
                on_click=on_step_change,
                args=(module_path, steps_file, idx_button, index_page_str),
                key=f"{index_page_str}_step_{str_button}",
            )

    # Compute a revisioned key for the prompt to allow forced remount/clear
    q_rev = st.session_state.get(f"{index_page_str}__q_rev", 0)
    prompt_key = f"{index_page_str}_q__{q_rev}"

    st.text_area(
        "Ask chatGPT:",
        key=prompt_key,
        on_change=on_query_change,
        args=(
            prompt_key,
            lab_dir,
            step,
            steps_file,
            st.session_state.df_file,
            index_page_str,
            env,
            st.session_state.get("lab_llm_provider", env.envars.get("LAB_LLM_PROVIDER", "openai")),
        ),
        placeholder="Enter your snippet in natural language",
        label_visibility="collapsed",
    )

    code_for_editor = (query[3] or "")
    detail_text = ""
    if len(query) > 4 and query[4]:
        detail_text = str(query[4]).strip()

    if detail_text:
        if code_for_editor:
            with st.expander("Assistant notes", expanded=False):
                st.markdown(detail_text)
        else:
            st.info(detail_text)

    remove_col, editor_col = st.columns((1, 11))

    with remove_col:
        disabled = st.session_state[index_page_str][-1] <= 0
        if st.button("🗑️", key=f"{index_page_str}_remove_step", disabled=disabled, help="Delete this step"):
            query[-1] = remove_step(lab_dir, str(step), steps_file, index_page_str)
            st.session_state[f"{index_page_str}__clear_q"] = True
            st.session_state[f"{index_page_str}__force_blank_q"] = True
            st.session_state[f"{index_page_str}__q_rev"] = st.session_state.get(f"{index_page_str}__q_rev", 0) + 1
            st.rerun()
            return

    with editor_col:
        snippet_dict: Optional[Dict[str, Any]] = None
        if code_for_editor:
            # Remount editor only when content actually changes
            rev = f"{step}-{len(code_for_editor)}"
            editor_key = f"{index_page_str}a{rev}"
            snippet_dict = code_editor(
                code_for_editor if code_for_editor.endswith("\n") else code_for_editor + "\n",
                height=(min(30, len(code_for_editor)) if code_for_editor else 100),
                theme="contrast",
                buttons=get_custom_buttons(),
                info=get_info_bar(),
                component_props=get_css_text(),
                props={"style": {"borderRadius": "0px 0px 8px 8px"}},
                key=editor_key,
            )

        action = snippet_dict.get("type") if snippet_dict else None
        if action == "remove":
            if st.session_state[index_page_str][-1] > 0:
                query[-1] = remove_step(lab_dir, str(step), steps_file, index_page_str)
                # Request prompt clear and refresh to reflect removed step state
                st.session_state[f"{index_page_str}__clear_q"] = True
                st.session_state[f"{index_page_str}__force_blank_q"] = True
                st.session_state[f"{index_page_str}__q_rev"] = st.session_state.get(f"{index_page_str}__q_rev", 0) + 1
                st.rerun()
                return
        elif action == "save":
            query[3] = snippet_dict["text"]
            save_query(lab_dir, query, steps_file)
        elif action == "next":
            query[3] = snippet_dict["text"]
            # Save current step
            save_query(lab_dir, query, steps_file)
            current_idx = int(query[0])
            nsteps_now = int(query[-1] or 0)
            # If we were on the last step, append a new blank step so the new button renders
            if current_idx >= max(0, nsteps_now - 1):
                new_nsteps, _ = save_step(lab_dir, ["", "", ""], current_idx + 1, nsteps_now, steps_file)
                query[-1] = new_nsteps
            # Advance to next step index if possible
            if query[0] < query[-1]:
                query[0] = current_idx + 1
                clean_query(index_page_str)
            # Request prompt clear on next run and bump revision so the widget remounts blank
            st.session_state[f"{index_page_str}__clear_q"] = True
            st.session_state[f"{index_page_str}__force_blank_q"] = True
            st.session_state[f"{index_page_str}__q_rev"] = st.session_state.get(f"{index_page_str}__q_rev", 0) + 1
            # Force UI to refresh and load the newly selected step
            st.rerun()
            return
        elif action == "run":
            query[3] = snippet_dict["text"]
            save_query(lab_dir, query, steps_file)
            if query[3] and not st.session_state.get("step_checked", False):
                run_lab(
                    query[1:-2],
                    st.session_state["snippet_file"],
                    env.copilot_file,
                )
                if isinstance(st.session_state.get("data"), pd.DataFrame) and not st.session_state["data"].empty:
                    export_target = st.session_state.get("df_file_out", "")
                    if save_csv(st.session_state["data"], export_target):
                        st.session_state["df_file_in"] = export_target
                        st.session_state["step_checked"] = True

    if st.session_state.pop("_experiment_reload_required", False):
        st.session_state.pop("loaded_df", None)

    if "loaded_df" not in st.session_state:
        df_source = st.session_state.get("df_file")
        st.session_state["loaded_df"] = (
            load_df_cached(Path(df_source)) if df_source else None
        )
    loaded_df = st.session_state["loaded_df"]
    if isinstance(loaded_df, pd.DataFrame) and not loaded_df.empty:
        st.dataframe(loaded_df)
    else:
        st.info("No data loaded yet. Click 'Run' to load dataset.")


def display_history_tab(steps_file: Path, module_path: Path) -> None:
    """Display the HISTORY tab with code editor for steps file."""
    if steps_file.exists():
        with open(steps_file, "rb") as f:
            code = f.read().decode("utf-8")
    else:
        code = ""
    action_onsteps = code_editor(
        code,
        height=min(30, len(code)),
        theme="contrast",
        buttons=get_custom_buttons(),
        info=get_info_bar(),
        component_props=get_css_text(),
        props={"style": {"borderRadius": "0px 0px 8px 8px"}},
        key=f"steps_{module_path}",
    )
    if action_onsteps["type"] == "save":
        try:
            with open(steps_file, "wb") as f:
                tomli_w.dump(json.loads(action_onsteps["text"]), f)
        except Exception as e:
            st.error(f"Failed to save steps file from editor: {e}")
            logger.error(f"Error saving steps file from editor: {e}")


def page() -> None:
    """Main page logic handler."""
    global df_file

    if 'env' not in st.session_state or not getattr(st.session_state["env"], "init_done", False):
        page_module = importlib.import_module("AGILAB")
        page_module.main()
        st.rerun()

    env: AgiEnv = st.session_state["env"]

    with open(Path(env.app_src) / "pre_prompt.json") as f:
        st.session_state["lab_prompt"] = json.load(f)

    sidebar_controls()

    lab_dir = Path(st.session_state["lab_dir"])
    index_page = st.session_state.get("index_page", lab_dir)
    index_page_str = str(index_page)
    steps_file = st.session_state["steps_file"]
    steps_file.parent.mkdir(parents=True, exist_ok=True)

    nsteps = len(get_steps_list(lab_dir, steps_file))
    st.session_state.setdefault(index_page_str, [nsteps, "", "", "", "", nsteps])
    st.session_state.setdefault(f"{index_page_str}__details", {})

    module_path = st.session_state["module_path"]
    # If a prompt clear was requested, clear the current revisioned key before loading the step
    if st.session_state.pop(f"{index_page_str}__clear_q", False):
        q_rev = st.session_state.get(f"{index_page_str}__q_rev", 0)
        st.session_state.pop(f"{index_page_str}_q__{q_rev}", None)
    load_last_step(module_path, steps_file, index_page_str)

    df_file = st.session_state.get("df_file")
    if not df_file or not Path(df_file).exists():
        st.info(
            f"No dataframe exported for {lab_dir.name}. "
            "Go to Execute, click “LOAD dataframe”, then “EXPORT dataframe” to produce export/export.csv."
        )
        st.stop()

    mlflow_controls()
    gpt_oss_controls(env)
    universal_offline_controls(env)

    lab_tab, history_tab = st.tabs(["ASSISTANT", "HISTORY"])
    with lab_tab:
        display_lab_tab(lab_dir, index_page_str, steps_file, module_path, env)
    with history_tab:
        display_history_tab(steps_file, module_path)


@st.cache_data
def get_df_files(export_abs_path: Path) -> List[Path]:
    return find_files(export_abs_path)


@st.cache_data
def load_df_cached(path: Path, nrows: int = 50, with_index: bool = True) -> Optional[pd.DataFrame]:
    return load_df(path, nrows, with_index)


def main() -> None:
    if 'env' not in st.session_state or not getattr(st.session_state["env"], "init_done", True):
        page_module = importlib.import_module("AGILAB")
        page_module.main()
        st.rerun()

    env: AgiEnv = st.session_state['env']

    try:
        st.set_page_config(
            layout="wide",
            menu_items=get_about_content(),
        )
        inject_theme(env.st_resources)

        st.session_state.setdefault("steps_file_name", STEPS_FILE_NAME)
        st.session_state.setdefault("help_path", Path(env.agilab_src) / "gui/help")
        st.session_state.setdefault("projects", env.apps_dir)
        st.session_state.setdefault("snippet_file", Path(env.AGILAB_LOG_ABS) / "lab_snippet.py")
        st.session_state.setdefault("server_started", False)
        st.session_state.setdefault("mlflow_port", 5000)

        df_dir_def = Path(env.AGILAB_EXPORT_ABS) / env.target
        st.session_state.setdefault("steps_file", Path(env.active_app) / STEPS_FILE_NAME)
        st.session_state.setdefault(
            "df_file_out", str(df_dir_def / ("lab_" + DEFAULT_DF.replace(".csv", "_out.csv")))
        )
        st.session_state.setdefault("df_file", str(df_dir_def / DEFAULT_DF))

        df_file = Path(st.session_state["df_file"]) if st.session_state["df_file"] else None
        if df_file:
            render_logo("Experiment on DATA")
        else:
            render_logo("Experiment on APPS")

        if not st.session_state.get("server_started", False):
            activate_mlflow(env)

        # Initialize session defaults
        defaults = {
            "response_dict": {"type": "", "text": ""},
            "apps_abs": env.apps_dir,
            "page_broken": False,
            "step_checked": False,
            "virgin_page": True,
        }
        for key, value in defaults.items():
            st.session_state.setdefault(key, value)

        page()

    except Exception as e:
        st.error(f"An error occurred: {e}")
        import traceback

        st.code(f"```\n{traceback.format_exc()}\n```")


if __name__ == "__main__":
    main()
