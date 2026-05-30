# BSD 3-Clause License
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
# Co-author: Codex cli
"""Streamlit entry point for the AGILab interactive lab."""

import asyncio
import html
import inspect
import json
import os
import importlib
import importlib.resources as importlib_resources
import importlib.util
import textwrap
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlencode
from agi_env.agi_logger import AgiLogger

try:
    from agilab.ui_performance import (
        UI_TIMING_SESSION_KEY,
        UI_TIMING_TRACE_ENV_KEY,
        record_ui_timing_span,
        ui_timing_trace_enabled,
    )
except ModuleNotFoundError as exc:
    if getattr(exc, "name", "") not in {"agilab", "agilab.ui_performance"}:
        raise
    _ui_performance_path = Path(__file__).resolve().parent / "ui_performance.py"
    _ui_performance_spec = importlib.util.spec_from_file_location(
        "agilab_ui_performance_local",
        _ui_performance_path,
    )
    if _ui_performance_spec is None or _ui_performance_spec.loader is None:
        raise ModuleNotFoundError(
            f"Unable to load ui_performance.py from {_ui_performance_path}"
        ) from exc
    _ui_performance_module = importlib.util.module_from_spec(_ui_performance_spec)
    sys.modules[_ui_performance_spec.name] = _ui_performance_module
    _ui_performance_spec.loader.exec_module(_ui_performance_module)
    UI_TIMING_SESSION_KEY = _ui_performance_module.UI_TIMING_SESSION_KEY
    UI_TIMING_TRACE_ENV_KEY = _ui_performance_module.UI_TIMING_TRACE_ENV_KEY
    record_ui_timing_span = _ui_performance_module.record_ui_timing_span
    ui_timing_trace_enabled = _ui_performance_module.ui_timing_trace_enabled

try:
    from agilab.streamlit_theme_env import (
        apply_streamlit_theme_environment,
        packaged_streamlit_config_path,
    )
except ModuleNotFoundError:
    _streamlit_theme_env_path = (
        Path(__file__).resolve().parent / "streamlit_theme_env.py"
    )
    _streamlit_theme_env_spec = importlib.util.spec_from_file_location(
        "agilab_streamlit_theme_env_local",
        _streamlit_theme_env_path,
    )
    if _streamlit_theme_env_spec is None or _streamlit_theme_env_spec.loader is None:
        raise ModuleNotFoundError(
            f"Unable to load streamlit_theme_env.py from {_streamlit_theme_env_path}"
        )
    _streamlit_theme_env_module = importlib.util.module_from_spec(
        _streamlit_theme_env_spec
    )
    _streamlit_theme_env_spec.loader.exec_module(_streamlit_theme_env_module)
    apply_streamlit_theme_environment = (
        _streamlit_theme_env_module.apply_streamlit_theme_environment
    )
    packaged_streamlit_config_path = (
        _streamlit_theme_env_module.packaged_streamlit_config_path
    )

logger = AgiLogger.get_logger(__name__)

apply_streamlit_theme_environment(packaged_streamlit_config_path(__file__))

import streamlit as st

_public_bind_guard_path = Path(__file__).resolve().parent / "ui_public_bind_guard.py"
_public_bind_guard_spec = importlib.util.spec_from_file_location(
    "agilab_ui_public_bind_guard_local",
    _public_bind_guard_path,
)
if _public_bind_guard_spec is None or _public_bind_guard_spec.loader is None:
    raise ModuleNotFoundError(
        f"Unable to load ui_public_bind_guard.py from {_public_bind_guard_path}"
    )
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
_import_guard_spec = importlib.util.spec_from_file_location(
    "agilab_import_guard_local", _import_guard_path
)
if _import_guard_spec is None or _import_guard_spec.loader is None:
    raise ModuleNotFoundError(
        f"Unable to load import_guard.py from {_import_guard_path}"
    )
