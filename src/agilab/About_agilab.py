# BSD 3-Clause License
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
# Co-author: Codex cli
"""Streamlit entry point for the AGILab interactive lab."""
import json
import os
import importlib.util
from pathlib import Path
from typing import Any, Dict, List, Optional
from agi_env.agi_logger import AgiLogger
from agi_env.pagelib_resource_support import about_content_payload as _about_content_payload

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
assert_python_environment_alignment = _import_guard_module.assert_python_environment_alignment
import_agilab_module = _import_guard_module.import_agilab_module

assert_agilab_checkout_alignment(__file__)
assert_python_environment_alignment(__file__)

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
_about_bootstrap = import_agilab_module(
    "agilab.about_page.bootstrap",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "about_page" / "bootstrap.py",
    fallback_name="agilab_about_page_bootstrap_fallback",
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

_pinned_expander_module = import_agilab_module(
    "agilab.pinned_expander",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pinned_expander.py",
    fallback_name="agilab_pinned_expander_fallback",
)
render_pinned_expanders = _pinned_expander_module.render_pinned_expanders

_workflow_ui_module = import_agilab_module(
    "agilab.workflow_ui",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "workflow_ui.py",
    fallback_name="agilab_workflow_ui_fallback",
)
render_page_context = _workflow_ui_module.render_page_context

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

from agi_env.credential_store_support import store_cluster_credentials
from agi_gui.ui_support import detect_agilab_version, read_theme_css, store_last_active_app

FIRST_PROOF_PROJECT = _about_onboarding.FIRST_PROOF_PROJECT
FIRST_PROOF_COMPATIBILITY_SLICE = _about_onboarding.FIRST_PROOF_COMPATIBILITY_SLICE
FIRST_PROOF_HELPER_SCRIPT_PREFIXES = _about_onboarding.FIRST_PROOF_HELPER_SCRIPT_PREFIXES


def get_about_content() -> dict[str, str]:
    """Return Streamlit About-menu content without importing the full pagelib stack."""
    return _about_content_payload()


def inject_theme(base_path: Path | None = None) -> None:
    """Inject AGILAB theme CSS without importing heavy dataframe/runtime helpers."""
    css = read_theme_css(base_path, module_file=__file__)
    if css is not None:
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def _sidebar_version_label(version: str) -> str:
    normalized = str(version or "").strip()
    if normalized.lower().startswith("v"):
        normalized = normalized[1:].strip()
    if not normalized:
        return ""
    return f"AGILAB v{normalized}"


def _sidebar_version_style(version_label: str) -> str:
    content_literal = json.dumps(version_label)
    return (
        "<style>"
        "[data-testid='stSidebarContent'] { padding-bottom: 2.5rem; }"
        "[data-testid='stSidebarContent']::after {"
        f"content: {content_literal};"
        "position: fixed;"
        "left: 1rem;"
        "bottom: 0.75rem;"
        "font-size: 0.8rem;"
        "opacity: 0.72;"
        "z-index: 999;"
        "pointer-events: none;"
        "white-space: nowrap;"
        "}"
        "</style>"
    )


def render_sidebar_version(version: str) -> None:
    """Render the sidebar version without importing the full pagelib stack."""
    version_label = _sidebar_version_label(version)
    if not version_label:
        return
    style_text = _sidebar_version_style(version_label)
    html_fn = getattr(st, "html", None)
    if callable(html_fn):
        html_fn(style_text)
        return
    markdown_fn = getattr(st, "markdown", None)
    if callable(markdown_fn):
        markdown_fn(style_text, unsafe_allow_html=True)
        return
    st.sidebar.caption(version_label)


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


def _first_proof_next_action_model(state: Dict[str, Any]) -> Dict[str, str]:
    """Return first-run microcopy for the next visible user action."""
    return _about_onboarding._first_proof_next_action_model(state)


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
    _about_layout.os = os


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
    """Keep optional OpenAI setup silent on the first-launch path."""
    _sync_layout_module()
    _about_layout.openai_status_banner(env, env_file_path=ENV_FILE_PATH)

ENV_FILE_PATH = _about_env_editor.ENV_FILE_PATH
TEMPLATE_ENV_PATH = _about_env_editor.TEMPLATE_ENV_PATH


def _normalize_active_app_input(env, raw_value: Optional[str]) -> Path | None:
    """Return a Path to the requested active app if the input is valid."""
    return _about_bootstrap.normalize_active_app_input(env, raw_value)


def _apply_active_app_request(env, request_value: Optional[str]) -> bool:
    """Switch AgiEnv to the requested app name/path; returns True if a change occurred."""
    return _about_bootstrap.apply_active_app_request(env, request_value, streamlit=st)


def _sync_active_app_from_query(env) -> None:
    """Honor ?active_app=… query parameter so all pages stay in sync."""
    _about_bootstrap.sync_active_app_from_query(
        env,
        streamlit=st,
        store_last_active_app=store_last_active_app,
        apply_request=_apply_active_app_request,
    )


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

    render_page_docs_access(
        env,
        html_file="agilab-help.html",
        key_prefix="about",
        sidebar=True,
        divider=False,
    )

    try:
        _sync_layout_module()
        _about_layout.render_sidebar_system_information(env)
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        pass
    render_pinned_expanders(st)
    render_page_context(st, page_label="ABOUT", env=env)

    with st.expander(f"Environment Variables ({ENV_FILE_PATH.expanduser()})", expanded=False):
        _render_env_editor(env)

    _sync_layout_module()
    _about_layout.render_footer()
    if "TABLE_MAX_ROWS" not in st.session_state:
        st.session_state["TABLE_MAX_ROWS"] = env.TABLE_MAX_ROWS
    if "GUI_SAMPLING" not in st.session_state:
        st.session_state["GUI_SAMPLING"] = env.GUI_SAMPLING


# ------------------------- Main Entrypoint -------------------------

def main() -> None:
    """Initialise the Streamlit app, bootstrap the environment and display the UI."""
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
    _pre_render_reset()

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
            result = _about_bootstrap.bootstrap_page_environment(
                streamlit=st,
                env_file_path=ENV_FILE_PATH,
                load_env_file_map=_load_env_file_map,
                logger=logger,
                apply_active_app_request=_apply_active_app_request,
                handle_data_root_failure=_handle_data_root_failure,
                refresh_env_from_file=_refresh_env_from_file,
                clean_openai_key=_clean_openai_key,
                store_cluster_credentials=store_cluster_credentials,
            )
            if result.handled_recovery:
                return
            if result.should_rerun:
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
