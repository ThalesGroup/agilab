import logging
import os
import json
import webbrowser
from pathlib import Path
import importlib
import importlib.metadata as importlib_metadata
import sys
import sysconfig
import textwrap
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

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
    run_agi,
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
from agi_env.defaults import get_default_openai_model

# Constants
STEPS_FILE_NAME = "lab_steps.toml"
DEFAULT_DF = "export.csv"
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
    st.session_state[f"{index_page}__q_rev"] = st.session_state.get(f"{index_page}__q_rev", 0) + 1
    # Drop any existing editor instance state for this step (best-effort)
    st.session_state.pop(f"{index_page}_a_{index_step}", None)
    venv_map = st.session_state.get(f"{index_page}__venv_map", {})
    st.session_state["lab_selected_venv"] = normalize_runtime_path(venv_map.get(index_step, ""))
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
            m = entry.get("M", "")
            c = entry.get("C", "")
            detail = details_store.get(current_step, "")
            st.session_state[index_page][1:6] = [d, q, m, c, detail]
            e = normalize_runtime_path(entry.get("E", ""))
            venv_map = st.session_state.setdefault(f"{index_page}__venv_map", {})
            if e:
                venv_map[current_step] = e
                st.session_state["lab_selected_venv"] = e
            else:
                venv_map.pop(current_step, None)
                st.session_state["lab_selected_venv"] = ""
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
    st.session_state[index_page][1:-1] = [df_value, "", "", "", ""]
    details_store = st.session_state.setdefault(f"{index_page}__details", {})
    current_step = st.session_state[index_page][0] if index_page in st.session_state else None
    if current_step is not None:
        details_store.pop(current_step, None)
        venv_store = st.session_state.setdefault(f"{index_page}__venv_map", {})
        venv_store.pop(current_step, None)
        st.session_state["lab_selected_venv"] = ""


def normalize_runtime_path(raw: Optional[Union[str, Path]]) -> str:
    """Return a canonical project directory for a runtime selection."""
    if not raw:
        return ""
    try:
        text = str(raw).strip()
        if not text:
            return ""
        candidate = Path(text).expanduser()
    except Exception:
        return str(raw)

    if candidate.name == ".venv":
        candidate = candidate.parent
    return str(candidate)


def _step_summary(entry: Optional[Dict[str, Any]], width: int = 60) -> str:
    """Return a concise summary for a step entry."""
    if not isinstance(entry, dict):
        return ""

    question = str(entry.get("Q") or "").strip()
    if question:
        collapsed = " ".join(question.split())
        return textwrap.shorten(collapsed, width=width, placeholder="…")

    code = str(entry.get("C") or "").strip()
    if code:
        first_line = code.splitlines()[0]
        collapsed = " ".join(first_line.split())
        return textwrap.shorten(collapsed, width=width, placeholder="…")

    return ""


def _step_label_for_multiselect(idx: int, entry: Optional[Dict[str, Any]]) -> str:
    """Label for the step order multiselect widget."""
    summary = _step_summary(entry)
    return f"Step {idx + 1}: {summary}" if summary else f"Step {idx + 1}"


def _step_button_label(display_idx: int, step_idx: int, entry: Optional[Dict[str, Any]]) -> str:
    """Label for a rendered step button respecting the selected order."""
    summary = _step_summary(entry)
    if summary:
        return f"{display_idx + 1}. {summary}"
    return f"{display_idx + 1}. Step {step_idx + 1}"


def _module_keys(module: Union[str, Path]) -> List[str]:
    """Return preferred TOML keys for the provided module path."""
    raw_path = Path(module)
    keys: List[str] = []
    env = st.session_state.get("env")
    if env:
        base = Path(getattr(env, "AGILAB_EXPORT_ABS", "") or "")
        if base:
            try:
                candidate = raw_path if raw_path.is_absolute() else (base / raw_path).resolve()
                rel = str(candidate.relative_to(base))
                keys.append(rel)
            except Exception:
                pass
    keys.append(str(raw_path))
    ordered: List[str] = []
    seen: set[str] = set()
    for key in keys:
        if key and key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered or [str(raw_path)]


def _ensure_primary_module_key(module: Union[str, Path], steps_file: Path) -> None:
    """Ensure steps are stored under the primary module key."""
    if not steps_file.exists():
        return
    try:
        with open(steps_file, "rb") as f:
            data = tomli.load(f)
    except Exception:
        return

    keys = _module_keys(module)
    primary = keys[0]
    candidates: List[Tuple[str, List[Dict[str, Any]]]] = []
    for key in keys:
        entries = data.get(key)
        if isinstance(entries, list) and entries:
            candidates.append((key, entries))

    if not candidates:
        return

    candidates.sort(key=lambda kv: (len(kv[1]), kv[0] != primary), reverse=True)
    best_key, best_entries = candidates[0]
    changed = best_key != primary or any(key != primary for key, _ in candidates[1:])
    if not changed:
        return

    data[primary] = best_entries
    for key, _ in candidates[1:]:
        if key != primary:
            data.pop(key, None)

    try:
        with open(steps_file, "wb") as f:
            tomli_w.dump(convert_paths_to_strings(data), f)
    except Exception:
        logger.warning("Failed to normalize module keys for %s", steps_file)


