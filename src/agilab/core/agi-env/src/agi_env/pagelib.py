# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
# Co-author: Codex cli
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
# 3. Neither the name of Jean-Pierre Morard nor the names of its contributors, or THALES SIX GTS France SAS, may be used to endorse or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import re
import json
from pathlib import Path
from functools import lru_cache
import pandas as pd
import os
import sqlite3
import subprocess
import time
import random
import socket
import runpy
from typing import Dict, Optional
import sys
import logging
from ._optional_ui import require_streamlit
from . import mlflow_store
from .pagelib_execution_support import (
    run_agi as _run_agi_impl,
    run_lab as _run_lab_impl,
)
from .pagelib_runtime_support import (
    activate_gpt_oss as _activate_gpt_oss_impl,
    activate_mlflow as _activate_mlflow_impl,
    get_random_port as _get_random_port_impl,
    is_port_in_use as _is_port_in_use_impl,
    next_free_port as _next_free_port_impl,
    run as _run_impl,
    run_with_output as _run_with_output_impl,
    subproc as _subproc_impl,
    wait_for_listen_port as _wait_for_listen_port_impl,
)
from .ui_support import (
    _GLOBAL_STATE_FILE,
    _LEGACY_LAST_APP_FILE,
    _dump_toml_payload,
    detect_agilab_version as _detect_agilab_version,
    focus_existing_docs_tab as _focus_existing_docs_tab,
    load_global_state as _load_global_state,
    load_last_active_app,
    open_docs,
    open_docs_url as _open_docs_url,
    open_local_docs,
    persist_global_state as _persist_global_state,
    read_base64_image,
    read_css_text,
    read_theme_css,
    read_version_from_pyproject as _read_version_from_pyproject,
    resolve_docs_path as _resolve_docs_path,
    store_last_active_app,
    with_anchor as _with_anchor,
)
from .source_analysis_support import (
    get_class_methods as extract_class_methods,
    get_classes_name as extract_class_names,
    get_functions_and_attributes,
    extract_base_info as _extract_base_info,
    get_full_attribute_name as _get_full_attribute_name,
    get_import_mapping as _get_import_mapping,
)
from .pagelib_data_support import (
    find_files as _find_files_impl,
    get_df_index as _get_df_index_impl,
    get_first_match_and_keyword as _get_first_match_and_keyword_impl,
    list_views as _list_views_impl,
    load_df as _load_df_impl,
    read_file_lines as _read_file_lines_impl,
    scan_dir as _scan_dir_impl,
)
from .pagelib_navigation_support import (
    active_app_candidates,
    build_project_selection,
    build_sidebar_dataframe_selection,
    clear_dataframe_selection_state,
    copy_widget_value,
    ensure_csv_files_state,
    normalize_query_param_value,
    resolve_default_selection,
    resolve_selected_df_path,
)
from .pagelib_project_support import (
    init_custom_ui as _init_custom_ui_impl,
    on_project_change as _on_project_change_impl,
)
from .pagelib_selection_support import (
    on_df_change as _on_df_change_impl,
    resolve_active_app as _resolve_active_app_impl,
    select_project as _select_project_impl,
    sidebar_views as _sidebar_views_impl,
)
from .pagelib_preview_support import (
    build_dataframe_preview,
    resolve_export_target,
    resolve_preview_nrows,
)
from .pagelib_resource_support import (
    about_content_payload,
    load_json_resource,
)
from .pagelib_session_support import (
    clear_project_session_state,
    reset_project_sections,
)
logger = logging.getLogger(__name__)
st = require_streamlit()

DEFAULT_DF_PREVIEW_MAX_ROWS = 1000
DEFAULT_DF_PREVIEW_MAX_COLS = 40
DEFAULT_MLFLOW_EXPERIMENT_NAME = "Default"
DEFAULT_MLFLOW_DB_NAME = "mlflow.db"
DEFAULT_MLFLOW_ARTIFACT_DIR = "artifacts"
_MLFLOW_SQLITE_UPGRADE_CHECKED: set[str] = set()
_MLFLOW_SCHEMA_RESET_MARKERS = (
    "Can't locate revision identified by",
    "No such revision or branch",
    "duplicate column name:",
)
def background_services_enabled() -> bool:
    """Return False under automated UI tests or when explicitly disabled."""
    if st.session_state.get("mlflow_autostart_disabled"):
        return False
    disable_flag = os.getenv("AGILAB_DISABLE_BACKGROUND_SERVICES", "").strip().lower()
    if disable_flag in {"1", "true", "yes", "on"}:
        return False
    testing_state = st.session_state.get("$$STREAMLIT_INTERNAL_KEY_TESTING")
    return not bool(testing_state)


