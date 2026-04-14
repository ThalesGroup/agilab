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
import io
from pathlib import Path
from functools import lru_cache
import pandas as pd
import os
import sqlite3
import subprocess
import streamlit as st
import time
import random
import socket
import runpy
from typing import Dict, Optional
import sys
import logging
import shlex
from . import mlflow_store
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
    port = get_random_port()
    while is_port_in_use(port):
        port = get_random_port()
    return port


def run_with_output(env, cmd, cwd="./", timeout=None):
    """
    Execute a command within a subprocess.
    """
    os.environ["uv_IGNORE_ACTIVE_VENV"] = "1"
    process_env = os.environ.copy()

    with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=True,
            cwd=Path(cwd).absolute(),
            env=process_env,
            text=True,
    ) as proc:
        try:
            outs, _ = proc.communicate(timeout=timeout)
            if "module not found" in outs:
                if not (env.apps_path / ".venv").exists():
                    raise JumpToMain(outs)
            elif proc.returncode or "failed" in outs.lower() or "error" in outs.lower():
                pass

        except subprocess.TimeoutExpired as err:
            proc.kill()
            outs, _ = proc.communicate()
            st.error(err)

        except subprocess.CalledProcessError as err:
            outs, _ = proc.communicate()
            st.error(err)

        # Process the output and remove ANSI escape codes
        return re.sub(r"\x1b[^m]*m", "", outs)


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
    """
    Execute a shell command.

    Args:
        command (str): The command to execute.
        cwd (str, optional): The working directory to execute the command in.

    Raises:
        subprocess.CalledProcessError: If the command exits with a non-zero status.
    """
    try:
        subprocess.run(
            command,
            shell=True,
            check=True,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        log(f"Executed: {command}")
    except subprocess.CalledProcessError as e:
        log(f"Error executing command: {command}")
        log(f"Exit Code: {e.returncode}")
        log(f"Output: {e.output.decode().strip()}")
        log(f"Error Output: {e.stderr.decode().strip()}")
        sys.exit(e.returncode)

def get_base64_of_image(image_path):
    try:
        return read_base64_image(image_path)
    except (OSError, TypeError) as exc:
        st.error(f"Error loading {image_path}: {exc}")
        return ""


@st.cache_data
def get_css_text():
    return read_css_text(st.session_state["env"].st_resources)


@st.cache_resource
def inject_theme(base_path: Path | None = None) -> None:
    css = read_theme_css(base_path, module_file=__file__)
    if css is not None:
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def render_logo(*_args, **_kwargs):
    env = st.session_state.get("env")
    if env is None:
        return

    agilab_logo_path = env.st_resources / "agilab_logo.png"
    if agilab_logo_path.exists():
        st.sidebar.image(str(agilab_logo_path), width=170)
        version = _detect_agilab_version(env)
        if version:
            st.sidebar.caption(f"v{version}")
    else:
        st.sidebar.warning("Logo could not be loaded. Please check the logo path.")


def subproc(command, cwd):
    """
    Execute a command in the background.

    Args:
        command (str): The command to be executed.
        cwd (str): The current working directory where the command will be executed.

    Returns:
        None
    """
    return subprocess.Popen(
        command,
        shell=True,
        cwd=os.path.abspath(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ).stdout


def _wait_for_listen_port(port: int, *, timeout_sec: float = 5.0, poll_interval_sec: float = 0.1) -> bool:
    deadline = time.monotonic() + max(timeout_sec, 0.0)
    while time.monotonic() < deadline:
        if is_port_in_use(port):
            return True
        time.sleep(max(poll_interval_sec, 0.01))
    return is_port_in_use(port)


def get_projects_zip():
    """
    Get a list of zip file names for projects.

    Returns:
        list: A list of zip file names for projects found in the env export_apps directory.
    """
    env = st.session_state["env"]
    return [p.name for p in env.export_apps.glob("*.zip")]


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
    Get the content of the 'About' section.

    Returns:
        dict: A dictionary containing information about the Agi&trade; agilab.

            'About': str
                A string containing information about the Agi&trade; agilab.

                    ':blue[Agi&trade;] V5\n\n:blue[S]peedy :blue[Py]thon :blue[D]istributed  agilab for Data Science  2020-2024 \n\nThales SIX GTS France SAS \n\nsupport: open a GitHub issue'
    """
    return about_content_payload()


def init_custom_ui(_form_path):
    """Keep edit-mode toggles in sync and signal app-args forms to refresh."""
    toggle_ui = bool(st.session_state.get("toggle_edit_ui", False))
    # `toggle_edit_ui=True` means ORCHESTRATE generic editor is active.
    # App-specific forms use `toggle_edit=True` for their guided editor branch,
    # so keep this state inverted when switching back to custom forms.
    st.session_state["toggle_edit"] = not toggle_ui
    # Reset custom form widget state on each mode switch so non-edit mode reloads
    # persisted args instead of stale in-memory values.
    for key in list(st.session_state.keys()):
        if ":app_args_form:" in key:
            del st.session_state[key]
    st.session_state["app_args_form_refresh_nonce"] = (
        int(st.session_state.get("app_args_form_refresh_nonce", 0)) + 1
    )
    return


def on_project_change(project, switch_to_select=False):
    """
    Callback function to handle project changes.

    Reset project-scoped session state, switch the active app, and re-seed the
    sidebar state for the newly selected project.
    """
    env = st.session_state["env"]
    session_state = st.session_state
    clear_project_session_state(session_state)

    try:
        env.change_app(env.apps_path / project)
        module = env.target
        try:
            store_last_active_app(env.active_app)
        except (OSError, RuntimeError):
            pass

        session_state.module_rel = Path(module)
        session_state.datadir = env.AGILAB_EXPORT_ABS / module
        session_state.datadir_str = str(session_state.datadir)
        session_state.df_export_file = str(session_state.datadir / "export.csv")

        session_state.switch_to_select = switch_to_select
        session_state.project_changed = True

    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as e:
        st.error(f"An error occurred while changing the project: {e}")

    reset_project_sections(session_state)


def is_port_in_use(target_port):
    """
    Check if a port is in use.

    Args:
        target_port: Port number to check.

    Returns:
        bool: True if the port is in use, False otherwise.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", target_port)) == 0


def get_random_port():
    """
    Generate a random port number between 8800 and 9900.

    Returns:
        int: A random port number between 8800 and 9900.
    """
    return random.randint(8800, 9900)



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
    env = st.session_state["env"]
    if isinstance(code, (list, tuple)):
        if len(code) >= 3:
            code_str = str(code[2])
        elif code:
            code_str = str(code[-1])
        else:
            code_str = ""
    elif code is None:
        code_str = ""
    else:
        code_str = str(code)

    code_str = code_str.strip("\n")
    if not code_str:
        st.warning("No code supplied for execution.")
        return None

    try:
        target_path = Path(path) if path else Path(env.agi_env)
    except TypeError:
        target_path = Path(env.agi_env)
    target_path = target_path.expanduser()
    if target_path.name == ".venv":
        target_path = target_path.parent

    # Regular expression pattern to match the string between "await" and "("
    pattern = r"await\s+(?:Agi\.)?([^\(]+)\("

    # Find all matches in the code
    matches = re.findall(pattern, code_str)
    snippet_name = matches[0] if matches else "AGI_command"

    snippet_prefix = re.sub(r"[^0-9A-Za-z_]+", "_", str(snippet_name)).strip("_") or "AGI_unknown_command"
    target_slug = re.sub(r"[^0-9A-Za-z_]+", "_", str(env.target)).strip("_") or "unknown_app_name"

    runenv_path = Path(env.runenv)
    logger.info(f"mkdir {runenv_path}")
    runenv_path.mkdir(parents=True, exist_ok=True)
    snippet_file = runenv_path / f"{snippet_prefix}_{target_slug}.py"
    with open(snippet_file, "w") as file:
        file.write(code_str)

    try:
        path_exists = target_path.exists()
    except PermissionError as exc:
        hint = diagnose_data_directory(target_path)
        msg = f"Permission denied while accessing '{target_path}': {exc}"
        if hint:
            msg = f"{msg}\n{hint}"
        st.error(msg)
        st.stop()
    except OSError as exc:
        st.error(f"Unable to access '{target_path}': {exc}")
        st.stop()

    if path_exists:
        return run_with_output(env, f"uv -q run python {snippet_file}", str(target_path))

    st.info("Please do an install first, ensure pyproject.toml lists required dependencies and rerun the project installation.")
    st.stop()


def run_lab(query, snippet, codex, *, env_overrides=None):
    """
    Run gui code.

    Args:
        query: The query data.
        snippet: The snippet file path.
        codex: The codex script path.
    """
    if not query:
        return
    with open(snippet, "w") as file:
        file.write(query[2])
    output = io.StringIO()
    sentinel = object()
    previous_env = {
        key: os.environ.get(key, sentinel)
        for key in (env_overrides or {})
    }
    try:
        for key, value in (env_overrides or {}).items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[str(key)] = str(value)
        stdout, stderr = sys.stdout, sys.stderr
        sys.stdout = output
        sys.stderr = output
        try:
            runpy.run_path(codex)
        finally:
            sys.stdout = stdout
            sys.stderr = stderr
    except (ImportError, OSError, RuntimeError, SyntaxError, NameError, ValueError, TypeError, AttributeError, KeyError, IndexError) as e:
        st.warning(f"Error: {e}")
        print(f"Error: {e}", file=output)
    finally:
        for key, value in previous_env.items():
            if value is sentinel:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)
    return output.getvalue().strip()


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
    """
    Render the project selection sidebar. Provides a lightweight filter so we
    never ship thousands of entries to the browser at once.

    :param projects: List of available projects.
    :type projects: list[str]
    :param current_project: Currently selected project.
    :type current_project: str
    """
    env = st.session_state.get("env")
    if env is not None:
        try:
            projects = env.get_projects(env.apps_path, env.builtin_apps_path)
            env.projects = projects
        except (OSError, TypeError, RuntimeError):
            pass

    search_term = st.sidebar.text_input("Filter projects", key="project_filter")
    selection_state = build_project_selection(projects, current_project, search_term, limit=50)
    shortlist = selection_state.shortlist

    if not shortlist:
        st.sidebar.info("No projects match that filter.")
        return

    if selection_state.needs_caption:
        st.sidebar.caption(
            f"Showing first {len(shortlist)} of {selection_state.total_matches} matches"
        )

    selection = st.sidebar.selectbox(
        "Project name",
        shortlist,
        index=selection_state.default_index,
        key="project_selectbox",
    )

    if selection != current_project:
        on_project_change(selection)


def resolve_active_app(env, preferred_base: Path | None = None) -> tuple[str, bool]:
    """
    Resolve the active app from ?active_app=... or last-active-app, optionally switching env.

    Returns (current_project_name, project_changed)
    """
    project_changed = False
    requested_val = normalize_query_param_value(st.query_params.get("active_app"))

    if requested_val and requested_val != env.app:
        for cand in active_app_candidates(
            requested_val,
            Path(env.apps_path),
            env.projects or [],
            preferred_base=preferred_base,
        ):
            if not cand.exists():
                continue
            try:
                env.change_app(cand)
                project_changed = True
                store_last_active_app(env.active_app)
                break
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                continue
    elif not requested_val:
        last_app = load_last_active_app()
        if last_app and last_app != env.active_app and last_app.exists():
            try:
                env.change_app(last_app)
                project_changed = True
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                pass

    return env.app, project_changed


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
    """
    Create sidebar controls for selecting modules and DataFrames.
    """
    env = st.session_state["env"]
    export_root = Path(env.AGILAB_EXPORT_ABS)
    modules = st.session_state.get("modules", scan_dir(export_root))

    _, lab_index = resolve_default_selection(
        modules,
        st.session_state.get("lab_dir"),
        env.target,
    )
    st.session_state["lab_dir"] = st.sidebar.selectbox(
        "Lab directory",
        modules,
        index=lab_index,
        on_change=lambda: on_lab_change(st.session_state.lab_dir_selectbox),
        key="lab_dir_selectbox",
    )

    lab_dir = export_root / st.session_state["lab_dir_selectbox"]
    st.session_state.df_dir = lab_dir

    df_files = find_files(lab_dir)
    st.session_state.df_files = df_files

    sidebar_state = build_sidebar_dataframe_selection(
        export_root,
        st.session_state["lab_dir_selectbox"],
        df_files,
        st.session_state.get("index_page"),
        env.target,
    )
    st.session_state["index_page"] = sidebar_state.index_page
    index_page_str = str(sidebar_state.index_page)
    st.session_state["module_path"] = sidebar_state.module_path
    st.sidebar.selectbox(
        "Dataframe",
        sidebar_state.df_files_rel,
        key=sidebar_state.key_df,
        index=sidebar_state.default_index,
        on_change=lambda: on_df_change(
            sidebar_state.module_path,
            index_page_str,
            st.session_state.get("df_file"),
        ),
        )
    if st.session_state[sidebar_state.key_df]:
        st.session_state["df_file"] = export_root / st.session_state[sidebar_state.key_df]
    else:
        st.session_state["df_file"] = None


def on_df_change(module_dir, index_page, df_file=None, steps_file=None):
    """
    Handle DataFrame selection.

    Args:
        module_dir (Path): The module path.
        df_file (Path): The DataFrame file path.
        index_page (str): The index page identifier.
        steps_file (Path): The steps file path.
    """
    index_page_str = str(index_page)
    select_df_key = index_page_str + "df"

    # Backward-compatible guard: if callers pass args in the old order, swap them.
    if (
        select_df_key not in st.session_state
        and df_file is not None
        and (str(df_file) + "df") in st.session_state
    ):
        df_file, index_page_str = index_page, str(df_file)
        select_df_key = index_page_str + "df"

    selected_df = st.session_state.get(select_df_key)
    env = st.session_state.get("env")
    export_root = Path(env.AGILAB_EXPORT_ABS) if env else None
    selected_path = resolve_selected_df_path(
        selected_df,
        fallback_df_file=df_file,
        export_root=export_root,
    )

    if selected_path is not None:
        st.session_state[index_page_str + "df_file"] = selected_path
        st.session_state["df_file"] = selected_path
    else:
        st.session_state.pop(index_page_str + "df_file", None)

    if steps_file:
        logger.info(f"mkdir {steps_file.parent}")
        steps_file.parent.mkdir(parents=True, exist_ok=True)
        load_last_step(module_dir, steps_file, index_page_str)
    st.session_state.pop(index_page_str, None)
    st.session_state.page_broken = True


def activate_mlflow(env=None):

    if not env:
        return

    st.session_state["rapids_default"] = True
    tracking_dir = _resolve_mlflow_tracking_dir(env)
    if not tracking_dir.exists():
        logger.info(f"mkdir {tracking_dir}")
    tracking_dir.mkdir(parents=True, exist_ok=True)
    env.MLFLOW_TRACKING_DIR = str(tracking_dir)

    port = _next_free_port()

    try:
        backend_uri = _ensure_default_mlflow_experiment(tracking_dir) or _ensure_mlflow_backend_ready(tracking_dir)
        artifact_uri = _resolve_mlflow_artifact_dir(tracking_dir).as_uri()
        cmd = (
            "uv -q run mlflow server "
            f"--backend-store-uri {shlex.quote(backend_uri)} "
            f"--default-artifact-root {shlex.quote(artifact_uri)} "
            "--host 127.0.0.1 "
            f"--port {port}"
        )
        subproc(cmd, os.getcwd())
        if not _wait_for_listen_port(port):
            st.session_state["server_started"] = False
            st.session_state.pop("mlflow_port", None)
            st.error(
                "Failed to start the MLflow server: the process did not open its listening port."
            )
            return False
        st.session_state.server_started = True
        st.session_state["mlflow_port"] = port
        return True
    except (RuntimeError, OSError, ValueError, AttributeError) as e:
        st.session_state["server_started"] = False
        st.session_state.pop("mlflow_port", None)
        st.error(f"Failed to start the server: {e}")
        return False


def activate_gpt_oss(env=None):
    """Spin up a local GPT-OSS responses server (stub backend) if available."""

    if not env:
        return False

    if st.session_state.get("gpt_oss_server_started"):
        return True

    st.session_state.pop("gpt_oss_autostart_failed", None)
    try:
        import gpt_oss  # noqa: F401
    except ImportError:
        st.warning("Install `gpt-oss` (`pip install gpt-oss`) to enable the offline assistant.")
        st.session_state["gpt_oss_autostart_failed"] = True
        return False

    backend = (
        st.session_state.get("gpt_oss_backend")
        or env.envars.get("GPT_OSS_BACKEND")
        or os.getenv("GPT_OSS_BACKEND")
        or "stub"
    ).strip() or "stub"
    checkpoint = (
        st.session_state.get("gpt_oss_checkpoint")
        or env.envars.get("GPT_OSS_CHECKPOINT")
        or os.getenv("GPT_OSS_CHECKPOINT")
        or ("gpt2" if backend == "transformers" else "")
    ).strip()
    extra_args = (
        st.session_state.get("gpt_oss_extra_args")
        or env.envars.get("GPT_OSS_EXTRA_ARGS")
        or os.getenv("GPT_OSS_EXTRA_ARGS")
        or ""
    ).strip()
    python_exec = (
        env.envars.get("GPT_OSS_PYTHON")
        or os.getenv("GPT_OSS_PYTHON")
        or sys.executable
    )
    requires_checkpoint = backend in {"transformers", "metal", "triton", "vllm"}
    if requires_checkpoint and not checkpoint:
        st.warning(
            "GPT-OSS backend requires a checkpoint. Set `GPT_OSS_CHECKPOINT` in the sidebar or environment."
        )
        st.session_state["gpt_oss_autostart_failed"] = True
        return False

    env.envars["GPT_OSS_BACKEND"] = backend
    if checkpoint:
        env.envars["GPT_OSS_CHECKPOINT"] = checkpoint
    elif "GPT_OSS_CHECKPOINT" in env.envars:
        del env.envars["GPT_OSS_CHECKPOINT"]
    if extra_args:
        env.envars["GPT_OSS_EXTRA_ARGS"] = extra_args

    port = _next_free_port()

    cmd = (
        f"{shlex.quote(python_exec)} -m gpt_oss.responses_api.serve "
        f"--inference-backend {shlex.quote(backend)} --port {int(port)}"
    )
    if checkpoint and backend != "stub":
        cmd += f" --checkpoint {shlex.quote(checkpoint)}"
    if extra_args:
        cmd = f"{cmd} {extra_args}"

    try:
        subproc(cmd, os.getcwd())
    except RuntimeError as e:
        st.error(f"Failed to start GPT-OSS server: {e}")
        return False

    endpoint = f"http://127.0.0.1:{port}/v1/responses"
    st.session_state["gpt_oss_server_started"] = True
    st.session_state["gpt_oss_port"] = port
    st.session_state["gpt_oss_endpoint"] = endpoint
    env.envars["GPT_OSS_ENDPOINT"] = endpoint
    st.session_state["gpt_oss_backend_active"] = backend
    if checkpoint:
        st.session_state["gpt_oss_checkpoint_active"] = checkpoint
    else:
        st.session_state.pop("gpt_oss_checkpoint_active", None)
    if extra_args:
        st.session_state["gpt_oss_extra_args_active"] = extra_args
    else:
        st.session_state.pop("gpt_oss_extra_args_active", None)
    st.session_state.pop("gpt_oss_autostart_failed", None)
    return True
