import logging
import os
import json
import traceback
import html
from pathlib import Path
import importlib
import importlib.util
import sys
import sysconfig
import subprocess
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

import pandas as pd
import re
os.environ.setdefault("STREAMLIT_CONFIG_FILE", str(Path(__file__).resolve().parents[1] / "resources" / "config.toml"))
import streamlit as st
from streamlit.errors import StreamlitAPIException
import tomllib        # For reading TOML files

PIPELINE_PROJECT_LABEL = "Project"
PIPELINE_PROJECT_HELP = (
    "Project workspace whose workflow stages and exported artifacts are shown below. "
    "Type in the dropdown to search."
)

_import_guard_path = Path(__file__).resolve().parents[1] / "import_guard.py"
_import_guard_spec = importlib.util.spec_from_file_location("agilab_import_guard_local", _import_guard_path)
if _import_guard_spec is None or _import_guard_spec.loader is None:
    raise ModuleNotFoundError(f"Unable to load import_guard.py from {_import_guard_path}")
_import_guard_module = importlib.util.module_from_spec(_import_guard_spec)
_import_guard_spec.loader.exec_module(_import_guard_module)
import_agilab_symbols = _import_guard_module.import_agilab_symbols
load_local_module = _import_guard_module.load_local_module

_page_project_selector_module = load_local_module(
    "agilab.page_project_selector",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "page_project_selector.py",
    fallback_name="agilab_page_project_selector_fallback",
)
_page_docs_module = load_local_module(
    "agilab.page_docs",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "page_docs.py",
    fallback_name="agilab_page_docs_fallback",
)
get_docs_menu_items = _page_docs_module.get_docs_menu_items