def _get_mlflow_module():
    return mlflow_store.get_mlflow_module()


def _resolve_mlflow_tracking_dir(env) -> Path:
    return mlflow_store.resolve_mlflow_tracking_dir(env, home_factory=Path.home, path_cls=Path)


def _resolve_mlflow_backend_db(tracking_dir: Path) -> Path:
    return mlflow_store.resolve_mlflow_backend_db(
        tracking_dir,
        default_db_name=DEFAULT_MLFLOW_DB_NAME,
    )


def _resolve_mlflow_artifact_dir(tracking_dir: Path) -> Path:
    return mlflow_store.resolve_mlflow_artifact_dir(
        tracking_dir,
        default_artifact_dir=DEFAULT_MLFLOW_ARTIFACT_DIR,
    )


def _sqlite_uri_for_path(db_path: Path) -> str:
    return mlflow_store.sqlite_uri_for_path(db_path, os_name=os.name, path_cls=Path)


def _legacy_mlflow_filestore_present(tracking_dir: Path) -> bool:
    return mlflow_store.legacy_mlflow_filestore_present(
        tracking_dir,
        default_db_name=DEFAULT_MLFLOW_DB_NAME,
        default_artifact_dir=DEFAULT_MLFLOW_ARTIFACT_DIR,
    )


def _sqlite_identifier(name: str) -> str:
    return mlflow_store.sqlite_identifier(name)


def _repair_mlflow_default_experiment_db(db_path: Path, artifact_uri: str | None = None) -> bool:
    return mlflow_store.repair_mlflow_default_experiment_db(
        db_path,
        default_experiment_name=DEFAULT_MLFLOW_EXPERIMENT_NAME,
        sqlite_identifier_fn=_sqlite_identifier,
        artifact_uri=artifact_uri,
    )


def _ensure_mlflow_sqlite_schema_current(db_path: Path) -> None:
    mlflow_store.ensure_mlflow_sqlite_schema_current(
        db_path,
        checked_uris=_MLFLOW_SQLITE_UPGRADE_CHECKED,
        sqlite_uri_for_path_fn=_sqlite_uri_for_path,
        schema_reset_markers=_MLFLOW_SCHEMA_RESET_MARKERS,
        reset_backend_fn=_reset_mlflow_sqlite_backend,
        run_cmd=subprocess.run,
        sys_executable=sys.executable,
    )


def _reset_mlflow_sqlite_backend(db_path: Path) -> Path | None:
    return mlflow_store.reset_mlflow_sqlite_backend(
        db_path,
        checked_uris=_MLFLOW_SQLITE_UPGRADE_CHECKED,
        sqlite_uri_for_path_fn=_sqlite_uri_for_path,
        timestamp_fn=lambda: time.strftime("%Y%m%d_%H%M%S", time.gmtime()),
    )


def _ensure_mlflow_backend_ready(tracking_dir: Path) -> str:
    return mlflow_store.ensure_mlflow_backend_ready(
        tracking_dir,
        resolve_mlflow_backend_db_fn=_resolve_mlflow_backend_db,
        legacy_mlflow_filestore_present_fn=_legacy_mlflow_filestore_present,
        sqlite_uri_for_path_fn=_sqlite_uri_for_path,
        ensure_mlflow_sqlite_schema_current_fn=_ensure_mlflow_sqlite_schema_current,
        resolve_mlflow_artifact_dir_fn=_resolve_mlflow_artifact_dir,
        repair_mlflow_default_experiment_db_fn=_repair_mlflow_default_experiment_db,
        run_cmd=subprocess.run,
        sys_executable=sys.executable,
    )


def _ensure_default_mlflow_experiment(tracking_dir: Path) -> str | None:
    return mlflow_store.ensure_default_mlflow_experiment(
        tracking_dir,
        get_mlflow_module_fn=_get_mlflow_module,
        resolve_mlflow_artifact_dir_fn=_resolve_mlflow_artifact_dir,
        resolve_mlflow_backend_db_fn=_resolve_mlflow_backend_db,
        ensure_mlflow_backend_ready_fn=_ensure_mlflow_backend_ready,
        reset_mlflow_sqlite_backend_fn=_reset_mlflow_sqlite_backend,
        default_experiment_name=DEFAULT_MLFLOW_EXPERIMENT_NAME,
        schema_reset_markers=_MLFLOW_SCHEMA_RESET_MARKERS,
    )


