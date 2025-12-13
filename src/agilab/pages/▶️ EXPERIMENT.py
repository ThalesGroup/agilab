import logging
import os
import json
import ast
import traceback
from pathlib import Path
import importlib
import importlib.metadata as importlib_metadata
import sys
import sysconfig
import textwrap
import subprocess
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

import pandas as pd
import re
os.environ.setdefault("STREAMLIT_CONFIG_FILE", str(Path(__file__).resolve().parents[1] / "resources" / "config.toml"))
import streamlit as st
import tomllib        # For reading TOML files
import tomli_w      # For writing TOML files

from code_editor import code_editor
import streamlit.components.v1 as components
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
    load_last_active_app,
    store_last_active_app,
)
from agi_env import AgiEnv, normalize_path
from agi_env.defaults import get_default_openai_model

# Constants
STEPS_FILE_NAME = "lab_steps.toml"
DEFAULT_DF = "lab_out.csv"
JUPYTER_URL = "http://localhost:8888"
# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
ANSI_ESCAPE_RE = re.compile(r"\x1b[^m]*m")


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


def _load_last_active_app_name(modules: List[str]) -> Optional[str]:
    """Return the last active app name if it maps to a known module directory."""
    last_path = load_last_active_app()
    if not last_path:
        return None
    candidates = [last_path.name, str(last_path)]

    def _normalize(candidate: str) -> Optional[str]:
        if candidate in modules:
            return candidate
        if candidate.endswith("_project") and candidate.removesuffix("_project") in modules:
            return candidate.removesuffix("_project")
        return None

    for name in candidates:
        if not name:
            continue
        normalized = _normalize(name)
        if normalized:
            return normalized
    return None


def _append_run_log(index_page: str, message: str) -> None:
    """Add a log line to the run log buffer (keeps the last 200)."""
    key = f"{index_page}__run_logs"
    logs: List[str] = st.session_state.setdefault(key, [])
    logs.append(message)
    if len(logs) > 200:
        st.session_state[key] = logs[-200:]


def _push_run_log(index_page: str, message: str, placeholder: Optional[Any] = None) -> None:
    """Append a log entry and refresh the visible placeholder if provided."""
    _append_run_log(index_page, message)
    log_file_key = f"{index_page}__run_log_file"
    log_file_path = st.session_state.get(log_file_key)
    if log_file_path:
        log_text = (message or "").rstrip("\n")
        if log_text:
            try:
                path_obj = Path(log_file_path).expanduser()
                path_obj.parent.mkdir(parents=True, exist_ok=True)
                with path_obj.open("a", encoding="utf-8") as log_file:
                    log_file.write(log_text + "\n")
            except Exception as exc:
                logger.debug(f"Failed to append experiment log to {log_file_path}: {exc}")
    if placeholder is not None:
        logs = st.session_state.get(f"{index_page}__run_logs", [])
        if logs:
            placeholder.code("\n".join(logs))
        else:
            placeholder.caption("No runs recorded yet.")


def _get_run_placeholder(index_page: str) -> Optional[Any]:
    """Return the cached run-log placeholder (if the UI has rendered it)."""
    key = f"{index_page}__run_placeholder"
    placeholder = st.session_state.get(key)
    return placeholder


def _python_for_venv(venv_root: str | Path | None) -> Path:
    """Return a python executable for a runtime selection.

    ``venv_root`` stored in lab steps is typically the *project* directory, not the
    venv itself. Prefer `<project>/.venv/bin/python` (or Windows Scripts) when present,
    otherwise fall back to the current interpreter.
    """
    if not venv_root:
        return Path(sys.executable)

    root = Path(venv_root).expanduser()
    venv_candidates = [root]
    project_venv = root / ".venv"
    if project_venv.exists():
        venv_candidates.insert(0, project_venv)

    for venv in venv_candidates:
        candidates = [
            venv / "bin" / "python",
            venv / "bin" / "python3",
            venv / "Scripts" / "python.exe",
            venv / "Scripts" / "python",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate

    return Path(sys.executable)


def _is_valid_runtime_root(venv_root: str | Path | None) -> bool:
    """Return True when the runtime root points at an existing project/venv."""
    if not venv_root:
        return False
    try:
        root = Path(venv_root).expanduser()
    except Exception:
        return False
    if not root.exists():
        return False
    if (root / ".venv").exists():
        return True
    for candidate in (
        root / "bin" / "python",
        root / "bin" / "python3",
        root / "Scripts" / "python.exe",
        root / "Scripts" / "python",
    ):
        if candidate.exists():
            return True
    return False


def _stream_run_command(
    env: AgiEnv,
    index_page: str,
    cmd: str,
    cwd: Path,
    placeholder: Optional[Any] = None,
    timeout: Optional[int] = None,
) -> str:
    """Run a shell command and stream its output into the run log."""
    process_env = os.environ.copy()
    process_env["uv_IGNORE_ACTIVE_VENV"] = "1"
    apps_root = getattr(env, "apps_path", None)
    extra_python_paths: List[str] = []
    if apps_root:
        try:
            apps_root = Path(apps_root).expanduser()
            src_root = apps_root.parent.parent
            if (src_root / "agilab").is_dir():
                extra_python_paths.append(str(src_root))
        except Exception:
            pass
    if extra_python_paths:
        existing = process_env.get("PYTHONPATH")
        joined = os.pathsep.join(extra_python_paths + ([existing] if existing else []))
        process_env["PYTHONPATH"] = joined
    lines: List[str] = []
    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=True,
        cwd=Path(cwd).resolve(),
        env=process_env,
        text=True,
        bufsize=1,
    ) as proc:
        try:
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                cleaned = ANSI_ESCAPE_RE.sub("", raw_line.rstrip())
                if cleaned:
                    lines.append(cleaned)
                    _push_run_log(index_page, cleaned, placeholder)
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            _push_run_log(index_page, f"Command timed out after {timeout} seconds.", placeholder)
        except subprocess.CalledProcessError as err:
            proc.kill()
            _push_run_log(index_page, f"Command failed: {err}", placeholder)
        combined = "\n".join(lines).strip()
        lowered = combined.lower()
        if "module not found" in lowered:
            apps_root = env.apps_path
            if apps_root and not (apps_root / ".venv").exists():
                raise JumpToMain(combined)
        return combined


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
            raw_e = normalize_runtime_path(entry.get("E", ""))
            e = raw_e if _is_valid_runtime_root(raw_e) else ""
            venv_map = st.session_state.setdefault(f"{index_page}__venv_map", {})
            if e:
                venv_map[current_step] = e
                st.session_state["lab_selected_venv"] = e
            else:
                venv_map.pop(current_step, None)
                st.session_state["lab_selected_venv"] = ""
            engine_map = st.session_state.setdefault(f"{index_page}__engine_map", {})
            selected_engine = entry.get("R", "") or ("agi.run" if e else "runpy")
            if selected_engine:
                engine_map[current_step] = selected_engine
            else:
                engine_map.pop(current_step, None)
            st.session_state["lab_selected_engine"] = selected_engine
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

    env = st.session_state.get("env")
    apps_root: Optional[Path] = None
    try:
        apps_root = Path(env.apps_path).expanduser()  # type: ignore[attr-defined]
    except Exception:
        apps_root = None

    if not candidate.is_absolute() and apps_root:
        candidate = apps_root / candidate

    # If the resolved path does not exist, but the basename matches an app under apps_root,
    # prefer that. This keeps older lab_steps that store repo-relative paths working.
    if apps_root and not candidate.exists():
        fallback = apps_root / candidate.name
        if fallback.exists():
            candidate = fallback

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
    try:
        base = Path(env.AGILAB_EXPORT_ABS)  # type: ignore[attr-defined]
        candidate = raw_path if raw_path.is_absolute() else (base / raw_path).resolve()
        rel = str(candidate.relative_to(base))
        keys.append(rel)
    except Exception:
        base = None
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
            data = tomllib.load(f)
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


def _sequence_meta_key(module_key: str) -> str:
    return f"{module_key}__sequence"