def _is_valid_step(entry: Dict[str, Any]) -> bool:
    """Return True if a step contains meaningful content."""
    if not entry:
        return False
    code = entry.get("C", "")
    if isinstance(code, str) and code.strip():
        return True
    return False


def _prune_invalid_entries(entries: List[Dict[str, Any]], keep_index: Optional[int] = None) -> List[Dict[str, Any]]:
    """Remove invalid steps, optionally preserving the entry at keep_index."""
    pruned: List[Dict[str, Any]] = []
    for idx, entry in enumerate(entries):
        if _is_valid_step(entry) or (keep_index is not None and idx == keep_index):
            pruned.append(entry)
    return pruned


def _bump_history_revision() -> None:
    """Increment the history revision so the HISTORY tab refreshes."""
    st.session_state["history_rev"] = st.session_state.get("history_rev", 0) + 1


def _persist_env_var(name: str, value: str) -> None:
    """Persist a key/value pair under ~/.agilab/.env, replacing prior entries."""
    from pathlib import Path

    env_dir = Path.home() / ".agilab"
    env_dir.mkdir(parents=True, exist_ok=True)
    env_file = env_dir / ".env"
    lines: List[str] = []
    if env_file.exists():
        lines = [
            line
            for line in env_file.read_text(encoding="utf-8").splitlines()
            if not line.strip().startswith(f"{name}=")
        ]
    lines.append(f'{name}="{value}"')
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _prompt_for_openai_api_key(message: str) -> None:
    """Prompt for a missing OpenAI API key and optionally persist it."""
    st.warning(message)
    default_val = st.session_state.get("openai_api_key", "")
    with st.form("experiment_missing_openai_api_key"):
        new_key = st.text_input(
            "OpenAI API key",
            value=default_val,
            type="password",
            help="Paste a valid OpenAI API token.",
        )
        save_profile = st.checkbox("Save to ~/.agilab/.env", value=True)
        submitted = st.form_submit_button("Update key")

    if submitted:
        cleaned = new_key.strip()
        if not cleaned:
            st.error("API key cannot be empty.")
        else:
            try:
                from agi_env import AgiEnv

                AgiEnv.set_env_var("OPENAI_API_KEY", cleaned)
            except Exception:
                pass
            env_obj = st.session_state.get("env")
            if getattr(env_obj, "envars", None) is not None:
                env_obj.envars["OPENAI_API_KEY"] = cleaned
            st.session_state["openai_api_key"] = cleaned
            if save_profile:
                try:
                    _persist_env_var("OPENAI_API_KEY", cleaned)
                    st.success("API key saved to ~/.agilab/.env")
                except Exception as exc:
                    st.warning(f"Could not persist API key: {exc}")
            else:
                st.success("API key updated for this session.")
            st.rerun()

    st.stop()


def _make_openai_client_and_model(envars: Dict[str, str], api_key: str):
    """
    Returns (client, model_name, is_azure). Supports:
      - OpenAI (api.openai.com)
      - Azure OpenAI (AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY / AZURE_OPENAI_API_VERSION)
      - Proxies/gateways via OPENAI_BASE_URL
    """
    import os
    from typing import Tuple

    # Inputs from env or envars
    base_url = (
        envars.get("OPENAI_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")               # common proxy var
        or os.getenv("OPENAI_API_BASE")               # legacy
        or ""
    )

    azure_endpoint = (
        envars.get("AZURE_OPENAI_ENDPOINT")
        or os.getenv("AZURE_OPENAI_ENDPOINT")
        or ""
    )
    azure_version = (
        envars.get("AZURE_OPENAI_API_VERSION")
        or os.getenv("AZURE_OPENAI_API_VERSION")
        or "2024-06-01"  # safe default as of 2025
    )
    # Model/deployment name
    model_name = (
        envars.get("OPENAI_MODEL")
        or os.getenv("OPENAI_MODEL")
        or os.getenv("AZURE_OPENAI_DEPLOYMENT")  # for Azure deployments
        or get_default_openai_model()
    )

    # Detect Azure vs OpenAI
    is_azure = bool(azure_endpoint) or bool(os.getenv("OPENAI_API_TYPE") == "azure") or bool(os.getenv("AZURE_OPENAI_API_KEY"))

    # Build client
    try:
        import openai
        # Prefer new SDK “OpenAI/AzureOpenAI” if present
        try:
            from openai import OpenAI as OpenAIClient
        except Exception:
            OpenAIClient = getattr(openai, "OpenAI", None)

        # Azure path
        if is_azure:
            try:
                from openai import AzureOpenAI
            except Exception:
                AzureOpenAI = None

            if AzureOpenAI is not None:
                client = AzureOpenAI(
                    api_key=api_key,
                    azure_endpoint=azure_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT"),
                    api_version=azure_version,
                )
                # For Azure, `model_name` must be the DEPLOYMENT name
                model_name = (
                    os.getenv("AZURE_OPENAI_DEPLOYMENT")
                    or envars.get("AZURE_OPENAI_DEPLOYMENT")
                    or model_name
                )
                return client, model_name, True
            else:
                # Fallback with base_url if azure client symbol isn’t available
                # Many gateways expose OpenAI-compatible endpoints at a base_url.
                endpoint = azure_endpoint.rstrip("/") + "/openai/deployments"
                # If no direct compat layer, still attempt with base_url if provided
                client = OpenAIClient(api_key=api_key, base_url=base_url or None) if OpenAIClient else None
                return client, model_name, True

        # Non-Azure path (OpenAI or proxy)
        if OpenAIClient:
            client_kwargs = {"api_key": api_key}
            if base_url:
                client_kwargs["base_url"] = base_url
            client = OpenAIClient(**client_kwargs)
            return client, model_name, False

        # Old SDK fallback
        openai.api_key = api_key
        if base_url:
            # Old SDK uses `openai.api_base`
            openai.api_base = base_url
        return openai, model_name, False

    except Exception as e:
        # Bubble up; caller handles a graceful error message.
        raise


