# BSD 3-Clause License
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
# Co-author: Codex cli
"""Streamlit entry point for the AGILab interactive lab."""
import asyncio
import inspect
import json
import os
import importlib.util
import textwrap
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from agi_env.agi_logger import AgiLogger

logger = AgiLogger.get_logger(__name__)

os.environ.setdefault("STREAMLIT_CONFIG_FILE", str(Path(__file__).resolve().parent / "resources" / "config.toml"))

import streamlit as st
_public_bind_guard_path = Path(__file__).resolve().parent / "ui_public_bind_guard.py"
_public_bind_guard_spec = importlib.util.spec_from_file_location(
    "agilab_ui_public_bind_guard_local",
    _public_bind_guard_path,
)
if _public_bind_guard_spec is None or _public_bind_guard_spec.loader is None:
    raise ModuleNotFoundError(f"Unable to load ui_public_bind_guard.py from {_public_bind_guard_path}")
_public_bind_guard_module = importlib.util.module_from_spec(_public_bind_guard_spec)
_public_bind_guard_spec.loader.exec_module(_public_bind_guard_module)

try:
    from streamlit import config as _streamlit_config

    _public_bind_guard_module.enforce_public_bind_policy(
        os.environ,
        streamlit_config_getter=_streamlit_config.get_option,
    )
except _public_bind_guard_module.PublicBindPolicyError as exc:
    st.error(str(exc))
    st.stop()

_import_guard_path = Path(__file__).resolve().parent / "import_guard.py"
_import_guard_spec = importlib.util.spec_from_file_location("agilab_import_guard_local", _import_guard_path)
if _import_guard_spec is None or _import_guard_spec.loader is None:
    raise ModuleNotFoundError(f"Unable to load import_guard.py from {_import_guard_path}")
_import_guard_module = importlib.util.module_from_spec(_import_guard_spec)
_import_guard_spec.loader.exec_module(_import_guard_module)
assert_agilab_checkout_alignment = _import_guard_module.assert_agilab_checkout_alignment
assert_python_environment_alignment = _import_guard_module.assert_python_environment_alignment
assert_sys_path_checkout_alignment = _import_guard_module.assert_sys_path_checkout_alignment
import_agilab_module = _import_guard_module.import_agilab_module


def _extract_import_guard_rebind_commands(message: str) -> List[tuple[str, str, str]]:
    labels = {
        "macOS/Linux:": ("Rebind command (macOS/Linux)", "bash"),
        "Windows PowerShell:": ("Rebind command (Windows PowerShell)", "powershell"),
    }
    commands: List[tuple[str, str, str]] = []
    lines = message.splitlines()
    index = 0
    while index < len(lines):
        label = labels.get(lines[index].strip())
        if label is None:
            index += 1
            continue
        command_lines: List[str] = []
        index += 1
        while index < len(lines) and lines[index].startswith("   "):
            command_lines.append(lines[index][3:])
            index += 1
        if command_lines:
            caption, language = label
            commands.append((caption, "\n".join(command_lines).strip(), language))

    if commands:
        return commands

    for line in message.splitlines():
        command = line.strip()
        if command.startswith("cd ") and "AGILAB_PYCHARM_ALLOW_SDK_REBIND=1" in command:
            return [("Rebind command", command, "bash")]
    return []


def _format_import_guard_diagnostic_for_display(message: str) -> str:
    """Keep full startup diagnostics readable inside Streamlit code blocks."""
    stripped = message.strip()
    if "\n" in stripped:
        return stripped

    readable = stripped
    for old, new in (
        (". Current file ", ".\nCurrent file "),
        (", but Python ", ",\nbut Python "),
        (". Remove stale ", ".\nRemove stale "),
        (". If you intentionally ", ".\nIf you intentionally "),
        (" The stale entry ", "\nThe stale entry "),
        (". Open/run ", ".\nOpen/run "),
        (". To intentionally ", ".\nTo intentionally "),
    ):
        readable = readable.replace(old, new)

    return "\n".join(
        textwrap.fill(line, width=110, break_long_words=False, break_on_hyphens=False)
        if len(line) > 110 and not line.startswith(("   ", "\t"))
        else line
        for line in readable.splitlines()
    )