_import_guard_module = importlib.util.module_from_spec(_import_guard_spec)
_import_guard_spec.loader.exec_module(_import_guard_module)
assert_agilab_checkout_alignment = _import_guard_module.assert_agilab_checkout_alignment
assert_python_environment_alignment = (
    _import_guard_module.assert_python_environment_alignment
)
assert_sys_path_checkout_alignment = (
    _import_guard_module.assert_sys_path_checkout_alignment
)
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

    st.error(
        "AGILAB cannot start because PyCharm/Python is bound to another AGILAB checkout."
    )
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

_AGILAB_ROOT = Path(__file__).resolve().parent


class _LazyAgilabModule:
    """Import heavier page helper modules only when their attributes are used."""

    def __init__(
        self, module_name: str, *, fallback_path: Path, fallback_name: str
    ) -> None:
        object.__setattr__(self, "_lazy_module_name", module_name)
        object.__setattr__(self, "_lazy_fallback_path", fallback_path)
        object.__setattr__(self, "_lazy_fallback_name", fallback_name)
        object.__setattr__(self, "_lazy_module", None)

    def _load(self) -> Any:
        module = object.__getattribute__(self, "_lazy_module")
        if module is None:
            module = _import_agilab_module_or_stop(
                object.__getattribute__(self, "_lazy_module_name"),
                current_file=__file__,
                fallback_path=object.__getattribute__(self, "_lazy_fallback_path"),
                fallback_name=object.__getattribute__(self, "_lazy_fallback_name"),
            )
            object.__setattr__(self, "_lazy_module", module)
        return module

    def __getattr__(self, name: str) -> Any:
        return getattr(self._load(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_lazy_"):
            object.__setattr__(self, name, value)
            return
        setattr(self._load(), name, value)

    def __delattr__(self, name: str) -> None:
        if name.startswith("_lazy_"):
            object.__delattr__(self, name)
            return
        delattr(self._load(), name)

    def __repr__(self) -> str:
        module_name = object.__getattribute__(self, "_lazy_module_name")
        loaded = object.__getattribute__(self, "_lazy_module") is not None
        return f"<_LazyAgilabModule {module_name!r} loaded={loaded}>"


_about_env_editor = _LazyAgilabModule(
    "agilab.about_page.env_editor",
    fallback_path=_AGILAB_ROOT / "about_page" / "env_editor.py",
    fallback_name="agilab_about_page_env_editor_fallback",
)
_about_layout = _LazyAgilabModule(
    "agilab.about_page.layout",
    fallback_path=_AGILAB_ROOT / "about_page" / "layout.py",
    fallback_name="agilab_about_page_layout_fallback",
)
_about_onboarding = _LazyAgilabModule(
    "agilab.about_page.onboarding",
    fallback_path=_AGILAB_ROOT / "about_page" / "onboarding.py",
    fallback_name="agilab_about_page_onboarding_fallback",
)
_about_bootstrap = _LazyAgilabModule(
    "agilab.about_page.bootstrap",
    fallback_path=_AGILAB_ROOT / "about_page" / "bootstrap.py",
    fallback_name="agilab_about_page_bootstrap_fallback",
)
_env_file_utils_module = _LazyAgilabModule(
    "agilab.env_file_utils",
    fallback_path=_AGILAB_ROOT / "env_file_utils.py",
    fallback_name="agilab_env_file_utils_fallback",
)
_runtime_diagnostics_module = _LazyAgilabModule(
    "agilab.runtime_diagnostics",
    fallback_path=_AGILAB_ROOT / "runtime_diagnostics.py",
    fallback_name="agilab_runtime_diagnostics_fallback",
)
GLOBAL_DIAGNOSTICS_ENV_KEY = "AGILAB_RUNTIME_DIAGNOSTICS_VERBOSE"


def _load_env_file_map(*args: Any, **kwargs: Any) -> Any:
    return _env_file_utils_module.load_env_file_map(*args, **kwargs)


def diagnostics_widget_key(*args: Any, **kwargs: Any) -> str:
    return _runtime_diagnostics_module.diagnostics_widget_key(*args, **kwargs)


def global_diagnostics_verbose(*args: Any, **kwargs: Any) -> int:
    return _runtime_diagnostics_module.global_diagnostics_verbose(*args, **kwargs)


def render_runtime_diagnostics_control(*args: Any, **kwargs: Any) -> int:
    return _runtime_diagnostics_module.render_runtime_diagnostics_control(
        *args, **kwargs
    )


_page_docs_module = _import_agilab_module_or_stop(
    "agilab.page_docs",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "page_docs.py",
    fallback_name="agilab_page_docs_fallback",
)
get_docs_menu_items = _page_docs_module.get_docs_menu_items
docs_menu_url = _page_docs_module.docs_menu_url

_pinned_expander_module = _LazyAgilabModule(
    "agilab.pinned_expander",
    fallback_path=_AGILAB_ROOT / "pinned_expander.py",
    fallback_name="agilab_pinned_expander_fallback",
)


def render_pinned_expanders(*args: Any, **kwargs: Any) -> Any:
    return _pinned_expander_module.render_pinned_expanders(*args, **kwargs)


_workflow_ui_module = _LazyAgilabModule(
    "agilab.workflow_ui",
    fallback_path=_AGILAB_ROOT / "workflow_ui.py",
    fallback_name="agilab_workflow_ui_fallback",
)


def render_page_context(*args: Any, **kwargs: Any) -> Any:
    return _workflow_ui_module.render_page_context(*args, **kwargs)


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

_LAZY_IMPORT_ATTR_CACHE: Dict[tuple[str, str], Any] = {}


def _lazy_import_attr(module_name: str, attr_name: str) -> Any:
    cache_key = (module_name, attr_name)
    if cache_key not in _LAZY_IMPORT_ATTR_CACHE:
        _LAZY_IMPORT_ATTR_CACHE[cache_key] = getattr(
            importlib.import_module(module_name), attr_name
        )
    return _LAZY_IMPORT_ATTR_CACHE[cache_key]


def store_cluster_credentials(*args: Any, **kwargs: Any) -> Any:
    return _lazy_import_attr(
        "agi_env.credential_store_support", "store_cluster_credentials"
    )(*args, **kwargs)


def detect_agilab_version(*args: Any, **kwargs: Any) -> str:
    return _lazy_import_attr("agi_gui.ui_support", "detect_agilab_version")(
        *args, **kwargs
    )


def read_theme_css(*args: Any, **kwargs: Any) -> Any:
    return _lazy_import_attr("agi_gui.ui_support", "read_theme_css")(*args, **kwargs)


def store_last_active_app(*args: Any, **kwargs: Any) -> Any:
    return _lazy_import_attr("agi_gui.ui_support", "store_last_active_app")(
        *args, **kwargs
    )


def compact_choice(*args: Any, **kwargs: Any) -> Any:
    return _lazy_import_attr("agi_gui.ux_widgets", "compact_choice")(*args, **kwargs)


FIRST_PROOF_PROJECT = "flight_telemetry_project"
FIRST_PROOF_COMPATIBILITY_SLICE = "Source checkout first proof"
FIRST_PROOF_HELPER_SCRIPT_PREFIXES = (
    "AGI_install_",
    "AGI_run_",
    "AGI_get_",
)
_NAVIGATION_PAGE_ROUTES: Dict[str, Any] = {}
_PAGE_MODULE_CACHE: Dict[Path, tuple[int, int, str, Any]] = {}
PAGE_LOAD_TIMING_ENV_KEY = "AGILAB_PAGE_LOAD_TIMING"


def _page_load_timing_enabled(environ: Any = os.environ) -> bool:
    value = str(environ.get(PAGE_LOAD_TIMING_ENV_KEY, "")).strip().lower()
    return value in {"1", "true", "yes", "on", "debug"}


def _render_page_load_timing(
    page_label: str,
    started_at: float,
    *,
    streamlit: Any = st,
    perf_counter: Callable[[], float] = time.perf_counter,
) -> None:
    """Render opt-in page load timing without adding default UI noise."""
    elapsed_ms = max(0.0, (perf_counter() - started_at) * 1000.0)
    if ui_timing_trace_enabled():
        _record_ui_timing_span(
            page_label,
            started_at,
            category="page",
            streamlit=streamlit,
            perf_counter=perf_counter,
        )
        _render_ui_timing_trace(streamlit=streamlit)
    if not _page_load_timing_enabled():
        return
    try:
        streamlit.sidebar.caption(f"{page_label} loaded in {elapsed_ms:.0f} ms")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        logger.info("%s loaded in %.0f ms", page_label, elapsed_ms)


def _record_ui_timing_span(
    label: str,
    started_at: float,
    *,
    category: str,
    streamlit: Any = st,
    perf_counter: Callable[[], float] = time.perf_counter,
) -> None:
    if not ui_timing_trace_enabled():
        return
    record_ui_timing_span(
        getattr(streamlit, "session_state", {}),
        label=label,
        started_at=started_at,
        category=category,
        perf_counter=perf_counter,
    )


def _render_ui_timing_trace(*, streamlit: Any = st, max_spans: int = 6) -> None:
    if not ui_timing_trace_enabled():
        return
    try:
        spans = list(streamlit.session_state.get(UI_TIMING_SESSION_KEY, ()))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return
    if not spans:
        return
    lines = []
    for span in spans[-max(1, max_spans) :]:
        try:
            label = str(span.get("label", ""))
            category = str(span.get("category", ""))
            elapsed_ms = float(span.get("elapsed_ms", "0") or 0.0)
        except (AttributeError, TypeError, ValueError):
            continue
        lines.append(f"{label} [{category}] {elapsed_ms:.0f} ms")
    if not lines:
        return
    try:
        streamlit.sidebar.caption("UI trace: " + " | ".join(lines))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        logger.info("UI trace: %s", " | ".join(lines))


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


def _active_app_readme_path(env: Any | None) -> Path | None:
    """Return the current app README path when the active project exposes one."""
    if env is None:
        return None

    candidates: list[Path] = []
    active_app = getattr(env, "active_app", None)
    if active_app not in (None, ""):
        try:
            candidates.append(Path(active_app).expanduser())
        except (OSError, RuntimeError, TypeError, ValueError):
            pass

    app_name = str(getattr(env, "app", "") or "").strip()
    apps_path = getattr(env, "apps_path", None)
    if app_name and apps_path not in (None, ""):
        try:
            apps_root = Path(apps_path).expanduser()
            candidates.extend([apps_root / app_name, apps_root / "builtin" / app_name])
        except (OSError, RuntimeError, TypeError, ValueError):
            pass

    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=False)
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        readme_path = resolved / "README.md"
        if readme_path.is_file():
            return readme_path
    return None


def _sidebar_readme_url(env: Any | None, readme_path: Path) -> str:
    return f"/PROJECT?{urlencode(_sidebar_readme_query_params(env, readme_path))}"


def _sidebar_readme_query_params(env: Any | None, readme_path: Path) -> dict[str, str]:
    app_name = str(getattr(env, "app", "") or readme_path.parent.name).strip()
    return {
        "active_app": app_name,
        "sidebar_selection": "Edit",
        "project_section": "readme",
    }


def _reset_project_readme_query_seed() -> None:
    """Allow the PROJECT README shortcut to work again after returning home."""
    try:
        st.session_state.pop("_project_section_query_seed_consumed", None)
        st.session_state.pop("_project_section_query_target", None)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass


def _sidebar_readme_link_markdown(env: Any | None, readme_path: Path) -> str:
    readme_url = html.escape(_sidebar_readme_url(env, readme_path), quote=True)
    return (
        f'<a href="{readme_url}" target="_self" title="Open the active project README in PROJECT.">'
        "README"
        "</a>"
    )


def _render_sidebar_readme_link(env: Any | None, readme_path: Path) -> bool:
    markdown_fn = getattr(st.sidebar, "markdown", None)
    if callable(markdown_fn):
        _reset_project_readme_query_seed()
        markdown_fn(
            _sidebar_readme_link_markdown(env, readme_path), unsafe_allow_html=True
        )
        return True

    query_params = _sidebar_readme_query_params(env, readme_path)
    switch_page_fn = getattr(st, "switch_page", None)
    button_fn = getattr(st.sidebar, "button", None)
    project_page = _NAVIGATION_PAGE_ROUTES.get("project")
    if callable(button_fn) and callable(switch_page_fn) and project_page is not None:
        _reset_project_readme_query_seed()
        if button_fn(
            "README",
            help="Open the active project README in PROJECT.",
            width="stretch",
        ):
            switch_page_fn(project_page, query_params=query_params)
        return True

    page_link_fn = getattr(st.sidebar, "page_link", None)
    if callable(page_link_fn) and project_page is not None:
        _reset_project_readme_query_seed()
        page_link_fn(
            project_page,
            label="README",
            query_params=query_params,
            help="Open the active project README in PROJECT.",
        )
        return True

    caption_fn = getattr(st.sidebar, "caption", None)
    if callable(caption_fn):
        _reset_project_readme_query_seed()
        caption_fn(f"README: {_sidebar_readme_url(env, readme_path)}")
        return True
    return False


def render_sidebar_settings_link(env: Any | None = None) -> None:
    """Keep persistent runtime controls and docs reachable from the sidebar."""
    settings_url = "/SETTINGS"
    docs_url = docs_menu_url("agilab-help.html")
    readme_path = _active_app_readme_path(env)
    markdown_fn = getattr(st.sidebar, "markdown", None)
    if callable(markdown_fn):
        markdown_fn(f"[Settings]({settings_url})")
        if readme_path is not None:
            _render_sidebar_readme_link(env, readme_path)
        markdown_fn(f"[Documentation]({docs_url})")
        return
    caption_fn = getattr(st.sidebar, "caption", None)
    if callable(caption_fn):
        caption_fn(f"Settings: {settings_url}")
        if readme_path is not None:
            _render_sidebar_readme_link(env, readme_path)
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
    """Switch the current app to the built-in flight-telemetry project and persist the choice."""
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


ENV_FILE_PATH = Path.home() / ".agilab/.env"
try:
    TEMPLATE_ENV_PATH = importlib_resources.files("agi_env") / "resources/.agilab/.env"
except (ModuleNotFoundError, FileNotFoundError, AttributeError, OSError):
    TEMPLATE_ENV_PATH = None


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


def _render_global_runtime_diagnostics(env: Any, container: Any | None = None) -> None:
    current_verbose = _global_runtime_diagnostics_verbose(env)
    settings: Dict[str, Any] = {"cluster": {"verbose": current_verbose}}
    diagnostics_container = container
    if diagnostics_container is None:
        with st.expander("Runtime diagnostics", expanded=False) as expander_container:
            selected_verbose = _render_global_runtime_diagnostics_control(
                expander_container, settings
            )
    else:
        selected_verbose = _render_global_runtime_diagnostics_control(
            diagnostics_container, settings
        )
    if selected_verbose != current_verbose:
        _store_global_runtime_diagnostics_verbose(env, selected_verbose)
    else:
        st.session_state["cluster_verbose"] = selected_verbose


def _render_global_runtime_diagnostics_control(
    container: Any, settings: Dict[str, Any]
) -> int:
    container.caption(
        "Global log detail reused by ORCHESTRATE, WORKFLOW, generated snippets, and CLI runs."
    )
    return render_runtime_diagnostics_control(
        st,
        container,
        settings,
        app_name="global",
        compact_choice_fn=compact_choice,
        key=diagnostics_widget_key("global"),
    )


def _refresh_env_from_file(env: Any) -> None:
    _sync_env_editor_module()
    _about_env_editor._refresh_env_from_file(env)


def _render_env_editor(env: Any, help_file: Path | None = None) -> None:
    _sync_env_editor_module()
    _about_env_editor._render_env_editor(env, help_file)


def _render_navigation_context(
    env: Any, *, page_label: str, show_project_context: bool = True
) -> None:
    try:
        render_sidebar_version(detect_agilab_version(env))
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        pass
    render_sidebar_settings_link(env)
    render_pinned_expanders(st)
    if show_project_context:
        render_page_context(st, page_label=page_label, env=env)


def _seed_session_runtime_defaults(env: Any) -> None:
    if "TABLE_MAX_ROWS" not in st.session_state:
        st.session_state["TABLE_MAX_ROWS"] = env.TABLE_MAX_ROWS
    if "GUI_SAMPLING" not in st.session_state:
        st.session_state["GUI_SAMPLING"] = env.GUI_SAMPLING


def page(env: Any) -> None:
    """Render the main landing page controls and footer for the lab."""
    _render_navigation_context(env, page_label="MAIN_PAGE", show_project_context=False)
    _sync_layout_module()
    _about_layout.render_footer()
    _seed_session_runtime_defaults(env)


def settings_page(env: Any) -> None:
    """Render persistent environment and diagnostics settings."""
    _render_navigation_context(env, page_label="SETTINGS")
    st.markdown("## Settings")
    st.caption(
        "Persistent environment variables and global runtime diagnostics for AGILAB actions."
    )
    st.markdown("#### Runtime diagnostics")
    _render_global_runtime_diagnostics(env, container=st)
    st.divider()
    st.markdown("#### Environment variables")
    st.caption(f"Stored in `{ENV_FILE_PATH.expanduser()}`.")
    _render_env_editor(env)
    _sync_layout_module()
    _about_layout.render_footer()
    _seed_session_runtime_defaults(env)


def _about_resources_path() -> Path:
    return Path(__file__).resolve().parent / "resources"


def _ensure_navigation_environment(
    resources_path: Path, *, rerun_after_bootstrap: bool
) -> Any | None:
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

    env = st.session_state["env"]
    _refresh_env_from_file(env)
    _sync_active_app_from_query(env)
    try:
        store_last_active_app(_about_bootstrap.active_app_store_path(env))
    except (OSError, RuntimeError, TypeError, ValueError):
        pass
    return env


def _render_navigation_page_shell(resources_path: Path) -> None:
    st.set_page_config(
        page_title="AGILab",
        menu_items=get_about_content(),
        layout="wide",
    )
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
        unsafe_allow_html=True,
    )