from agi_gui.pagelib import (
    activate_mlflow,
    background_services_enabled,
    find_files,
    run_agi,
    load_df,
    get_custom_buttons,
    get_info_bar,
    get_css_text,
    export_df,
    resolve_selected_df_path,
    render_logo,
    inject_theme,
)
from agi_gui.file_picker import agi_file_picker
from agi_env import AgiEnv, normalize_path
from agi_env.app_provider_registry import app_name_aliases
from agi_env.pagelib_selection_support import on_df_change as _on_df_change_impl
import_agilab_symbols(
    globals(),
    "agilab.pipeline_views",
    {
        "load_pipeline_conceptual_dot": "load_pipeline_conceptual_dot",
        "render_pipeline_view": "render_pipeline_view",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "pipeline_views.py",
    fallback_name="agilab_pipeline_views_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.page_bootstrap",
    {
        "ensure_page_env": "_ensure_page_env",
        "load_about_page_module": "_load_about_page_module_impl",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "page_bootstrap.py",
    fallback_name="agilab_page_bootstrap_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.pinned_expander",
    {
        "render_pinned_expanders": "render_pinned_expanders",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "pinned_expander.py",
    fallback_name="agilab_pinned_expander_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.workflow_ui",
    {
        "is_dag_based_app": "is_dag_based_app",
        "render_page_context": "render_page_context",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "workflow_ui.py",
    fallback_name="agilab_workflow_ui_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.runtime_diagnostics",
    {
        "global_diagnostics_verbose": "global_diagnostics_verbose",
        "load_settings_file": "load_runtime_diagnostics_settings_file",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "runtime_diagnostics.py",
    fallback_name="agilab_runtime_diagnostics_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.pipeline_stages",
    {
        "ORCHESTRATE_LOCKED_SOURCE_KEY": "ORCHESTRATE_LOCKED_SOURCE_KEY",
        "ORCHESTRATE_LOCKED_STAGE_KEY": "ORCHESTRATE_LOCKED_STAGE_KEY",
        "bump_history_revision": "_bump_history_revision",
        "ensure_primary_module_key": "_ensure_primary_module_key",
        "get_available_virtualenvs": "get_available_virtualenvs",
        "is_displayable_stage": "_is_displayable_stage",
        "is_orchestrate_locked_stage": "_is_orchestrate_locked_stage",
        "is_runnable_stage": "_is_runnable_stage",
        "load_sequence_preferences": "_load_sequence_preferences",
        "looks_like_stage": "_looks_like_stage",
        "module_keys": "_module_keys",
        "normalize_runtime_path": "normalize_runtime_path",
        "orchestrate_snippet_source": "_orchestrate_snippet_source",
        "persist_sequence_preferences": "_persist_sequence_preferences",
        "pipeline_export_root": "_pipeline_export_root",
        "prune_invalid_entries": "_prune_invalid_entries",
        "restore_missing_export_stages": "_restore_missing_export_stages",
        "snippet_source_guidance": "_snippet_source_guidance",
        "stage_button_label": "_stage_button_label",
        "stage_label_for_multiselect": "_stage_label_for_multiselect",
        "stage_summary": "_stage_summary",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "pipeline_stages.py",
    fallback_name="agilab_pipeline_stages_fallback",
)
_pipeline_ai_module = import_agilab_symbols(
    globals(),
    "agilab.pipeline_ai",
    {
        "CODE_STRICT_INSTRUCTIONS": "CODE_STRICT_INSTRUCTIONS",
        "UOAIC_AUTOFIX_ENV": "UOAIC_AUTOFIX_ENV",
        "UOAIC_AUTOFIX_MAX_ENV": "UOAIC_AUTOFIX_MAX_ENV",
        "UOAIC_AUTOFIX_MAX_STATE_KEY": "UOAIC_AUTOFIX_MAX_STATE_KEY",
        "UOAIC_AUTOFIX_STATE_KEY": "UOAIC_AUTOFIX_STATE_KEY",
        "UOAIC_DATA_ENV": "UOAIC_DATA_ENV",
        "UOAIC_DB_ENV": "UOAIC_DB_ENV",
        "UOAIC_MODE_ENV": "UOAIC_MODE_ENV",
        "UOAIC_MODE_OLLAMA": "UOAIC_MODE_OLLAMA",
        "UOAIC_MODE_RAG": "UOAIC_MODE_RAG",
        "UOAIC_MODE_STATE_KEY": "UOAIC_MODE_STATE_KEY",
        "UOAIC_PROVIDER": "UOAIC_PROVIDER",
        "UOAIC_REBUILD_FLAG_KEY": "UOAIC_REBUILD_FLAG_KEY",
        "UOAIC_RUNTIME_KEY": "UOAIC_RUNTIME_KEY",
        "GENERATION_MODE_SAFE_ACTIONS": "GENERATION_MODE_SAFE_ACTIONS",
        "ask_gpt": "ask_gpt",
        "configure_assistant_engine": "configure_assistant_engine",
        "extract_code": "extract_code",
        "gpt_oss_controls": "gpt_oss_controls",
        "universal_offline_controls": "universal_offline_controls",
        "_maybe_autofix_generated_code": "_maybe_autofix_generated_code",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "pipeline_ai.py",
    fallback_name="agilab_pipeline_ai_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.pipeline_editor",
    {
        "_capture_pipeline_snapshot": "_capture_pipeline_snapshot",
        "_force_persist_stage": "_force_persist_stage",
        "_restore_pipeline_snapshot": "_restore_pipeline_snapshot",
        "build_notebook_export_context": "build_notebook_export_context",
        "get_stages_list": "get_stages_list",
        "on_preview_notebook_import": "on_preview_notebook_import",
        "refresh_notebook_export": "refresh_notebook_export",
        "render_notebook_import_preview": "render_notebook_import_preview",
        "resolve_pycharm_notebook_path": "resolve_pycharm_notebook_path",
        "remove_stage": "remove_stage",
        "save_stage": "save_stage",
        "toml_to_notebook": "toml_to_notebook",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "pipeline_editor.py",
    fallback_name="agilab_pipeline_editor_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.pipeline_lab",
    {
        "PipelineLabDeps": "PipelineLabDeps",
        "display_lab_tab": "display_lab_tab",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "pipeline_lab.py",
    fallback_name="agilab_pipeline_lab_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.pipeline_runtime",
    {
        "label_for_stage_runtime": "_label_for_stage_runtime",
        "ensure_safe_service_template": "_ensure_safe_service_template",
        "is_valid_runtime_root": "_is_valid_runtime_root",
        "python_for_stage": "_python_for_stage",
        "python_for_venv": "_python_for_venv",
        "run_locked_stage": "_run_locked_stage",
        "stream_run_command": "_stream_run_command",
        "to_bool_flag": "_to_bool_flag",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "pipeline_runtime.py",
    fallback_name="agilab_pipeline_runtime_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.pipeline_run_controls",
    {
        "PIPELINE_LOCK_DEFAULT_TTL_SEC": "PIPELINE_LOCK_DEFAULT_TTL_SEC",
        "PIPELINE_LOCK_FILENAME": "PIPELINE_LOCK_FILENAME",
        "PIPELINE_LOCK_SCHEMA": "PIPELINE_LOCK_SCHEMA",
        "_acquire_pipeline_run_lock": "_acquire_pipeline_run_lock",
        "_append_run_log": "_append_run_log",
        "_clear_pipeline_run_lock": "_clear_pipeline_run_lock",
        "_get_run_placeholder": "_get_run_placeholder",
        "_inspect_pipeline_run_lock": "_inspect_pipeline_run_lock",
        "_mlflow_parent_payload": "_mlflow_parent_payload",
        "_mlflow_stage_payload": "_mlflow_stage_payload",
        "_pipeline_lock_owner_alive": "_pipeline_lock_owner_alive",
        "_pipeline_lock_owner_text": "_pipeline_lock_owner_text",
        "_pipeline_lock_path": "_pipeline_lock_path",
        "_pipeline_lock_ttl_seconds": "_pipeline_lock_ttl_seconds",
        "_prepare_run_log_file": "_prepare_run_log_file",
        "_push_run_log": "_push_run_log",
        "_read_pipeline_lock_payload": "_read_pipeline_lock_payload",
        "_refresh_pipeline_run_lock": "_refresh_pipeline_run_lock",
        "_release_pipeline_run_lock": "_release_pipeline_run_lock",
        "_rerun_fragment_or_app": "_rerun_fragment_or_app",
        "run_all_stages": "_run_all_stages_impl",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "pipeline_run_controls.py",
    fallback_name="agilab_pipeline_run_controls_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.pipeline_sidebar",
    {
        "available_lab_modules": "_available_lab_modules",
        "load_last_active_app_name": "_load_last_active_app_name",
        "normalize_lab_choice": "_normalize_lab_choice",
        "on_lab_change": "on_lab_change",
        "open_notebook_in_browser": "open_notebook_in_browser",
        "resolve_lab_export_dir": "_resolve_lab_export_dir",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "pipeline_sidebar.py",
    fallback_name="agilab_pipeline_sidebar_fallback",
)
import_agilab_symbols(
    globals(),
    "agilab.logging_utils",
    {
        "LOG_DETAIL_LIMIT": "LOG_DETAIL_LIMIT",
        "LOG_PATH_LIMIT": "LOG_PATH_LIMIT",
        "bound_log_value": "bound_log_value",
    },
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "logging_utils.py",
    fallback_name="agilab_logging_utils_fallback",
)

# Constants
STAGES_FILE_NAME = "lab_stages.toml"
DEFAULT_DF = "lab_out.csv"
SAFE_SERVICE_START_TEMPLATE_FILENAME = "AGI_serve_safe_start_template.py"
SAFE_SERVICE_START_TEMPLATE_MARKER = "# AGILAB_AUTO_GENERATED_PIPELINE_SNIPPET: SAFE_SERVICE_START"
logger = logging.getLogger(__name__)
ANSI_ESCAPE_RE = re.compile(r"\x1b[^m]*m")


class JumpToMain(Exception):
    """Custom exception to jump back to the main execution flow."""
    pass


_pipeline_ai_module.JumpToMain = JumpToMain


def run_all_stages(
    lab_dir: Path,
    index_page_str: str,
    stages_file: Path,
    module_path: Path,
    env: AgiEnv,
    log_placeholder: Optional[Any] = None,
    force_lock_clear: bool = False,
) -> None:
    """Execute all stages sequentially, honouring per-stage virtual environments."""
    _run_all_stages_impl(
        lab_dir,
        index_page_str,
        stages_file,
        module_path,
        env,
        load_all_stages_fn=load_all_stages,
        stream_run_command_fn=lambda *args, **kwargs: _stream_run_command(
            *args,
            push_run_log=_push_run_log,
            ansi_escape_re=ANSI_ESCAPE_RE,
            jump_exception_cls=JumpToMain,
            **kwargs,
        ),
        log_placeholder=log_placeholder,
        force_lock_clear=force_lock_clear,
    )

def on_page_change() -> None:
    """Set the 'page_broken' flag in session state."""
    st.session_state.page_broken = True


def on_stage_change(
    module_dir: Path,
    stages_file: Path,
    index_stage: int,
    index_page: str,
) -> None:
    """Update session state when a stage is selected."""
    st.session_state[index_page][0] = index_stage
    st.session_state.stage_checked = False
    # Schedule prompt clear and blank on next render; bump input revision to remount widget
    st.session_state[f"{index_page}__clear_q"] = True
    st.session_state[f"{index_page}__q_rev"] = st.session_state.get(f"{index_page}__q_rev", 0) + 1
    # Drop any existing editor instance state for this stage (best-effort)
    st.session_state.pop(f"{index_page}_a_{index_stage}", None)
    venv_map = st.session_state.get(f"{index_page}__venv_map", {})
    st.session_state["lab_selected_venv"] = normalize_runtime_path(venv_map.get(index_stage, ""))
    # Do not call st.rerun() here: callbacks automatically trigger a rerun
    # after returning. Rely on the updated session_state to refresh the UI.
    return


def load_last_stage(
    module_dir: Path,
    stages_file: Path,
    index_page: str,
) -> None:
    """Load the last stage for a module into session state."""
    details_store = st.session_state.setdefault(f"{index_page}__details", {})
    all_stages = load_all_stages(module_dir, stages_file, index_page)
    if all_stages:
        last_stage = len(all_stages) - 1
        current_stage = st.session_state[index_page][0]
        if current_stage <= last_stage:
            entry = all_stages[current_stage] or {}
            d = entry.get("D", "")
            q = entry.get("Q", "")
            m = entry.get("M", "")
            c = entry.get("C", "")
            detail = details_store.get(current_stage, "")
            st.session_state[index_page][1:6] = [d, q, m, c, detail]
            raw_e = normalize_runtime_path(entry.get("E", ""))
            e = raw_e if _is_valid_runtime_root(raw_e) else ""
            venv_map = st.session_state.setdefault(f"{index_page}__venv_map", {})
            if e:
                venv_map[current_stage] = e
                st.session_state["lab_selected_venv"] = e
            else:
                venv_map.pop(current_stage, None)
                st.session_state["lab_selected_venv"] = ""
            engine_map = st.session_state.setdefault(f"{index_page}__engine_map", {})
            selected_engine = entry.get("R", "") or ("agi.run" if e else "runpy")
            if selected_engine:
                engine_map[current_stage] = selected_engine
            else:
                engine_map.pop(current_stage, None)
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


def on_df_change(module_dir: Path, index_page, df_file=None, stages_file=None) -> None:
    """Update dataframe selection using the WORKFLOW page-local stage loader."""
    return _on_df_change_impl(
        module_dir,
        index_page,
        df_file,
        stages_file,
        session_state=st.session_state,
        resolve_selected_df_path_fn=resolve_selected_df_path,
        load_last_stage_fn=load_last_stage,
        logger=logger,
        path_cls=Path,
    )


def clean_query(index_page: str) -> None:
    """Reset the query fields in session state."""
    df_value = st.session_state.get("df_file", "") or ""
    st.session_state[index_page][1:-1] = [df_value, "", "", "", ""]
    details_store = st.session_state.setdefault(f"{index_page}__details", {})
    current_stage = st.session_state[index_page][0] if index_page in st.session_state else None
    if current_stage is not None:
        details_store.pop(current_stage, None)
        venv_store = st.session_state.setdefault(f"{index_page}__venv_map", {})
        venv_store.pop(current_stage, None)
        st.session_state["lab_selected_venv"] = ""


def _resolve_dataframe_selection(
    selection: Any,
    *,
    df_files_rel: List[Path],
    export_root: Path,
) -> Tuple[Path, str] | None:
    """Return a valid relative dataframe selection and absolute picker path."""
    if selection in (None, ""):
        return None

    try:
        raw_path = Path(selection)
    except TypeError:
        return None
    export_root_resolved = export_root.resolve(strict=False)
    if raw_path.is_absolute():
        try:
            relative_path = raw_path.resolve(strict=False).relative_to(export_root_resolved)
        except ValueError:
            return None
    else:
        relative_path = raw_path

    if relative_path not in df_files_rel:
        return None
    return relative_path, str((export_root_resolved / relative_path).resolve(strict=False))


def _apply_dataframe_picker_selection(
    picked_df: str | Path | None,
    *,
    dataframe_key: str,
    df_files_rel: List[Path],
    export_root: Path,
) -> bool:
    """Apply a picker selection and return whether it changed the active dataframe."""
    selected = _resolve_dataframe_selection(
        picked_df,
        df_files_rel=df_files_rel,
        export_root=export_root,
    )
    if selected is None:
        return False

    picked_df_rel, picked_abs = selected
    current_selection = _resolve_dataframe_selection(
        st.session_state.get(dataframe_key),
        df_files_rel=df_files_rel,
        export_root=export_root,
    )
    current_df_rel = current_selection[0] if current_selection else None
    st.session_state[dataframe_key] = picked_df_rel
    st.session_state[f"{dataframe_key}_file"] = picked_abs
    st.session_state["df_file"] = picked_abs
    return current_df_rel is not None and current_df_rel != picked_df_rel


def _clear_dataframe_picker_selection(dataframe_key: str, *, picker_key: str | None = None) -> None:
    if picker_key:
        st.session_state.pop(f"{picker_key}:selected_paths", None)
    st.session_state.pop(dataframe_key, None)
    st.session_state.pop(f"{dataframe_key}_file", None)
    st.session_state["df_file"] = None


@st.cache_data(show_spinner=False)
def _read_stages(stages_file: Path, module_key: str, mtime_ns: int) -> List[Dict[str, Any]]:
    """Read stages for a specific module key from a TOML file.

    Caches on (path, module_key, mtime_ns) so saves invalidate automatically.
    """
    with open(stages_file, "rb") as f:
        data = tomllib.load(f)
    return list(data.get(module_key, []))


def _ensure_notebook_export(stages_file: Path) -> None:
    """Materialize the notebook export for a stages file when missing."""
    notebook_path = stages_file.with_suffix(".ipynb")
    if notebook_path.exists():
        return
    try:
        with open(stages_file, "rb") as stream:
            stages_full = tomllib.load(stream)
        toml_to_notebook(stages_full, stages_file)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, TypeError, ValueError) as exc:
        logger.warning(
            "Skipping notebook generation: %s",
            bound_log_value(exc, LOG_DETAIL_LIMIT),
        )


def _render_notebook_download_button(
    notebook_path: Path,
    key: str,
    *,
    pycharm_path: Path | None = None,
    container: Any | None = None,
) -> None:
    """Render the notebook download button for an exported notebook."""
    target = container or st
    try:
        notebook_data = notebook_path.read_bytes()
        target.download_button(
            "Download pipeline notebook",
            data=notebook_data,
            file_name=notebook_path.name,
            mime="application/x-ipynb+json",
            key=key,
        )
        if pycharm_path is not None:
            target.caption(f"PyCharm notebook: `{pycharm_path}`")
    except (OSError, StreamlitAPIException) as exc:
        target.error(f"Failed to prepare notebook export: {exc}")


def _render_notebook_actions(
    env: AgiEnv,
    module_path: Path,
    stages_file: Path,
    index_page_str: str,
    *,
    project_name: str,
) -> None:
    """Render notebook import/export actions in the main pipeline workspace."""
    with st.expander("Notebook", expanded=False):
        st.caption(
            f"Active stages file: `{stages_file.name}`. "
            "Import a notebook into this pipeline or export the current pipeline as a runnable "
            "`.ipynb` so the work remains reusable outside AGILAB."
        )

        key = index_page_str + "import_notebook"
        import_module_dir = stages_file.parent
        view_manifest_dir = _resolve_active_app_project_dir(env, project_name)
        st.markdown("##### Import")
        st.file_uploader(
            "Import notebook",
            type="ipynb",
            key=key,
            on_change=on_preview_notebook_import,
            args=(key, import_module_dir, index_page_str, view_manifest_dir),
        )
        render_notebook_import_preview(
            import_module_dir,
            stages_file,
            index_page_str,
            view_manifest_dir=view_manifest_dir,
        )

        export_context = build_notebook_export_context(
            env,
            module_path,
            stages_file,
            project_name=project_name,
        )
        notebook_path = refresh_notebook_export(stages_file, export_context=export_context)
        st.markdown("##### Export")
        if notebook_path and notebook_path.exists():
            _render_notebook_download_button(
                notebook_path,
                index_page_str + "export_notebook",
                pycharm_path=resolve_pycharm_notebook_path(stages_file, export_context=export_context),
            )
        else:
            st.caption("No notebook export is available for this pipeline yet.")


def load_all_stages(
    module_path: Path,
    stages_file: Path,
    index_page: str,
) -> Optional[List[Dict[str, Any]]]:
    """Load all stages for a module from a TOML file using str(module_path) as key.

    Uses a small cache keyed by file mtime to avoid re-parsing on every rerun.
    """
    try:
        module_key = _module_keys(module_path)[0]
        mtime_ns = stages_file.stat().st_mtime_ns
        raw_entries = _read_stages(stages_file, module_key, mtime_ns)
        filtered_entries = _prune_invalid_entries(raw_entries)
        if filtered_entries and not st.session_state[index_page][-1]:
            st.session_state[index_page][-1] = len(filtered_entries)
        if filtered_entries and not stages_file.with_suffix(".ipynb").exists():
            _ensure_notebook_export(stages_file)
        return filtered_entries
    except FileNotFoundError:
        return []
    except tomllib.TOMLDecodeError as e:
        st.error(f"Error decoding TOML: {e}")
        return []


def on_query_change(
    request_key: str,
    module: Path,
    stage: int,
    stages_file: Path,
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
                raw_text,
                df_file,
                index_page,
                env.envars,
                generation_mode=GENERATION_MODE_SAFE_ACTIONS,
                load_df_cached=load_df_cached,
            )
            detail = answer[4] if len(answer) > 4 else ""
            model_label = answer[2] if len(answer) > 2 else ""
            extra_fields = answer[5] if len(answer) > 5 and isinstance(answer[5], dict) else None
            if not str(answer[3] if len(answer) > 3 else "").strip():
                if detail:
                    st.info(detail)
                else:
                    st.info("Assistant response did not include runnable code. Stage was not saved.")
                return
            venv_map = st.session_state.get(f"{index_page}__venv_map", {})
            engine_map = st.session_state.get(f"{index_page}__engine_map", {})
            nstage, entry = save_stage(
                module,
                answer,
                stage,
                0,
                stages_file,
                venv_map=venv_map,
                engine_map=engine_map,
                extra_fields=extra_fields,
            )
            skipped = st.session_state.get("_experiment_last_save_skipped", False)
            details_key = f"{index_page}__details"
            details_store = st.session_state.setdefault(details_key, {})
            if skipped or not detail:
                details_store.pop(stage, None)
            else:
                details_store[stage] = detail
            if skipped:
                st.info("Assistant response did not include runnable code. Stage was not saved.")
            _bump_history_revision()
            st.session_state[index_page][0] = stage
            # Deterministic mapping to D/Q/M/C slots
            d = entry.get("D", "")
            q = entry.get("Q", "")
            c = entry.get("C", "")
            m = entry.get("M", model_label)
            st.session_state[index_page][1:6] = [d, q, m, c, detail or ""]
            e = entry.get("E", "")
            if e:
                venv_map[stage] = e
                st.session_state["lab_selected_venv"] = e
            st.session_state[f"{index_page}_q"] = q
            st.session_state[index_page][-1] = nstage
        st.session_state.pop(f"{index_page}_a_{stage}", None)
        st.session_state.page_broken = True
    except JumpToMain:
        pass


def on_nb_change(
    module: Path,
    query: List[Any],
    file_stage_path: Path,
    project: str,
    notebook_file: Path,
    env: AgiEnv,
) -> None:
    """Handle notebook interaction and run notebook if possible."""
    module_path = Path(module)
    index_page = str(st.session_state.get("index_page", module_path))
    venv_map = st.session_state.get(f"{index_page}__venv_map", {})
    engine_map = st.session_state.get(f"{index_page}__engine_map", {})
    save_stage(
        module_path,
        query[1:5],
        query[0],
        query[-1],
        file_stage_path,
        venv_map=venv_map,
        engine_map=engine_map,
    )
    _bump_history_revision()
    project_path = env.apps_path / project
    if notebook_file.exists():
        cmd = ["uv", "-q", "run", "jupyter", "notebook", str(notebook_file)]
        code = (
            "import subprocess\n"
            f"subprocess.Popen({cmd!r}, cwd={str(project_path)!r})\n"
        )
        output = run_agi(code, path=project_path)
        if output is None:
            open_notebook_in_browser()
        else:
            st.info(output)
    else:
        st.info(f"No file named {notebook_file} found!")


def _pipeline_project_catalog(env: AgiEnv) -> List[str]:
    try:
        projects = env.get_projects(
            getattr(env, "apps_path", None),
            getattr(env, "builtin_apps_path", None),
            getattr(env, "apps_repository_root", None),
        )
    except (AttributeError, OSError, RuntimeError, TypeError):
        return []
    seen: set[str] = set()
    catalog: List[str] = []
    for project in projects:
        name = str(project or "").strip()
        if name and name not in seen:
            catalog.append(name)
            seen.add(name)
    return catalog


def _canonical_pipeline_project_name(raw_name: Any, project_catalog: List[str]) -> str:
    name = Path(str(raw_name or "").strip()).name
    if not name or name == "apps":
        return ""
    for alias in app_name_aliases(name):
        if alias in project_catalog:
            return alias
    return name


def _canonical_pipeline_project_modules(env: AgiEnv, raw_modules: List[str]) -> List[str]:
    project_catalog = _pipeline_project_catalog(env)
    modules: List[str] = []
    seen: set[str] = set()

    def _add(raw_name: Any) -> None:
        canonical = _canonical_pipeline_project_name(raw_name, project_catalog)
        if canonical and canonical not in seen:
            modules.append(canonical)
            seen.add(canonical)

    for module in raw_modules:
        _add(module)

    # Keep the active app selectable, but do not add an unsuffixed alias when a
    # canonical *_project directory is known.
    _add(getattr(env, "target", ""))
    return modules


def _resolve_active_app_project_dir(env: AgiEnv, project_name: str) -> Path | None:
    raw_names = [project_name, getattr(env, "app", None), getattr(env, "target", None)]
    app_names = [str(name).strip() for name in raw_names if str(name or "").strip()]
    candidates: list[Any] = []
    for root_attr in ("apps_path", "builtin_apps_path"):
        root = getattr(env, root_attr, None)
        if not root:
            continue
        for app_name in app_names:
            candidates.append(Path(root) / app_name)
    apps_path = getattr(env, "apps_path", None)
    if apps_path:
        for app_name in app_names:
            candidates.append(Path(apps_path) / "builtin" / app_name)
    for attr in ("active_app", "active_app_path", "app_path"):
        value = getattr(env, attr, None)
        if not value:
            continue
        try:
            candidate = Path(value).expanduser()
        except (OSError, TypeError, ValueError):
            continue
        if app_names and candidate.name not in app_names:
            continue
        candidates.append(candidate)

    seen: set[Path] = set()
    for raw_candidate in candidates:
        try:
            candidate = Path(raw_candidate).expanduser()
        except (OSError, TypeError, ValueError):
            continue
        if not candidate.is_absolute() and len(candidate.parts) <= 1:
            continue
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError):
            resolved = candidate
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_dir():
            return resolved
    return None


def sidebar_controls() -> None:
    """Create sidebar controls for selecting modules and DataFrames."""
    env: AgiEnv = st.session_state["env"]
    Agi_export_abs = _pipeline_export_root(env)
    modules = _canonical_pipeline_project_modules(env, _available_lab_modules(env, Agi_export_abs))
    if not modules:
        modules = [env.target] if env.target else []

    requested_lab = _normalize_lab_choice(st.session_state.get("_requested_lab_dir"), modules)

    # If no explicit project was known, prefer the configured environment target.
    project_changed = st.session_state.pop("project_changed", False)
    if project_changed:
        for key in (
            "project_selectbox",
            "lab_dir_selectbox",
            "lab_dir",
            "index_page",
            "stages_file",
            "df_file",
            "df_file_in",
            "df_file_out",
            "stages_files",
            "df_files",
            "df_dir",
            "lab_prompt",
            "_experiment_reload_required",
        ):
            st.session_state.pop(key, None)
        st.session_state["_experiment_reload_required"] = True

    modules = [m for m in modules if m != "apps"]
    if not modules:
        modules = ["apps"]
    st.session_state['modules'] = modules

    def _qp_first(key: str) -> str | None:
        val = st.query_params.get(key)
        if isinstance(val, list):
            return val[0] if val else None
        if val is None:
            return None
        return str(val)

    last_active = _load_last_active_app_name(modules)
    normalized_target = _normalize_lab_choice(env.target, modules)
    if project_changed:
        persisted_lab = requested_lab or normalized_target or env.target
    else:
        persisted_lab = (
            _normalize_lab_choice(_qp_first("lab_dir_selectbox"), modules)
            or _normalize_lab_choice(st.session_state.get("project_selectbox"), modules)
            or _normalize_lab_choice(st.session_state.get("lab_dir_selectbox"), modules)
            or _normalize_lab_choice(st.session_state.get("lab_dir"), modules)
            or _normalize_lab_choice(last_active, modules)
            or normalized_target
            or env.target
        )

    if persisted_lab not in modules:
        fallback = _normalize_lab_choice(env.target, modules)
        persisted_lab = fallback if fallback in modules else modules[0]
    elif persisted_lab == "apps" and normalized_target in modules:
        # Avoid selecting the top-level "apps" directory; prefer the active app/target.
        persisted_lab = normalized_target

    st.session_state.pop("project_filter", None)
    project_options = modules
    project_index = modules.index(persisted_lab) if persisted_lab in modules else 0
    if st.session_state.get("project_selectbox") not in project_options:
        st.session_state.pop("project_selectbox", None)
    project_selector_col, project_edit_col = st.sidebar.columns([0.76, 0.24], vertical_alignment="bottom")
    selected_lab = project_selector_col.selectbox(
        PIPELINE_PROJECT_LABEL,
        project_options,
        index=project_index,
        on_change=lambda: on_lab_change(st.session_state.project_selectbox),
        key="project_selectbox",
        help=PIPELINE_PROJECT_HELP,
    )
    if project_edit_col.button(
        "Edit",
        key="project_selectbox__edit",
        help=f"Edit {selected_lab}.",
        use_container_width=True,
    ):
        st.query_params["active_app"] = selected_lab
        st.switch_page(Path("pages/1_PROJECT.py"))
    st.session_state["lab_dir_selectbox"] = selected_lab
    st.session_state["lab_dir"] = selected_lab
    if selected_lab != persisted_lab:
        on_lab_change(selected_lab)
    if requested_lab and st.session_state.get("lab_dir_selectbox") == requested_lab:
        st.session_state.pop("_requested_lab_dir", None)

    try:
        diagnostics_settings_file = env.resolve_user_app_settings_file(selected_lab)
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        diagnostics_settings_file = getattr(env, "app_settings_file", None)
    diagnostics_settings = load_runtime_diagnostics_settings_file(diagnostics_settings_file)
    selected_diagnostics_verbose = global_diagnostics_verbose(
        session_state=st.session_state,
        envars=getattr(env, "envars", None),
        environ=os.environ,
        settings=diagnostics_settings,
    )
    st.session_state["cluster_verbose"] = selected_diagnostics_verbose

    stages_file_name = st.session_state["stages_file_name"]
    export_root = _pipeline_export_root(env)
    lab_choice = Path(st.session_state["lab_dir_selectbox"]).name
    lab_dir = _resolve_lab_export_dir(export_root, lab_choice)
    lab_dir.mkdir(parents=True, exist_ok=True)
    st.session_state.df_dir = lab_dir
    stages_file = (lab_dir / stages_file_name).resolve()
    st.session_state["stages_file"] = stages_file
    module_path = lab_dir.relative_to(Agi_export_abs)
    st.session_state["module_path"] = module_path
    restored_source = _restore_missing_export_stages(module_path, stages_file, env=env)
    if restored_source:
        st.session_state["_pipeline_stages_restored_from"] = str(restored_source)

    stages_files = find_files(lab_dir, ".toml")
    st.session_state.stages_files = stages_files
    lab_root = lab_dir.name
    stages_files_path = [
        Path(file)
        for file in stages_files
        if Path(file).is_file()
        and Path(file).suffix.lower() == ".toml"
        and "lab_stages" in Path(file).name
    ]
    stages_file_rel = sorted(
        [
            rel_path
            for rel_path in (
                file.relative_to(Agi_export_abs)
                for file in stages_files_path
                if file.is_relative_to(Agi_export_abs)
            )
            if rel_path.parts and rel_path.parts[0] == lab_root
        ],
        key=str,
    )

    if "index_page" not in st.session_state:
        index_page = stages_file_rel[0] if stages_file_rel else env.target
        st.session_state["index_page"] = index_page
    else:
        index_page = st.session_state["index_page"]

    index_page_str = str(index_page)

    if stages_file_rel and index_page not in stages_file_rel:
        index_page = stages_file_rel[0]
        st.session_state["index_page"] = index_page
        index_page_str = str(index_page)

    df_files = _filter_pipeline_dataframe_files(find_files(lab_dir))
    st.session_state.df_files = df_files

    if not stages_file.parent.exists():
        stages_file.parent.mkdir(parents=True, exist_ok=True)

    df_files_rel = sorted((Path(file).relative_to(Agi_export_abs) for file in df_files), key=str)
    key_df = index_page_str + "df"
    index = next((i for i, f in enumerate(df_files_rel) if f.name == DEFAULT_DF), 0)
    df_file_default = st.session_state.get("df_file")
    current_df_selection = st.session_state.get(key_df)
    if current_df_selection is not None and _resolve_dataframe_selection(
        current_df_selection,
        df_files_rel=df_files_rel,
        export_root=Agi_export_abs,
    ) is None:
        st.session_state.pop(key_df, None)

    picker_default: Path | None = None
    if df_file_default and _resolve_dataframe_selection(
        df_file_default,
        df_files_rel=df_files_rel,
        export_root=Agi_export_abs,
    ):
        picker_default = Path(df_file_default)
    elif df_files_rel:
        picker_default = Agi_export_abs / df_files_rel[index]
    picker_key = f"{index_page_str}:dataframe_picker"

    if df_files_rel:
        picked_df = agi_file_picker(
            "Data source",
            roots={lab_root: lab_dir},
            key=picker_key,
            patterns=_PIPELINE_DATA_SOURCE_PATTERNS,
            default=picker_default,
            selection_mode="single",
            allow_files=True,
            allow_dirs=False,
            recursive=True,
            container=st.sidebar,
            help="Select a dataframe-like artifact under the active project export directory.",
        )
        st.sidebar.caption("Used by generated pipeline steps.")
        if picked_df:
            try:
                picked_df_rel = Path(picked_df).resolve(strict=False).relative_to(Agi_export_abs)
            except ValueError:
                st.sidebar.warning("Selected data source is outside the export directory.")
            else:
                if _resolve_dataframe_selection(
                    picked_df_rel,
                    df_files_rel=df_files_rel,
                    export_root=Agi_export_abs,
                ) is None:
                    _clear_dataframe_picker_selection(key_df, picker_key=picker_key)
                else:
                    dataframe_changed = _apply_dataframe_picker_selection(
                        picked_df_rel,
                        dataframe_key=key_df,
                        df_files_rel=df_files_rel,
                        export_root=Agi_export_abs,
                    )
                    if dataframe_changed:
                        st.session_state.pop(index_page_str, None)
                        st.session_state.page_broken = True
        else:
            _clear_dataframe_picker_selection(key_df, picker_key=picker_key)
    else:
        _clear_dataframe_picker_selection(key_df, picker_key=picker_key)
    if _resolve_dataframe_selection(
        st.session_state.get(key_df),
        df_files_rel=df_files_rel,
        export_root=Agi_export_abs,
    ) is None:
        _clear_dataframe_picker_selection(key_df)

    # Persist sidebar selections into query params for reloads
    st.query_params.update(
        {
            "lab_dir_selectbox": st.session_state.get("lab_dir_selectbox", ""),
            "index_page": str(st.session_state.get("index_page", "")),
            "lab_llm_provider": st.session_state.get("lab_llm_provider", ""),
            "gpt_oss_endpoint": st.session_state.get("gpt_oss_endpoint", ""),
            "df_file": st.session_state.get("df_file") or "",
            # Keep other pages (e.g., Explore) aware of the current project
            "active_app": st.session_state.get("lab_dir_selectbox", ""),
        }
    )

    # Persist last active app for cross-page defaults (use current lab_dir path)
    # Last active app is now persisted via on_lab_change when user switches labs.


def mlflow_controls() -> None:
    """Display MLflow UI controls in sidebar."""
    if not st.session_state.get("server_started"):
        return

    st.sidebar.divider()
    mlflow_port = st.session_state.get("mlflow_port", 5000)
    mlflow_url = f"http://localhost:{mlflow_port}"
    st.sidebar.markdown(f"### [MLflow]({mlflow_url})")
    st.sidebar.markdown(f"**Status:** running  \n**Port:** `{mlflow_port}`")


def _load_pre_prompt_messages(env: AgiEnv) -> list[Any]:
    """Load pre-prompt messages for the current app, falling back to an empty list."""
    pre_prompt_path = Path(env.app_src) / "pre_prompt.json"
    try:
        with open(pre_prompt_path, encoding="utf-8") as stream:
            pre_prompt_content = json.load(stream)
    except FileNotFoundError:
        logger.info("No pre_prompt.json found at %s; using empty Workflow prompt.", pre_prompt_path)
        return []
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        st.warning(f"Failed to load pre_prompt.json: {exc}")
        return []

    if isinstance(pre_prompt_content, list):
        return pre_prompt_content

    st.warning(f"pre_prompt.json at {pre_prompt_path} is not a list of messages; using empty prompt.")
    return []


def _caption_once(key: str, message: str) -> None:
    """Render low-priority WORKFLOW guidance once per Streamlit session."""
    notice_key = f"_pipeline_notice_seen__{key}"
    if st.session_state.get(notice_key):
        return
    st.caption(message)
    st.session_state[notice_key] = True


_PIPELINE_HEADER_INCOMPLETE_TOKENS = (
    "incomplete",
    "missing",
    "no output",
    "not available",
    "not configured",
    "not selected",
    "not set",
    "unknown",
)
_PIPELINE_DATAFRAME_SUFFIXES = {
    ".csv",
    ".feather",
    ".json",
    ".jsonl",
    ".parquet",
    ".pickle",
    ".pkl",
    ".pq",
    ".tsv",
    ".xls",
    ".xlsx",
}
_PIPELINE_DATA_SOURCE_PATTERNS = tuple(
    f"*{suffix}" for suffix in sorted(_PIPELINE_DATAFRAME_SUFFIXES)
)
_PIPELINE_OUTPUT_EXCLUDED_NAMES = {
    STAGES_FILE_NAME,
    "notebook_import_pipeline_view.json",
    "pipeline_view.dot",
    "pipeline_view.json",
}
_PIPELINE_OUTPUT_EXCLUDED_DIRS = {
    ".git",
    ".ipynb_checkpoints",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}


def _filter_pipeline_dataframe_files(files: Iterable[Path]) -> List[Path]:
    return sorted(
        (
            Path(file)
            for file in files
            if Path(file).suffix.lower() in _PIPELINE_DATAFRAME_SUFFIXES
        ),
        key=str,
    )


def _pipeline_header_value_state(value: str, caption: str = "") -> str:
    normalized = f"{value or ''} {caption or ''}".strip().lower()
    if not normalized:
        return "incomplete"
    if any(token in normalized for token in _PIPELINE_HEADER_INCOMPLETE_TOKENS):
        return "incomplete"
    return "ready"


def _render_pipeline_header_card(
    label: str,
    value: str,
    caption: str = "",
    *,
    state: str | None = None,
) -> None:
    visual_state = state or _pipeline_header_value_state(value, caption)
    st.markdown(
        (
            f"<div class='agilab-header-card agilab-header-card--{visual_state}'>"
            f"<div class='agilab-header-label'>{html.escape(label)}</div>"
            f"<div class='agilab-header-value agilab-header-value--{visual_state}'>"
            f"{html.escape(str(value))}</div>"
            f"<div class='agilab-header-caption'>{html.escape(caption)}</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _format_pipeline_timestamp(timestamp: float | None, *, empty: str) -> str:
    if timestamp is None:
        return empty
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


def _scan_pipeline_output_files(root: Path, *, limit: int = 500) -> dict[str, Any]:
    if not root.exists():
        return {"count": 0, "dataframes": 0, "latest": None, "truncated": False}
    count = 0
    dataframes = 0
    latest: float | None = None
    truncated = False
    try:
        for current_root, dirs, files in os.walk(root):
            dirs[:] = sorted(dirname for dirname in dirs if dirname not in _PIPELINE_OUTPUT_EXCLUDED_DIRS)
            for filename in sorted(files):
                if filename.startswith(".") or filename in _PIPELINE_OUTPUT_EXCLUDED_NAMES:
                    continue
                path = Path(current_root) / filename
                count += 1
                if path.suffix.lower() in _PIPELINE_DATAFRAME_SUFFIXES:
                    dataframes += 1
                try:
                    latest = max(latest or path.stat().st_mtime, path.stat().st_mtime)
                except OSError:
                    pass
                if count >= limit:
                    truncated = True
                    raise StopIteration
    except StopIteration:
        pass
    except OSError:
        pass
    return {"count": count, "dataframes": dataframes, "latest": latest, "truncated": truncated}


def _latest_pipeline_workspace_mtime(root: Path, stages_file: Path) -> float | None:
    candidates: list[Path] = [stages_file]
    if root.exists():
        try:
            for current_root, dirs, files in os.walk(root):
                dirs[:] = sorted(dirname for dirname in dirs if dirname not in _PIPELINE_OUTPUT_EXCLUDED_DIRS)
                for filename in sorted(files):
                    if filename.startswith("."):
                        continue
                    candidates.append(Path(current_root) / filename)
        except OSError:
            pass
    latest: float | None = None
    for path in candidates:
        try:
            latest = max(latest or path.stat().st_mtime, path.stat().st_mtime)
        except OSError:
            continue
    return latest


def _pipeline_graph_shape_from_json(source: Path) -> tuple[int, int] | None:
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    nodes = payload.get("nodes")
    edges = payload.get("edges", payload.get("links"))
    node_count = len(nodes) if isinstance(nodes, list) else 0
    edge_count = len(edges) if isinstance(edges, list) else 0
    if node_count or edge_count:
        return node_count, edge_count
    return None


def _pipeline_graph_shape_from_dot(dot: str) -> tuple[int, int] | None:
    if not dot.strip():
        return None
    nodes: set[str] = set()
    edge_count = 0
    edge_re = re.compile(r'^\s*("?[\w:.\-/]+"?)\s*->\s*("?[\w:.\-/]+"?)', re.MULTILINE)
    node_re = re.compile(r'^\s*("?[\w:.\-/]+"?)\s*\[', re.MULTILINE)
    for match in edge_re.finditer(dot):
        edge_count += 1
        nodes.add(match.group(1).strip('"'))
        nodes.add(match.group(2).strip('"'))
    for match in node_re.finditer(dot):
        node = match.group(1).strip('"')
        if node not in {"graph", "node", "edge"}:
            nodes.add(node)
    if nodes or edge_count:
        return len(nodes), edge_count
    return None


def _pipeline_graph_shape_summary(
    *,
    conceptual_source: Path | None,
    conceptual_dot: str,
    execution_nodes: int,
) -> tuple[str, str, str]:
    shape: tuple[int, int] | None = None
    if conceptual_source and conceptual_source.suffix.lower() == ".json":
        shape = _pipeline_graph_shape_from_json(conceptual_source)
    if shape is None and conceptual_dot:
        shape = _pipeline_graph_shape_from_dot(conceptual_dot)

    if shape is not None:
        nodes, links = shape
        source_label = conceptual_source.name if conceptual_source else "conceptual view"
        return f"{nodes}/{links}", f"{source_label}: stages / dependencies", "ready" if nodes else "incomplete"

    execution_links = max(execution_nodes - 1, 0)
    return (
        f"{execution_nodes}/{execution_links}",
        "execution order: stages / dependencies",
        "ready" if execution_nodes else "incomplete",
    )


def _render_pipeline_workspace_overview(env: AgiEnv, lab_dir: Path, stages_file: Path) -> None:
    stages = get_stages_list(lab_dir, stages_file)
    total_stages = len(stages)
    dict_stages = [entry for entry in stages if isinstance(entry, dict)]
    displayable_stages = sum(1 for entry in dict_stages if _is_displayable_stage(entry))
    runnable_stages = sum(1 for entry in dict_stages if _is_runnable_stage(entry))
    output_summary = _scan_pipeline_output_files(lab_dir)
    output_count = int(output_summary["count"])
    dataframe_count = int(output_summary["dataframes"])
    output_suffix = "+" if output_summary["truncated"] else ""
    conceptual_source, conceptual_dot = load_pipeline_conceptual_dot(env, lab_dir)
    graph_value, graph_caption, graph_state = _pipeline_graph_shape_summary(
        conceptual_source=conceptual_source,
        conceptual_dot=conceptual_dot,
        execution_nodes=displayable_stages,
    )
    workspace_updated = _latest_pipeline_workspace_mtime(lab_dir, stages_file)

    with st.container(border=True):
        top_cols = st.columns(3)
        with top_cols[0]:
            _render_pipeline_header_card(
                "Workflow stages",
                f"{displayable_stages}/{total_stages}",
                "visible / stored",
                state="ready" if total_stages else "incomplete",
            )
        with top_cols[1]:
            _render_pipeline_header_card(
                "Runnable",
                str(runnable_stages),
                "stages with executable code",
                state="ready" if runnable_stages else "incomplete",
            )
        with top_cols[2]:
            _render_pipeline_header_card(
                "Output files",
                f"{output_count}{output_suffix}",
                _format_pipeline_timestamp(output_summary["latest"], empty="no output yet"),
                state="ready" if output_count else "incomplete",
            )

        bottom_cols = st.columns(3)
        with bottom_cols[0]:
            _render_pipeline_header_card(
                "Dataframes",
                str(dataframe_count),
                "previewable table files",
                state="ready" if dataframe_count else "incomplete",
            )
        with bottom_cols[1]:
            _render_pipeline_header_card(
                "Workflow graph",
                graph_value,
                graph_caption,
                state=graph_state,
            )
        with bottom_cols[2]:
            _render_pipeline_header_card(
                "Updated",
                _format_pipeline_timestamp(workspace_updated, empty="not available"),
                lab_dir.name,
                state="neutral" if workspace_updated else "incomplete",
            )


def _load_about_page_module():
    """Load the main page module using import fallback for source and packaged layouts."""
    return _load_about_page_module_impl(__file__, load_module=load_local_module)


def page() -> None:
    """Main page logic handler."""
    global df_file

    env = _ensure_page_env(
        st,
        __file__,
        init_done_default=False,
        load_module=load_local_module,
    )
    if env is None:
        return

    if "openai_api_key" not in st.session_state:
        seed_key = env.envars.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
        if seed_key:
            st.session_state["openai_api_key"] = seed_key

    st.session_state["lab_prompt"] = _load_pre_prompt_messages(env)

    sidebar_controls()

    # Use the stages file parent as the concrete lab directory path
    lab_dir = Path(st.session_state["stages_file"]).parent
    index_page = st.session_state.get("index_page", lab_dir)
    index_page_str = str(index_page)
    stages_file = st.session_state["stages_file"]
    stages_file.parent.mkdir(parents=True, exist_ok=True)
    restored_source = st.session_state.pop("_pipeline_stages_restored_from", "")
    if restored_source:
        st.info(f"Restored missing Workflow stages from `{restored_source}`.")

    nstages = len(get_stages_list(lab_dir, stages_file))
    _render_pipeline_workspace_overview(env, lab_dir, stages_file)
    st.session_state.setdefault(index_page_str, [nstages, "", "", "", "", "", nstages])
    st.session_state.setdefault(f"{index_page_str}__details", {})
    st.session_state.setdefault(f"{index_page_str}__venv_map", {})
    st.session_state.setdefault(f"{index_page_str}__engine_map", {})

    module_path = st.session_state["module_path"]
    _render_notebook_actions(
        env,
        module_path,
        stages_file,
        index_page_str,
        project_name=Path(st.session_state.get("lab_dir_selectbox", env.target)).name,
    )
    # If a prompt clear was requested, clear the current revisioned key before loading the stage
    if st.session_state.pop(f"{index_page_str}__clear_q", False):
        q_rev = st.session_state.get(f"{index_page_str}__q_rev", 0)
        st.session_state.pop(f"{index_page_str}_q__{q_rev}", None)
    load_last_stage(module_path, stages_file, index_page_str)

    df_file = st.session_state.get("df_file")
    if not is_dag_based_app(env, index_page_str) and (not df_file or not Path(df_file).exists()):
        default_df_path = (lab_dir / DEFAULT_DF).resolve()
        _caption_once(
            f"missing_df::{lab_dir}",
            f"No workflow dataframe found for {lab_dir.name} yet. "
            f"Only data-dependent stages need `{default_df_path}`.",
        )
        st.session_state["df_file"] = None

    mlflow_controls()
    gpt_oss_controls(env)
    universal_offline_controls(env)

    lab_deps = PipelineLabDeps(
        load_all_stages=load_all_stages,
        save_stage=save_stage,
        remove_stage=remove_stage,
        force_persist_stage=_force_persist_stage,
        capture_pipeline_snapshot=_capture_pipeline_snapshot,
        restore_pipeline_snapshot=_restore_pipeline_snapshot,
        run_all_stages=run_all_stages,
        prepare_run_log_file=_prepare_run_log_file,
        get_run_placeholder=_get_run_placeholder,
        push_run_log=_push_run_log,
        rerun_fragment_or_app=_rerun_fragment_or_app,
        bump_history_revision=_bump_history_revision,
        ask_gpt=ask_gpt,
        configure_assistant_engine=configure_assistant_engine,
        maybe_autofix_generated_code=_maybe_autofix_generated_code,
        load_df_cached=load_df_cached,
        ensure_safe_service_template=_ensure_safe_service_template,
        inspect_pipeline_run_lock=_inspect_pipeline_run_lock,
        refresh_pipeline_run_lock=_refresh_pipeline_run_lock,
        acquire_pipeline_run_lock=_acquire_pipeline_run_lock,
        release_pipeline_run_lock=_release_pipeline_run_lock,
        label_for_stage_runtime=_label_for_stage_runtime,
        python_for_stage=_python_for_stage,
        python_for_venv=_python_for_venv,
        stream_run_command=lambda *args, **kwargs: _stream_run_command(
            *args,
            push_run_log=_push_run_log,
            ansi_escape_re=ANSI_ESCAPE_RE,
            jump_exception_cls=JumpToMain,
            **kwargs,
        ),
        run_locked_stage=_run_locked_stage,
        load_pipeline_conceptual_dot=load_pipeline_conceptual_dot,
        render_pipeline_view=render_pipeline_view,
        default_df=DEFAULT_DF,
        safe_service_template_filename=SAFE_SERVICE_START_TEMPLATE_FILENAME,
        safe_service_template_marker=SAFE_SERVICE_START_TEMPLATE_MARKER,
    )

    display_lab_tab(lab_dir, index_page_str, stages_file, module_path, env, lab_deps)
    # Disabled per request to hide the lab_stages.toml expander from the main UI.
    # display_history_tab(stages_file, module_path)


@st.cache_data
def get_df_files(export_abs_path: Path) -> List[Path]:
    return find_files(export_abs_path)


@st.cache_data
def load_df_cached(path: Path, nrows: int = 50, with_index: bool = True) -> Optional[pd.DataFrame]:
    return load_df(path, nrows, with_index)


def main() -> None:
    env = _ensure_page_env(st, __file__, load_module=load_local_module)
    if env is None:
        return

    env: AgiEnv = st.session_state['env']

    try:
        st.set_page_config(
            page_title="AGILab WORKFLOW",
            layout="wide",
            menu_items=get_docs_menu_items(html_file="experiment-help.html"),
        )
        inject_theme(env.st_resources)

        st.session_state.setdefault("stages_file_name", STAGES_FILE_NAME)
        st.session_state.setdefault("help_path", Path(env.agilab_pck) / "gui/help")
        st.session_state.setdefault("projects", env.apps_path)
        st.session_state.setdefault("snippet_file", Path(env.AGILAB_LOG_ABS) / "lab_snippet.py")
        st.session_state.setdefault("server_started", False)
        st.session_state.setdefault("mlflow_port", 5000)
        st.session_state.setdefault("lab_selected_venv", "")

        df_dir_def = _pipeline_export_root(env) / env.target
        st.session_state.setdefault("stages_file", Path(env.active_app) / STAGES_FILE_NAME)
        st.session_state.setdefault("df_file_out", str(df_dir_def / DEFAULT_DF))
        st.session_state.setdefault("df_file", str(df_dir_def / DEFAULT_DF))

        df_file = Path(st.session_state["df_file"]) if st.session_state["df_file"] else None
        if df_file:
            render_logo()
        else:
            render_logo()
        render_pinned_expanders(st)
        render_page_context(st, page_label="WORKFLOW", env=env)

        if background_services_enabled() and not st.session_state.get("server_started", False):
            activate_mlflow(env)

        # Initialize session defaults
        defaults = {
            "response_dict": {"type": "", "text": ""},
            "apps_abs": env.apps_path,
            "page_broken": False,
            "stage_checked": False,
            "virgin_page": True,
        }
        for key, value in defaults.items():
            st.session_state.setdefault(key, value)

        page()

    except (RuntimeError, OSError, TypeError, ValueError, AttributeError, KeyError) as e:
        st.error(f"An error occurred: {e}")
        import traceback

        st.caption("Full traceback")
        st.code(traceback.format_exc(), language="text")


if __name__ == "__main__":
    main()