def _stop_for_import_guard_error(exc: BaseException) -> None:
    message = str(exc)
    rebind_commands = _extract_import_guard_rebind_commands(message)

    st.error("AGILAB cannot start because PyCharm/Python is bound to another AGILAB checkout.")
    st.markdown(
        "**What happened:** this Streamlit run is using AGILAB code from one checkout "
        "and the Python SDK or import path from another checkout. Stop the current run, "
        "then rebind PyCharm to the checkout you want to launch."
    )
    for caption, command, language in rebind_commands:
        st.caption(caption)
        st.code(command, language=language)
    st.caption("Full diagnostic")
    st.code(_format_import_guard_diagnostic_for_display(message), language="text")
    st.stop()
    raise exc


def _import_agilab_module_or_stop(*args: Any, **kwargs: Any) -> Any:
    try:
        return import_agilab_module(*args, **kwargs)
    except _import_guard_module.MixedCheckoutImportError as exc:
        _stop_for_import_guard_error(exc)


try:
    assert_python_environment_alignment(__file__)
    assert_sys_path_checkout_alignment(__file__)
    assert_agilab_checkout_alignment(__file__)
except _import_guard_module.MixedCheckoutImportError as exc:
    _stop_for_import_guard_error(exc)

_about_env_editor = _import_agilab_module_or_stop(
    "agilab.about_page.env_editor",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "about_page" / "env_editor.py",
    fallback_name="agilab_about_page_env_editor_fallback",
)
_about_layout = _import_agilab_module_or_stop(
    "agilab.about_page.layout",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "about_page" / "layout.py",
    fallback_name="agilab_about_page_layout_fallback",
)
_about_onboarding = _import_agilab_module_or_stop(
    "agilab.about_page.onboarding",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "about_page" / "onboarding.py",
    fallback_name="agilab_about_page_onboarding_fallback",
)
_about_bootstrap = _import_agilab_module_or_stop(
    "agilab.about_page.bootstrap",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "about_page" / "bootstrap.py",
    fallback_name="agilab_about_page_bootstrap_fallback",
)

_env_file_utils_module = _import_agilab_module_or_stop(
    "agilab.env_file_utils",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "env_file_utils.py",
    fallback_name="agilab_env_file_utils_fallback",
)
_load_env_file_map = _env_file_utils_module.load_env_file_map

_runtime_diagnostics_module = _import_agilab_module_or_stop(
    "agilab.runtime_diagnostics",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "runtime_diagnostics.py",
    fallback_name="agilab_runtime_diagnostics_fallback",
)
GLOBAL_DIAGNOSTICS_ENV_KEY = _runtime_diagnostics_module.GLOBAL_DIAGNOSTICS_ENV_KEY
diagnostics_widget_key = _runtime_diagnostics_module.diagnostics_widget_key
global_diagnostics_verbose = _runtime_diagnostics_module.global_diagnostics_verbose
render_runtime_diagnostics_control = _runtime_diagnostics_module.render_runtime_diagnostics_control

_page_docs_module = _import_agilab_module_or_stop(
    "agilab.page_docs",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "page_docs.py",
    fallback_name="agilab_page_docs_fallback",
)
get_docs_menu_items = _page_docs_module.get_docs_menu_items
docs_menu_url = _page_docs_module.docs_menu_url

_pinned_expander_module = _import_agilab_module_or_stop(
    "agilab.pinned_expander",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pinned_expander.py",
    fallback_name="agilab_pinned_expander_fallback",
)
render_pinned_expanders = _pinned_expander_module.render_pinned_expanders

