# BSD 3-Clause License
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
# Co-author: Codex cli
"""Streamlit entry point for the AGILab interactive lab."""
import os
import sys
import argparse
import importlib.resources as importlib_resources
import importlib.util
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional
from agi_env.agi_logger import AgiLogger

logger = AgiLogger.get_logger(__name__)

os.environ.setdefault("STREAMLIT_CONFIG_FILE", str(Path(__file__).resolve().parent / "resources" / "config.toml"))

import streamlit as st
_import_guard_path = Path(__file__).resolve().parent / "import_guard.py"
_import_guard_spec = importlib.util.spec_from_file_location("agilab_import_guard_local", _import_guard_path)
if _import_guard_spec is None or _import_guard_spec.loader is None:
    raise ModuleNotFoundError(f"Unable to load import_guard.py from {_import_guard_path}")
_import_guard_module = importlib.util.module_from_spec(_import_guard_spec)
_import_guard_spec.loader.exec_module(_import_guard_module)
assert_agilab_checkout_alignment = _import_guard_module.assert_agilab_checkout_alignment
import_agilab_symbols = _import_guard_module.import_agilab_symbols

assert_agilab_checkout_alignment(__file__)

import_agilab_symbols(
    globals(),
    "agilab.env_file_utils",
    {"load_env_file_map": "_load_env_file_map"},
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "env_file_utils.py",
    fallback_name="agilab_env_file_utils_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.page_docs",
    ["render_page_docs_access"],
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "page_docs.py",
    fallback_name="agilab_page_docs_fallback",
)

# --- minimal session-state safety (add this block) ---
def _pre_render_reset() -> None:
    # If last run asked for a reset, clear BEFORE widgets are created this run
    if st.session_state.pop("env_editor_reset", False):
        st.session_state["env_editor_new_key"] = ""
        st.session_state["env_editor_new_value"] = ""

# One-time safe defaults (ok to run every time)
st.session_state.setdefault("env_editor_new_key", "")
st.session_state.setdefault("env_editor_new_value", "")
st.session_state.setdefault("env_editor_reset", False)
st.session_state.setdefault("env_editor_feedback", None)

from agi_env.pagelib import background_services_enabled, inject_theme, render_sidebar_version
from agi_env.credential_store_support import (
    CLUSTER_CREDENTIALS_KEY,
    KEYRING_SENTINEL,
    read_cluster_credentials,
    store_cluster_credentials,
)
from agi_env.ui_support import detect_agilab_version, load_last_active_app, store_last_active_app

FIRST_PROOF_PROJECT = "flight_project"
FIRST_PROOF_COMPATIBILITY_SLICE = "Web UI local first proof"
FIRST_PROOF_HELPER_SCRIPT_PREFIXES = (
    "AGI_install_",
    "AGI_run_",
    "AGI_get_",
)

# ----------------- Fast-Loading Banner UI -----------------
def _newcomer_first_proof_content() -> Dict[str, Any]:
    """Return the first-proof onboarding contract shown on the landing page."""
    return {
        "title": "Start here",
        "intro": "Goal: make one demo work on your computer. Start from PROJECT, not from this page.",
        "steps": [
            ("PROJECT", "Go to `PROJECT`. Choose `flight_project`."),
            ("ORCHESTRATE", "Go to `ORCHESTRATE`. Click INSTALL, then EXECUTE."),
        ],
        "success_criteria": [
            "`flight_project` runs without error.",
            "Generated files are created for `flight_project`.",
            "Now you can try another demo.",
        ],
        "links": [
            ("Quick start", "https://thalesgroup.github.io/agilab/quick-start.html"),
            ("Newcomer guide", "https://thalesgroup.github.io/agilab/newcomer-guide.html"),
            ("Compatibility matrix", "https://thalesgroup.github.io/agilab/compatibility-matrix.html"),
            ("Flight project guide", "https://thalesgroup.github.io/agilab/flight-project.html"),
        ],
    }


def _newcomer_first_proof_project_path(env: Any) -> Path | None:
    """Return the preferred built-in first-proof app path when available."""
    candidates: list[Path] = []
    try:
        apps_path = Path(getattr(env, "apps_path", "")).expanduser()
    except (TypeError, ValueError, RuntimeError):
        apps_path = Path()
    if str(apps_path):
        candidates.extend(
            [
                apps_path / FIRST_PROOF_PROJECT,
                apps_path / "builtin" / FIRST_PROOF_PROJECT,
            ]
        )

    module_builtin = Path(__file__).resolve().parent / "apps" / "builtin" / FIRST_PROOF_PROJECT
    candidates.append(module_builtin)

    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.exists():
            return resolved
    return None


def _first_proof_output_dir(env: Any) -> Path:
    """Return the log directory used by the built-in first-proof route."""
    log_root = Path(getattr(env, "AGILAB_LOG_ABS", Path.home() / "log")).expanduser()
    return log_root / "execute" / "flight"


def _list_first_proof_outputs(output_dir: Path) -> list[Path]:
    """Return evidence-like outputs, excluding seeded AGI helper scripts."""
    if not output_dir.exists():
        return []
    outputs: list[Path] = []
    for child in sorted(output_dir.iterdir(), key=lambda item: item.name):
        if child.name.startswith("."):
            continue
        if child.is_file() and child.suffix == ".py" and child.name.startswith(FIRST_PROOF_HELPER_SCRIPT_PREFIXES):
            continue
        outputs.append(child)
    return outputs


