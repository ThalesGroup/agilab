# BSD 3-Clause License
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
# Co-author: Codex cli
"""Streamlit entry point for the AGILab interactive lab."""
import os
import sys
import argparse
import importlib.resources as importlib_resources
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional
from agi_env.agi_logger import AgiLogger

logger = AgiLogger.get_logger(__name__)

os.environ.setdefault("STREAMLIT_CONFIG_FILE", str(Path(__file__).resolve().parent / "resources" / "config.toml"))

import streamlit as st

# --- minimal session-state safety (add this block) ---
def _pre_render_reset():
    # If last run asked for a reset, clear BEFORE widgets are created this run
    if st.session_state.pop("env_editor_reset", False):
        st.session_state["env_editor_new_key"] = ""
        st.session_state["env_editor_new_value"] = ""

# One-time safe defaults (ok to run every time)
st.session_state.setdefault("env_editor_new_key", "")
st.session_state.setdefault("env_editor_new_value", "")
st.session_state.setdefault("env_editor_reset", False)
st.session_state.setdefault("env_editor_feedback", None)

from agi_env.pagelib import inject_theme, load_last_active_app, store_last_active_app

def _render_env_editor(env, help_file: Path):
    feedback = st.session_state.pop("env_editor_feedback", None)
    if feedback:
        st.success(feedback)

    # Clear inputs BEFORE widgets are created in this run
    if st.session_state.pop("env_editor_reset", False):
        st.session_state["env_editor_new_key"] = ""
        st.session_state["env_editor_new_value"] = ""

    # Provide defaults (safe before instantiation)
    st.session_state.setdefault("env_editor_new_key", "")
    st.session_state.setdefault("env_editor_new_value", "")

# ----------------- Fast-Loading Banner UI -----------------
def quick_logo(resources_path: Path):
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
    except Exception as e:
        st.info(str(e))
        st.info("Welcome to AGILAB", icon="📦")


def display_landing_page(resources_path: Path):
    """Display the introductory copy describing AGILab's value proposition."""
    from agi_env.pagelib import get_base64_of_image
    # You can optionally show a small logo here if wanted.
    md_content = f"""
    <div class="uvp-highlight">
    <ul>
      AGILAB revolutionizing data Science experimentation with zero integration hassles. As a comprehensive framework built on pure Python and powered by Gen AI and ML, AGILAB scales effortlessly—from embedded systems to the cloud—empowering seamless collaboration on data insights and predictive modeling.
    </ul>
    </div>
    <div class="uvp-highlight">
      <strong>Founding Concept:</strong>
    <ul>
      AGILAB outlines a method for scaling into a project’s execution environment without the need for virtualization or containerization (such as Docker). The approach involves encapsulating an app's logic into two components: a worker (which is scalable and free from dependency constraints) and a manager (which is easily integrable due to minimal dependency requirements). This design enables seamless integration within a single app, contributing to the move toward Artificial General Intelligence (AGI).
      For infrastructure that required docker, there is an agilab docker script to generate a docker image in the docker directory under the project root.
    </ul>      
    </div>
      <strong>Key Features:</strong>
    <ul>
      <li><strong>Strong AI Enabler</strong>: Algos Integrations.</li>
      <li><strong>Engineering AI Enabler</strong>: Feature Engineering.</li>
      <li><strong>Availability</strong>: Works online and in standalone mode.</li>
      <li><strong>Enhanced Deployment Productivity</strong>: Automates virtual environment deployment.</li>
      <li><strong>Assisted by Generative AI</strong>: Seamless integration with OpenAI API (online), GPT-OSS (local), and Mistral-instruct (local).</li>
      <li><strong>Enhanced Scalability</strong>: Distributes both data and algorithms on a cluster.</li>
      <li><strong>User-Friendly Interface for Data Science</strong>: Integration of Jupyter-ai and ML Flow.</li>
      <li><strong>Advanced Execution Tools</strong>: Enables Map Reduce and Direct Acyclic Graph Orchestration.</li>
    </ul>
    <p>
      With AGILAB, there’s no need for additional integration—our all-in-one framework is ready to deploy, enabling you to focus on innovation rather than setup.
    </p>
    
    """
    st.markdown(md_content, unsafe_allow_html=True)