_workflow_ui_module = _import_agilab_module_or_stop(
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
from agi_gui.ux_widgets import compact_choice

FIRST_PROOF_PROJECT = _about_onboarding.FIRST_PROOF_PROJECT
FIRST_PROOF_COMPATIBILITY_SLICE = _about_onboarding.FIRST_PROOF_COMPATIBILITY_SLICE
FIRST_PROOF_HELPER_SCRIPT_PREFIXES = _about_onboarding.FIRST_PROOF_HELPER_SCRIPT_PREFIXES
_NAVIGATION_PAGE_ROUTES: Dict[str, Any] = {}


def get_about_content() -> dict[str, str]:
    """Return Streamlit About-menu content without importing the full pagelib stack."""
    return get_docs_menu_items(html_file="agilab-help.html")


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


def render_sidebar_documentation_link() -> None:
    """Keep the Main Page sidebar useful without mixing in execution state."""
    docs_url = docs_menu_url("agilab-help.html")
    markdown_fn = getattr(st.sidebar, "markdown", None)
    if callable(markdown_fn):
        markdown_fn(f"[Documentation]({docs_url})")
        return
    caption_fn = getattr(st.sidebar, "caption", None)
    if callable(caption_fn):
        caption_fn(f"Documentation: {docs_url}")


def _sync_onboarding_module() -> None:
    """Mirror main-page compatibility globals into onboarding helpers."""
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
        page_routes=_NAVIGATION_PAGE_ROUTES,
    )


def _sync_layout_module() -> None:
    """Mirror main-page compatibility globals into display helpers."""
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
    """Mirror main-page compatibility globals into the extracted env editor."""
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


def _global_runtime_diagnostics_verbose(env: Any) -> int:
    return global_diagnostics_verbose(
        session_state=st.session_state,
        envars=getattr(env, "envars", None),
        environ=os.environ,
        default=1,
    )


def _store_global_runtime_diagnostics_verbose(env: Any, verbose: int) -> None:
    value = str(verbose)
    _upsert_env_var(ENV_FILE_PATH, GLOBAL_DIAGNOSTICS_ENV_KEY, value)
    os.environ[GLOBAL_DIAGNOSTICS_ENV_KEY] = value
    if hasattr(env, "envars") and isinstance(env.envars, dict):
        env.envars[GLOBAL_DIAGNOSTICS_ENV_KEY] = value
    st.session_state[GLOBAL_DIAGNOSTICS_ENV_KEY] = value
    st.session_state["cluster_verbose"] = verbose


def _render_global_runtime_diagnostics(env: Any) -> None:
    current_verbose = _global_runtime_diagnostics_verbose(env)
    settings: Dict[str, Any] = {"cluster": {"verbose": current_verbose}}
    with st.expander("Runtime diagnostics", expanded=False) as diagnostics_container:
        diagnostics_container.caption(
            "Global log detail reused by ORCHESTRATE, WORKFLOW, generated snippets, and CLI runs."
        )
        selected_verbose = render_runtime_diagnostics_control(
            st,
            diagnostics_container,
            settings,
            app_name="global",
            compact_choice_fn=compact_choice,
            key=diagnostics_widget_key("global"),
        )
    if selected_verbose != current_verbose:
        _store_global_runtime_diagnostics_verbose(env, selected_verbose)
    else:
        st.session_state["cluster_verbose"] = selected_verbose


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
    render_sidebar_documentation_link()
    render_pinned_expanders(st)
    render_page_context(st, page_label="MAIN_PAGE", env=env)

    with st.expander(f"Environment Variables ({ENV_FILE_PATH.expanduser()})", expanded=False):
        _render_env_editor(env)

    _render_global_runtime_diagnostics(env)

    _sync_layout_module()
    _about_layout.render_footer()
    if "TABLE_MAX_ROWS" not in st.session_state:
        st.session_state["TABLE_MAX_ROWS"] = env.TABLE_MAX_ROWS
    if "GUI_SAMPLING" not in st.session_state:
        st.session_state["GUI_SAMPLING"] = env.GUI_SAMPLING


def _about_resources_path() -> Path:
    return Path(__file__).resolve().parent / "resources"


