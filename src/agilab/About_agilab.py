# BSD 3-Clause License
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
# Co-author: Codex cli
"""Streamlit entry point for the AGILab interactive lab."""
import os
import sys
import argparse
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
import_agilab_module = _import_guard_module.import_agilab_module

assert_agilab_checkout_alignment(__file__)

_about_env_editor = import_agilab_module(
    "agilab.about_page.env_editor",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "about_page" / "env_editor.py",
    fallback_name="agilab_about_page_env_editor_fallback",
)
_about_layout = import_agilab_module(
    "agilab.about_page.layout",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "about_page" / "layout.py",
    fallback_name="agilab_about_page_layout_fallback",
)
_about_onboarding = import_agilab_module(
    "agilab.about_page.onboarding",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "about_page" / "onboarding.py",
    fallback_name="agilab_about_page_onboarding_fallback",
)

_env_file_utils_module = import_agilab_module(
    "agilab.env_file_utils",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "env_file_utils.py",
    fallback_name="agilab_env_file_utils_fallback",
)
_load_env_file_map = _env_file_utils_module.load_env_file_map

_page_docs_module = import_agilab_module(
    "agilab.page_docs",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "page_docs.py",
    fallback_name="agilab_page_docs_fallback",
)
render_page_docs_access = _page_docs_module.render_page_docs_access

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

from agi_gui.pagelib import background_services_enabled, inject_theme, render_sidebar_version
from agi_env.credential_store_support import (
    CLUSTER_CREDENTIALS_KEY,
    KEYRING_SENTINEL,
    store_cluster_credentials,
)
from agi_gui.ui_support import detect_agilab_version, load_last_active_app, store_last_active_app

FIRST_PROOF_PROJECT = _about_onboarding.FIRST_PROOF_PROJECT
FIRST_PROOF_COMPATIBILITY_SLICE = _about_onboarding.FIRST_PROOF_COMPATIBILITY_SLICE
FIRST_PROOF_HELPER_SCRIPT_PREFIXES = _about_onboarding.FIRST_PROOF_HELPER_SCRIPT_PREFIXES


def _sync_onboarding_module() -> None:
    """Mirror About-page compatibility globals into onboarding helpers."""
    _about_onboarding.st = st


def _newcomer_first_proof_content() -> Dict[str, Any]:
    """Return the first-proof onboarding contract shown on the landing page."""
    return _about_onboarding._newcomer_first_proof_content()


def _newcomer_first_proof_project_path(env: Any) -> Path | None:
    """Return the preferred built-in first-proof app path when available."""
    return _about_onboarding._newcomer_first_proof_project_path(env)


def _first_proof_output_dir(env: Any) -> Path:
    """Return the log directory used by the built-in first-proof route."""
    return _about_onboarding._first_proof_output_dir(env)


def _list_first_proof_outputs(output_dir: Path) -> list[Path]:
    """Return evidence-like outputs, excluding seeded AGI helper scripts."""
    return _about_onboarding._list_first_proof_outputs(output_dir)


def _newcomer_first_proof_state(env: Any) -> Dict[str, Any]:
    """Return concrete wizard state for the in-product first-proof path."""
    return _about_onboarding._newcomer_first_proof_state(env)


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


def _first_proof_progress_rows(state: Dict[str, Any]) -> List[Dict[str, str]]:
    """Return compact first-proof progress rows for the onboarding card."""
    return _about_onboarding._first_proof_progress_rows(state)


def _first_proof_progress_markdown(rows: List[Dict[str, str]]) -> str:
    """Render progress rows as a small Markdown table."""
    return _about_onboarding._first_proof_progress_markdown(rows)


def _render_first_proof_next_action(env: Any, state: Dict[str, Any]) -> None:
    """Render the primary next action before diagnostics."""
    _sync_onboarding_module()
    _about_onboarding._render_first_proof_next_action(
        env,
        state,
        _activate_newcomer_first_proof_project,
    )


def render_newcomer_first_proof(env: Any | None = None) -> None:
    """Render the first-proof onboarding surface."""
    _sync_onboarding_module()
    _about_onboarding.render_newcomer_first_proof(
        env,
        activate_project=_activate_newcomer_first_proof_project,
        display_landing_page=display_landing_page,
    )


def _sync_layout_module() -> None:
    """Mirror About-page compatibility globals into display helpers."""
    _about_layout.st = st


def quick_logo(resources_path: Path) -> None:
    """Render a lightweight banner with the AGILab logo."""
    _sync_layout_module()
    _about_layout.quick_logo(resources_path)


def _landing_page_sections() -> Dict[str, Any]:
    """Return compact secondary guidance shown under the first-step path."""
    return _about_layout.landing_page_sections()


def display_landing_page(resources_path: Path) -> None:
    """Display compact secondary context under the first-step instructions."""
    _sync_layout_module()
    _about_layout.display_landing_page(resources_path)