def show_banner_and_intro(resources_path: Path):
    """Render the branding banner."""
    quick_logo(resources_path)

def _clean_openai_key(key: str | None) -> str | None:
    """Return None for missing/placeholder keys to avoid confusing 401s."""
    if not key:
        return None
    trimmed = key.strip()
    placeholders = {"your-key", "sk-your-key", "sk-XXXX"}
    if trimmed in placeholders or len(trimmed) < 12:
        return None
    return trimmed


def openai_status_banner(env):
    """Show a non-blocking banner if OpenAI features are unavailable and direct users to the env editor."""
    import os

    try:
        env_key = env.OPENAI_API_KEY
    except Exception:
        env_key = None

    key = _clean_openai_key(os.environ.get("OPENAI_API_KEY") or env_key)
    if not key:
        st.warning(
            f"OpenAI features are disabled. Set OPENAI_API_KEY in {ENV_FILE_PATH} via the 'Environment Variables' expander, then reload the app.",
            icon="⚠️",
        )

ENV_FILE_PATH = Path.home() / ".agilab/.env"
try:
    TEMPLATE_ENV_PATH = importlib_resources.files("agi_env") / "resources/.agilab/.env"
except Exception:
    TEMPLATE_ENV_PATH = None


def _normalize_active_app_input(env, raw_value: Optional[str]) -> Path | None:
    """Return a Path to the requested active app if the input is valid."""
    if not raw_value:
        return None

    candidates: list[Path] = []
    try:
        provided = Path(raw_value).expanduser()
    except Exception:
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
    except Exception as exc:
        st.warning(f"Unable to switch to project '{target_name}': {exc}")
        return False
    return True


def _sync_active_app_from_query(env) -> None:
    """Honor ?active_app=… query parameter so all pages stay in sync."""
    try:
        requested = st.query_params.get("active_app")
    except Exception:
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
        except Exception:
            pass

    # Persist the latest active app for reuse on next launch only if it changed via request
    try:
        if changed:
            store_last_active_app(Path(env.apps_path) / env.app)
    except Exception:
        pass

def _ensure_env_file(path: Path) -> Path:
    """Ensure the ~/.agilab/.env file exists without touching mtime on every rerun."""
    try:
        if path.exists():
            return path
    except Exception:
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
            except Exception:
                pass
        path.touch(exist_ok=True)
    except Exception as exc:
        logger.warning(f"Unable to create env file at {path}: {exc}")
    return path

def _refresh_share_dir(env, new_value: str) -> None:
    """Update the in-memory AgiEnv share-path attributes after a UI change."""
    if not new_value:
        return

    share_value = str(new_value)
    share_dir = Path(share_value).expanduser()
    if not share_dir.is_absolute():
        share_dir = Path(env.home_abs).expanduser() / share_dir
    share_dir = share_dir.resolve(strict=False)

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
    except Exception as exc:
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
        submitted = st.form_submit_button("Save and retry", use_container_width=True)

    if submitted:
        new_value = (st.session_state.get(key) or "").strip()
        if not new_value:
            st.warning("AGI_SHARE_DIR cannot be empty.")
        else:
            agi_env_cls.set_env_var("AGI_SHARE_DIR", new_value)
            st.success(f"Saved AGI_SHARE_DIR = {new_value}. Reloading…")
            st.session_state["first_run"] = True
            st.rerun()
    return True

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
                        "value": value,
                        "raw": raw,
                        "commented": stripped.startswith("#"),
                    }
                )
            else:
                entries.append({"type": "comment", "raw": raw})
    return entries

def _write_env_file(path: Path, entries: List[Dict[str, str]], updates: Dict[str, str], new_entry: Dict[str, str] | None) -> None:
    path = _ensure_env_file(path)
    lines: List[str] = []
    processed_keys = set()

    for entry in entries:
        if entry["type"] != "entry":
            lines.append(entry["raw"])
            continue
        key = entry["key"]
        processed_keys.add(key)
        value = updates.get(key, entry["value"])
        lines.append(f"{key}={value}")

    for key, value in updates.items():
        if key not in processed_keys:
            lines.append(f"{key}={value}")
            processed_keys.add(key)

    if new_entry and new_entry.get("key") and new_entry["key"] not in processed_keys:
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
        os.environ[key] = val
        try:
            if env.envars is not None:
                env.envars[key] = val
        except Exception:
            pass
    st.session_state["env_file_mtime_ns"] = current_mtime