# ------------------------- Main Entrypoint -------------------------


def _render_about_page_entry() -> None:
    """Initialise the main page and display the landing UI."""
    started_at = time.perf_counter()
    resources_path = _about_resources_path()
    _render_navigation_page_shell(resources_path)
    bootstrap_started_at = time.perf_counter()
    env = _ensure_navigation_environment(resources_path, rerun_after_bootstrap=False)
    _record_ui_timing_span(
        "ABOUT:bootstrap", bootstrap_started_at, category="bootstrap"
    )
    if env is None:
        return
    render_started_at = time.perf_counter()
    show_banner_and_intro(resources_path, env)
    openai_status_banner(env)
    # Quick hint for operators: where to check install errors
    page(env)
    _record_ui_timing_span("ABOUT:render", render_started_at, category="render")
    _render_page_load_timing("ABOUT", started_at)


def _render_settings_page_entry() -> None:
    """Initialise the settings page and display persistent runtime controls."""
    started_at = time.perf_counter()
    resources_path = _about_resources_path()
    _render_navigation_page_shell(resources_path)
    bootstrap_started_at = time.perf_counter()
    env = _ensure_navigation_environment(resources_path, rerun_after_bootstrap=False)
    _record_ui_timing_span(
        "SETTINGS:bootstrap", bootstrap_started_at, category="bootstrap"
    )
    if env is None:
        return
    render_started_at = time.perf_counter()
    settings_page(env)
    _record_ui_timing_span("SETTINGS:render", render_started_at, category="render")
    _render_page_load_timing("SETTINGS", started_at)