def _newcomer_first_proof_state(env: Any) -> Dict[str, Any]:
    """Return concrete wizard state for the in-product first-proof path."""
    content = _newcomer_first_proof_content()
    project_path = _newcomer_first_proof_project_path(env)
    active_app_name = str(getattr(env, "app", "") or "")
    output_dir = _first_proof_output_dir(env)
    visible_outputs = _list_first_proof_outputs(output_dir)
    helper_scripts_present = all(
        (output_dir / script_name).exists()
        for script_name in (
            "AGI_install_flight.py",
            "AGI_run_flight.py",
        )
    )
    current_app_matches = active_app_name == FIRST_PROOF_PROJECT

    if project_path is None:
        next_step = "Fix the app list first. `flight_project` is missing."
    elif not current_app_matches:
        next_step = "Go to `PROJECT`. Choose `flight_project`."
    elif not visible_outputs:
        next_step = "Go to `ORCHESTRATE`. Click INSTALL, then EXECUTE."
    else:
        next_step = "First proof done. Now you can try another demo."

    return {
        "content": content,
        "compatibility_slice": FIRST_PROOF_COMPATIBILITY_SLICE,
        "project_path": project_path,
        "project_available": project_path is not None,
        "active_app_name": active_app_name,
        "current_app_matches": current_app_matches,
        "output_dir": output_dir,
        "helper_scripts_present": helper_scripts_present,
        "visible_outputs": visible_outputs,
        "run_output_detected": bool(visible_outputs),
        "next_step": next_step,
    }


def _activate_newcomer_first_proof_project(env: Any, project_path: Path) -> bool:
    """Switch the current app to the built-in flight project and persist the choice."""
    changed = _apply_active_app_request(env, str(project_path))
    try:
        st.query_params["active_app"] = env.app
    except (AttributeError, RuntimeError, TypeError):
        pass
    try:
        store_last_active_app(project_path)
    except (OSError, RuntimeError, TypeError, ValueError):
        pass
    return changed or str(getattr(env, "app", "")) == FIRST_PROOF_PROJECT