def _render_env_editor(env, help_file: Path):
    feedback = st.session_state.pop("env_editor_feedback", None)
    if feedback:
        st.success(feedback)

    st.session_state.setdefault("env_editor_new_key", "")
    st.session_state.setdefault("env_editor_new_value", "")

    entries = _read_env_file(ENV_FILE_PATH)
    existing_entries = [entry for entry in entries if entry["type"] == "entry"]
    seen_keys: set[str] = set()
    existing_values = {entry["key"]: entry["value"].strip() for entry in existing_entries}

    with st.form("env_editor_form"):
        updated_values: Dict[str, str] = {}
        for entry in existing_entries:
            key = entry["key"]
            if key in seen_keys:
                continue
            seen_keys.add(key)
            default_value = entry["value"].strip()
            updated_values[key] = st.text_input(
                key,
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
        for entry in existing_entries:
            key = entry["key"]
            cleaned_updates[key] = st.session_state.get(f"env_editor_val_{key}", "").strip()

        new_entry_data = None
        new_key_clean = new_key.strip()
        if new_key_clean:
            new_value_clean = new_value.strip()
            if new_key_clean in cleaned_updates:
                cleaned_updates[new_key_clean] = new_value_clean
            else:
                new_entry_data = {"key": new_key_clean, "value": new_value_clean}

        try:
            _write_env_file(ENV_FILE_PATH, entries, cleaned_updates, new_entry_data)
            combined_updates = dict(cleaned_updates)
            if new_entry_data:
                combined_updates[new_entry_data["key"]] = new_entry_data["value"]

            for key, value in combined_updates.items():
                os.environ[key] = value
                if hasattr(env, "envars") and isinstance(env.envars, dict):
                    env.envars[key] = value

            new_share = combined_updates.get("AGI_SHARE_DIR")
            if new_share is not None and new_share.strip() and new_share.strip() != existing_values.get("AGI_SHARE_DIR"):
                _refresh_share_dir(env, new_share.strip())

            st.session_state["env_editor_feedback"] = "Environment variables updated."
            st.session_state["env_editor_reset"] = True
            st.rerun()
        except Exception as exc:
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
            current[key.strip()] = val.strip()

        merged = []
        for key in template_keys:
            merged.append(f"{key}={current.get(key, '')}")
        if merged:
            st.code("\n".join(merged))
        else:
            st.caption("No environment variables found in the current .env.")
    except FileNotFoundError:
        st.caption(f"Template or current .env file not found (template: {TEMPLATE_ENV_PATH}, current: {ENV_FILE_PATH}).")
    except Exception as exc:
        st.error(f"Unable to read env files: {exc}")

def page(env):
    """Render the main landing page controls and footer for the lab."""
    cols = st.columns(1)
    help_file = Path(env.help_path) / "index.html"
    from agi_env.pagelib import open_docs, open_local_docs

    with st.expander("Introduction", expanded=True):
        display_landing_page(Path(env.st_resources))

    with st.expander(f"Environment Variables ({ENV_FILE_PATH.expanduser()})", expanded=False):
        _render_env_editor(env, help_file)

    with st.expander("Installed package versions", expanded=False):
        try:
            from importlib import metadata as importlib_metadata
        except Exception:
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
        import subprocess

        st.write(f"OS: {platform.system()} {platform.release()}")
        cpu_name = platform.processor() or platform.machine()
        st.write(f"CPU: {cpu_name}")
        try:
            hw_info = subprocess.check_output(["system_profiler", "SPHardwareDataType"], text=True, timeout=2)
            for line in hw_info.splitlines():
                stripped = line.strip()
                if stripped.startswith("Chip:") or stripped.startswith("Model Identifier:") or stripped.startswith("Memory:"):
                    st.write(stripped)
        except Exception:
            pass

    col_docs_remote, col_docs_local = st.columns(2)
    with col_docs_remote:
        if st.button("Read Documentation", use_container_width=True, type="primary"):
            open_docs(env, help_file, "project-editor")
    with col_docs_local:
        if st.button("Open Local Documentation", use_container_width=True):
            try:
                open_local_docs(env, help_file, "project-editor")
            except FileNotFoundError:
                st.error("Local documentation not found. Regenerate via docs/gen-docs.sh.")

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

def main():
    """Initialise the Streamlit app, bootstrap the environment and display the UI."""
    from agi_env.pagelib import get_about_content
    st.set_page_config(
        menu_items=get_about_content(),
        layout="wide",
    )
    resources_path = Path(__file__).resolve().parent / "resources"
    os.environ.setdefault("STREAMLIT_CONFIG_FILE", str(resources_path / "config.toml"))
    try:
        inject_theme(resources_path)
    except Exception as e:
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
            parser.add_argument("--cluster-ssh-credentials", type=str, help="Cluster credentials (username:password)",
                                default=None)
            parser.add_argument("--openai-api-key", type=str, help="OpenAI API key (optional; can also use OPENAI_API_KEY)", default=None)
            parser.add_argument("--apps-dir", type=str, help="Where you store your apps (default is ./)",
                                default=None)
            parser.add_argument(
                "--active-app",
                type=str,
                help="App name or path to select on startup (mirrors ?active_app= query parameter).",
                default=None,
            )

            args, _ = parser.parse_known_args()
            # Support both old --apps-path and new --apps-dir flags.
            apps_arg = getattr(args, "apps_dir", None)
            if not apps_arg:
                apps_arg = getattr(args, "apps_path", None)

            if apps_arg is None:
                with open(Path("~/").expanduser() / ".local/share/agilab/.agilab-path", "r") as f:
                    agilab_path = f.read()
                    before, sep, after = agilab_path.rpartition(".venv")
                    apps_arg = Path(before) / "apps"

            if apps_arg is None:
                st.error("Error: Missing mandatory parameter: --apps-dir")
                sys.exit(1)

            apps_path = Path(apps_arg).expanduser() if apps_arg else None
            if apps_path is None:
                st.error("Error: Missing mandatory parameter: --apps-dir")
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

            if not st.session_state.get("server_started"):
                activate_mlflow(env)
                st.session_state["server_started"] = True

            try:
                store_last_active_app(Path(env.apps_path) / env.app)
            except Exception:
                pass

            try:
                _refresh_env_from_file(env)
            except Exception:
                pass

            openai_api_key = _clean_openai_key(env.OPENAI_API_KEY if env.OPENAI_API_KEY else args.openai_api_key)
            if not openai_api_key:
                st.warning("OPENAI_API_KEY not set. OpenAI-powered features will be disabled.")

            cluster_credentials = env.CLUSTER_CREDENTIALS if env.CLUSTER_CREDENTIALS else args.cluster_ssh_credentials or ""
            if openai_api_key:
                AgiEnv.set_env_var("OPENAI_API_KEY", openai_api_key)
            AgiEnv.set_env_var("CLUSTER_CREDENTIALS", cluster_credentials)
            AgiEnv.set_env_var("IS_SOURCE_ENV", str(int(bool(env.is_source_env))))
            AgiEnv.set_env_var("IS_WORKER_ENV", str(int(bool(env.is_worker_env))))
            AgiEnv.set_env_var("APPS_PATH", str(apps_path))

            st.session_state["first_run"] = False
            try:
                st.query_params["active_app"] = env.app
            except Exception:
                pass
            st.rerun()
        return  # Don't continue

    # ---- After init, always show banner+intro and then main UI ----
    env = st.session_state['env']
    _refresh_env_from_file(env)
    _sync_active_app_from_query(env)
    try:
        store_last_active_app(Path(env.apps_path) / env.app)
    except Exception:
        pass
    show_banner_and_intro(resources_path)
    openai_status_banner(env)
    # Quick hint for operators: where to check install errors
    page(env)


# ----------------- Run App -----------------
if __name__ == "__main__":
    main()