def show_banner_and_intro(resources_path: Path, env: Any | None = None) -> None:
    """Render the branding banner."""
    quick_logo(resources_path)
    render_newcomer_first_proof(env)


def _clean_openai_key(key: str | None) -> str | None:
    """Return None for missing/placeholder keys to avoid confusing 401s."""
    return _about_layout.clean_openai_key(key)


def openai_status_banner(env: Any) -> None:
    """Show a non-blocking banner if OpenAI features are unavailable and direct users to the env editor."""
    _sync_layout_module()
    _about_layout.openai_status_banner(env, env_file_path=ENV_FILE_PATH)

ENV_FILE_PATH = _about_env_editor.ENV_FILE_PATH
TEMPLATE_ENV_PATH = _about_env_editor.TEMPLATE_ENV_PATH


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


def _sync_env_editor_module() -> None:
    """Mirror About-page compatibility globals into the extracted env editor."""
    _about_env_editor.st = st
    _about_env_editor.logger = logger
    _about_env_editor.ENV_FILE_PATH = ENV_FILE_PATH
    _about_env_editor.TEMPLATE_ENV_PATH = TEMPLATE_ENV_PATH
    _about_env_editor._load_env_file_map = _load_env_file_map


def _ensure_env_file(path: Path) -> Path:
    _sync_env_editor_module()
    return _about_env_editor._ensure_env_file(path)


def _resolve_share_dir_path(raw_value: str, *, home_path: Path) -> Path:
    return _about_env_editor._resolve_share_dir_path(raw_value, home_path=home_path)


def _refresh_share_dir(env: Any, new_value: str) -> None:
    _sync_env_editor_module()
    _about_env_editor._refresh_share_dir(env, new_value)


def _handle_data_root_failure(exc: Exception, *, agi_env_cls: Any) -> bool:
    _sync_env_editor_module()
    return _about_env_editor._handle_data_root_failure(exc, agi_env_cls=agi_env_cls)


def _strip_dotenv_quotes(value: str) -> str:
    return _about_env_editor._strip_dotenv_quotes(value)


def _read_env_file(path: Path) -> List[Dict[str, str]]:
    _sync_env_editor_module()
    return _about_env_editor._read_env_file(path)


def _is_worker_python_override_key(key: str) -> bool:
    return _about_env_editor._is_worker_python_override_key(key)


def _worker_python_override_host(key: str) -> str:
    return _about_env_editor._worker_python_override_host(key)


def _env_editor_field_label(key: str) -> str:
    return _about_env_editor._env_editor_field_label(key)


def _visible_env_editor_keys(
    template_keys: List[str],
    existing_entries: List[Dict[str, str]],
) -> List[str]:
    return _about_env_editor._visible_env_editor_keys(template_keys, existing_entries)


def _write_env_file(
    path: Path,
    entries: List[Dict[str, str]],
    updates: Dict[str, str],
    new_entry: Dict[str, str] | None,
) -> None:
    _sync_env_editor_module()
    _about_env_editor._write_env_file(path, entries, updates, new_entry)


def _upsert_env_var(path: Path, key: str, value: str) -> None:
    _sync_env_editor_module()
    _about_env_editor._upsert_env_var(path, key, value)


def _refresh_env_from_file(env: Any) -> None:
    _sync_env_editor_module()
    _about_env_editor._refresh_env_from_file(env)


def _render_env_editor(env: Any, help_file: Path | None = None) -> None:
    _sync_env_editor_module()
    _about_env_editor._render_env_editor(env, help_file)

def page(env: Any) -> None:
    """Render the main landing page controls and footer for the lab."""
    try:
        render_sidebar_version(detect_agilab_version(env))
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        pass

    with st.expander(f"Environment Variables ({ENV_FILE_PATH.expanduser()})", expanded=False):
        _render_env_editor(env)

    with st.expander("Installed package versions", expanded=False):
        _sync_layout_module()
        _about_layout.render_package_versions()

    with st.expander("System information", expanded=False):
        _sync_layout_module()
        _about_layout.render_system_information()

    render_page_docs_access(
        env,
        html_file="agilab-help.html",
        key_prefix="about",
        sidebar=True,
        divider=False,
    )

    _sync_layout_module()
    _about_layout.render_footer()
    if "TABLE_MAX_ROWS" not in st.session_state:
        st.session_state["TABLE_MAX_ROWS"] = env.TABLE_MAX_ROWS
    if "GUI_SAMPLING" not in st.session_state:
        st.session_state["GUI_SAMPLING"] = env.GUI_SAMPLING


# ------------------------- Main Entrypoint -------------------------

def main() -> None:
    """Initialise the Streamlit app, bootstrap the environment and display the UI."""
    from agi_gui.pagelib import get_about_content
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
            from agi_gui.pagelib import activate_mlflow
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