def _ensure_navigation_environment(resources_path: Path, *, rerun_after_bootstrap: bool) -> Any | None:
    """Bootstrap AGILAB once before a navigation page renders project-specific UI."""
    os.environ.setdefault("STREAMLIT_CONFIG_FILE", str(resources_path / "config.toml"))
    st.session_state.setdefault("first_run", True)
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
                return None
            if result.should_rerun or rerun_after_bootstrap:
                st.rerun()
                return None

    env = st.session_state['env']
    _refresh_env_from_file(env)
    _sync_active_app_from_query(env)
    try:
        store_last_active_app(_about_bootstrap.active_app_store_path(env))
    except (OSError, RuntimeError, TypeError, ValueError):
        pass
    return env


# ------------------------- Main Entrypoint -------------------------

def _render_about_page_entry() -> None:
    """Initialise the main page and display the landing UI."""
    st.set_page_config(
        page_title="AGILab",
        menu_items=get_about_content(),
        layout="wide",
    )
    resources_path = _about_resources_path()
    try:
        inject_theme(resources_path)
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as e:
        # Non-fatal: UI will still load without custom theme
        st.warning(f"Theme injection skipped: {e}")
    _pre_render_reset()

    # Always set background style
    st.markdown(
        """<style>
        body { background: #f6f8fa !important; }
        </style>""",
        unsafe_allow_html=True
    )

    env = _ensure_navigation_environment(resources_path, rerun_after_bootstrap=False)
    if env is None:
        return
    show_banner_and_intro(resources_path, env)
    openai_status_banner(env)
    # Quick hint for operators: where to check install errors
    page(env)


def _navigation_pages() -> list[Any]:
    """Return the supported visible pages while keeping the main page hidden from the page list."""
    root = Path(__file__).resolve().parent
    pages_root = root / "pages"
    main_page = st.Page(
        _render_about_page_entry,
        title="Main Page",
        url_path="",
        default=True,
        visibility="hidden",
    )
    project_page = st.Page(
        pages_root / "1_PROJECT.py",
        title="PROJECT",
        url_path="PROJECT",
        visibility="hidden",
    )
    orchestrate_page = st.Page(
        _page_file_runner(pages_root / "2_ORCHESTRATE.py"),
        title="ORCHESTRATE",
        url_path="ORCHESTRATE",
    )
    workflow_page = st.Page(
        _page_file_runner(pages_root / "3_WORKFLOW.py"),
        title="WORKFLOW",
        url_path="WORKFLOW",
    )
    analysis_page = st.Page(
        _page_file_runner(pages_root / "4_ANALYSIS.py"),
        title="ANALYSIS",
        url_path="ANALYSIS",
    )
    _NAVIGATION_PAGE_ROUTES.clear()
    _NAVIGATION_PAGE_ROUTES.update(
        {
            "project": project_page,
            "orchestrate": orchestrate_page,
            "workflow": workflow_page,
            "analysis": analysis_page,
        }
    )
    return [main_page, project_page, orchestrate_page, workflow_page, analysis_page]


def _page_file_runner(page_file: Path) -> Callable[[], None]:
    """Run a guarded Streamlit page file through ``st.Page`` without changing the page contract."""

    def _run_page() -> None:
        if _ensure_navigation_environment(_about_resources_path(), rerun_after_bootstrap=True) is None:
            return
        module_name = f"_agilab_streamlit_page_{abs(hash(page_file.resolve()))}"
        spec = importlib.util.spec_from_file_location(module_name, page_file)
        if spec is None or spec.loader is None:
            raise ModuleNotFoundError(f"Unable to load page from {page_file}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        main_fn = getattr(module, "main", None)
        if main_fn is None:
            raise AttributeError(f"Page {page_file} does not expose a main() function")
        if inspect.iscoroutinefunction(main_fn):
            asyncio.run(main_fn())
        else:
            main_fn()

    _run_page.__name__ = f"run_{page_file.stem}"
    return _run_page


def main() -> None:
    """Initialise AGILAB navigation and run the selected Streamlit page."""
    st.navigation(_navigation_pages()).run()


# ----------------- Run App -----------------
if __name__ == "__main__":
    main()