def _next_free_port() -> int:
    return _next_free_port_impl(
        get_random_port_fn=get_random_port,
        is_port_in_use_fn=is_port_in_use,
    )


def run_with_output(env, cmd, cwd="./", timeout=None):
    """Execute a command within a subprocess."""
    return _run_with_output_impl(
        env,
        cmd,
        cwd=cwd,
        timeout=timeout,
        path_cls=Path,
        os_module=os,
        popen_factory=subprocess.Popen,
        streamlit=st,
        jump_to_main_exc=JumpToMain,
    )


def is_valid_ip(ip: str) -> bool:
    """Return ``True`` when ``ip`` is a syntactically valid IPv4 address."""

    pattern = re.compile(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$")
    if pattern.match(ip):
        parts = ip.split(".")
        return all(0 <= int(part) <= 255 for part in parts)
    return False

class JumpToMain(Exception):
    """
    Custom exception to jump back to the main execution flow.
    """

    pass


def log(message):
    """
    Log an informational message.
    """
    logging.info(message)


def _current_mount_points() -> dict[Path, str]:
    """Return currently mounted directories mapped to their filesystem type."""

    mounts: dict[Path, str] = {}
    proc_mounts = Path("/proc/mounts")
    if proc_mounts.exists():
        try:
            for raw_line in proc_mounts.read_text(encoding="utf-8", errors="ignore").splitlines():
                parts = raw_line.split()
                if len(parts) < 3:
                    continue
                target = Path(parts[1]).expanduser().resolve(strict=False)
                mounts[target] = parts[2]
        except OSError as exc:
            logging.debug("Unable to read /proc/mounts: %s", exc)
        return mounts

    try:
        result = subprocess.run(
            ["mount"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        logging.debug("Unable to query current mount points: %s", exc)
        return {}

    for raw_line in result.stdout.splitlines():
        if " on " not in raw_line:
            continue
        try:
            _, remainder = raw_line.split(" on ", 1)
            target, details = remainder.split(" (", 1)
        except ValueError:
            continue
        target_path = target.strip()
        if not target_path:
            continue
        fstype = details.split(",", 1)[0].strip()
        mounts[Path(target_path).expanduser().resolve(strict=False)] = fstype
    return mounts


@lru_cache(maxsize=1)
def _fstab_mount_points() -> tuple[Path, ...]:
    """Return mount points declared in ``/etc/fstab`` (if the file exists)."""

    fstab = Path("/etc/fstab")
    if not fstab.exists():
        return tuple()

    mounts: list[Path] = []
    try:
        for raw_line in fstab.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            mounts.append(Path(parts[1]).expanduser())
    except OSError as exc:
        logging.debug("Unable to read /etc/fstab: %s", exc)
    return tuple(mounts)


def diagnose_data_directory(directory: Path) -> str | None:
    """Return a user-friendly explanation when ``directory`` is unavailable."""

    directory = Path(directory).expanduser()
    try:
        directory = directory.resolve(strict=False)
    except RuntimeError:
        directory = directory.absolute()
    mounts = _fstab_mount_points()
    current_mounts = _current_mount_points()

    for mount in mounts:
        try:
            mount_resolved = mount.expanduser().resolve(strict=False)
            directory.relative_to(mount_resolved)
        except ValueError:
            continue

        if not mount_resolved.exists():
            return (
                f"The data share at '{mount_resolved}' is not mounted; "
                "the shared file server may be down."
            )
        fstype = current_mounts.get(mount_resolved)
        if fstype is None:
            return (
                f"The data share at '{mount_resolved}' is not mounted; "
                "the shared file server may be down."
            )
        if fstype.lower() == "autofs":
            prefix = str(mount_resolved)
            if not prefix.endswith(os.sep):
                prefix += os.sep
            has_active_child = any(
                str(child).startswith(prefix) and fs.lower() != "autofs"
                for child, fs in current_mounts.items()
            )
            if not has_active_child:
                return (
                    f"The data share at '{mount_resolved}' is not mounted; "
                    "the shared file server may be down."
                )
        if mount_resolved.is_dir():
            try:
                next(mount_resolved.iterdir())
            except StopIteration:
                return (
                    f"The data share at '{mount_resolved}' appears empty; "
                    "ensure the shared file export is reachable."
                )
            except OSError:
                return (
                    f"The data share at '{mount_resolved}' is unreachable; "
                    "the shared file server may be down."
                )
        break
    return None


def run(command, cwd=None):
    """Execute a shell command."""
    _run_impl(command, cwd=cwd, subprocess_module=subprocess, log_fn=log, sys_module=sys)

def get_base64_of_image(image_path):
    try:
        return read_base64_image(image_path)
    except (OSError, TypeError) as exc:
        st.error(f"Error loading {image_path}: {exc}")
        return ""


@st.cache_data
def get_css_text():
    return read_css_text(st.session_state["env"].st_resources)


def inject_theme(base_path: Path | None = None) -> None:
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


def render_logo(*_args, **_kwargs):
    env = st.session_state.get("env")
    if env is None:
        return

    agilab_logo_path = env.st_resources / "agilab_logo.png"
    if agilab_logo_path.exists():
        logo_fn = getattr(st, "logo", None)
        if callable(logo_fn):
            logo_fn(str(agilab_logo_path), size="large")
        else:
            st.sidebar.image(str(agilab_logo_path), width=170)
        version = _detect_agilab_version(env)
        if version:
            render_sidebar_version(version)
    else:
        st.sidebar.warning("Logo could not be loaded. Please check the logo path.")


def subproc(command, cwd):
    """Execute a command in the background."""
    return _subproc_impl(command, cwd, subprocess_module=subprocess, os_module=os)


def _wait_for_listen_port(port: int, *, timeout_sec: float = 15.0, poll_interval_sec: float = 0.1) -> bool:
    return _wait_for_listen_port_impl(
        port,
        timeout_sec=timeout_sec,
        poll_interval_sec=poll_interval_sec,
        time_module=time,
        is_port_in_use_fn=is_port_in_use,
    )


def get_projects_zip():
    """
    Get a list of zip file names for projects.

    Returns:
        list: A list of zip file names for projects found in the env export_apps directory.
    """
    env = st.session_state["env"]
    return sorted(p.name for p in env.export_apps.glob("*.zip"))


def get_templates():
    """
    Get a list of template names.

    Returns:
        list: A list of template names (strings).
    """
    env = st.session_state["env"]
    candidates = []
    templates_root = env.apps_path / "templates"
    if templates_root.exists():
        candidates.extend(
            p.name
            for p in templates_root.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )

    agilab_templates = env.agilab_pck
    if agilab_templates:
        agilab_templates = Path(agilab_templates) / "agilab/templates"
        if agilab_templates.exists():
            candidates.extend(
                p.name
                for p in agilab_templates.iterdir()
                if p.is_dir() and not p.name.startswith(".")
            )

    if not candidates:
        candidates.extend(p.stem for p in env.apps_path.glob("*template"))

    return sorted(dict.fromkeys(candidates))


def get_about_content():
    """
    Get the Streamlit About-menu content.

    Returns:
        dict: A Streamlit menu item payload with the canonical AGILAB About text.
    """
    return about_content_payload()


def init_custom_ui(_form_path):
    _init_custom_ui_impl(st.session_state)
    return


def on_project_change(project, switch_to_select=False):
    """
    Callback function to handle project changes.

    Reset project-scoped session state, switch the active app, and re-seed the
    sidebar state for the newly selected project.
    """
    _on_project_change_impl(
        project,
        session_state=st.session_state,
        store_last_active_app_fn=store_last_active_app,
        clear_project_session_state_fn=clear_project_session_state,
        reset_project_sections_fn=reset_project_sections,
        error_fn=st.error,
        switch_to_select=switch_to_select,
        path_cls=Path,
    )


def is_port_in_use(target_port):
    """
    Check if a port is in use.

    Args:
        target_port: Port number to check.

    Returns:
        bool: True if the port is in use, False otherwise.
    """
    return _is_port_in_use_impl(target_port, socket_module=socket)


def get_random_port():
    """
    Generate a random port number between 8800 and 9900.

    Returns:
        int: A random port number between 8800 and 9900.
    """
    return _get_random_port_impl(random_module=random)



@st.cache_data
def find_files(directory, ext=".csv", recursive=True):
    """
    Finds all files with a specific extension in a directory and its subdirectories.

    Args:
        directory (Path): Root directory to search.
        ext (str): The file extension to search for.

    Returns:
        List[Path]: List of Path objects that match the given extension.
    """
    return _find_files_impl(
        directory,
        ext=ext,
        recursive=recursive,
        path_type=Path,
        diagnose_data_directory_fn=diagnose_data_directory,
    )



@st.cache_data
def get_custom_buttons():
    """
    Retrieve custom buttons data from a JSON file and cache the data.

    Returns:
        dict: Custom buttons data loaded from the JSON file.

    Notes:
        This function uses Streamlit's caching mechanism to avoid reloading the data each time it is called.
    """
    env = st.session_state["env"]
    return load_json_resource(Path(env.st_resources), "custom_buttons.json")


@st.cache_data
def get_info_bar():
    """
    Retrieve information from the 'info_bar.json' file and return the data as a dictionary.

    :return: Data read from the 'info_bar.json' file.
    :rtype: dict

    :note: This function is cached using Streamlit's st.cache_data decorator to prevent unnecessary file reads.

    :raise FileNotFoundError: If the 'info_bar.json' file cannot be found.
    """
    env = st.session_state["env"]
    return load_json_resource(Path(env.st_resources), "info_bar.json")


def export_df():
    """
    Export the loaded DataFrame to a CSV file.

    Checks if the loaded DataFrame exists in the session state and exports it to a CSV file specified in the session state. If the DataFrame is empty, a warning message is displayed.

    Args:
        None

    Returns:
        None

    Raises:
        None
    """
    df = st.session_state.get("loaded_df")
    target = st.session_state.get("df_file_out", "")

    if df is None:
        st.warning("DataFrame is empty. Nothing to export.")
        return

    if save_csv(df, target):
        st.success(f"Saved to {target}!")
    else:
        st.warning("Export failed; please check the filename and dataframe content.")

def get_fcts_and_attrs_name(src_path: str | Path, class_name: Optional[str] = None) -> Dict[str, list[str]]:
    """Compatibility wrapper over the pure source-analysis helper."""
    return get_functions_and_attributes(src_path, class_name=class_name)


def get_classes_name(src_path):
    """Compatibility wrapper over the pure source-analysis helper."""
    return extract_class_names(src_path)


def get_class_methods(src_path: Path, class_name: str) -> list[str]:
    """Compatibility wrapper over the pure source-analysis helper."""
    return extract_class_methods(src_path, class_name)


def get_import_mapping(source: str, *, logger=None):
    """Compatibility wrapper for source-analysis import mapping."""
    return _get_import_mapping(source, logger=logger)


def extract_base_info(base, import_mapping):
    """Compatibility wrapper for extracting AST base-class metadata."""
    return _extract_base_info(base, import_mapping)


def get_full_attribute_name(node):
    """Compatibility wrapper for reconstructing dotted AST attributes."""
    return _get_full_attribute_name(node)


def run_agi(code, path="."):
    """
    Run code in the core environment.

    Args:
        code (str): The code to execute.
        env: The environment configuration object.
        id_core (int): Core identifier.
        path (str): The working directory.
    """
    return _run_agi_impl(
        code,
        env=st.session_state["env"],
        path=path,
        streamlit=st,
        logger=logger,
        run_with_output_fn=run_with_output,
        diagnose_data_directory_fn=diagnose_data_directory,
        path_cls=Path,
        re_module=re,
    )


def run_lab(query, snippet, codex, *, env_overrides=None):
    """
    Run gui code.

    Args:
        query: The query data.
        snippet: The snippet file path.
        codex: The codex script path.
    """
    return _run_lab_impl(
        query,
        snippet,
        codex,
        env_overrides=env_overrides,
        warning_fn=st.warning,
        os_module=os,
        sys_module=sys,
        runpy_module=runpy,
    )


@st.cache_data
def cached_load_df(path, with_index=True, nrows=None):
    """Convenience wrapper that honors TABLE_MAX_ROWS for lightweight previews."""
    df_max_rows = resolve_preview_nrows(
        nrows,
        st.session_state.get("TABLE_MAX_ROWS") if "TABLE_MAX_ROWS" in st.session_state else None,
    )

    return load_df(path, with_index=with_index, nrows=df_max_rows)


def render_dataframe_preview(
    df: pd.DataFrame,
    *,
    max_rows: int = DEFAULT_DF_PREVIEW_MAX_ROWS,
    max_cols: int = DEFAULT_DF_PREVIEW_MAX_COLS,
    width: str = "stretch",
    hide_index: bool = False,
    truncation_label: Optional[str] = None,
    **dataframe_kwargs,
) -> None:
    """Render a bounded dataframe preview to avoid oversized Streamlit payloads."""
    preview, caption = build_dataframe_preview(
        df,
        max_rows=max_rows,
        max_cols=max_cols,
        truncation_label=truncation_label,
    )
    st.dataframe(preview, width=width, hide_index=hide_index, **dataframe_kwargs)
    if caption:
        st.caption(caption)

def get_first_match_and_keyword(string_list, keywords_to_find):
    """
    Finds the first occurrence of any keyword in any string.
    Returns a tuple: (actual_matched_substring, found_keyword_pattern)
    - actual_matched_substring: The segment from the string that matched.
    - found_keyword_pattern: The keyword from keywords_to_find that matched.

    Search is case-insensitive.
    Returns (None, None) if no keyword is found in any string.
    """
    return _get_first_match_and_keyword_impl(string_list, keywords_to_find)
@st.cache_data
def load_df(path: Path, nrows=None, with_index=True, cache_buster=None):
    """
    Load data from a specified path. Supports loading from CSV and Parquet files.

    Args:
        path (Path): The path to the file or directory.
        nrows (int, optional): Number of rows to read from the file (for CSV files only).
        with_index (bool): Whether to set the "date" column as the DataFrame's index.
        cache_buster (Any): Unused sentinel that forces Streamlit to refresh the cache
            whenever callers pass a different value (for example a file timestamp).

    Returns:
        pd.DataFrame or None: The loaded DataFrame or None if no valid files are found.
    """
    return _load_df_impl(path, nrows=nrows, with_index=with_index, cache_buster=cache_buster, path_type=Path)



def save_csv(df, path: Path, sep=",") -> bool:
    """
    Save a DataFrame to a CSV file.

    Args:
        df (DataFrame): The DataFrame to save.
        path (Path): The file path to save the CSV.
        sep (str): The separator to use in the CSV file.
    """
    path, error_message = resolve_export_target(path)
    if error_message:
        st.error(error_message)
        return False
    assert path is not None
    if df.shape[1] == 0:
        return False
    logger.info(f"mkdir {path.parent}")
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, sep=sep, index=False)
    # Bust cached directory listings so dependent pages (Experiment, Explore) pick up new exports immediately.
    try:
        find_files.clear()
    except (AttributeError, RuntimeError):
        pass
    return True


def get_df_index(df_files, df_file):
    """
    Get the index of a DataFrame file in a list of files.

    Args:
        df_files (list): List of DataFrame file paths.
        df_file (Path): The DataFrame file to find.

    Returns:
        int or None: The index if found, else None.
    """
    return _get_df_index_impl(df_files, df_file)


@lru_cache(maxsize=None)
def list_views(views_root):
    """
    List all view Python files in the pages directory.

    Args:
        views_root (Path): The root directory of pages.

    Returns:
        list: Sorted list of view file paths.
    """
    return _list_views_impl(views_root)


def read_file_lines(filepath):
    """
    Read lines from a file.

    Args:
        filepath (Path): The path to the file.

    Returns:
        generator: Generator yielding lines from the file.
    """
    return _read_file_lines_impl(filepath)


def handle_go_action(view_module, view_path):
    """
    Handle the action when a "Go" button is clicked for a specific view.

    Args:
        view_module (str): The name of the view module.
        view_path (Path): The path to the view.
    """
    st.success(f"'Go' button clicked for view: {view_module}")
    st.write(f"View Path: {view_path}")
    # Implement your desired functionality here.


def update_views(project, pages):
    """
    Create and remove hard links according to pages checkbox.

    Args:
        project (str): The project name.
        pages (list): The currently selected pages.

    Returns:
        bool: True if an update was required, False otherwise.
    """
    update_required = False
    env = st.session_state._env
    env.change_app(project)
    st.session_state.preview_tree = False

    pages_root = Path(os.getcwd()) / "src/gui/pages"
    existing_pages = set(os.listdir(pages_root))

    expected_pages = set()
    for view_abs in pages:
        view_abs_path = Path(view_abs)
        page_name = f"{view_abs_path.stem}.py"
        expected_pages.add(page_name)

        page_link = pages_root / page_name
        if not page_link.exists():
            update_required = True
            os.link(view_abs_path, page_link)

    for page in existing_pages:
        page_abs = pages_root / page
        try:
            if page not in expected_pages and os.stat(page_abs).st_nlink > 1:
                os.remove(page_abs)
                update_required = True
        except FileNotFoundError:
            continue

    return update_required


def initialize_csv_files():
    """
    Initialize CSV files in the data directory.
    """
    discovered_files = st.session_state.get("csv_files") or find_files(st.session_state.datadir)
    ensure_csv_files_state(st.session_state, Path(st.session_state.datadir), discovered_files)


def update_var(var_key, widget_key):
    """
    Args:
        var_key: Description of var_key.
        widget_key: Description of widget_key.

    Returns:
        Description of the return value.
    """
    copy_widget_value(st.session_state, var_key, widget_key)


def update_datadir(var_key, widget_key):
    """
    Update the data directory and reinitialize CSV files.

    Args:
        var_key: The key of the variable to update.
        widget_key: The key of the widget whose value will be used.
    """
    clear_dataframe_selection_state(st.session_state)
    update_var(var_key, widget_key)
    initialize_csv_files()


def select_project(projects, current_project):
    return _select_project_impl(
        projects,
        current_project,
        session_state=st.session_state,
        sidebar=st.sidebar,
        build_project_selection_fn=build_project_selection,
        on_project_change_fn=on_project_change,
    )


def resolve_active_app(env, preferred_base: Path | None = None) -> tuple[str, bool]:
    return _resolve_active_app_impl(
        env,
        query_params=st.query_params,
        normalize_query_param_value_fn=normalize_query_param_value,
        active_app_candidates_fn=active_app_candidates,
        store_last_active_app_fn=store_last_active_app,
        load_last_active_app_fn=load_last_active_app,
        preferred_base=preferred_base,
        path_cls=Path,
    )


def open_new_tab(url):
    # JavaScript to open a new tab
    """
    Open a new tab in the browser with the given URL.

    Args:
        url (str): The URL of the page to be opened in a new tab.

    Returns:
        None

    Note:
        This function uses Streamlit's `st.markdown` function and HTML
        to execute JavaScript code to open a new tab.

    Example:
        open_new_tab('http://www.example.com')
    """
    js = f"window.open('{url}');"
    # Inject the JavaScript into the Streamlit app
    st.markdown(f"<script>{js}</script>", unsafe_allow_html=True)


def scan_dir(path):
    """
    Scan a directory and list its subdirectories.

    Args:
        path (Path): The directory path.

    Returns:
        list: List of subdirectory names.
    """
    return _scan_dir_impl(path)


def sidebar_views():
    return _sidebar_views_impl(
        session_state=st.session_state,
        sidebar=st.sidebar,
        scan_dir_fn=scan_dir,
        find_files_fn=find_files,
        resolve_default_selection_fn=resolve_default_selection,
        build_sidebar_dataframe_selection_fn=build_sidebar_dataframe_selection,
        on_lab_change_fn=on_lab_change,
        on_df_change_fn=on_df_change,
        path_cls=Path,
    )


def load_last_stage(_module_dir, _stages_file, _index_page_str):
    """Optional hook used by legacy sidebar integrations after dataframe changes."""
    return None


def on_df_change(module_dir, index_page, df_file=None, stages_file=None):
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


def activate_mlflow(env=None):
    return _activate_mlflow_impl(
        env,
        session_state=st.session_state,
        streamlit=st,
        logger=logger,
        resolve_mlflow_tracking_dir_fn=_resolve_mlflow_tracking_dir,
        ensure_default_mlflow_experiment_fn=_ensure_default_mlflow_experiment,
        ensure_mlflow_backend_ready_fn=_ensure_mlflow_backend_ready,
        resolve_mlflow_artifact_dir_fn=_resolve_mlflow_artifact_dir,
        next_free_port_fn=_next_free_port,
        wait_for_listen_port_fn=_wait_for_listen_port,
        subproc_fn=subproc,
        cwd=os.getcwd(),
    )


def activate_gpt_oss(env=None):
    """Spin up a local GPT-OSS responses server (stub backend) if available."""
    return _activate_gpt_oss_impl(
        env,
        session_state=st.session_state,
        streamlit=st,
        next_free_port_fn=_next_free_port,
        subproc_fn=subproc,
        cwd=os.getcwd(),
        os_module=os,
        sys_module=sys,
    )