def _render_newcomer_first_proof_static() -> None:
    """Render the legacy concise newcomer checklist used by helper tests."""
    content = _newcomer_first_proof_content()
    steps_html = "".join(
        f"<li><strong>{label}</strong>: {detail}</li>"
        for label, detail in content["steps"]
    )
    success_html = "".join(
        f"<li>{item}</li>"
        for item in content["success_criteria"]
    )
    st.markdown(
        f"""
        <div style="border: 1px solid rgba(120, 120, 120, 0.35); border-radius: 12px; padding: 1rem 1.2rem; margin: 1rem 0 1.25rem 0; background: rgba(250, 250, 250, 0.82);">
          <h3 style="margin-top: 0;">{content["title"]}</h3>
          <p style="margin-bottom: 0.75rem;">{content["intro"]}</p>
          <p style="margin-bottom: 0.35rem;"><strong>First proof steps</strong></p>
          <ol style="margin-top: 0.1rem; margin-bottom: 0.75rem;">{steps_html}</ol>
          <p style="margin-bottom: 0.35rem;"><strong>You are done when</strong></p>
          <ul style="margin-top: 0.1rem; margin-bottom: 0.5rem;">{success_html}</ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_newcomer_first_proof(env: Any | None = None) -> None:
    """Render the first-proof onboarding surface."""
    if env is None:
        _render_newcomer_first_proof_static()
        return

    state = _newcomer_first_proof_state(env)
    content = state["content"]
    feedback = st.session_state.pop("first_proof_feedback", None)
    if feedback:
        st.success(str(feedback))

    with st.expander(content["title"], expanded=True):
        st.write(content["intro"])
        st.markdown("**Do this now**")
        step_lines = [
            f"{index}. {detail}"
            for index, (_, detail) in enumerate(content["steps"], start=1)
        ]
        st.markdown("\n".join(step_lines))

        if not state["project_available"]:
            st.error(state["next_step"])
        elif not state["current_app_matches"]:
            st.warning(f"Next action: {state['next_step']}")
            if st.button(
                "Use `flight_project`",
                key="first_proof:activate",
                type="primary",
                use_container_width=True,
            ):
                if _activate_newcomer_first_proof_project(env, state["project_path"]):
                    st.session_state["first_proof_feedback"] = "`flight_project` selected."
                    st.rerun()
        elif not state["run_output_detected"]:
            st.info(f"Next action: {state['next_step']}")
        else:
            st.success(f"Next action: {state['next_step']}")

        if state["visible_outputs"]:
            preview = ", ".join(path.name for path in state["visible_outputs"][:3])
            if len(state["visible_outputs"]) > 3:
                preview += ", …"
            st.caption(f"Generated files found: {preview}")

        st.markdown("**You are done when**")
        st.markdown("\n".join(f"- {item}" for item in content["success_criteria"]))
        st.caption("After that: try another demo. Keep cluster mode for later.")

        st.divider()
        display_landing_page(Path(env.st_resources))


def quick_logo(resources_path: Path) -> None:
    """Render a lightweight banner with the AGILab logo."""
    try:
        from agi_env.pagelib import get_base64_of_image
        img_data = get_base64_of_image(resources_path / "agilab_logo.png")
        img_src = f"data:image/png;base64,{img_data}"
        st.markdown(
            f"""<div style="background-color: #333333; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); max-width: 800px; margin: 20px auto;">
                    <div style="display: flex; align-items: center; justify-content: center;">
                        <h1 style="margin: 0; padding: 0 10px 0 0;">Welcome to</h1>
                        <img src="{img_src}" alt="AGI Logo" style="width:160px; margin-bottom: 20px;">
                    </div>
                    <div style="text-align: center;">
                        <strong style="color: black;">a step further toward AGI</strong>
                    </div>
                </div>""", unsafe_allow_html=True
        )
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as e:
        st.info(str(e))
        st.info("Welcome to AGILAB", icon="📦")


def _landing_page_sections() -> Dict[str, Any]:
    """Return compact secondary guidance shown under the first-step path."""
    return {
        "after_first_demo": [
            "try another built-in demo",
            "keep cluster mode for later",
        ],
    }


def display_landing_page(resources_path: Path) -> None:
    """Display compact secondary context under the first-step instructions."""
    del resources_path
    st.info("After the first demo: try another built-in demo. Keep cluster mode for later.")


def show_banner_and_intro(resources_path: Path, env: Any | None = None) -> None:
    """Render the branding banner."""
    quick_logo(resources_path)
    render_newcomer_first_proof(env)

def _clean_openai_key(key: str | None) -> str | None:
    """Return None for missing/placeholder keys to avoid confusing 401s."""
    if not key:
        return None
    trimmed = key.strip()
    placeholders = {"your-key", "sk-your-key", "sk-XXXX"}
    if trimmed in placeholders or len(trimmed) < 12:
        return None
    return trimmed


def openai_status_banner(env: Any) -> None:
    """Show a non-blocking banner if OpenAI features are unavailable and direct users to the env editor."""
    import os

    env_key = getattr(env, "OPENAI_API_KEY", None)

    key = _clean_openai_key(os.environ.get("OPENAI_API_KEY") or env_key)
    if not key:
        st.warning(
            f"OpenAI features are disabled. Set OPENAI_API_KEY below in 'Environment Variables', then reload the app. The value will be saved in {ENV_FILE_PATH}.",
            icon="⚠️",
        )

ENV_FILE_PATH = Path.home() / ".agilab/.env"
try:
    TEMPLATE_ENV_PATH = importlib_resources.files("agi_env") / "resources/.agilab/.env"
except (ModuleNotFoundError, FileNotFoundError, AttributeError, OSError):
    TEMPLATE_ENV_PATH = None


def _normalize_active_app_input(env, raw_value: Optional[str]) -> Path | None:
    """Return a Path to the requested active app if the input is valid."""
    if not raw_value:
        return None

    candidates: list[Path] = []
    try:
        provided = Path(raw_value).expanduser()
    except (TypeError, RuntimeError, ValueError):
        return None

    # If the user passed a direct path, trust it first.
    if provided.is_absolute():
        candidates.append(provided)
    else:
        candidates.append((Path.cwd() / provided).resolve())
        candidates.append((env.apps_path / provided).resolve())
        candidates.append((env.apps_path / provided.name).resolve())

    # Shortcut when the value already matches a known project name.
    if raw_value in env.projects:
        candidates.insert(0, (env.apps_path / raw_value).resolve())
    elif provided.name in env.projects:
        candidates.insert(0, (env.apps_path / provided.name).resolve())

    for candidate in candidates:
        try:
            candidate = candidate.resolve()
        except OSError:
            continue
        if candidate.exists():
            return candidate
    return None


def _apply_active_app_request(env, request_value: Optional[str]) -> bool:
    """Switch AgiEnv to the requested app name/path; returns True if a change occurred."""
    target_path = _normalize_active_app_input(env, request_value)
    if not target_path:
        return False

    target_name = target_path.name
    if target_name == env.app:
        return False
    try:
        env.change_app(target_path)
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
        st.warning(f"Unable to switch to project '{target_name}': {exc}")
        return False
    return True


def _sync_active_app_from_query(env) -> None:
    """Honor ?active_app=… query parameter so all pages stay in sync."""
    try:
        requested = st.query_params.get("active_app")
    except (AttributeError, RuntimeError, TypeError):
        requested = None

    if isinstance(requested, (list, tuple)):
        requested_value = requested[0] if requested else None
    else:
        requested_value = requested

    changed = False
    if requested_value:
        changed = _apply_active_app_request(env, str(requested_value))

    if not requested_value or changed or requested_value != env.app:
        try:
            st.query_params["active_app"] = env.app
        except (AttributeError, RuntimeError, TypeError):
            pass

    # Persist the latest active app for reuse on next launch only if it changed via request
    try:
        if changed:
            store_last_active_app(Path(env.apps_path) / env.app)
    except (OSError, RuntimeError, TypeError, ValueError):
        pass

def _ensure_env_file(path: Path) -> Path:
    """Ensure the ~/.agilab/.env file exists without touching mtime on every rerun."""
    try:
        if path.exists():
            return path
    except OSError:
        return path

    parent = path.parent
    try:
        try:
            parent.mkdir(parents=True, exist_ok=False)
            logger.info(f"mkdir {parent}")
        except FileExistsError:
            pass
        if TEMPLATE_ENV_PATH is not None:
            try:
                template_text = TEMPLATE_ENV_PATH.read_text(encoding="utf-8")
                path.write_text(template_text, encoding="utf-8")
                return path
            except (OSError, UnicodeError):
                pass
        path.touch(exist_ok=True)
    except OSError as exc:
        logger.warning(f"Unable to create env file at {path}: {exc}")
    return path

def _resolve_share_dir_path(raw_value: str, *, home_path: Path) -> Path:
    """Return a normalized AGI share path or raise ``ValueError`` when invalid."""
    try:
        share_dir = Path(str(raw_value)).expanduser()
    except (TypeError, ValueError) as exc:
        raise ValueError("AGI_SHARE_DIR is not a valid filesystem path.") from exc

    if not share_dir.is_absolute():
        share_dir = home_path.expanduser() / share_dir

    try:
        return share_dir.resolve(strict=False)
    except (OSError, ValueError) as exc:
        raise ValueError(f"AGI_SHARE_DIR cannot be resolved: {exc}") from exc

def _refresh_share_dir(env, new_value: str) -> None:
    """Update the in-memory AgiEnv share-path attributes after a UI change."""
    if not new_value:
        return

    share_value = str(new_value)
    try:
        share_dir = _resolve_share_dir_path(share_value, home_path=Path(env.home_abs))
    except ValueError as exc:
        st.warning(str(exc))
        return

    # Persist the raw value (without forcing absolutes) so workers can resolve
    # relative mounts appropriately; share_root_path() performs the expansion.
    env.agi_share_path = share_value
    env._share_root_cache = share_dir
    env.agi_share_path_abs = share_dir
    share_target = env.share_target_name
    env.app_data_rel = share_dir / share_target
    env.dataframe_path = env.app_data_rel / "dataframe"
    try:
        env.data_root = env.ensure_data_root()
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
        st.warning(f"AGI_SHARE_DIR update saved but data directory is still unreachable: {exc}")

def _handle_data_root_failure(exc: Exception, *, agi_env_cls) -> bool:
    """Render a recovery UI when the AGI share directory is unavailable."""
    message = str(exc)
    if "AGI_SHARE_DIR" not in message and "data directory" not in message:
        return False

    agi_env_cls._ensure_defaults()
    current_value = (
        st.session_state.get("agi_share_path_override_input")
        or agi_env_cls.envars.get("AGI_SHARE_DIR")
        or os.environ.get("AGI_SHARE_DIR")
        or agi_env_cls.envars.get("AGI_LOCAL_SHARE")
        or ""
    )
    share_dir_path = Path(str(current_value)).expanduser()

    st.error(
        "AGILAB cannot reach the configured AGI share directory. "
        "Mount the expected path or override `AGI_SHARE_DIR` before continuing."
    )
    st.code(message)
    st.info(
        f"The value is persisted in `{ENV_FILE_PATH}` so CLI and Streamlit stay in sync. "
        "Point it to a mounted folder (local path or NFS mount) that AGILAB can create files in."
    )
    st.write(f"Current setting: `{current_value}` (expands to `{share_dir_path}`)")

    key = "agi_share_path_override_input"
    if key not in st.session_state or not st.session_state[key]:
        st.session_state[key] = str(current_value)

    with st.form("agi_share_path_override_form"):
        st.text_input("New AGI_SHARE_DIR", key=key, help="Provide an absolute or home-relative path")
        submitted = st.form_submit_button("Save and retry", width="stretch")

    if submitted:
        new_value = (st.session_state.get(key) or "").strip()
        if not new_value:
            st.warning("AGI_SHARE_DIR cannot be empty.")
        else:
            try:
                _resolve_share_dir_path(new_value, home_path=Path(agi_env_cls.home_abs))
            except ValueError as exc:
                st.warning(str(exc))
                return True
            agi_env_cls.set_env_var("AGI_SHARE_DIR", new_value)
            st.success(f"Saved AGI_SHARE_DIR = {new_value}. Reloading…")
            st.session_state["first_run"] = True
            st.rerun()
    return True

def _strip_dotenv_quotes(value: str) -> str:
    """Remove surrounding quotes from a .env value, matching python-dotenv behaviour."""
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
        return v[1:-1]
    return v


def _read_env_file(path: Path) -> List[Dict[str, str]]:
    path = _ensure_env_file(path)
    entries: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle.readlines():
            raw = raw_line.rstrip("\n")
            stripped = raw.strip()
            if not stripped:
                entries.append({"type": "comment", "raw": raw})
                continue

            # Treat commented KEY=VAL lines as entries so they can be edited/uncommented.
            target = stripped.lstrip("#").strip()
            if "=" in target:
                key, value = target.split("=", 1)
                entries.append(
                    {
                        "type": "entry",
                        "key": key.strip(),
                        "value": _strip_dotenv_quotes(value),
                        "raw": raw,
                        "commented": stripped.startswith("#"),
                    }
                )
            else:
                entries.append({"type": "comment", "raw": raw})
    return entries


def _is_worker_python_override_key(key: str) -> bool:
    """Return True for host-specific worker Python version keys."""
    normalized = str(key).strip()
    return normalized.endswith("_PYTHON_VERSION") and normalized != "AGI_PYTHON_VERSION"


def _worker_python_override_host(key: str) -> str:
    """Return the host portion of ``<worker-host>_PYTHON_VERSION``."""
    normalized = str(key).strip()
    if not _is_worker_python_override_key(normalized):
        return ""
    return normalized[: -len("_PYTHON_VERSION")]


def _env_editor_field_label(key: str) -> str:
    """Return a human-readable label for environment-variable fields."""
    normalized = str(key).strip()
    if normalized == "AGI_PYTHON_VERSION":
        return "Default Python version"
    if normalized == "AGI_PYTHON_FREE_THREADED":
        return "Use free-threaded Python"
    if _is_worker_python_override_key(normalized):
        host = _worker_python_override_host(normalized)
        return f"Worker Python version for {host}" if host else "Worker Python version"
    return normalized


def _visible_env_editor_keys(
    template_keys: List[str],
    existing_entries: List[Dict[str, str]],
) -> List[str]:
    """Return env-editor keys in template order plus worker Python overrides."""
    ordered_keys: List[str] = list(template_keys)
    seen = set(ordered_keys)
    for entry in existing_entries:
        if entry.get("type") != "entry":
            continue
        key = str(entry.get("key", "")).strip()
        if not key or key in seen:
            continue
        if _is_worker_python_override_key(key):
            ordered_keys.append(key)
            seen.add(key)
    if ordered_keys:
        return ordered_keys
    return list(dict.fromkeys(str(entry["key"]).strip() for entry in existing_entries if entry.get("type") == "entry"))

def _write_env_file(path: Path, entries: List[Dict[str, str]], updates: Dict[str, str], new_entry: Dict[str, str] | None) -> None:
    """Write the .env file, consolidating duplicate keys (last value wins)."""
    path = _ensure_env_file(path)
    lines: List[str] = []
    emitted_keys: set[str] = set()

    # Build consolidated value map: for each key, determine the final value.
    # updates > last file occurrence > first file occurrence.
    file_values: Dict[str, str] = {}
    for entry in entries:
        if entry["type"] == "entry":
            file_values[entry["key"]] = entry["value"]
    final_values: Dict[str, str] = {**file_values, **updates}

    for entry in entries:
        if entry["type"] != "entry":
            lines.append(entry["raw"])
            continue
        key = entry["key"]
        if key in emitted_keys:
            continue  # skip duplicate — already written with the final value
        emitted_keys.add(key)
        value = final_values.get(key, entry["value"])
        lines.append(f"{key}={value}")

    for key, value in updates.items():
        if key not in emitted_keys:
            lines.append(f"{key}={value}")
            emitted_keys.add(key)

    if new_entry and new_entry.get("key") and new_entry["key"] not in emitted_keys:
        lines.append(f"{new_entry['key']}={new_entry['value']}")

    content = "\n".join(lines).rstrip() + "\n"
    path.write_text(content, encoding="utf-8")


def _upsert_env_var(path: Path, key: str, value: str) -> None:
    """Update or append a single KEY=VALUE in the .env file."""
    path = _ensure_env_file(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    rewritten: List[str] = []
    key_eq = f"{key}="
    updated = False
    for raw in lines:
        stripped = raw.strip()
        target = stripped.lstrip("#").strip()
        if target.startswith(key_eq):
            rewritten.append(f"{key}={value}")
            updated = True
        else:
            rewritten.append(raw)
    if not updated:
        rewritten.append(f"{key}={value}")
    path.write_text("\n".join(rewritten).rstrip() + "\n", encoding="utf-8")


def _refresh_env_from_file(env: Any) -> None:
    """Re-load ~/.agilab/.env into env.envars and os.environ when it changes."""
    try:
        current_mtime = ENV_FILE_PATH.stat().st_mtime_ns
    except FileNotFoundError:
        return

    last_mtime = st.session_state.get("env_file_mtime_ns")
    if last_mtime is not None and last_mtime == current_mtime:
        return

    env_map = _load_env_file_map(ENV_FILE_PATH)
    if not env_map:
        st.session_state["env_file_mtime_ns"] = current_mtime
        return

    for key, val in env_map.items():
        resolved_value = val
        if key == CLUSTER_CREDENTIALS_KEY:
            resolved_value = read_cluster_credentials(
                val,
                environ=os.environ,
                logger=logger,
            )
        os.environ[key] = resolved_value
        try:
            if env.envars is not None:
                env.envars[key] = resolved_value
        except (AttributeError, TypeError):
            pass

    # Keep env.apps_path in sync with the user's .env APPS_PATH
    new_apps_path = env_map.get("APPS_PATH", "").strip()
    if new_apps_path and str(getattr(env, "apps_path", "")) != new_apps_path:
        try:
            resolved = Path(new_apps_path).expanduser().resolve()
            env.apps_path = resolved
        except (OSError, RuntimeError, TypeError, ValueError):
            pass

    st.session_state["env_file_mtime_ns"] = current_mtime


def _render_env_editor(env: Any, help_file: Path | None = None) -> None:
    feedback = st.session_state.pop("env_editor_feedback", None)
    if feedback:
        st.success(feedback)

    st.session_state.setdefault("env_editor_new_key", "")
    st.session_state.setdefault("env_editor_new_value", "")

    entries = _read_env_file(ENV_FILE_PATH)
    existing_entries = [entry for entry in entries if entry["type"] == "entry"]

    # Build a last-wins value map so that the form shows the most recent value
    # for each *active* key (AgiEnv.set_env_var appends updates at the end of the file).
    # Commented template/example lines are documentation, not live current values.
    last_value_map: Dict[str, str] = {}
    commented_default_map: Dict[str, str] = {}
    for entry in existing_entries:
        key = entry["key"]
        value = entry["value"].strip()
        if entry.get("commented"):
            commented_default_map[key] = value
            continue
        last_value_map[key] = value
    existing_values = dict(last_value_map)

    # Only show keys defined in the template .env (the canonical user-facing
    # settings), in template order, with values from the user's file.
    template_keys: List[str] = []
    template_defaults: Dict[str, str] = {}
    if TEMPLATE_ENV_PATH is not None:
        try:
            with TEMPLATE_ENV_PATH.open("r", encoding="utf-8") as tf:
                for raw in tf.readlines():
                    stripped = raw.strip()
                    if not stripped or "=" not in stripped:
                        continue
                    key_part, value_part = stripped.lstrip("#").split("=", 1)
                    key = key_part.strip()
                    value = value_part.strip()
                    if key and key not in template_keys:
                        template_keys.append(key)
                    if key and key not in template_defaults:
                        template_defaults[key] = value
        except (OSError, UnicodeError):
            pass

    unique_keys = _visible_env_editor_keys(template_keys, existing_entries)

    st.caption(
        "`AGI_PYTHON_VERSION` sets the default Python version. "
        "Workers can override it with `<worker-host>_PYTHON_VERSION`, "
        "for example `127.0.0.1_PYTHON_VERSION=3.13`."
    )

    with st.form("env_editor_form"):
        updated_values: Dict[str, str] = {}
        for key in unique_keys:
            default_value = last_value_map.get(key, template_defaults.get(key, ""))
            if key == CLUSTER_CREDENTIALS_KEY and key not in last_value_map:
                # Treat the commented template credential as documentation, not a
                # live default value that would be re-saved into the user's env.
                default_value = ""
            if key == CLUSTER_CREDENTIALS_KEY and default_value == KEYRING_SENTINEL:
                default_value = (
                    str(getattr(env, "CLUSTER_CREDENTIALS", "") or "")
                    or str(getattr(env, "envars", {}).get(CLUSTER_CREDENTIALS_KEY, "") or "")
                )
            updated_values[key] = st.text_input(
                _env_editor_field_label(key),
                value=default_value,
                key=f"env_editor_val_{key}",
                help=f"Set value for {key}",
            )

        st.markdown("#### Add a new variable")
        new_key = st.text_input("Variable name", key="env_editor_new_key", placeholder="MY_SETTING")
        new_value = st.text_input("Variable value", key="env_editor_new_value", placeholder="value")

        submitted = st.form_submit_button("Save .env", type="primary")

    if submitted:
        cleaned_updates: Dict[str, str] = {}
        for key in unique_keys:
            submitted_value = st.session_state.get(f"env_editor_val_{key}", "").strip()
            untouched_template_default = commented_default_map.get(key, template_defaults.get(key, ""))
            if key not in last_value_map and submitted_value == untouched_template_default:
                continue
            cleaned_updates[key] = submitted_value

        new_entry_data = None
        new_key_clean = new_key.strip()
        if new_key_clean:
            new_value_clean = new_value.strip()
            if new_key_clean in cleaned_updates:
                cleaned_updates[new_key_clean] = new_value_clean
            else:
                new_entry_data = {"key": new_key_clean, "value": new_value_clean}

        try:
            runtime_updates = dict(cleaned_updates)
            env_file_updates = dict(cleaned_updates)
            env_file_new_entry = dict(new_entry_data) if new_entry_data else None
            if CLUSTER_CREDENTIALS_KEY in runtime_updates:
                cluster_secret = runtime_updates[CLUSTER_CREDENTIALS_KEY]
                if store_cluster_credentials(cluster_secret, environ=os.environ, logger=logger):
                    env_file_updates[CLUSTER_CREDENTIALS_KEY] = KEYRING_SENTINEL

            if (
                env_file_new_entry
                and env_file_new_entry.get("key") == CLUSTER_CREDENTIALS_KEY
                and env_file_new_entry.get("value")
            ):
                if store_cluster_credentials(env_file_new_entry["value"], environ=os.environ, logger=logger):
                    env_file_new_entry["value"] = KEYRING_SENTINEL

            _write_env_file(ENV_FILE_PATH, entries, env_file_updates, env_file_new_entry)
            combined_updates = dict(runtime_updates)
            if new_entry_data:
                combined_updates[new_entry_data["key"]] = new_entry_data["value"]

            for key, value in combined_updates.items():
                os.environ[key] = value
                if hasattr(env, "envars") and isinstance(env.envars, dict):
                    env.envars[key] = value
            if CLUSTER_CREDENTIALS_KEY in combined_updates:
                env.CLUSTER_CREDENTIALS = combined_updates[CLUSTER_CREDENTIALS_KEY]

            new_share = combined_updates.get("AGI_SHARE_DIR")
            if new_share is not None and new_share.strip() and new_share.strip() != existing_values.get("AGI_SHARE_DIR"):
                _refresh_share_dir(env, new_share.strip())

            st.session_state["env_editor_feedback"] = "Environment variables updated."
            st.session_state["env_editor_reset"] = True
            st.rerun()
        except (OSError, RuntimeError, TypeError, UnicodeError, ValueError) as exc:
            st.error(f"Failed to save .env file: {exc}")

    st.divider()
    st.markdown("#### .env contents (template order; all variables)")
    try:
        if TEMPLATE_ENV_PATH is None:
            raise FileNotFoundError("AgiEnv template .env not found in package resources.")

        template_keys: List[str] = []
        with TEMPLATE_ENV_PATH.open("r", encoding="utf-8") as tf:
            for raw in tf.readlines():
                stripped = raw.strip()
                if not stripped or "=" not in stripped:
                    continue
                # Allow commented template entries (lines starting with '#')
                key = stripped.lstrip("#").split("=", 1)[0].strip()
                if key:
                    template_keys.append(key)

        env_lines = ENV_FILE_PATH.read_text(encoding="utf-8").splitlines()
        current: Dict[str, str] = {}
        for raw in env_lines:
            stripped = raw.strip()
            if not stripped or "=" not in stripped:
                continue
            normalized = stripped.lstrip("#").strip()
            if "=" not in normalized:
                continue
            key, val = normalized.split("=", 1)
            current[key.strip()] = _strip_dotenv_quotes(val)

        merged = []
        for key in template_keys:
            value = current.get(key, "")
            if key == CLUSTER_CREDENTIALS_KEY and value == KEYRING_SENTINEL:
                value = "<stored in keyring>"
            merged.append(f"{key}={value}")
        for key in sorted(current.keys()):
            if key in template_keys:
                continue
            if key == CLUSTER_CREDENTIALS_KEY and current.get(key) == KEYRING_SENTINEL:
                merged.append(f"{key}=<stored in keyring>")
            else:
                merged.append(f"{key}={current[key]}")
        if merged:
            st.code("\n".join(merged))
        else:
            st.caption("No environment variables found in the current .env.")
    except FileNotFoundError:
        st.caption(f"Template or current .env file not found (template: {TEMPLATE_ENV_PATH}, current: {ENV_FILE_PATH}).")
    except (OSError, UnicodeError) as exc:
        st.error(f"Unable to read env files: {exc}")

def page(env: Any) -> None:
    """Render the main landing page controls and footer for the lab."""
    try:
        render_sidebar_version(detect_agilab_version(env))
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        pass

    with st.expander(f"Environment Variables ({ENV_FILE_PATH.expanduser()})", expanded=False):
        _render_env_editor(env)

    with st.expander("Installed package versions", expanded=False):
        try:
            from importlib import metadata as importlib_metadata
        except ImportError:
            import importlib_metadata  # type: ignore

        packages = [
            ("agilab", "agilab"),
            ("agi-core", "agi-core"),
            ("agi-node", "agi-node"),
            ("agi-env", "agi-env"),
        ]

        version_rows = []
        for label, pkg_name in packages:
            try:
                version = importlib_metadata.version(pkg_name)
            except importlib_metadata.PackageNotFoundError:
                version = "not installed"
            version_rows.append(f"{label}: {version}")

        for entry in version_rows:
            st.write(entry)

    with st.expander("System information", expanded=False):
        import platform

        st.write(f"OS: {platform.system()} {platform.release()}")
        cpu_name = platform.processor() or platform.machine()
        st.write(f"CPU: {cpu_name}")

    render_page_docs_access(
        env,
        html_file="agilab-help.html",
        key_prefix="about",
        sidebar=True,
        divider=False,
    )

    current_year = datetime.now().year
    st.markdown(
        f"""
    <div class='footer' style="display: flex; justify-content: flex-end;">
        <span>&copy; 2020-{current_year} Thales SIX GTS. Licensed under the BSD 3-Clause License.</span>
    </div>
    """,
        unsafe_allow_html=True,
    )
    if "TABLE_MAX_ROWS" not in st.session_state:
        st.session_state["TABLE_MAX_ROWS"] = env.TABLE_MAX_ROWS
    if "GUI_SAMPLING" not in st.session_state:
        st.session_state["GUI_SAMPLING"] = env.GUI_SAMPLING


# ------------------------- Main Entrypoint -------------------------

def main() -> None:
    """Initialise the Streamlit app, bootstrap the environment and display the UI."""
    from agi_env.pagelib import get_about_content
    st.set_page_config(
        page_title="AGILab",
        menu_items=get_about_content(),
        layout="wide",
    )
    resources_path = Path(__file__).resolve().parent / "resources"
    os.environ.setdefault("STREAMLIT_CONFIG_FILE", str(resources_path / "config.toml"))
    try:
        inject_theme(resources_path)
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as e:
        # Non-fatal: UI will still load without custom theme
        st.warning(f"Theme injection skipped: {e}")
    st.session_state.setdefault("first_run", True)

    # Always set background style
    st.markdown(
        """<style>
        body { background: #f6f8fa !important; }
        </style>""",
        unsafe_allow_html=True
    )

    # ---- Initialize if needed (on cold start, or if 'env' key lost) ----
    if st.session_state.get("first_run", True) or "env" not in st.session_state:
        with st.spinner("Initializing environment..."):
            from agi_env.pagelib import activate_mlflow
            from agi_env import AgiEnv
            parser = argparse.ArgumentParser(description="Run the AGI Streamlit App with optional parameters.")
            parser.add_argument("--apps-path", type=str, help="Where you store your apps (default is ./)",
                                default=None)
            parser.add_argument(
                "--active-app",
                type=str,
                help="App name or path to select on startup (mirrors ?active_app= query parameter).",
                default=None,
            )

            args, _ = parser.parse_known_args()
            apps_arg = args.apps_path

            if apps_arg is None:
                # Prefer the user's .env APPS_PATH over the .agilab-path default
                _env_apps = _load_env_file_map(ENV_FILE_PATH).get("APPS_PATH")
                if _env_apps and _env_apps.strip() and not _env_apps.startswith("/path/to"):
                    apps_arg = _env_apps.strip()

            if apps_arg is None:
                if os.name == "nt":
                    agi_path_file = Path(os.getenv("LOCALAPPDATA", "")) / "agilab/.agilab-path"
                else:
                    agi_path_file = Path.home() / ".local/share/agilab/.agilab-path"

                with open(agi_path_file, "r") as f:
                    agilab_path = f.read().strip()
                    if not agilab_path:
                        raise FileNotFoundError(f"Empty .agilab-path at {agi_path_file}")
                    before, sep, after = agilab_path.rpartition(".venv")
                    if not sep:
                        raise ValueError(
                            f"Malformed .agilab-path (missing .venv marker): {agilab_path!r}"
                        )
                    candidate = Path(before).resolve(strict=False) / "apps"
                    # Reject paths containing traversal components
                    try:
                        candidate = candidate.resolve(strict=False)
                    except OSError as path_err:
                        raise ValueError(
                            f"Cannot resolve apps path from .agilab-path: {path_err}"
                        ) from path_err
                    apps_arg = candidate

            if apps_arg is None:
                st.error("Error: Missing mandatory parameter: --apps-path")
                sys.exit(1)

            apps_path = Path(apps_arg).expanduser() if apps_arg else None
            if apps_path is None:
                st.error("Error: Missing mandatory parameter: --apps-path")
                sys.exit(1)

            st.session_state["apps_path"] = str(apps_path)

            try:
                env = AgiEnv(apps_path=apps_path, verbose=1)
            except RuntimeError as exc:
                if _handle_data_root_failure(exc, agi_env_cls=AgiEnv):
                    return
                raise
            # Determine requested app: CLI flag first, then last-remembered app.
            requested_app = args.active_app
            if not requested_app:
                last_app = load_last_active_app()
                if last_app:
                    requested_app = str(last_app)
            # Honor the requested app, falling back to env default when invalid.
            _apply_active_app_request(env, requested_app)
            env.init_done = True
            st.session_state['env'] = env
            st.session_state["IS_SOURCE_ENV"] = env.is_source_env
            st.session_state["IS_WORKER_ENV"] = env.is_worker_env

            if background_services_enabled() and not st.session_state.get("server_started"):
                activate_mlflow(env)

            try:
                store_last_active_app(Path(env.apps_path) / env.app)
            except (OSError, RuntimeError, TypeError, ValueError):
                pass

            try:
                _refresh_env_from_file(env)
            except (OSError, RuntimeError, TypeError, ValueError):
                pass

            openai_api_key = _clean_openai_key(env.OPENAI_API_KEY)
            if not openai_api_key:
                st.warning("OPENAI_API_KEY not set. OpenAI-powered features will be disabled.")

            cluster_credentials = env.CLUSTER_CREDENTIALS or ""

            # Only persist defaults for keys NOT already saved in the user's
            # .env file so that values edited via the UI survive page reloads.
            # Explicit CLI arguments always take priority.
            _saved = _load_env_file_map(ENV_FILE_PATH)

            def _init_env_var(key: str, value: str, *, force: bool = False) -> None:
                """Set env var in memory; persist to .env only if missing."""
                os.environ[key] = value
                if hasattr(env, "envars") and isinstance(env.envars, dict):
                    env.envars[key] = value
                if force or key not in _saved:
                    AgiEnv.set_env_var(key, value)

            if openai_api_key:
                _init_env_var("OPENAI_API_KEY", openai_api_key)
            if cluster_credentials:
                os.environ[CLUSTER_CREDENTIALS_KEY] = cluster_credentials
                if hasattr(env, "envars") and isinstance(env.envars, dict):
                    env.envars[CLUSTER_CREDENTIALS_KEY] = cluster_credentials
                if CLUSTER_CREDENTIALS_KEY not in _saved:
                    if store_cluster_credentials(cluster_credentials, environ=os.environ, logger=logger):
                        AgiEnv.set_env_var(CLUSTER_CREDENTIALS_KEY, KEYRING_SENTINEL)
                    else:
                        AgiEnv.set_env_var(CLUSTER_CREDENTIALS_KEY, cluster_credentials)
            else:
                _init_env_var(CLUSTER_CREDENTIALS_KEY, "")
            _init_env_var("IS_SOURCE_ENV", str(int(bool(env.is_source_env))))
            _init_env_var("IS_WORKER_ENV", str(int(bool(env.is_worker_env))))
            _init_env_var("APPS_PATH", str(apps_path), force=bool(args.apps_path))

            st.session_state["first_run"] = False
            try:
                st.query_params["active_app"] = env.app
            except (AttributeError, RuntimeError, TypeError):
                pass
            if background_services_enabled():
                st.rerun()
                return

    # ---- After init, always show banner+intro and then main UI ----
    env = st.session_state['env']
    _refresh_env_from_file(env)
    _sync_active_app_from_query(env)
    try:
        store_last_active_app(Path(env.apps_path) / env.app)
    except (OSError, RuntimeError, TypeError, ValueError):
        pass
    show_banner_and_intro(resources_path, env)
    openai_status_banner(env)
    # Quick hint for operators: where to check install errors
    page(env)


# ----------------- Run App -----------------
if __name__ == "__main__":
    main()