def _load_sequence_preferences(module: Union[str, Path], steps_file: Path) -> List[int]:
    """Return the stored execution order for a module, if any."""
    module_key = _module_keys(module)[0]
    try:
        with open(steps_file, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return []
    except tomllib.TOMLDecodeError as exc:
        logger.warning("Failed to parse sequence metadata from %s: %s", steps_file, exc)
        return []
    meta = data.get("__meta__", {})
    raw_sequence = meta.get(_sequence_meta_key(module_key), [])
    if not isinstance(raw_sequence, list):
        return []
    return [idx for idx in raw_sequence if isinstance(idx, int) and idx >= 0]


def _persist_sequence_preferences(
    module: Union[str, Path],
    steps_file: Path,
    sequence: List[int],
) -> None:
    """Persist the execution sequence ordering alongside the steps file."""
    module_key = _module_keys(module)[0]
    normalized = [int(idx) for idx in sequence if isinstance(idx, int) and idx >= 0]
    try:
        if steps_file.exists():
            with open(steps_file, "rb") as f:
                data = tomllib.load(f)
        else:
            data = {}
    except tomllib.TOMLDecodeError as exc:
        logger.error("Failed to load steps while saving sequence metadata: %s", exc)
        return
    meta = data.setdefault("__meta__", {})
    meta_key = _sequence_meta_key(module_key)
    if meta.get(meta_key) == normalized:
        return
    meta[meta_key] = normalized
    try:
        steps_file.parent.mkdir(parents=True, exist_ok=True)
        with open(steps_file, "wb") as f:
            tomli_w.dump(convert_paths_to_strings(data), f)
    except Exception as exc:
        logger.error("Failed to persist execution sequence to %s: %s", steps_file, exc)


def _is_valid_step(entry: Dict[str, Any]) -> bool:
    """Return True if a step contains meaningful content."""
    if not entry:
        return False
    code = entry.get("C", "")
    if isinstance(code, str) and code.strip():
        return True
    return False


def _looks_like_step(value: Any) -> bool:
    """Heuristic: True when value represents a non-negative integer step index."""
    try:
        iv = int(value)
        return iv >= 0
    except Exception:
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
            if isinstance(env_obj, AgiEnv) and env_obj.envars is not None:
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
    if cached and not _is_placeholder_api_key(cached):
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
    if candidate and not _is_placeholder_api_key(candidate):
        st.session_state["openai_api_key"] = candidate
        return candidate

    st.session_state["openai_api_key"] = ""
    return ""


@st.cache_data(show_spinner=False)
def _read_steps(steps_file: Path, module_key: str, mtime_ns: int) -> List[Dict[str, Any]]:
    """Read steps for a specific module key from a TOML file.

    Caches on (path, module_key, mtime_ns) so saves invalidate automatically.
    """
    with open(steps_file, "rb") as f:
        data = tomllib.load(f)
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
                    steps_full = tomllib.load(f)
                toml_to_notebook(steps_full, steps_file)
            except Exception as e:
                logger.warning(f"Skipping notebook generation: {e}")
        return filtered_entries
    except FileNotFoundError:
        return []
    except tomllib.TOMLDecodeError as e:
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
            raw_text = str(st.session_state[request_key])
            trimmed = raw_text.strip()
            # Skip chat calls when the input looks like a pure comment.
            if trimmed.startswith("#") or trimmed.endswith("#"):
                st.info("Query skipped because it looks like a comment (starts/ends with '#').")
                return

            answer = ask_gpt(
                raw_text, df_file, index_page, env.envars
            )
            detail = answer[4] if len(answer) > 4 else ""
            model_label = answer[2] if len(answer) > 2 else ""
            venv_map = st.session_state.get(f"{index_page}__venv_map", {})
            engine_map = st.session_state.get(f"{index_page}__engine_map", {})
            nstep, entry = save_step(
                module,
                answer,
                step,
                0,
                steps_file,
                venv_map=venv_map,
                engine_map=engine_map,
            )
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
    except Exception:
        return []

    try:
        parsed = json.loads(raw)
    except Exception:
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
        if not name:
            continue
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
        except Exception:
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
        except Exception:
            return float(default)

    def _int_env(name: str) -> Optional[int]:
        raw = envars.get(name) or os.getenv(name)
        if raw is None or not str(raw).strip():
            return None
        try:
            return int(float(raw))
        except Exception:
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


def _exec_code_on_df(code: str, df: pd.DataFrame) -> Tuple[Optional[pd.DataFrame], str]:
    """Execute code against a copy of df. Returns (new_df, error)."""
    df_local = df.copy()
    local_vars: Dict[str, Any] = {"df": df_local, "pd": pd}
    try:
        compiled = compile(code, "<lab_step>", "exec")
        exec(compiled, {}, local_vars)
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


def _load_env_file_map(path: Path) -> Dict[str, str]:
    """Return a key/value mapping from the .env file (commented lines included)."""
    env_map: Dict[str, str] = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            stripped = raw.strip()
            if not stripped or "=" not in stripped:
                continue
            target = stripped.lstrip("#").strip()
            if "=" not in target:
                continue
            key, val = target.split("=", 1)
            key = key.strip()
            if key:
                env_map[key] = val.strip()
    except FileNotFoundError:
        pass
    return env_map


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
    if v in {"your-key", "sk-your-key", "sk-XXXX"}:
        return True
    if len(v) < 12:
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

    # Refresh envars from the latest .env so model/key changes take effect without restart.
    env_file_map = _load_env_file_map(ENV_FILE_PATH)
    if env_file_map:
        envars.update(env_file_map)

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
    except Exception:
        max_attempts = 2
    if max_attempts <= 0:
        return merged_code, model_label, detail

    df: Any = st.session_state.get("loaded_df")
    if not isinstance(df, pd.DataFrame) or df.empty:
        df_file = st.session_state.get("df_file")
        if df_file:
            df = load_df_cached(Path(df_file))

    if not isinstance(df, pd.DataFrame) or df.empty:
        _push_run_log(index_page, "Auto-fix skipped: no dataframe is loaded.", _get_run_placeholder(index_page))
        return merged_code, model_label, detail

    placeholder = _get_run_placeholder(index_page)
    _, err = _exec_code_on_df(merged_code, df)
    if not err:
        _push_run_log(index_page, "Auto-fix: generated code validated successfully.", placeholder)
        return merged_code, model_label, detail

    _push_run_log(index_page, f"Auto-fix: initial execution failed.\n{err}", placeholder)
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
            _push_run_log(index_page, f"Auto-fix attempt {attempt}: model returned no code.", placeholder)
            break

        candidate = f"# {fix_detail}\n{fix_code}".strip() if fix_detail else fix_code.strip()
        _, candidate_err = _exec_code_on_df(candidate, df)
        if not candidate_err:
            _push_run_log(index_page, f"Auto-fix: success on attempt {attempt}.", placeholder)
            return candidate, fix_model, fix_detail

        summary = candidate_err.strip().splitlines()[-1] if candidate_err.strip() else "Unknown error"
        _push_run_log(index_page, f"Auto-fix attempt {attempt} failed: {summary}", placeholder)
        current_code = candidate
        current_model = fix_model
        current_detail = fix_detail
        current_err = candidate_err

    _push_run_log(index_page, "Auto-fix failed; keeping the last generated code.", placeholder)
    return current_code, current_model, current_detail


def is_query_valid(query: Any) -> bool:
    """Check if a query is valid."""
    return isinstance(query, list) and bool(query[2])


def get_steps_list(module: Path, steps_file: Path) -> List[Any]:
    """Get the list of steps for a module from a TOML file."""
    module_path = Path(module)
    _ensure_primary_module_key(module_path, steps_file)
    try:
        with open(steps_file, "rb") as f:
            steps = tomllib.load(f)
    except (FileNotFoundError, tomllib.TOMLDecodeError):
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
            steps = tomllib.load(f)
    except (FileNotFoundError, tomllib.TOMLDecodeError):
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
    engine_key = f"{index_page}__engine_map"
    engine_store = st.session_state.setdefault(engine_key, {})
    sequence_key = f"{index_page}__run_sequence"
    sequence_store = st.session_state.setdefault(sequence_key, list(range(nsteps)))
    if 0 <= index_step < nsteps:
        del steps[module_key][index_step]
        nsteps -= 1
        st.session_state[index_page][0] = max(0, nsteps - 1)
        st.session_state[index_page][-1] = nsteps
        shifted: Dict[int, str] = {}
        vshifted: Dict[int, str] = {}
        eshifted: Dict[int, str] = {}
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
        for idx, engine in engine_store.items():
            if idx < index_step:
                eshifted[idx] = engine
            elif idx > index_step:
                eshifted[idx - 1] = engine
        st.session_state[engine_key] = eshifted
        new_sequence: List[int] = []
        for idx in sequence_store:
            if idx == index_step:
                continue
            new_idx = idx - 1 if idx > index_step else idx
            if 0 <= new_idx < nsteps and new_idx not in new_sequence:
                new_sequence.append(new_idx)
        if nsteps > 0 and not new_sequence:
            new_sequence = list(range(nsteps))
        st.session_state[sequence_key] = new_sequence
    else:
        st.session_state[index_page][0] = 0
        st.session_state[venv_key] = venv_store
        st.session_state[engine_key] = engine_store
        st.session_state[sequence_key] = [idx for idx in sequence_store if idx < nsteps]

    steps[module_key] = _prune_invalid_entries(steps[module_key])
    nsteps = len(steps[module_key])
    st.session_state[index_page][-1] = nsteps
    current_sequence = st.session_state.get(sequence_key, [])
    _persist_sequence_preferences(module_path, steps_file, current_sequence)

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
        if module == "__meta__" or not isinstance(steps, list):
            continue
        for step in steps:
            code_text = ""
            if isinstance(step, dict):
                code_text = str(step.get("C", "") or "")
            elif isinstance(step, str):
                code_text = step
            if not code_text:
                continue
            code_cell = {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": code_text.splitlines(keepends=True),
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
        engine_map = st.session_state.get(f"{index_page}__engine_map", {})
        # Persist only D, Q, M, and C
        query[-1], _ = save_step(
            module_path,
            query[1:5],
            query[0],
            query[-1],
            steps_file,
            venv_map=venv_map,
            engine_map=engine_map,
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
    engine_map: Optional[Dict[int, str]] = None,
) -> Tuple[int, Dict[str, Any]]:
    """Save a step in the steps file."""
    st.session_state["_experiment_last_save_skipped"] = False
    module_path = Path(module)
    _ensure_primary_module_key(module_path, steps_file)
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
            steps = tomllib.load(f)
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

    # Capture any existing entry so we can preserve values when maps aren't provided
    existing_entry: Dict[str, Any] = {}
    if 0 <= index_step < len(steps[module_str]):
        current_entry = steps[module_str][index_step]
        if isinstance(current_entry, dict):
            existing_entry = current_entry

    # Persist only D, Q, M, and C (+ E/R when provided). Handle both shapes:
    # - [D, Q, M, C]
    # - [step, D, Q, M, C, ...]
    if len(query) >= 5 and _looks_like_step(query[0]):
        d_idx, q_idx, m_idx, c_idx = 1, 2, 3, 4
    else:
        d_idx, q_idx, m_idx, c_idx = 0, 1, 2, 3

    entry = {
        "D": query[d_idx] if d_idx < len(query) else "",
        "Q": query[q_idx] if q_idx < len(query) else "",
        "M": query[m_idx] if m_idx < len(query) else "",
        "C": query[c_idx] if c_idx < len(query) else "",
    }

    # Prefer the current env's OPENAI_MODEL (or Azure deployment) when available
    try:
        env = st.session_state.get("env")
        if env and env.envars:
            model_from_env = env.envars.get("OPENAI_MODEL") or env.envars.get("AZURE_OPENAI_DEPLOYMENT")
            if model_from_env:
                entry["M"] = model_from_env
    except Exception:
        pass
    if venv_map is not None:
        try:
            entry["E"] = normalize_runtime_path(venv_map.get(index_step, ""))
        except Exception:
            entry["E"] = ""
    elif "E" in existing_entry:
        entry["E"] = normalize_runtime_path(existing_entry.get("E", ""))

    if engine_map is not None:
        try:
            entry["R"] = str(engine_map.get(index_step, "") or "")
        except Exception:
            entry["R"] = ""
    elif "R" in existing_entry:
        entry["R"] = str(existing_entry.get("R", "") or "")

    code_text = entry.get("C", "")
    if not isinstance(code_text, str):
        code_text = str(code_text or "")
    entry["C"] = code_text

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
        st.session_state["_experiment_last_save_skipped"] = True
        return nsteps, entry

    toml_to_notebook(steps, steps_file)
    return nsteps, entry


def _force_persist_step(
    module_path: Path,
    steps_file: Path,
    step_idx: int,
    entry: Dict[str, Any],
) -> None:
    """Ensure the given entry is written to steps_file at step_idx."""
    try:
        module_key = _module_keys(module_path)[0]
        steps: Dict[str, Any] = {}
        if steps_file.exists():
            with open(steps_file, "rb") as f:
                steps = tomllib.load(f)
        steps.setdefault(module_key, [])
        while len(steps[module_key]) <= step_idx:
            steps[module_key].append({})
        steps[module_key][step_idx] = convert_paths_to_strings(entry)
        steps_file.parent.mkdir(parents=True, exist_ok=True)
        with open(steps_file, "wb") as f:
            tomli_w.dump(steps, f)
    except Exception as exc:
        logger.error(f"Force persist failed for step {step_idx} -> {steps_file}: {exc}")


def run_all_steps(
    lab_dir: Path,
    index_page_str: str,
    steps_file: Path,
    module_path: Path,
    env: AgiEnv,
    log_placeholder: Optional[Any] = None,
) -> None:
    """Execute all steps sequentially, honouring per-step virtual environments."""
    if log_placeholder is None:
        log_placeholder = _get_run_placeholder(index_page_str)
    _push_run_log(index_page_str, "Run pipeline invoked.", log_placeholder)
    steps = load_all_steps(module_path, steps_file, index_page_str) or []
    if not steps:
        st.info(f"No steps available to run from {steps_file}.")
        _push_run_log(index_page_str, "Run pipeline aborted: no steps available.", log_placeholder)
        return

    selected_map = st.session_state.setdefault(f"{index_page_str}__venv_map", {})
    engine_map = st.session_state.setdefault(f"{index_page_str}__engine_map", {})
    sequence_state_key = f"{index_page_str}__run_sequence"
    details_store = st.session_state.setdefault(f"{index_page_str}__details", {})
    original_step = st.session_state[index_page_str][0]
    original_selected = normalize_runtime_path(st.session_state.get("lab_selected_venv", ""))
    original_engine = st.session_state.get("lab_selected_engine", "")
    snippet_file = st.session_state.get("snippet_file")
    display_order: Dict[int, int] = {}
    if not snippet_file:
        st.error("Snippet file is not configured. Reload the page and try again.")
        _push_run_log(index_page_str, "Run pipeline aborted: snippet file not configured.", log_placeholder)
        return

    raw_sequence = st.session_state.get(sequence_state_key, [])
    sequence = [idx for idx in raw_sequence if 0 <= idx < len(steps)]
    if not sequence:
        sequence = list(range(len(steps)))

    executed = 0
    with st.spinner("Running all steps…"):
        for idx in sequence:
            entry = steps[idx]
            code = entry.get("C", "")
            if not _is_valid_step(entry) or not code:
                continue
            _push_run_log(index_page_str, f"Running step {idx + 1}…", log_placeholder)

            raw_runtime = normalize_runtime_path(entry.get("E", ""))
            venv_path = raw_runtime if _is_valid_runtime_root(raw_runtime) else ""
            if venv_path:
                selected_map[idx] = venv_path
                st.session_state["lab_selected_venv"] = venv_path
            else:
                selected_map.pop(idx, None)
            runtime_root = venv_path or st.session_state.get("lab_selected_venv", "")

            st.session_state[index_page_str][0] = idx
            st.session_state[index_page_str][1] = entry.get("D", "")
            st.session_state[index_page_str][2] = entry.get("Q", "")
            st.session_state[index_page_str][3] = entry.get("M", "")
            st.session_state[index_page_str][4] = code
            st.session_state[index_page_str][5] = details_store.get(idx, "")

            venv_root = runtime_root
            entry_engine = str(entry.get("R", "") or "")
            ui_engine = str(engine_map.get(idx) or "")
            if ui_engine and ui_engine != entry_engine:
                if entry_engine.startswith("agi.") and ui_engine == "runpy":
                    engine = entry_engine
                else:
                    engine = ui_engine
            elif entry_engine:
                engine = entry_engine
            else:
                engine = "agi.run" if venv_root else "runpy"
            if venv_root and engine == "runpy":
                engine = "agi.run"
            if engine.startswith("agi.") and not venv_root:
                fallback_runtime = normalize_runtime_path(getattr(env, "active_app", "") or "")
                if _is_valid_runtime_root(fallback_runtime):
                    venv_root = fallback_runtime
                    st.session_state["lab_selected_venv"] = venv_root
            target_base = Path(steps_file).parent.resolve()
            # Collapse duplicated tail (e.g., export/<app>/export/<app>)
            if target_base.name == target_base.parent.name:
                target_base = target_base.parent
            target_base.mkdir(parents=True, exist_ok=True)
            if engine == "runpy":
                output = run_lab(
                    [entry.get("D", ""), entry.get("Q", ""), code],
                    snippet_file,
                    env.copilot_file,
                )
            else:
                script_path = (target_base / "AGI_run.py").resolve()
                script_path.write_text(code)
                python_cmd = _python_for_venv(venv_root)
                output = _stream_run_command(
                    env,
                    index_page_str,
                    f"{python_cmd} {script_path}",
                    cwd=target_base,
                    placeholder=log_placeholder,
                )

            # Append execution output to logs for better visibility
            if output:
                preview = output.strip()
                if preview:
                    _push_run_log(
                        index_page_str,
                        f"Output (step {idx + 1}):\n{preview}",
                        log_placeholder,
                    )
                    if "No such file or directory" in preview:
                        _push_run_log(
                            index_page_str,
                            "Hint: the code tried to call a file that is not present in the export environment. "
                            "Adjust the step to use a path that exists under the export/lab directory.",
                            log_placeholder,
                        )
            else:
                _push_run_log(
                    index_page_str,
                    f"Output (step {idx + 1}): {engine} executed (no captured stdout)",
                    log_placeholder,
                )

            if isinstance(st.session_state.get("data"), pd.DataFrame) and not st.session_state["data"].empty:
                export_target = st.session_state.get("df_file_out", "")
                if save_csv(st.session_state["data"], export_target):
                    st.session_state["df_file_in"] = export_target
                    st.session_state["step_checked"] = True
            summary = _step_summary({"Q": entry.get("Q", ""), "C": code})
            env_label = Path(venv_root).name if venv_root else "default env"
            _push_run_log(
                index_page_str,
                f"Step {idx + 1}: engine={engine}, env={env_label}, summary=\"{summary}\"",
                log_placeholder,
            )
            executed += 1

    st.session_state[index_page_str][0] = original_step
    st.session_state["lab_selected_venv"] = normalize_runtime_path(original_selected)
    st.session_state["lab_selected_engine"] = original_engine
    st.session_state[f"{index_page_str}__force_blank_q"] = True
    st.session_state[f"{index_page_str}__q_rev"] = st.session_state.get(f"{index_page_str}__q_rev", 0) + 1

    if executed:
        st.success(f"Executed {executed} step{'s' if executed != 1 else ''}.")
        _push_run_log(index_page_str, f"Run pipeline completed: {executed} step(s) executed.", log_placeholder)
    else:
        st.info("No runnable code found in the steps.")
        _push_run_log(index_page_str, "Run pipeline completed: no runnable code found.", log_placeholder)


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
    engine_map = st.session_state.get(f"{index_page}__engine_map", {})
    save_step(
        module_path,
        query[1:5],
        query[0],
        query[-1],
        file_step_path,
        venv_map=venv_map,
        engine_map=engine_map,
    )
    _bump_history_revision()
    project_path = env.apps_path / project
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
    env = st.session_state.get("env")
    try:
        base = Path(env.apps_path)  # type: ignore[attr-defined]
        builtin_base = base / "builtin"
        for cand in (
            base / new_index_page,
            builtin_base / new_index_page,
            base / f"{new_index_page}_project",
            builtin_base / f"{new_index_page}_project",
        ):
            if cand.exists():
                store_last_active_app(cand)
                break
    except Exception:
        pass


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
    home_root = Path(env.home_abs)
    # Fall back to ~/export when env does not expose AGILAB_EXPORT_ABS
    try:
        export_root = env.AGILAB_EXPORT_ABS
    except Exception:
        export_root = home_root / "export"
    Agi_export_abs = Path(export_root)
    if not Agi_export_abs.is_absolute():
        Agi_export_abs = home_root / Agi_export_abs
    modules = scan_dir(Agi_export_abs)
    # Drop a top-level "apps" directory when other labs exist; it isn't a valid lab.
    if len(modules) > 1 and "apps" in modules:
        modules = [m for m in modules if m != "apps"]
    if not modules:
        modules = [env.target]
    st.session_state['modules'] = modules

    def _qp_first(key: str) -> str | None:
        val = st.query_params.get(key)
        if isinstance(val, list):
            return val[0] if val else None
        if val is None:
            return None
        return str(val)

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

    last_active = _load_last_active_app_name(modules)
    persisted_lab = (
        _qp_first("lab_dir_selectbox")
        or st.session_state.get("lab_dir_selectbox")
        or st.session_state.get("lab_dir")
        or last_active
        or env.target
    )

    if persisted_lab not in modules:
        # If env.target is a name and not present, try its parent or the first module.
        fallback = env.target if env.target in modules else None
        if fallback is None and env.target:
            try:
                target_name = Path(env.target).name
                if target_name in modules:
                    fallback = target_name
            except Exception:
                fallback = None
        persisted_lab = fallback if fallback in modules else modules[0]
    elif persisted_lab == "apps" and env.target in modules:
        # Avoid selecting the top-level "apps" directory; prefer the active app/target.
        persisted_lab = env.target

    st.session_state["lab_dir"] = st.sidebar.selectbox(
        "Lab directory",
        modules,
        index=modules.index(persisted_lab),
        on_change=lambda: on_lab_change(st.session_state.lab_dir_selectbox),
        key="lab_dir_selectbox",
    )

    steps_file_name = st.session_state["steps_file_name"]
    export_root = Path(env.AGILAB_EXPORT_ABS).expanduser()
    if not export_root.is_absolute():
        export_root = (Path.home() / export_root).resolve()
    lab_name = Path(st.session_state["lab_dir_selectbox"]).name
    lab_dir = (export_root / lab_name).resolve()
    st.session_state.df_dir = lab_dir
    steps_file = (lab_dir / steps_file_name).resolve()
    st.session_state["steps_file"] = steps_file

    # Page title reflecting current lab/project
    st.markdown(f"### Pipeline for project: `{st.session_state['lab_dir_selectbox']}`")

    steps_files = find_files(lab_dir, ".toml")
    st.session_state.steps_files = steps_files
    lab_root = Path(st.session_state["lab_dir_selectbox"]).name
    steps_files_path = [
        Path(file)
        for file in steps_files
        if Path(file).is_file()
        and Path(file).suffix.lower() == ".toml"
        and "lab_steps" in Path(file).name
    ]
    steps_file_rel = sorted(
        [
            rel_path
            for rel_path in (
                file.relative_to(Agi_export_abs)
                for file in steps_files_path
                if file.is_relative_to(Agi_export_abs)
            )
            if rel_path.parts and rel_path.parts[0] == lab_root
        ],
        key=str,
    )

    if "index_page" not in st.session_state:
        index_page = steps_file_rel[0] if steps_file_rel else env.target
        st.session_state["index_page"] = index_page
    else:
        index_page = st.session_state["index_page"]

    index_page_str = str(index_page)

    if steps_file_rel:
        st.sidebar.selectbox("Steps file", steps_file_rel, key="index_page", on_change=on_page_change)

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
        "Dataframe",
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

    # Persist sidebar selections into query params for reloads
    st.query_params.update(
        {
            "lab_dir_selectbox": st.session_state.get("lab_dir_selectbox", ""),
            "index_page": str(st.session_state.get("index_page", "")),
            "lab_llm_provider": st.session_state.get("lab_llm_provider", ""),
            "gpt_oss_endpoint": st.session_state.get("gpt_oss_endpoint", ""),
            "df_file": st.session_state.get("df_file", ""),
            # Keep other pages (e.g., Explore) aware of the current project
            "active_app": st.session_state.get("lab_dir_selectbox", ""),
        }
    )

    # Persist last active app for cross-page defaults (use current lab_dir path)
    # Last active app is now persisted via on_lab_change when user switches labs.

    key = index_page_str + "import_notebook"
    st.sidebar.file_uploader(
        "Import notebook",
        type="ipynb",
        key=key,
        on_change=on_import_notebook,
        args=(key, module_path, index_page_str, steps_file),
    )


def mlflow_controls() -> None:
    """Display MLflow UI controls in sidebar."""
    if st.session_state.get("server_started"):
        mlflow_port = st.session_state.get("mlflow_port", 5000)
        mlflow_url = f"http://localhost:{mlflow_port}"
        if not st.session_state.get("mlflow_button_css"):
            st.sidebar.markdown(
                """
                <style>
                .mlflow-anchor-btn {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    width: 100%;
                    padding: 0.45rem 0.75rem;
                    border-radius: 0.5rem;
                    border: 1px solid var(--primary-color);
                    background: var(--primary-color);
                    color: var(--secondary-background-color);
                    font-weight: 600;
                    text-decoration: none;
                    transition: filter 0.15s ease-in-out;
                }
                .mlflow-anchor-btn:hover {
                    filter: brightness(0.9);
                    text-decoration: none;
                }
                </style>
                """,
                unsafe_allow_html=True,
            )
            st.session_state["mlflow_button_css"] = True

        if st.sidebar.button(f"Open MLflow UI (port {mlflow_port})"):
            components.html(
                f"<script>window.open('{mlflow_url}', '_blank');</script>",
                height=0,
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
            except Exception:
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
            except Exception:
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
        except Exception:
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
    base_dirs.append(str(Path(env.active_app)))
    base_dirs.append(str(Path(env.apps_path)))
    if env.runenv:
        base_dirs.append(str(Path(env.runenv)))
    if env.wenv_abs:
        base_dirs.append(str(Path(env.wenv_abs)))
    if env.agi_env:
        base_dirs.append(str(Path(env.agi_env)))

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
    def _normalize_editor_text(raw: Optional[str]) -> str:
        if raw is None:
            return ""
        text = str(raw)
        return text if text.strip() else ""
    """Display the pipeline tab with steps and query input."""
    # Reset active step and count to reflect persisted steps
    persisted_steps = load_all_steps(module_path, steps_file, index_page_str) or []
    if not persisted_steps and steps_file.exists():
        try:
            import tomllib
            with open(steps_file, "rb") as f:
                raw = tomllib.load(f)
            module_key = _module_keys(module_path)[0]
            fallback_steps = raw.get(module_key, [])
            if isinstance(fallback_steps, list):
                persisted_steps = [s for s in fallback_steps if _is_valid_step(s)]
        except Exception:
            pass
    total_steps = len(persisted_steps)
    safe_prefix = index_page_str.replace("/", "_")
    total_steps_key = f"{safe_prefix}_total_steps"
    prev_total = st.session_state.get(total_steps_key)
    st.session_state[index_page_str][0] = 0
    st.session_state[index_page_str][-1] = total_steps

    sequence_state_key = f"{index_page_str}__run_sequence"
    stored_sequence = st.session_state.get(sequence_state_key)
    if stored_sequence is None:
        stored_sequence = _load_sequence_preferences(module_path, steps_file)
        st.session_state[sequence_state_key] = stored_sequence

    if total_steps == 0:
        if stored_sequence:
            st.session_state[sequence_state_key] = []
            _persist_sequence_preferences(module_path, steps_file, [])
    else:
        current_sequence = [idx for idx in stored_sequence if 0 <= idx < total_steps]
        if not current_sequence:
            current_sequence = list(range(total_steps))
        elif isinstance(prev_total, int) and total_steps > prev_total:
            for idx in range(prev_total, total_steps):
                if idx not in current_sequence:
                    current_sequence.append(idx)
        if current_sequence != st.session_state[sequence_state_key]:
            st.session_state[sequence_state_key] = current_sequence
            _persist_sequence_preferences(module_path, steps_file, current_sequence)

    if prev_total != total_steps:
        st.session_state[total_steps_key] = total_steps
        expander_reset_key = f"{safe_prefix}_expander_open"
        st.session_state[expander_reset_key] = {}

    available_venvs = [
        normalize_runtime_path(path) for path in get_available_virtualenvs(env)
    ]
    available_venvs = [path for path in dict.fromkeys(available_venvs) if path]
    env_active_app = normalize_runtime_path(env.active_app)
    if env_active_app:
        available_venvs = [env_active_app] + [p for p in available_venvs if p != env_active_app]

    venv_state_key = f"{index_page_str}__venv_map"
    selected_map: Dict[int, str] = st.session_state.setdefault(venv_state_key, {})
    engine_state_key = f"{index_page_str}__engine_map"
    engine_map: Dict[int, str] = st.session_state.setdefault(engine_state_key, {})
    for idx_key, raw_value in list(selected_map.items()):
        normalized_value = normalize_runtime_path(raw_value)
        if normalized_value:
            selected_map[idx_key] = normalized_value
        else:
            selected_map.pop(idx_key, None)

    # No steps yet: allow creating the first one via Generate code
    if total_steps == 0:
        st.info("No steps recorded yet. Generate your first step below.")
        new_q_key = f"{index_page_str}_new_q"
        new_venv_key = f"{index_page_str}_new_venv"
        if new_q_key not in st.session_state:
            st.session_state[new_q_key] = ""
        with st.expander("New step", expanded=True):
            st.text_area(
                "Ask code generator:",
                key=new_q_key,
                placeholder="Enter a prompt describing the code you want generated",
                label_visibility="collapsed",
            )
            venv_labels = ["Use AGILAB environment"] + available_venvs
            selected_new_venv = st.selectbox(
                "venv",
                venv_labels,
                key=new_venv_key,
                help="Choose which virtual environment should execute this step.",
            )
            selected_path = (
                "" if selected_new_venv == venv_labels[0] else normalize_runtime_path(selected_new_venv)
            )
            run_new = st.button("Generate code", type="primary", use_container_width=True)
            if run_new:
                prompt_text = st.session_state.get(new_q_key, "").strip()
                if not prompt_text:
                    st.warning("Enter a prompt before generating code.")
                else:
                    df_path = Path(st.session_state.df_file) if st.session_state.get("df_file") else Path()
                    answer = ask_gpt(prompt_text, df_path, index_page_str, env.envars)
                    venv_map = {0: selected_path} if selected_path else {}
                    eng_map = {0: "agi.run" if selected_path else "runpy"}
                    expander_state_key = f"{safe_prefix}_expander_open"
                    expander_state = st.session_state.setdefault(expander_state_key, {})
                    expander_state[0] = True
                    st.session_state[expander_state_key] = expander_state
                    save_step(
                        module_path,
                        answer,
                        0,
                        1,
                        steps_file,
                        venv_map=venv_map,
                        engine_map=eng_map,
                    )
                    _bump_history_revision()
                    st.rerun()
        return

    run_logs_key = f"{index_page_str}__run_logs"
    run_placeholder_key = f"{index_page_str}__run_placeholder"
    st.session_state.setdefault(run_logs_key, [])
    expander_state_key = f"{safe_prefix}_expander_open"
    expander_state: Dict[int, bool] = st.session_state.setdefault(expander_state_key, {})

    for step, entry in enumerate(persisted_steps):
        # Per-step keys
        q_key = f"{safe_prefix}_q_step_{step}"
        code_val_key = f"{safe_prefix}_code_step_{step}"
        select_key = f"{safe_prefix}_venv_{step}"
        rev_key = f"{safe_prefix}_editor_rev_{step}"
        pending_q_key = f"{safe_prefix}_pending_q_{step}"
        pending_c_key = f"{safe_prefix}_pending_c_{step}"
        undo_key = f"{safe_prefix}_undo_{step}"
        apply_q_key = f"{q_key}_apply_pending"
        apply_c_key = f"{code_val_key}_apply_pending"
        # Apply any pending updates (set during a previous run-trigger) before rendering widgets.
        pending_q = st.session_state.pop(pending_q_key, None)
        pending_c = st.session_state.pop(pending_c_key, None)
        if pending_q is not None:
            st.session_state[apply_q_key] = pending_q
        if pending_c is not None:
            st.session_state[apply_c_key] = pending_c
        if (pending_q is not None or pending_c is not None) and (q_key in st.session_state or code_val_key in st.session_state):
            st.session_state.pop(q_key, None)
            st.session_state.pop(code_val_key, None)
            st.rerun()

        initial_q = entry.get("Q", "")
        initial_c = entry.get("C", "")
        apply_q = st.session_state.pop(apply_q_key, None)
        apply_c = st.session_state.pop(apply_c_key, None)
        init_key = f"{safe_prefix}_step_init_{step}"
        resync_sig_key = f"{safe_prefix}_editor_resync_sig_{step}"
        ignore_blank_key = f"{safe_prefix}_ignore_blank_editor_{step}"
        seeded_c: Optional[str] = None
        if not st.session_state.get(init_key):
            # First render of this step in the session: seed from disk/pending values.
            st.session_state[q_key] = apply_q if apply_q is not None else initial_q
            seeded_code = apply_c if apply_c is not None else initial_c
            st.session_state[code_val_key] = seeded_code
            # If the expander is open on first load, the editor component can emit an initial blank value
            # that would overwrite seeded code. Mark the seed so we remount once and ignore a blank mount.
            seeded_c = seeded_code or None
            st.session_state[init_key] = True
        else:
            # Always apply pending values, even after first render.
            if apply_q is not None or q_key not in st.session_state:
                st.session_state[q_key] = apply_q if apply_q is not None else initial_q
            if apply_c is not None:
                seeded_c = apply_c
                st.session_state[code_val_key] = apply_c
            else:
                current_c = st.session_state.get(code_val_key, "")
                if code_val_key not in st.session_state or (not current_c and initial_c):
                    seeded_c = initial_c
                    st.session_state[code_val_key] = initial_c
        # If we had to reseed code after a reload (stale editor state), force a remount once.
        if seeded_c is not None:
            last_sig = st.session_state.get(resync_sig_key)
            if last_sig != seeded_c:
                st.session_state[resync_sig_key] = seeded_c
                st.session_state[ignore_blank_key] = True
                st.session_state[rev_key] = st.session_state.get(rev_key, 0) + 1
        if rev_key not in st.session_state:
            st.session_state[rev_key] = 0
        if undo_key not in st.session_state or not st.session_state[undo_key]:
            initial_snapshot = (entry.get("Q", ""), entry.get("C", ""))
            st.session_state[undo_key] = [initial_snapshot]

        # Seed venv options
        current_path_raw = normalize_runtime_path(selected_map.get(step, ""))
        current_path = current_path_raw if _is_valid_runtime_root(current_path_raw) else ""
        if not current_path:
            entry_venv_raw = normalize_runtime_path(entry.get("E", ""))
            entry_venv = entry_venv_raw if _is_valid_runtime_root(entry_venv_raw) else ""
            if entry_venv:
                selected_map[step] = entry_venv
                current_path = entry_venv
        venv_labels = ["Use AGILAB environment"] + available_venvs
        if current_path and current_path not in venv_labels:
            venv_labels.append(current_path)

        live_entry = {
            "Q": st.session_state.get(q_key, entry.get("Q", "")),
            "C": st.session_state.get(code_val_key, entry.get("C", "")),
        }
        summary = _step_summary(live_entry, width=80)
        dirty_key = f"{q_key}_dirty"
        if st.session_state.pop(dirty_key, False):
            # On a dirty change, refresh the summary by rerunning
            st.rerun()
        expanded_flag = expander_state.get(step, False)
        title_suffix = summary if summary else "No description yet"
        expander_title = f"{step + 1} {title_suffix}"
        with st.expander(expander_title, expanded=expanded_flag):
            # venv selector
            venv_col, _ = st.columns([3, 2], gap="small")
            with venv_col:
                session_label = st.session_state.get(select_key, "")
                initial_label = session_label or current_path or ""
                if initial_label and initial_label not in venv_labels:
                    venv_labels.append(initial_label)
                default_label = initial_label or venv_labels[0]
                if default_label not in venv_labels:
                    venv_labels.append(default_label)
                if select_key not in st.session_state or st.session_state[select_key] not in venv_labels:
                    st.session_state[select_key] = default_label
                selected_label = st.selectbox(
                    "venv",
                    venv_labels,
                    key=select_key,
                    help="Choose which virtual environment should execute this step.",
                )
                selected_path = "" if selected_label == venv_labels[0] else normalize_runtime_path(selected_label)
                if selected_path:
                    selected_map[step] = selected_path
                else:
                    selected_map.pop(step, None)

            # Engine derived from venv selection
            computed_engine = "agi.run" if selected_map.get(step) else "runpy"
            engine_map[step] = computed_engine
            st.session_state["lab_selected_engine"] = computed_engine

            # Form for prompt and code
            run_pressed = False
            revert_pressed = False
            save_pressed = False
            delete_clicked = False
            snippet_dict: Optional[Dict[str, Any]] = None
            st.text_area(
                "Ask code generator:",
                key=q_key,
                placeholder="Enter a prompt describing the code you want generated",
                label_visibility="collapsed",
                on_change=lambda k=q_key: st.session_state.__setitem__(f"{q_key}_dirty", True),
            )
            btn_save, btn_run, btn_revert, btn_delete = st.columns([1, 1, 1, 1], gap="small")
            with btn_save:
                save_pressed = st.button(
                    "Save",
                    type="secondary",
                    use_container_width=True,
                    key=f"{safe_prefix}_save_{step}",
                )
            with btn_run:
                run_pressed = st.button(
                    "Gen code",
                    type="primary",
                    use_container_width=True,
                    key=f"{safe_prefix}_run_{step}",
                )
            with btn_revert:
                revert_pressed = st.button(
                    "Undo",
                    type="secondary",
                    use_container_width=True,
                    key=f"{safe_prefix}_revert_{step}",
                )
            with btn_delete:
                delete_clicked = st.button(
                    "Remove",
                    type="secondary",
                    use_container_width=True,
                    key=f"{safe_prefix}_delete_{step}",
                )

            # Code editor rendered outside the form so overlay actions fire without submit
            code_text = st.session_state.get(code_val_key, "")
            rev = st.session_state.get(rev_key, 0)
            editor_key = f"{safe_prefix}a{step}-{rev}"
            snippet_dict = code_editor(
                code_text if code_text.endswith("\n") else code_text + "\n",
                height=(min(30, len(code_text)) if code_text else 100),
                theme="contrast",
                buttons=get_custom_buttons(),
                info=get_info_bar(),
                component_props=get_css_text(),
                props={"style": {"borderRadius": "0px 0px 8px 8px"}},
                key=editor_key,
            )

            # Handle actions
            if snippet_dict and snippet_dict.get("text") is not None:
                normalized_text = _normalize_editor_text(snippet_dict.get("text"))
                if normalized_text == "" and st.session_state.get(ignore_blank_key) and st.session_state.get(code_val_key):
                    # Skip a single empty mount update after a resync; keep seeded code.
                    st.session_state.pop(ignore_blank_key, None)
                else:
                    st.session_state[code_val_key] = normalized_text
                    st.session_state.pop(ignore_blank_key, None)
            code_current = st.session_state.get(code_val_key, "")

            if revert_pressed:
                undo_stack = st.session_state.get(undo_key, [])
                if len(undo_stack) > 1:
                    undo_stack.pop()
                restored_q, restored_c = undo_stack[-1] if undo_stack else ("", "")
                st.session_state[undo_key] = undo_stack if undo_stack else [(restored_q, restored_c)]
                # Queue the restore for next render to avoid touching instantiated widgets
                st.session_state[pending_q_key] = restored_q
                st.session_state[pending_c_key] = restored_c
                # Persist the restored content so reload matches what was just shown
                save_step(
                    module_path,
                    [entry.get("D", ""), restored_q, entry.get("M", ""), restored_c],
                    step,
                    total_steps,
                    steps_file,
                    venv_map=selected_map,
                    engine_map=engine_map,
                )
                _bump_history_revision()
                expander_state[step] = True
                st.session_state[expander_state_key] = expander_state
                st.session_state[rev_key] = st.session_state.get(rev_key, 0) + 1
                st.rerun()

            if save_pressed:
                undo_stack = st.session_state.get(undo_key, [])
                undo_stack.append((st.session_state.get(q_key, ""), st.session_state.get(code_val_key, "")))
                st.session_state[undo_key] = undo_stack
                st.session_state[code_val_key] = code_current
                st.session_state[rev_key] = st.session_state.get(rev_key, 0) + 1
                expander_state[step] = True
                st.session_state[expander_state_key] = expander_state
                save_step(
                    module_path,
                    [entry.get("D", ""), st.session_state.get(q_key, ""), entry.get("M", ""), code_current],
                    step,
                    total_steps,
                    steps_file,
                    venv_map=selected_map,
                    engine_map=engine_map,
                )
                # Force sync to disk in case upstream save was skipped/overwritten
                _force_persist_step(
                    module_path,
                    steps_file,
                    step,
                    {
                        "D": entry.get("D", ""),
                        "Q": st.session_state.get(q_key, ""),
                        "M": entry.get("M", ""),
                        "C": code_current,
                        "E": normalize_runtime_path(selected_map.get(step, "")),
                        "R": engine_map.get(step, "") or ("agi.run" if selected_map.get(step) else "runpy"),
                    },
                )
                # Queue what was saved; keys will be applied on next render if not already set
                st.session_state[pending_q_key] = st.session_state.get(q_key, "")
                st.session_state[pending_c_key] = code_current
                st.session_state.pop(q_key, None)
                st.session_state.pop(code_val_key, None)
                # _append_run_log(index_page_str, f"Saved step {step + 1}.")
                _bump_history_revision()
                st.rerun()

            overlay_type = snippet_dict.get("type") if snippet_dict else None
            overlay_flag_key = f"{safe_prefix}_overlay_done_{step}"
            overlay_sig_key = f"{safe_prefix}_overlay_sig_{step}"
            current_sig = (
                overlay_type,
                snippet_dict.get("text") if snippet_dict else None,
            )
            last_sig = st.session_state.get(overlay_sig_key)
            if overlay_type is None:
                st.session_state.pop(overlay_flag_key, None)
                st.session_state.pop(overlay_sig_key, None)
            elif overlay_type in {"save", "run"} and current_sig == last_sig:
                # Duplicate event from the editor; skip handling to avoid loops
                continue
            if snippet_dict and overlay_type == "save":
                if st.session_state.get(overlay_flag_key):
                    # Already handled; clear and skip
                    st.session_state.pop(overlay_flag_key, None)
                    snippet_dict = None
                else:
                    st.session_state[overlay_flag_key] = True
                    st.session_state[overlay_sig_key] = current_sig
                if snippet_dict is None:
                    continue
                undo_stack = st.session_state.get(undo_key, [])
                undo_stack.append((st.session_state.get(q_key, ""), st.session_state.get(code_val_key, "")))
                st.session_state[undo_key] = undo_stack
                code_current = snippet_dict.get("text")
                if code_current is None:
                    code_current = st.session_state.get(code_val_key, "")
                code_current = _normalize_editor_text(code_current)
                st.session_state[code_val_key] = code_current
                st.session_state[rev_key] = st.session_state.get(rev_key, 0) + 1
                expander_state[step] = True
                st.session_state[expander_state_key] = expander_state
                save_step(
                    module_path,
                    [entry.get("D", ""), st.session_state.get(q_key, ""), entry.get("M", ""), code_current],
                    step,
                    total_steps,
                    steps_file,
                    venv_map=selected_map,
                    engine_map=engine_map,
                )
                _force_persist_step(
                    module_path,
                    steps_file,
                    step,
                    {
                        "D": entry.get("D", ""),
                        "Q": st.session_state.get(q_key, ""),
                        "M": entry.get("M", ""),
                        "C": code_current,
                        "E": normalize_runtime_path(selected_map.get(step, "")),
                        "R": engine_map.get(step, "") or ("agi.run" if selected_map.get(step) else "runpy"),
                    },
                )
                # _append_run_log(index_page_str, f"Saved step {step + 1} (overlay).")
                _bump_history_revision()
                # Mirror the manual save flow so the expander stays open after rerun.
                st.session_state[pending_q_key] = st.session_state.get(q_key, "")
                st.session_state[pending_c_key] = code_current
                st.session_state.pop(q_key, None)
                st.session_state.pop(code_val_key, None)
                st.session_state[expander_state_key] = expander_state
                st.rerun()
            elif snippet_dict and overlay_type == "run":
                if st.session_state.get(overlay_flag_key):
                    # Already handled; clear and skip
                    st.session_state.pop(overlay_flag_key, None)
                    snippet_dict = None
                else:
                    st.session_state[overlay_flag_key] = True
                    st.session_state[overlay_sig_key] = current_sig
                if snippet_dict is None:
                    continue
                # Execute the current code using the selected engine/venv
                code_to_run = snippet_dict.get("text", st.session_state.get(code_val_key, ""))
                venv_root = normalize_runtime_path(selected_map.get(step, ""))
                entry_runtime_raw = normalize_runtime_path(entry.get("E", ""))
                entry_runtime = entry_runtime_raw if _is_valid_runtime_root(entry_runtime_raw) else ""
                if not venv_root and entry_runtime:
                    venv_root = entry_runtime
                    selected_map[step] = entry_runtime
                if not venv_root:
                    fallback_venv = normalize_runtime_path(st.session_state.get("lab_selected_venv", ""))
                    if fallback_venv and _is_valid_runtime_root(fallback_venv):
                        venv_root = fallback_venv
                        selected_map[step] = fallback_venv
                        if fallback_venv not in venv_labels:
                            venv_labels.append(fallback_venv)
                        st.session_state[select_key] = fallback_venv
                entry_engine = str(entry.get("R", "") or "")
                ui_engine = str(engine_map.get(step) or "")
                if ui_engine and ui_engine != entry_engine:
                    if entry_engine.startswith("agi.") and ui_engine == "runpy":
                        engine = entry_engine
                    else:
                        engine = ui_engine
                elif entry_engine:
                    engine = entry_engine
                else:
                    engine = "agi.run" if venv_root else "runpy"
                if venv_root and engine == "runpy":
                    engine = "agi.run"
                if engine.startswith("agi.") and not venv_root:
                    fallback_runtime = normalize_runtime_path(getattr(env, "active_app", "") or "")
                    if _is_valid_runtime_root(fallback_runtime):
                        venv_root = fallback_runtime
                        st.session_state["lab_selected_venv"] = venv_root
                engine_map[step] = engine
                if venv_root:
                    st.session_state["lab_selected_venv"] = venv_root
                stored_placeholder = st.session_state.get(run_placeholder_key)
                st.session_state[run_logs_key] = []
                if stored_placeholder is not None:
                    stored_placeholder.caption("Starting overlay run…")
                snippet_file = st.session_state.get("snippet_file")
                if not snippet_file:
                    st.error("Snippet file is not configured. Reload the page and try again.")
                else:
                    target_base = Path(steps_file).parent.resolve()
                    target_base.mkdir(parents=True, exist_ok=True)
                    run_output = ""
                    if engine == "runpy":
                        run_output = run_lab(
                            [entry.get("D", ""), st.session_state.get(q_key, ""), code_to_run],
                            snippet_file,
                            env.copilot_file,
                        )
                    else:
                        script_path = (target_base / "AGI_run.py").resolve()
                        script_path.write_text(code_to_run)
                        python_cmd = _python_for_venv(venv_root)
                        run_output = _stream_run_command(
                            env,
                            index_page_str,
                            f"{python_cmd} {script_path}",
                            cwd=target_base,
                            placeholder=stored_placeholder,
                        )
                    env_label = Path(venv_root).name if venv_root else "default env"
                    summary = _step_summary({"Q": entry.get("Q", ""), "C": code_to_run})
                    _push_run_log(
                        index_page_str,
                        f"Step {step + 1}: engine={engine}, env={env_label}, summary=\"{summary}\"",
                        stored_placeholder,
                    )
                    if run_output:
                        preview = run_output.strip()
                        if preview:
                            _push_run_log(
                                index_page_str,
                                f"Output (step {step + 1}):\n{preview}",
                                stored_placeholder,
                            )
                            if "No such file or directory" in preview:
                                _push_run_log(
                                    index_page_str,
                                    "Hint: the code tried to call a file that is not present in the export environment. "
                                    "Adjust the step to use a path that exists under the export/lab directory.",
                                    stored_placeholder,
                                )
                    elif engine == "runpy":
                        _push_run_log(
                            index_page_str,
                            f"Output (step {step + 1}): runpy executed (no captured stdout)",
                            stored_placeholder,
                        )

            if run_pressed:
                undo_stack = st.session_state.get(undo_key, [])
                undo_stack.append(
                    (
                        st.session_state.get(q_key, ""),
                        st.session_state.get(code_val_key, ""),
                    )
                )
                st.session_state[undo_key] = undo_stack
                prompt_text = st.session_state.get(q_key, "")
                df_path = (
                    Path(st.session_state.df_file)
                    if st.session_state.get("df_file")
                    else Path()
                )
                answer = ask_gpt(prompt_text, df_path, index_page_str, env.envars)
                # Merge the model detail (answer[4]) into the generated code (answer[3]) as a leading comment
                merged_code = None
                code_txt = answer[3] if len(answer) > 3 else ""
                detail_txt = (answer[4] or "").strip() if len(answer) > 4 else ""
                if code_txt:
                    summary_line = f"# {detail_txt}\n" if detail_txt else ""
                    merged_code = f"{summary_line}{code_txt}"
                    if len(answer) > 3:
                        answer[3] = merged_code
                else:
                    # If no code returned, retain current editor content to avoid wiping the step
                    merged_code = st.session_state.get(code_val_key, "")
                    if len(answer) > 3:
                        answer[3] = merged_code

                if merged_code:
                    fixed_code, fixed_model, fixed_detail = _maybe_autofix_generated_code(
                        original_request=prompt_text,
                        df_path=df_path,
                        index_page=index_page_str,
                        env=env,
                        merged_code=str(merged_code),
                        model_label=str(answer[2] if len(answer) > 2 else ""),
                        detail=str(answer[4] if len(answer) > 4 else ""),
                    )
                    merged_code = fixed_code
                    if len(answer) > 3:
                        answer[3] = fixed_code
                    if len(answer) > 2:
                        answer[2] = fixed_model
                    if len(answer) > 4:
                        answer[4] = fixed_detail

                save_step(
                    module_path,
                    answer,
                    step,
                    total_steps,
                    steps_file,
                    venv_map=selected_map,
                    engine_map=engine_map,
                )
                # Force the UI to show exactly what we saved
                if len(answer) > 1:
                    st.session_state[pending_q_key] = answer[1]
                st.session_state[pending_c_key] = (
                    merged_code
                    if merged_code is not None
                    else st.session_state.get(code_val_key, "")
                )
                st.session_state[rev_key] = st.session_state.get(rev_key, 0) + 1

                detail_store = st.session_state.setdefault(
                    f"{index_page_str}__details", {}
                )
                detail = answer[4] if len(answer) > 4 else ""
                if detail:
                    detail_store[step] = detail
                env_label = (
                    Path(selected_map.get(step, "")).name
                    if selected_map.get(step)
                    else "default env"
                )
                summary = _step_summary(
                    {
                        "Q": answer[1] if len(answer) > 1 else "",
                        "C": answer[4] if len(answer) > 4 else "",
                    }
                )
                _push_run_log(
                    index_page_str,
                    f"Step {step + 1}: engine={engine_map.get(step,'')}, env={env_label}, summary=\"{summary}\"",
                    _get_run_placeholder(index_page_str),
                )
                expander_state[step] = True
                st.session_state[expander_state_key] = expander_state
                st.rerun()

            if delete_clicked:
                selected_map.pop(step, None)
                st.session_state.pop(select_key, None)
                remove_step(lab_dir, str(step), steps_file, index_page_str)
                st.rerun()

    # Add-step expander to append a new step at the end
    new_q_key = f"{safe_prefix}_new_q"
    new_venv_key = f"{safe_prefix}_new_venv"
    if new_q_key not in st.session_state:
        st.session_state[new_q_key] = ""
    with st.expander("Add step", expanded=False):
        st.text_area(
            "Ask code generator:",
            key=new_q_key,
            placeholder="Enter a prompt describing the code you want generated",
            label_visibility="collapsed",
        )
        venv_labels = ["Use AGILAB environment"] + available_venvs
        selected_new_venv = st.selectbox(
            "venv",
            venv_labels,
            key=new_venv_key,
            help="Choose which virtual environment should execute this step.",
        )
        selected_path = "" if selected_new_venv == venv_labels[0] else normalize_runtime_path(selected_new_venv)
        run_new = st.button("Generate code", type="primary", use_container_width=True, key=f"{safe_prefix}_add_step_btn")
        if run_new:
            prompt_text = st.session_state.get(new_q_key, "").strip()
            if prompt_text:
                df_path = Path(st.session_state.df_file) if st.session_state.get("df_file") else Path()
                answer = ask_gpt(prompt_text, df_path, index_page_str, env.envars)
                merged_code = None
                code_txt = answer[3] if len(answer) > 3 else ""
                detail_txt = (answer[4] or "").strip() if len(answer) > 4 else ""
                if code_txt:
                    summary_line = f"# {detail_txt}\n" if detail_txt else ""
                    merged_code = f"{summary_line}{code_txt}"
                    if len(answer) > 3:
                        answer[3] = merged_code

                if merged_code:
                    fixed_code, fixed_model, fixed_detail = _maybe_autofix_generated_code(
                        original_request=prompt_text,
                        df_path=df_path,
                        index_page=index_page_str,
                        env=env,
                        merged_code=str(merged_code),
                        model_label=str(answer[2] if len(answer) > 2 else ""),
                        detail=str(answer[4] if len(answer) > 4 else ""),
                    )
                    merged_code = fixed_code
                    if len(answer) > 3:
                        answer[3] = fixed_code
                    if len(answer) > 2:
                        answer[2] = fixed_model
                    if len(answer) > 4:
                        answer[4] = fixed_detail
                new_idx = len(persisted_steps)
                venv_map = selected_map.copy()
                engine_map_local = engine_map.copy()
                if selected_path:
                    venv_map[new_idx] = selected_path
                    engine_map_local[new_idx] = "agi.run"
                else:
                    engine_map_local[new_idx] = "runpy"
                save_step(
                    module_path,
                    answer,
                    new_idx,
                    new_idx + 1,
                    steps_file,
                    venv_map=venv_map,
                    engine_map=engine_map_local,
                )
                detail_store = st.session_state.setdefault(f"{index_page_str}__details", {})
                detail = answer[4] if len(answer) > 4 else ""
                if detail:
                    detail_store[new_idx] = detail
                _bump_history_revision()
                st.rerun()
            else:
                st.warning("Enter a prompt before generating code.")

    sequence_state_key = f"{index_page_str}__run_sequence"
    sequence_widget_key = f"{safe_prefix}_run_sequence_widget"
    if total_steps > 0:
        sequence_options = list(range(total_steps))
        summary_labels = {}
        for idx in sequence_options:
            label = _step_summary(persisted_steps[idx], width=80)
            summary_labels[idx] = label if label else f"{idx + 1}"
        stored_sequence = [idx for idx in st.session_state.get(sequence_state_key, sequence_options) if idx in sequence_options]
        if not stored_sequence:
            stored_sequence = sequence_options
            st.session_state[sequence_state_key] = stored_sequence
        if sequence_widget_key not in st.session_state:
            st.session_state[sequence_widget_key] = stored_sequence
        else:
            st.session_state[sequence_widget_key] = [
                idx for idx in st.session_state[sequence_widget_key] if idx in sequence_options
            ]
            if not st.session_state[sequence_widget_key]:
                st.session_state[sequence_widget_key] = stored_sequence

        def _format_sequence_option(idx: int) -> str:
            label = summary_labels.get(idx, f"{idx + 1}")
            return f"{idx + 1} {label}"

        selected_sequence = st.multiselect(
            "Execution sequence",
            options=sequence_options,
            key=sequence_widget_key,
            format_func=_format_sequence_option,
            help="Select which steps to run. They execute in the order shown.",
        )
        sanitized_selection = [idx for idx in selected_sequence if idx in sequence_options]
        final_sequence = sanitized_selection or sequence_options
        if st.session_state.get(sequence_state_key) != final_sequence:
            st.session_state[sequence_state_key] = final_sequence
            _persist_sequence_preferences(module_path, steps_file, final_sequence)

    run_all_col, delete_all_col = st.columns(2)
    with run_all_col:
        run_all_clicked = st.button(
            "Run pipeline",
            key=f"{index_page_str}_run_all",
            help="Execute every step sequentially using its saved virtual environment.",
            type="secondary",
            use_container_width=True,
        )
    with delete_all_col:
        delete_all_clicked = st.button(
            "Delete pipeline",
            key=f"{index_page_str}_delete_all",
            help="Remove every step in this lab.",
            type="secondary",
            use_container_width=True,
        )

    if run_all_clicked:
        run_placeholder = _get_run_placeholder(index_page_str)
        log_dir_candidate = env.runenv or (Path.home() / "log" / "execute" / env.app)
        log_dir_path = Path(log_dir_candidate).expanduser()
        log_file_path: Optional[Path] = None
        try:
            log_dir_path.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_file_path = log_dir_path / f"pipeline_{timestamp}.log"
            log_file_path.write_text("", encoding="utf-8")
            log_file_key = f"{index_page_str}__run_log_file"
            st.session_state[log_file_key] = str(log_file_path)
            st.session_state[f"{index_page_str}__last_run_log_file"] = str(log_file_path)
            _push_run_log(
                index_page_str,
                f"Run pipeline started… logs will be saved to {log_file_path}",
                run_placeholder,
            )
        except Exception as exc:
            _push_run_log(
                index_page_str,
                f"Run pipeline started… (unable to prepare log file: {exc})",
                run_placeholder,
            )
            log_file_path = None
        # Collapse all step expanders after running the pipeline
        st.session_state[expander_state_key] = {}
        try:
            run_all_steps(lab_dir, index_page_str, steps_file, module_path, env, log_placeholder=run_placeholder)
        finally:
            st.session_state.pop(f"{index_page_str}__run_log_file", None)
        st.rerun()

    if delete_all_clicked:
        total_steps = st.session_state[index_page_str][-1]
        for idx_remove in reversed(range(total_steps)):
            remove_step(lab_dir, str(idx_remove), steps_file, index_page_str)
        st.session_state[index_page_str] = [0, "", "", "", "", "", 0]
        st.session_state[f"{index_page_str}__details"] = {}
        st.session_state[f"{index_page_str}__venv_map"] = {}
        st.session_state[f"{index_page_str}__run_sequence"] = []
        st.session_state.pop(sequence_widget_key, None)
        st.session_state["lab_selected_venv"] = ""
        st.session_state[f"{index_page_str}__clear_q"] = True
        st.session_state[f"{index_page_str}__force_blank_q"] = True
        st.session_state[f"{index_page_str}__q_rev"] = st.session_state.get(f"{index_page_str}__q_rev", 0) + 1
        st.session_state.pop(select_key, None)
        _bump_history_revision()
        _persist_sequence_preferences(module_path, steps_file, [])
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
        st.info(
            f"No data loaded yet. Generate and execute a step so the latest {DEFAULT_DF} appears under the Dataframe selector."
        )

    with st.expander("Run logs", expanded=True):
        clear_logs = st.button(
            "Clear logs",
            key=f"{index_page_str}__clear_logs_global",
            type="secondary",
            use_container_width=True,
        )
        if clear_logs:
            st.session_state[run_logs_key] = []
        log_placeholder = st.empty()
        st.session_state[run_placeholder_key] = log_placeholder
        logs = st.session_state.get(run_logs_key, [])
        if logs:
            log_placeholder.code("\n".join(logs))
        else:
            log_placeholder.caption("No runs recorded yet.")
        last_log_file = st.session_state.get(f"{index_page_str}__last_run_log_file")
        if last_log_file:
            st.caption(f"Most recent pipeline log: {last_log_file}")


def display_history_tab(steps_file: Path, module_path: Path) -> None:
    """Display the HISTORY tab with code editor for steps file."""
    _ensure_primary_module_key(module_path, steps_file)
    if steps_file.exists():
        with open(steps_file, "rb") as f:
            raw_data = tomllib.load(f)
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

    pre_prompt_path = Path(env.app_src) / "pre_prompt.json"
    try:
        with open(pre_prompt_path) as f:
            st.session_state["lab_prompt"] = json.load(f)
    except FileNotFoundError:
        st.session_state["lab_prompt"] = {}
        st.warning(f"Missing pre_prompt.json at {pre_prompt_path}; using empty prompt.")
    except Exception as exc:
        st.session_state["lab_prompt"] = {}
        st.warning(f"Failed to load pre_prompt.json: {exc}")

    sidebar_controls()

    # Use the steps file parent as the concrete lab directory path
    lab_dir = Path(st.session_state["steps_file"]).parent
    index_page = st.session_state.get("index_page", lab_dir)
    index_page_str = str(index_page)
    steps_file = st.session_state["steps_file"]
    steps_file.parent.mkdir(parents=True, exist_ok=True)

    nsteps = len(get_steps_list(lab_dir, steps_file))
    st.session_state.setdefault(index_page_str, [nsteps, "", "", "", "", "", nsteps])
    st.session_state.setdefault(f"{index_page_str}__details", {})
    st.session_state.setdefault(f"{index_page_str}__venv_map", {})
    st.session_state.setdefault(f"{index_page_str}__engine_map", {})

    module_path = st.session_state["module_path"]
    # If a prompt clear was requested, clear the current revisioned key before loading the step
    if st.session_state.pop(f"{index_page_str}__clear_q", False):
        q_rev = st.session_state.get(f"{index_page_str}__q_rev", 0)
        st.session_state.pop(f"{index_page_str}_q__{q_rev}", None)
    load_last_step(module_path, steps_file, index_page_str)

    df_file = st.session_state.get("df_file")
    if not df_file or not Path(df_file).exists():
        default_df_path = (lab_dir / DEFAULT_DF).resolve()
        st.info(
            f"No dataframe exported for {lab_dir.name}. "
            f"You can proceed without a dataframe; data-dependent steps may need {default_df_path}."
        )
        st.session_state["df_file"] = None

    mlflow_controls()
    gpt_oss_controls(env)
    universal_offline_controls(env)

    display_lab_tab(lab_dir, index_page_str, steps_file, module_path, env)
    # Disabled per request to hide the lab_steps.toml expander from the main UI.
    # display_history_tab(steps_file, module_path)


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
        st.session_state.setdefault("projects", env.apps_path)
        st.session_state.setdefault("snippet_file", Path(env.AGILAB_LOG_ABS) / "lab_snippet.py")
        st.session_state.setdefault("server_started", False)
        st.session_state.setdefault("mlflow_port", 5000)
        st.session_state.setdefault("lab_selected_venv", "")

        df_dir_def = Path(env.AGILAB_EXPORT_ABS) / env.target
        st.session_state.setdefault("steps_file", Path(env.active_app) / STEPS_FILE_NAME)
        st.session_state.setdefault("df_file_out", str(df_dir_def / DEFAULT_DF))
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
            "apps_abs": env.apps_path,
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