def _navigation_pages() -> list[Any]:
    """Return the supported navigation pages."""
    root = Path(__file__).resolve().parent
    pages_root = root / "pages"
    main_page = st.Page(
        _render_about_page_entry,
        title="ABOUT",
        url_path="",
        default=True,
        visibility="hidden",
    )
    settings_nav_page = st.Page(
        pages_root / "0_SETTINGS.py",
        title="SETTINGS",
        url_path="SETTINGS",
        visibility="hidden",
    )
    project_page = st.Page(
        _page_file_runner(pages_root / "1_PROJECT.py"),
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
            "settings": settings_nav_page,
            "project": project_page,
            "orchestrate": orchestrate_page,
            "workflow": workflow_page,
            "analysis": analysis_page,
        }
    )
    return [
        main_page,
        settings_nav_page,
        project_page,
        orchestrate_page,
        workflow_page,
        analysis_page,
    ]


def _page_module_name(page_file: Path) -> str:
    return f"_agilab_streamlit_page_{abs(hash(str(page_file)))}"


def _load_page_module(page_file: Path) -> Any:
    """Load a Streamlit page module once per source version to reduce rerun latency."""
    resolved_page = page_file.resolve()
    stat = resolved_page.stat()
    cached = _PAGE_MODULE_CACHE.get(resolved_page)
    if (
        os.environ.get("AGILAB_DISABLE_PAGE_MODULE_CACHE") != "1"
        and cached is not None
        and cached[0] == stat.st_mtime_ns
        and cached[1] == stat.st_size
    ):
        return cached[3]

    module_name = cached[2] if cached is not None else _page_module_name(resolved_page)
    spec = importlib.util.spec_from_file_location(module_name, resolved_page)
    if spec is None or spec.loader is None:
        raise ModuleNotFoundError(f"Unable to load page from {resolved_page}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    _PAGE_MODULE_CACHE[resolved_page] = (
        stat.st_mtime_ns,
        stat.st_size,
        module_name,
        module,
    )
    return module