def _ensure_cached_api_key(envars: Dict[str, str]) -> str:
    """Seed from session, secrets, env, and Azure if present."""
    cached = st.session_state.get("openai_api_key")
    if cached:
        return cached

    secret = ""
    try:
        secret = st.secrets.get("OPENAI_API_KEY", "")
    except Exception:
        pass

    candidate = (
        secret
        or envars.get("OPENAI_API_KEY")
        or os.environ.get("OPENAI_API_KEY", "")
        or os.environ.get("AZURE_OPENAI_API_KEY", "")  # Azure fallback
    )
    if candidate:
        st.session_state["openai_api_key"] = candidate
    return candidate


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
    _ensure_primary_module_key(module_path, steps_file)
    try:
        module_key = _module_keys(module_path)[0]
        mtime_ns = steps_file.stat().st_mtime_ns
        raw_entries = _read_steps(steps_file, module_key, mtime_ns)
        filtered_entries = _prune_invalid_entries(raw_entries)
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
            detail = answer[4] if len(answer) > 4 else ""
            model_label = answer[2] if len(answer) > 2 else ""
            venv_map = st.session_state.get(f"{index_page}__venv_map", {})
            nstep, entry = save_step(module, answer, step, 0, steps_file, venv_map=venv_map)
            skipped = st.session_state.get("_experiment_last_save_skipped", False)
            details_key = f"{index_page}__details"
            details_store = st.session_state.setdefault(details_key, {})
            if skipped or not detail:
                details_store.pop(step, None)
            else:
                details_store[step] = detail
            if skipped:
                st.info("Assistant response did not include runnable code. Step was not saved.")
            _bump_history_revision()
            st.session_state[index_page][0] = step
            # Deterministic mapping to D/Q/M/C slots
            d = entry.get("D", "")
            q = entry.get("Q", "")
            c = entry.get("C", "")
            m = entry.get("M", model_label)
            st.session_state[index_page][1:6] = [d, q, m, c, detail or ""]
            e = entry.get("E", "")
            if e:
                venv_map[step] = e
                st.session_state["lab_selected_venv"] = e
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
    """True only when clearly missing or visibly redacted."""
    if not key:
        return True
    v = str(key).strip()
    if not v:
        return True

    # Only reject obvious redactions/placeholders
    # Keep this extremely conservative to avoid false positives.
    U = v.upper()
    if "***" in v or "…" in v:
        return True
    if "YOUR-API-KEY" in U or "YOUR_API_KEY" in U:
        return True

    # Do NOT check prefixes or length; accept Azure / proxy / org-scoped formats.
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

    api_key = _ensure_cached_api_key(envars)
    if not api_key or _is_placeholder_api_key(api_key):
        _prompt_for_openai_api_key(
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
        client, model_name, is_azure = _make_openai_client_and_model(envars, api_key)
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
        if status in (401, 403):
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
        result, model_label = chat_universal_offline(question, prompt, envars)
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


def is_query_valid(query: Any) -> bool:
    """Check if a query is valid."""
    return isinstance(query, list) and bool(query[2])


def get_steps_list(module: Path, steps_file: Path) -> List[Any]:
    """Get the list of steps for a module from a TOML file."""
    module_path = Path(module)
    _ensure_primary_module_key(module_path, steps_file)
    try:
        with open(steps_file, "rb") as f:
            steps = tomli.load(f)
    except (FileNotFoundError, tomli.TOMLDecodeError):
        return []

    for key in _module_keys(module_path):
        entries = steps.get(key)
        if isinstance(entries, list):
            return entries
    return []


def get_steps_dict(module: Path, steps_file: Path) -> Dict[str, Any]:
    """Get the steps dictionary from a TOML file."""
    module_path = Path(module)
    _ensure_primary_module_key(module_path, steps_file)
    try:
        with open(steps_file, "rb") as f:
            steps = tomli.load(f)
    except (FileNotFoundError, tomli.TOMLDecodeError):
        steps = {}
    else:
        keys = _module_keys(module_path)
        primary = keys[0]
        for alt_key in keys[1:]:
            if alt_key != primary:
                steps.pop(alt_key, None)
    return steps


def remove_step(
    module: Path,
    step: str,
    steps_file: Path,
    index_page: str,
) -> int:
    """Remove a step from the steps file."""
    module_path = Path(module)
    steps = get_steps_dict(module_path, steps_file)
    module_keys = _module_keys(module_path)
    module_key = next((key for key in module_keys if key in steps), module_keys[0])
    steps.setdefault(module_key, [])
    nsteps = len(steps.get(module_key, []))
    index_step = int(step)
    details_key = f"{index_page}__details"
    details_store = st.session_state.setdefault(details_key, {})
    venv_key = f"{index_page}__venv_map"
    venv_store = st.session_state.setdefault(venv_key, {})
    if 0 <= index_step < nsteps:
        del steps[module_key][index_step]
        nsteps -= 1
        st.session_state[index_page][0] = max(0, nsteps - 1)
        st.session_state[index_page][-1] = nsteps
        shifted: Dict[int, str] = {}
        vshifted: Dict[int, str] = {}
        for idx, text in details_store.items():
            if idx < index_step:
                shifted[idx] = text
            elif idx > index_step:
                shifted[idx - 1] = text
        st.session_state[details_key] = shifted
        for idx, path in venv_store.items():
            if idx < index_step:
                vshifted[idx] = path
            elif idx > index_step:
                vshifted[idx - 1] = path
        st.session_state[venv_key] = vshifted
    else:
        st.session_state[index_page][0] = 0
        st.session_state[venv_key] = venv_store

    steps[module_key] = _prune_invalid_entries(steps[module_key])
    nsteps = len(steps[module_key])
    st.session_state[index_page][-1] = nsteps

    serializable_steps = convert_paths_to_strings(steps)
    try:
        with open(steps_file, "wb") as f:
            tomli_w.dump(serializable_steps, f)
    except Exception as e:
        st.error(f"Failed to save steps file: {e}")
        logger.error(f"Error writing TOML in remove_step: {e}")

    _bump_history_revision()
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


def save_query(
    module: Path,
    query: List[Any],
    steps_file: Path,
    index_page: str,
) -> None:
    """Save the query to the steps file if valid."""
    module_path = Path(module)
    if is_query_valid(query):
        venv_map = st.session_state.get(f"{index_page}__venv_map", {})
        # Persist only D, Q, M, and C
        query[-1], _ = save_step(
            module_path,
            query[1:5],
            query[0],
            query[-1],
            steps_file,
            venv_map=venv_map,
        )
        _bump_history_revision()
    export_df()


def save_step(
    module: Path,
    query: List[Any],
    current_step: int,
    nsteps: int,
    steps_file: Path,
    venv_map: Optional[Dict[int, str]] = None,
) -> Tuple[int, Dict[str, Any]]:
    """Save a step in the steps file."""
    st.session_state["_experiment_last_save_skipped"] = False
    module_path = Path(module)
    _ensure_primary_module_key(module_path, steps_file)
    # Persist only D, Q, M, and C
    fields = ["D", "Q", "M", "C"]
    entry = {field: (query[i] if i < len(query) else "") for i, field in enumerate(fields)}
    if venv_map is not None:
        try:
            entry["E"] = normalize_runtime_path(venv_map.get(int(current_step), ""))
        except Exception:
            entry["E"] = ""
    else:
        entry.setdefault("E", "")
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

    module_keys = _module_keys(module_path)
    module_str = module_keys[0]
    steps.setdefault(module_str, [])
    for alt_key in module_keys[1:]:
        if alt_key in steps:
            alt_entries = steps.pop(alt_key)
            if not steps[module_str] or len(alt_entries) > len(steps[module_str]):
                steps[module_str] = alt_entries

    code_text = entry.get("C", "")
    if not isinstance(code_text, str):
        code_text = str(code_text or "")
    if not code_text.strip():
        st.session_state["_experiment_last_save_skipped"] = True
        existing_entry: Dict[str, Any] = {}
        if 0 <= index_step < len(steps[module_str]):
            current_entry = steps[module_str][index_step]
            if isinstance(current_entry, dict):
                existing_entry = current_entry
        return len(steps[module_str]), existing_entry

    nsteps_saved = len(steps[module_str])
    nsteps = max(int(nsteps), nsteps_saved)

    if index_step < nsteps_saved:
        steps[module_str][index_step] = entry
    else:
        steps[module_str].append(entry)

    steps[module_str] = _prune_invalid_entries(steps[module_str], keep_index=index_step)
    nsteps = len(steps[module_str])

    serializable_steps = convert_paths_to_strings(steps)
    try:
        with open(steps_file, "wb") as f:
            tomli_w.dump(serializable_steps, f)
    except Exception as e:
        st.error(f"Failed to save steps file: {e}")
        logger.error(f"Error writing TOML in save_step: {e}")

    toml_to_notebook(steps, steps_file)
    return nsteps, entry


def run_all_steps(
    lab_dir: Path,
    index_page_str: str,
    steps_file: Path,
    module_path: Path,
    env: AgiEnv,
) -> None:
    """Execute all steps sequentially, honouring per-step virtual environments."""
    steps = load_all_steps(module_path, steps_file, index_page_str) or []
    if not steps:
        st.info("No steps available to run.")
        return

    selected_map = st.session_state.setdefault(f"{index_page_str}__venv_map", {})
    details_store = st.session_state.setdefault(f"{index_page_str}__details", {})
    original_step = st.session_state[index_page_str][0]
    original_selected = normalize_runtime_path(st.session_state.get("lab_selected_venv", ""))
    snippet_file = st.session_state.get("snippet_file")
    if not snippet_file:
        st.error("Snippet file is not configured. Reload the page and try again.")
        return

    executed = 0
    with st.spinner("Running all steps…"):
        for idx, entry in enumerate(steps):
            code = entry.get("C", "")
            if not _is_valid_step(entry) or not code:
                continue

            venv_path = normalize_runtime_path(entry.get("E", ""))
            if venv_path:
                selected_map[idx] = venv_path
            else:
                selected_map.pop(idx, None)
            st.session_state["lab_selected_venv"] = venv_path

            st.session_state[index_page_str][0] = idx
            st.session_state[index_page_str][1] = entry.get("D", "")
            st.session_state[index_page_str][2] = entry.get("Q", "")
            st.session_state[index_page_str][3] = entry.get("M", "")
            st.session_state[index_page_str][4] = code
            st.session_state[index_page_str][5] = details_store.get(idx, "")

            venv_root = normalize_runtime_path(entry.get("E", ""))
            if venv_root:
                target_path = Path(venv_root).expanduser()
                run_agi(code, path=target_path)
            else:
                run_lab(
                    [entry.get("D", ""), entry.get("Q", ""), code],
                    snippet_file,
                    env.copilot_file,
                )

            if isinstance(st.session_state.get("data"), pd.DataFrame) and not st.session_state["data"].empty:
                export_target = st.session_state.get("df_file_out", "")
                if save_csv(st.session_state["data"], export_target):
                    st.session_state["df_file_in"] = export_target
                    st.session_state["step_checked"] = True
            executed += 1

    st.session_state[index_page_str][0] = original_step
    st.session_state["lab_selected_venv"] = normalize_runtime_path(original_selected)
    st.session_state[f"{index_page_str}__force_blank_q"] = True
    st.session_state[f"{index_page_str}__q_rev"] = st.session_state.get(f"{index_page_str}__q_rev", 0) + 1

    if executed:
        st.success(f"Executed {executed} step{'s' if executed != 1 else ''}.")
    else:
        st.info("No runnable code found in the steps.")


def on_nb_change(
    module: Path,
    query: List[Any],
    file_step_path: Path,
    project: str,
    notebook_file: Path,
    env: AgiEnv,
) -> None:
    """Handle notebook interaction and run notebook if possible."""
    module_path = Path(module)
    index_page = str(st.session_state.get("index_page", module_path))
    venv_map = st.session_state.get(f"{index_page}__venv_map", {})
    save_step(module_path, query[1:5], query[0], query[-1], file_step_path, venv_map=venv_map)
    _bump_history_revision()
    project_path = env.apps_dir / project
    if notebook_file.exists():
        cmd = f"uv -q run jupyter notebook {notebook_file}"
        code = (
            "import subprocess\n"
            f"subprocess.Popen({cmd!r}, shell=True, cwd={str(project_path)!r})\n"
        )
        output = run_agi(code, path=project_path)
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


def _normalize_venv_root(candidate: Path) -> Optional[Path]:
    """Return the resolved virtual environment directory when present."""
    try:
        path = candidate.expanduser()
    except Exception:
        path = candidate
    if not path.exists() or not path.is_dir():
        return None
    cfg = path / "pyvenv.cfg"
    if cfg.exists():
        try:
            return path.resolve()
        except Exception:
            return path
    return None


def _iter_venv_roots(base: Path) -> Iterator[Path]:
    """Yield virtual environments discovered directly underneath ``base``."""
    direct = _normalize_venv_root(base)
    if direct:
        yield direct
    dot = _normalize_venv_root(base / ".venv")
    if dot:
        yield dot
    try:
        for child in base.iterdir():
            if not child.is_dir():
                continue
            direct_child = _normalize_venv_root(child)
            if direct_child:
                yield direct_child
            dot_child = _normalize_venv_root(child / ".venv")
            if dot_child:
                yield dot_child
    except OSError:
        return


@st.cache_data(show_spinner=False)
def _cached_virtualenvs(base_dirs: Tuple[str, ...]) -> List[str]:
    """Return cached virtual environment paths under ``base_dirs``."""
    discovered: List[str] = []
    seen: set[str] = set()
    for raw in base_dirs:
        if not raw:
            continue
        base = Path(raw)
        if not base.exists() or not base.is_dir():
            continue
        for venv_root in _iter_venv_roots(base):
            key = str(venv_root)
            if key in seen:
                continue
            seen.add(key)
            discovered.append(key)
    discovered.sort()
    return discovered


def get_available_virtualenvs(env: AgiEnv) -> List[Path]:
    """Return virtual environments relevant to the active AGILab session."""
    base_dirs: List[str] = []
    for attr in ("active_app", "apps_dir", "runenv"):
        value = getattr(env, attr, None)
        if value:
            base_dirs.append(str(Path(value)))
    wenv_abs = getattr(env, "wenv_abs", None)
    if wenv_abs:
        base_dirs.append(str(Path(wenv_abs)))
    agilab_env = getattr(env, "agi_env", None)
    if agilab_env:
        base_dirs.append(str(Path(agilab_env)))

    cache_key = tuple(dict.fromkeys(base_dirs))
    venv_paths = _cached_virtualenvs(cache_key) if cache_key else []
    return [Path(path) for path in venv_paths]


def display_lab_tab(
    lab_dir: Path,
    index_page_str: str,
    steps_file: Path,
    module_path: Path,
    env: AgiEnv,
) -> None:
    """Display the ASSISTANT tab with steps and query input."""
    query = st.session_state[index_page_str]
    persisted_steps = load_all_steps(module_path, steps_file, index_page_str) or []
    persisted_count = len(persisted_steps)
    try:
        requested_total = int(query[-1])
    except Exception:
        requested_total = persisted_count
    if requested_total < 0:
        requested_total = 0
    total_steps = max(persisted_count, requested_total)
    if query[-1] != total_steps:
        query[-1] = total_steps
    all_steps = persisted_steps + [{} for _ in range(total_steps - persisted_count)]
    step = query[0]
    step_indices = list(range(total_steps))

    order_key = f"{index_page_str}__step_order"
    existing_order = st.session_state.get(order_key)
    if isinstance(existing_order, list):
        sanitized_order = [idx for idx in existing_order if idx in step_indices]
    else:
        sanitized_order = step_indices.copy()
        if not sanitized_order and step_indices:
            sanitized_order = step_indices.copy()
    if st.session_state.get(order_key) != sanitized_order:
        st.session_state[order_key] = sanitized_order

    displayed_indices = sanitized_order

    step_map = {idx: pos for pos, idx in enumerate(displayed_indices)}

    if total_steps and (step not in step_indices or step >= total_steps):
        fallback = displayed_indices[0] if displayed_indices else 0
        st.session_state[index_page_str][0] = fallback
        step = fallback
    elif displayed_indices and step not in displayed_indices:
        fallback = displayed_indices[0]
        st.session_state[index_page_str][0] = fallback
        step = fallback
    elif not total_steps:
        st.session_state[index_page_str][0] = 0
        step = 0

    st.subheader("Steps", divider="gray")
    snippet_file = st.session_state.get("snippet_file")

    if displayed_indices:
        cols = st.columns(min(len(displayed_indices), 3) or 1)
        for display_pos, step_idx in enumerate(displayed_indices):
            col = cols[display_pos % len(cols)]
            label_entry = all_steps[step_idx] if step_idx < total_steps else None
            button_label = _step_button_label(display_pos, step_idx, label_entry)
            button_type = "primary" if step_idx == step else "secondary"
            col.button(
                button_label,
                type=button_type,
                use_container_width=True,
                on_click=on_step_change,
                args=(module_path, steps_file, step_idx, index_page_str),
                key=f"{index_page_str}_step_{step_idx}",
            )
    elif total_steps == 0:
        st.info("No steps recorded yet. Ask the assistant to generate your first step.")
    else:
        st.info("No steps selected. Use the controls below to pick which steps are visible.")

    header_col, action_col = st.columns((20, 1))
    with header_col:
        display_position = step_map.get(step, step)
        summary = _step_summary(all_steps[step] if 0 <= step < total_steps else None, width=80)
        if summary:
            header_text = f"Step {display_position + 1 if display_position is not None else step + 1}: {summary}"
        else:
            header_text = f"Step {display_position + 1 if display_position is not None else step + 1}"
        st.markdown(f"<h3 style='font-size:16px;'>{header_text}</h3>", unsafe_allow_html=True)
    with action_col:
        delete_clicked = st.button(
            "🗑️",
            key=f"{index_page_str}_remove_step",
            disabled=total_steps <= 0,
            help="Delete this step",
        )

    if delete_clicked:
        query[-1] = remove_step(lab_dir, str(step), steps_file, index_page_str)
        st.session_state[f"{index_page_str}__clear_q"] = True
        st.session_state[f"{index_page_str}__force_blank_q"] = True
        st.session_state[f"{index_page_str}__q_rev"] = st.session_state.get(f"{index_page_str}__q_rev", 0) + 1
        st.rerun()
        return

    available_venvs = [
        normalize_runtime_path(path) for path in get_available_virtualenvs(env)
    ]
    available_venvs = [path for path in dict.fromkeys(available_venvs) if path]

    venv_state_key = f"{index_page_str}__venv_map"
    selected_map: Dict[int, str] = st.session_state.setdefault(venv_state_key, {})
    for idx_key, raw_value in list(selected_map.items()):
        normalized_value = normalize_runtime_path(raw_value)
        if normalized_value:
            selected_map[idx_key] = normalized_value
        else:
            selected_map.pop(idx_key, None)

    current_path = normalize_runtime_path(selected_map.get(step, ""))
    lab_selected_path = normalize_runtime_path(st.session_state.get("lab_selected_venv", ""))
    env_active_app = normalize_runtime_path(getattr(env, "active_app", ""))

    if env_active_app:
        available_venvs = [env_active_app] + [p for p in available_venvs if p != env_active_app]

    for candidate in [current_path, lab_selected_path, *selected_map.values()]:
        candidate_normalized = normalize_runtime_path(candidate)
        if candidate_normalized and candidate_normalized not in available_venvs:
            available_venvs.append(candidate_normalized)

    default_env_label = "Use AGILAB environment"
    venv_labels = [default_env_label] + available_venvs
    select_key = f"{index_page_str}_venv_{step}"
    with st.container(border=True):
        st.caption("Execution environment")
        session_label = st.session_state.get(select_key, "")
        initial_label = session_label or current_path or lab_selected_path or env_active_app
        if initial_label and initial_label not in venv_labels:
            venv_labels.append(initial_label)
        if initial_label:
            default_label = initial_label
        else:
            default_label = default_env_label
        if default_label not in venv_labels:
            venv_labels.append(default_label)
        if select_key not in st.session_state or st.session_state[select_key] not in venv_labels:
            st.session_state[select_key] = default_label
        selected_label = st.selectbox(
            "Active app",
            venv_labels,
            key=select_key,
            help="Choose which virtual environment should execute this step.",
        )
        selected_path = "" if selected_label == venv_labels[0] else normalize_runtime_path(selected_label)
        previous_path = normalize_runtime_path(selected_map.get(step, ""))
        if selected_path:
            selected_map[step] = selected_path
        else:
            selected_map.pop(step, None)
        if selected_path != previous_path:
            save_step(
                lab_dir,
                [query[1], query[2], query[3], query[4]],
                step,
                query[-1],
                steps_file,
                venv_map=selected_map,
            )
            _bump_history_revision()
        st.session_state["lab_selected_venv"] = selected_path

    # Compute a revisioned key for the prompt to allow forced remount/clear
    q_rev = st.session_state.get(f"{index_page_str}__q_rev", 0)
    prompt_key = f"{index_page_str}_q__{q_rev}"

    default_prompt_value = st.session_state.get(prompt_key)
    if default_prompt_value is None:
        st.session_state[prompt_key] = ""

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
        placeholder="Enter your code request in natural language",
        label_visibility="collapsed",
    )

    code_for_editor = (query[4] or "")
    detail_text = ""
    if len(query) > 5 and query[5]:
        detail_text = str(query[5]).strip()

    if detail_text:
        if code_for_editor:
            with st.expander("Assistant notes", expanded=False):
                st.markdown(detail_text)
        else:
            st.info(detail_text)


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
            selected_map.pop(step, None)
            st.session_state.pop(select_key, None)
            query[-1] = remove_step(lab_dir, str(step), steps_file, index_page_str)
            # Request prompt clear and refresh to reflect removed step state
            st.session_state[f"{index_page_str}__clear_q"] = True
            st.session_state[f"{index_page_str}__force_blank_q"] = True
            st.session_state[f"{index_page_str}__q_rev"] = st.session_state.get(f"{index_page_str}__q_rev", 0) + 1
            st.rerun()
            return
    elif action == "save":
        query[4] = snippet_dict["text"]
        save_query(lab_dir, query, steps_file, index_page_str)
    elif action == "next":
        query[4] = snippet_dict["text"]
        # Save current step
        save_query(lab_dir, query, steps_file, index_page_str)
        current_idx = int(query[0])
        nsteps_now = int(query[-1] or 0)
        # If we were on the last step, append a new blank step so the new button renders
        if current_idx >= max(0, nsteps_now - 1):
            new_total = max(nsteps_now + 1, current_idx + 2)
            query[-1] = new_total
            st.session_state[index_page_str][-1] = new_total
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
        query[4] = snippet_dict["text"]
        save_query(lab_dir, query, steps_file, index_page_str)
        if query[4] and not st.session_state.get("step_checked", False):
            selected_env = normalize_runtime_path(st.session_state.get("lab_selected_venv", ""))
            if selected_env:
                target_path = Path(selected_env).expanduser()
                run_agi(query[4], path=target_path)
            else:
                if not snippet_file:
                    st.error("Snippet file is not configured. Reload the page and try again.")
                    return
                run_lab([query[1], query[2], query[4]], snippet_file, env.copilot_file)
            if isinstance(st.session_state.get("data"), pd.DataFrame) and not st.session_state["data"].empty:
                export_target = st.session_state.get("df_file_out", "")
                if save_csv(st.session_state["data"], export_target):
                    st.session_state["df_file_in"] = export_target
                    st.session_state["step_checked"] = True

    st.subheader("Execution controls", divider="gray")
    st.caption("Select the steps to show (uncheck to hide); their order sets the button order.")
    selected_order = st.multiselect(
        "Step order & visibility",
        step_indices,
        key=order_key,
        format_func=lambda idx: _step_label_for_multiselect(idx, all_steps[idx] if idx < total_steps else None),
        help="Reorder or hide steps; changes are kept in session only.",
    )
    cleaned_selection = [idx for idx in selected_order if idx in step_indices]
    if cleaned_selection != st.session_state.get(order_key):
        st.session_state[order_key] = cleaned_selection

    run_all_col, delete_all_col = st.columns(2)
    with run_all_col:
        run_all_clicked = st.button(
            "Run all steps",
            key=f"{index_page_str}_run_all",
            help="Execute every step sequentially using its saved virtual environment.",
            type="secondary",
            use_container_width=True,
        )
    with delete_all_col:
        delete_all_clicked = st.button(
            "Delete all steps",
            key=f"{index_page_str}_delete_all",
            help="Remove every step in this lab.",
            type="secondary",
            use_container_width=True,
        )

    if run_all_clicked:
        run_all_steps(lab_dir, index_page_str, steps_file, module_path, env)
    if delete_all_clicked:
        total_steps = st.session_state[index_page_str][-1]
        for idx_remove in reversed(range(total_steps)):
            remove_step(lab_dir, str(idx_remove), steps_file, index_page_str)
        st.session_state[index_page_str] = [0, "", "", "", "", "", 0]
        st.session_state[f"{index_page_str}__details"] = {}
        st.session_state[f"{index_page_str}__venv_map"] = {}
        st.session_state["lab_selected_venv"] = ""
        st.session_state[f"{index_page_str}__clear_q"] = True
        st.session_state[f"{index_page_str}__force_blank_q"] = True
        st.session_state[f"{index_page_str}__q_rev"] = st.session_state.get(f"{index_page_str}__q_rev", 0) + 1
        st.session_state.pop(select_key, None)
        _bump_history_revision()
        st.rerun()

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
    _ensure_primary_module_key(module_path, steps_file)
    if steps_file.exists():
        with open(steps_file, "rb") as f:
            raw_data = tomli.load(f)
        cleaned: Dict[str, List[Dict[str, Any]]] = {}
        for mod, entries in raw_data.items():
            if isinstance(entries, list):
                filtered = [entry for entry in entries if _is_valid_step(entry)]
                if filtered:
                    cleaned[mod] = filtered
        code = json.dumps(cleaned, indent=2)
    else:
        code = "{}"
    history_rev = st.session_state.get("history_rev", 0)
    action_onsteps = code_editor(
        code,
        height=min(30, len(code)),
        theme="contrast",
        buttons=get_custom_buttons(),
        info=get_info_bar(),
        component_props=get_css_text(),
        props={"style": {"borderRadius": "0px 0px 8px 8px"}},
        key=f"steps_{module_path}_{history_rev}",
    )
    if action_onsteps["type"] == "save":
        try:
            data = json.loads(action_onsteps["text"] or "{}")
            cleaned: Dict[str, List[Dict[str, Any]]] = {}
            for mod, entries in data.items():
                if isinstance(entries, list):
                    filtered = [entry for entry in entries if _is_valid_step(entry)]
                    if filtered:
                        cleaned[mod] = filtered
            with open(steps_file, "wb") as f:
                tomli_w.dump(convert_paths_to_strings(cleaned), f)
            _bump_history_revision()
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
    if "openai_api_key" not in st.session_state:
        seed_key = env.envars.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
        if seed_key:
            st.session_state["openai_api_key"] = seed_key

    with open(Path(env.app_src) / "pre_prompt.json") as f:
        st.session_state["lab_prompt"] = json.load(f)

    sidebar_controls()

    lab_dir = Path(st.session_state["lab_dir"])
    index_page = st.session_state.get("index_page", lab_dir)
    index_page_str = str(index_page)
    steps_file = st.session_state["steps_file"]
    steps_file.parent.mkdir(parents=True, exist_ok=True)

    nsteps = len(get_steps_list(lab_dir, steps_file))
    st.session_state.setdefault(index_page_str, [nsteps, "", "", "", "", "", nsteps])
    st.session_state.setdefault(f"{index_page_str}__details", {})
    st.session_state.setdefault(f"{index_page_str}__venv_map", {})

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
        st.session_state.setdefault("help_path", Path(env.agilab_pck) / "gui/help")
        st.session_state.setdefault("projects", env.apps_dir)
        st.session_state.setdefault("snippet_file", Path(env.AGILAB_LOG_ABS) / "lab_snippet.py")
        st.session_state.setdefault("server_started", False)
        st.session_state.setdefault("mlflow_port", 5000)
        st.session_state.setdefault("lab_selected_venv", "")

        df_dir_def = Path(env.AGILAB_EXPORT_ABS) / env.target
        st.session_state.setdefault("steps_file", Path(env.active_app) / STEPS_FILE_NAME)
        st.session_state.setdefault(
            "df_file_out", str(df_dir_def / ("lab_" + DEFAULT_DF.replace(".csv", "_out.csv")))
        )
        st.session_state.setdefault("df_file", str(df_dir_def / DEFAULT_DF))

        df_file = Path(st.session_state["df_file"]) if st.session_state["df_file"] else None
        if df_file:
            render_logo()
        else:
            render_logo()

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