def _page_file_runner(page_file: Path) -> Callable[[], None]:
    """Run a guarded Streamlit page file through ``st.Page`` without changing the page contract."""

    def _run_page() -> None:
        started_at = time.perf_counter()
        page_label = page_file.stem
        bootstrap_started_at = time.perf_counter()
        if (
            _ensure_navigation_environment(
                _about_resources_path(), rerun_after_bootstrap=True
            )
            is None
        ):
            _record_ui_timing_span(
                f"{page_label}:bootstrap", bootstrap_started_at, category="bootstrap"
            )
            return
        _record_ui_timing_span(
            f"{page_label}:bootstrap", bootstrap_started_at, category="bootstrap"
        )
        import_started_at = time.perf_counter()
        module = _load_page_module(page_file)
        _record_ui_timing_span(
            f"{page_label}:import", import_started_at, category="import"
        )
        main_fn = getattr(module, "main", None)
        if main_fn is None:
            raise AttributeError(f"Page {page_file} does not expose a main() function")
        render_started_at = time.perf_counter()
        if inspect.iscoroutinefunction(main_fn):
            asyncio.run(main_fn())
        else:
            main_fn()
        _record_ui_timing_span(
            f"{page_label}:render", render_started_at, category="render"
        )
        _render_page_load_timing(page_label, started_at)

    _run_page.__name__ = f"run_{page_file.stem}"
    return _run_page


def main() -> None:
    """Initialise AGILAB navigation and run the selected Streamlit page."""
    st.navigation(_navigation_pages()).run()


# ----------------- Run App -----------------
if __name__ == "__main__":
    main()
