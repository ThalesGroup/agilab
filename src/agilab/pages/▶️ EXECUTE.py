import asyncio

# ===========================
# Standard Imports (lightweight)
# ===========================
import os
import sys
import socket
import runpy
import ast
import re
import json
import numbers
import logging
import subprocess
from functools import lru_cache
from pathlib import Path
import importlib
from typing import Optional
from datetime import datetime

# Third-Party imports
import networkx as nx
from networkx.readwrite import json_graph
import textwrap

try:
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
except ModuleNotFoundError as exc:
    plt = None  # type: ignore[assignment]
    Patch = None  # type: ignore[assignment]
    _MATPLOTLIB_IMPORT_ERROR = exc
else:
    _MATPLOTLIB_IMPORT_ERROR = None
from collections import defaultdict
import tomllib       # For reading TOML files
import tomli_w       # For writing TOML files
import pandas as pd
# Theme configuration
os.environ.setdefault("STREAMLIT_CONFIG_FILE", str(Path(__file__).resolve().parents[1] / "resources" / "config.toml"))
import streamlit as st
# Project Libraries:
from agi_env.pagelib import (
    get_about_content, render_logo, activate_mlflow, save_csv, init_custom_ui, select_project, open_new_tab,
    cached_load_df, inject_theme, is_valid_ip, find_files, resolve_active_app, store_last_active_app
)

from agi_env import AgiEnv

# ===========================
# Session State Initialization
# ===========================
def init_session_state(defaults: dict):
    """
    Initialize session state variables with default values if they are not already set.
    """
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

# ===========================
# Utility and Helper Functions
# ===========================

def clear_log():
    """
    Clear the accumulated log in session_state.
    Call this before starting a new run (INSTALL, DISTRIBUTE, or EXECUTE)
    to avoid mixing logs.
    """
    st.session_state["log_text"] = ""

def update_log(live_log_placeholder, message, max_lines=1000):
    """
    Append a cleaned message to the accumulated log and update the live display.
    Keeps only the last max_lines lines in the log.
    """
    if "log_text" not in st.session_state:
        st.session_state["log_text"] = ""

    clean_msg = strip_ansi(message).rstrip()
    if st.session_state.get('cluster_verbose', 1) < 2:
        if getattr(update_log, '_skip_traceback', False):
            if not clean_msg:
                update_log._skip_traceback = False
            return
        if clean_msg.lower().startswith("traceback (most recent call last"):
            update_log._skip_traceback = True
            return
        if _is_dask_shutdown_noise(clean_msg):
            return
    if clean_msg:
        st.session_state["log_text"] += clean_msg + "\n"

    # Keep only last max_lines lines to avoid huge memory/logs
    lines = st.session_state["log_text"].splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
        st.session_state["log_text"] = "\n".join(lines) + "\n"

    display_lines = lines[-LOG_DISPLAY_MAX_LINES:]
    live_view = "\n".join(display_lines)

    # Calculate height in pixels roughly: 20px per line, capped at 500px (but keep a usable minimum)
    line_count = max(len(display_lines), 1)
    height_px = min(max(20 * line_count, LIVE_LOG_MIN_HEIGHT), 500)

    live_log_placeholder.code(live_view, language="python", height=height_px)

update_log._skip_traceback = False



def strip_ansi(text: str) -> str:
    if not text:
        return ""
    ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
    return ansi_escape.sub('', text)


def _is_dask_shutdown_noise(line: str) -> bool:
    """
    Return True when the line is one of the noisy Dask shutdown messages
    that we don’t want to surface in the UI.
    """
    if not line:
        return False
    normalized = line.strip().lower()
    noise_patterns = (
        "stream is closed",
        "streamclosederror",
        "commclosederror",
        "batched comm closed",
        "closing scheduler",
        "scheduler closing all comms",
        "remove worker addr",
        "close client connection",
        "tornado.iostream.streamclosederror",
        "nbytes = yield coro",
        "value = future.result",
        "convert_stream_closed_error",
        "^",
    )
    if any(pattern in normalized for pattern in noise_patterns):
        return True
    if "traceback (most recent call last" in normalized:
        return True
    if normalized.startswith("the above exception was the direct cause"):
        return True
    if normalized.startswith("traceback"):
        return True
    if normalized.startswith("file \"") and (
        "/site-packages/distributed/" in normalized
        or "/site-packages/tornado/" in normalized
    ):
        return True
    return False


def _filter_noise_lines(text: str) -> str:
    lines = [
        line
        for line in text.splitlines()
        if not _is_dask_shutdown_noise(line.strip())
    ]
    return "\n".join(lines)

def _reset_traceback_skip() -> None:
    _TRACEBACK_SKIP["active"] = False
    update_log._skip_traceback = False


def _append_log_lines(buffer: list[str], payload: str) -> None:
    """
    Append cleaned lines from ``payload`` to ``buffer`` while filtering out
    Dask shutdown chatter. Suppresses multi-line tracebacks emitted during
    scheduler shutdown by skipping until the next blank line (only when verbosity < 2).
    """
    filtered = strip_ansi(payload or "")
    if st.session_state.get('cluster_verbose', 1) < 2:
        skip = _TRACEBACK_SKIP["active"]
        for raw_line in filtered.splitlines():
            stripped = raw_line.rstrip()
            lowered = stripped.lower()
            if skip:
                if not stripped:
                    skip = False
                continue
            if lowered.startswith("traceback (most recent call last"):
                skip = True
                continue
            if stripped and not _is_dask_shutdown_noise(stripped):
                buffer.append(stripped)
        _TRACEBACK_SKIP["active"] = skip
    else:
        for raw_line in filtered.splitlines():
            stripped = raw_line.rstrip()
            if stripped:
                buffer.append(stripped)


_INSTALL_LOG_FATAL_PATTERNS: tuple[tuple[str, ...], ...] = (
    #("connection to", "timed out"),
    #("failed to connect",),
    #("connection refused",),
    #("no route to host",),
    #("ssh_exchange_identification",),
    #("broken pipe",),
    ("error",),
)
_INSTALL_LOG_FATAL_PATTERNS_LOWER: tuple[tuple[str, ...], ...] = tuple(
    tuple(token.lower() for token in pattern if token)
    for pattern in _INSTALL_LOG_FATAL_PATTERNS
    if pattern
)


def _log_indicates_install_failure(lines: list[str]) -> bool:
    """
    Return True when install logs contain fatal phrases that do not always
    propagate through stderr (e.g., SSH transport errors).
    We reuse a single lower-cased tail snippet so substring checks stay O(1) per token.
    """
    if not lines or not _INSTALL_LOG_FATAL_PATTERNS_LOWER:
        return False

    snippet = "\n".join(lines[-200:]).lower()
    for pattern in _INSTALL_LOG_FATAL_PATTERNS_LOWER:
        for token in pattern:
            if token not in snippet:
                break
        else:
            return True
    return False


_SHARED_FILESYSTEM_TYPES: set[str] = {
    # Networked filesystems
    "nfs",
    "nfs4",
    "cifs",
    "smbfs",
    "sshfs",
    "afpfs",
    "webdav",
    # Common shared/cluster filesystems
    "lustre",
    "gpfs",
    "panfs",
    "beegfs",
    "ceph",
    "glusterfs",
    "gfs2",
    # Automounter (often backing NFS/SMB shares)
    "autofs",
}


@lru_cache(maxsize=1)
def _mount_table() -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    try:
        if sys.platform.startswith("linux"):
            mounts = Path("/proc/mounts")
            if mounts.exists():
                for line in mounts.read_text(encoding="utf-8", errors="replace").splitlines():
                    parts = line.split()
                    if len(parts) >= 3:
                        mountpoint = parts[1].replace("\\040", " ")
                        fstype = parts[2]
                        entries.append((mountpoint, fstype))
        elif sys.platform == "darwin":
            proc = subprocess.run(["mount"], capture_output=True, text=True, check=False)
            for line in (proc.stdout or "").splitlines():
                match = re.match(r".+ on (?P<mountpoint>.+?) \((?P<fstype>[^,\)]+)", line)
                if match:
                    entries.append((match.group("mountpoint").strip(), match.group("fstype").strip()))
    except Exception:
        entries = []

    entries.sort(key=lambda item: len(item[0]), reverse=True)
    return entries


def _fstype_for_path(path: Path) -> Optional[str]:
    path_str = str(path)
    for mountpoint, fstype in _mount_table():
        mp = mountpoint.rstrip("/") or "/"
        if mp == "/":
            return fstype.lower()
        if path_str == mp or path_str.startswith(mp + "/"):
            return fstype.lower()
    return None


def _looks_like_shared_path(path: Path) -> bool:
    """
    Best-effort heuristic: try to detect whether ``path`` is on a filesystem that
    remote workers can also see (e.g., NFS/SMB/Lustre).

    This is intentionally conservative and only used to emit a UI warning; it
    cannot guarantee that *remote* nodes mount the same path.
    """
    raw = path.expanduser()
    try:
        resolved = raw.resolve()
    except Exception:
        resolved = raw

    for candidate in (raw, resolved):
        fstype = _fstype_for_path(candidate)
        if fstype and fstype in _SHARED_FILESYSTEM_TYPES:
            return True

    home_raw = Path.home().expanduser()
    home = Path.home().resolve()
    try:
        resolved.relative_to(home)
        # If the path is inside the home directory, default to "local" unless it
        # lives on a known shared filesystem (handled above) or is a mountpoint
        # under home. (Mount detection is platform-dependent and not always
        # reliable, but helps as a fallback.)
        for current, stop in ((raw, home_raw), (resolved, home)):
            node = current
            while True:
                try:
                    if os.path.ismount(node):
                        return True
                except Exception:
                    break
                if node == stop:
                    break
                parent = node.parent
                if parent == node:
                    break
                node = parent
        return False
    except ValueError:
        pass

    project_root = Path(__file__).resolve().parents[2]
    try:
        resolved.relative_to(project_root)
        return False
    except ValueError:
        pass

    return resolved.is_absolute()


def _macos_autofs_hint(share_candidate: Path) -> Optional[str]:
    """Return a short, actionable hint when a macOS autofs map seems misconfigured."""
    if sys.platform != "darwin":
        return None

    auto_master = Path("/etc/auto_master")
    auto_nfs = Path("/etc/auto_nfs")
    if not auto_master.exists() or not auto_nfs.exists():
        return None

    try:
        candidate_str = str(share_candidate.expanduser())
    except Exception:
        candidate_str = str(share_candidate)

    try:
        auto_nfs_lines = auto_nfs.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return None

    has_mapping = False
    for raw in auto_nfs_lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts and parts[0] == candidate_str:
            has_mapping = True
            break

    if not has_mapping:
        return None

    try:
        master_text = auto_master.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    has_direct_ref = re.search(r"^\s*/-\s+auto_nfs(\s|$)", master_text, flags=re.MULTILINE) is not None
    if not has_direct_ref:
        has_static = re.search(r"^\s*/-\s+-static(\s|$)", master_text, flags=re.MULTILINE) is not None
        if has_static:
            return (
                "macOS autofs: `/etc/auto_nfs` contains a mapping for this path, but `/etc/auto_master` is using the built-in `/- -static` map. "
                "macOS only honors the first `/-` entry (duplicates are ignored), so replace `/- -static` with `/- auto_nfs` "
                "(or add the mount to `/etc/fstab`), then run `sudo automount -vc`."
            )
        return (
            "macOS autofs: `/etc/auto_nfs` contains a mapping for this path, but `/etc/auto_master` does not reference it. "
            "Set the `/-` entry to `auto_nfs` (e.g. replace `/- -static` with `/- auto_nfs`) and run `sudo automount -vc`."
        )

    return (
        "macOS autofs: this path is present in `/etc/auto_nfs`. If the mount is on-demand, it may only appear after first access; "
        "try `ls <share_dir>` or `sudo automount -vc`."
    )


LOG_DISPLAY_MAX_LINES = 250
LIVE_LOG_MIN_HEIGHT = 160
INSTALL_LOG_HEIGHT = 320
_TRACEBACK_SKIP = {"active": False}


def _format_log_block(text: str, *, newest_first: bool = True) -> str:
    """Return a trimmed/ordered view of the provided multiline text."""
    if not text:
        return ""
    lines = text.splitlines()
    tail = lines[-LOG_DISPLAY_MAX_LINES:]
    if newest_first:
        tail = list(reversed(tail))
    return "\n".join(tail)


def display_log(stdout, stderr):
    # Use cached log if stdout empty
    if not stdout.strip() and "log_text" in st.session_state:
        stdout = st.session_state["log_text"]

    # Strip ANSI color codes from both stdout and stderr
    clean_stdout = strip_ansi(stdout or "")
    clean_stderr = strip_ansi(stderr or "")
    clean_stdout = _filter_noise_lines(clean_stdout)
    clean_stderr = _filter_noise_lines(clean_stderr)

    # Clean up extra blank lines
    clean_stdout = "\n".join(line for line in clean_stdout.splitlines() if line.strip())
    clean_stderr = "\n".join(line for line in clean_stderr.splitlines() if line.strip())

    combined = "\n".join([clean_stdout, clean_stderr]).strip()

    if "warning:" in combined.lower():
        st.warning("Warnings occurred during cluster installation:")
        st.code(_format_log_block(combined, newest_first=False), language="python", height=400)
    elif clean_stderr:
        st.error("Errors occurred during cluster installation:")
        st.code(_format_log_block(clean_stderr, newest_first=False), language="python", height=400)
    else:
        st.code(_format_log_block(clean_stdout, newest_first=False) or "No logs available", language="python", height=400)


def parse_benchmark(benchmark_str):
    """
    Parse a benchmark string into a dictionary.

    This function converts a benchmark string that may have unquoted numeric keys and
    single quotes into a valid JSON string and then parses it into a dictionary.
    Numeric keys are converted to integers.
    """
    if not isinstance(benchmark_str, str):
        raise ValueError("Input must be a string.")
    if len(benchmark_str) < 3:
        return None

    try:
        # Replace unquoted numeric keys with quoted keys
        json_str = re.sub(r'([{,]\s*)(\d+):', r'\1"\2":', benchmark_str)
        # Replace single quotes with double quotes
        json_str = json_str.replace("'", '"')
        # Parse the JSON string
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError("Invalid benchmark string. Failed to decode JSON.") from e

    def try_int(key):
        return int(key) if key.isdigit() else key

    return {try_int(k): v for k, v in data.items()}


def safe_eval(expression, expected_type, error_message):
    try:
        result = ast.literal_eval(expression)
        if not isinstance(result, expected_type):
            st.error(error_message)
            return None
        return result
    except (SyntaxError, ValueError):
        st.error(error_message)
        return None

def parse_and_validate_scheduler(scheduler):
    """
    Accept IP or IP:PORT. Validate IP via is_valid_ip(host) and optional numeric port.
    """

    host, sep, port = scheduler.partition(":")
    if not is_valid_ip(host):
        st.error(f"The scheduler host '{scheduler}' is invalid. Expect IP or IP:PORT.")
        return None
    if sep and (not port.isdigit() or not (0 < int(port) < 65536)):
        st.error(f"The scheduler port in '{scheduler}' is invalid.")
        return None
    return scheduler

def parse_and_validate_workers(workers_input):
    env = st.session_state["env"]
    workers = safe_eval(
        expression=workers_input,
        expected_type=dict,
        error_message="Workers must be provided as a dictionary of IP addresses and capacities (e.g., {'192.168.0.1': 2})."
    )
    if workers is not None:
        invalid_ips = [ip for ip in workers.keys() if not is_valid_ip(ip)]
        if invalid_ips:
            st.error(f"The following worker IPs are invalid: {', '.join(invalid_ips)}")
            return {"127.0.0.1": 1}
        invalid_values = {ip: num for ip, num in workers.items() if not isinstance(num, int) or num <= 0}
        if invalid_values:
            error_details = ", ".join([f"{ip}: {num}" for ip, num in invalid_values.items()])
            st.error(f"All worker capacities must be positive integers. Invalid entries: {error_details}")
            return {"127.0.0.1": 1}
    return workers or {"127.0.0.1": 1}

def initialize_app_settings(args_override=None):
    env = st.session_state["env"]

    file_settings = load_toml_file(env.app_settings_file)
    session_settings = st.session_state.get("app_settings")
    app_settings = {}

    if isinstance(file_settings, dict):
        app_settings.update(file_settings)
    if isinstance(session_settings, dict):
        for key, value in session_settings.items():
            if key in {"args", "cluster"} and isinstance(value, dict):
                base = app_settings.get(key, {})
                if isinstance(base, dict):
                    merged = {**base, **value}
                else:
                    merged = value
                app_settings[key] = merged
            else:
                app_settings[key] = value

    if env.app == "flight_project":
        try:
            from flight import apply_source_defaults, load_args_from_toml

            args_model = apply_source_defaults(load_args_from_toml(env.app_settings_file))
            app_settings["args"] = args_model.to_toml_payload()
        except Exception as exc:
            st.warning(f"Unable to load Flight args: {exc}")
            app_settings.setdefault("args", {})
    else:
        app_settings.setdefault("args", {})

    cluster_settings = app_settings.setdefault("cluster", {})
    if args_override is not None:
        app_settings["args"] = args_override
    st.session_state.app_settings = app_settings
    st.session_state["args_project"] = env.app

def filter_warning_messages(log: str) -> str:
    """
    Remove lines containing a specific warning about VIRTUAL_ENV mismatches.
    """
    filtered_lines = []
    for line in log.splitlines():
        if ("VIRTUAL_ENV=" in line and
            "does not match the project environment path" in line and
            ".venv" in line):
            continue
        filtered_lines.append(line)
    return "\n".join(filtered_lines)

# ===========================
# Caching Functions for Performance
# ===========================
@st.cache_data(ttl=300, show_spinner=False)
def load_toml_file(file_path):
    file_path = Path(file_path)
    if file_path.exists():
        try:
            with file_path.open("rb") as f:
                return tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            st.warning(f"Invalid TOML detected in {file_path.name}: {exc}")
            logger = logging.getLogger(__name__)
            logger.warning("Failed to parse %s: %s", file_path, exc)
            return {}
    return {}

@st.cache_data(show_spinner=False)
def load_distribution(file_path):
    with open(file_path, "r") as f:
        data = json.load(f)
    workers = [f"{ip}-{i}" for ip, count in data.get("workers", {}).items() for i in range(1, count + 1)]
    return workers, data.get("work_plan_metadata", []), data.get("work_plan", [])

@st.cache_data(show_spinner=False)
def generate_profile_report(df):
    env = st.session_state["env"]
    if env.python_version > "3.12":
        from ydata_profiling.profile_report import ProfileReport
        return ProfileReport(df, minimal=True)
    else:
        st.info(f"Function not available with this version of Python {env.python_version}.")
        return None

# ===========================
# UI Rendering Functions
# ===========================
def render_generic_ui():
    env = st.session_state["env"]
    ncols = 2
    cols = st.columns([10, 1, 10])
    new_args_list = []
    arg_valid = True

    args_default = st.session_state.app_settings["args"]
    for i, (key, val) in enumerate(args_default.items()):
        with cols[0 if i % ncols == 0 else 2]:
            c1, c2, c3, c4 = st.columns([5, 5, 3, 1])
            new_key = c1.text_input("Name", value=key, key=f"args_name{i}")
            new_val = c2.text_input("Value", value=repr(val), key=f"args_value{i}")
            try:
                new_val = ast.literal_eval(new_val)
            except (SyntaxError, ValueError):
                pass
            c3.text(type(new_val).__name__)
            if not c4.button("🗑️", key=f"args_remove_button{i}", type="primary", help=f"Remove {new_key}"):
                new_args_list.append((new_key, new_val))
            else:
                st.session_state["args_remove_arg"] = True

    c1_add, c2_add, c3_add = st.columns(3)
    i = len(args_default) + 1
    new_key = c1_add.text_input("Name", placeholder="Name", key=f"args_name{i}")
    new_val = c2_add.text_input("Value", placeholder="Value", key=f"args_value{i}")
    if c3_add.button("Add argument", type="primary", key=f"args_add_arg_button"):
        if new_val == "":
            new_val = None
        try:
            new_val = ast.literal_eval(new_val)
        except (SyntaxError, ValueError):
            pass
        new_args_list.append((new_key, new_val))

    if not all(key.strip() for key, _ in new_args_list):
        st.error("Argument name must not be empty.")
        arg_valid = False

    if len(new_args_list) != len(set(key for key, _ in new_args_list)):
        st.error("Argument name already exists.")
        arg_valid = False

    args_input = dict(new_args_list)
    is_args_reload_required = arg_valid and (args_input != st.session_state.app_settings.get("args", {}))

    if is_args_reload_required:
        st.session_state["args_input"] = args_input
        app_settings_file = env.app_settings_file
        if env.app == "flight_project":
            try:
                from flight import apply_source_defaults, dump_args_to_toml, FlightArgs
                from pydantic import ValidationError

                parsed_args = FlightArgs(**args_input)
            except ValidationError as exc:
                messages = env.humanize_validation_errors(exc)
                st.warning("\n".join(messages))
            else:
                parsed_args = apply_source_defaults(parsed_args)
                dump_args_to_toml(parsed_args, app_settings_file)
                st.session_state.app_settings["args"] = parsed_args.to_toml_payload()
        else:
            existing_app_settings = load_toml_file(app_settings_file)
            existing_app_settings.setdefault("args", {})
            existing_app_settings.setdefault("cluster", {})
            existing_app_settings["args"] = args_input
            st.session_state.app_settings = existing_app_settings
            with open(app_settings_file, "wb") as file:
                tomli_w.dump(existing_app_settings, file)

    if st.session_state.get("args_remove_arg"):
        st.session_state["args_remove_arg"] = False
        st.rerun()

    if arg_valid and st.session_state.get("args_add_arg_button"):
        st.rerun()

    if arg_valid:
        st.session_state.app_settings["args"] = args_input

def render_cluster_settings_ui():

    env = st.session_state["env"]
    app_settings = st.session_state.get("app_settings")
    if not isinstance(app_settings, dict):
        app_settings = {"args": {}, "cluster": {}}
        st.session_state["app_settings"] = app_settings

    cluster_params = app_settings.setdefault("cluster", {})

    boolean_params = ["cython", "pool"]
    if env.is_managed_pc:
        cluster_params["rapids"] = False
    else:
        boolean_params.append("rapids")
    cols_other = st.columns(len(boolean_params))
    for idx, param in enumerate(boolean_params):
        current_value = cluster_params.get(param, False)
        updated_value = cols_other[idx].checkbox(
            param.replace("_", " ").capitalize(),
            value=current_value,
            key=f"cluster_{param}",
            help=f"Enable or disable {param}."
        )
        cluster_params[param] = updated_value

    # -------- per-project cluster toggle seeded from TOML; do not pass value= while also using session_state
    cluster_enabled_key = f"cluster_enabled__{env.app}"
    if cluster_enabled_key not in st.session_state:
        st.session_state[cluster_enabled_key] = bool(cluster_params.get("cluster_enabled", False))
    cluster_enabled = st.toggle(
        "Enable Cluster",
        key=cluster_enabled_key,
        help="Enable cluster: provide a scheduler IP and workers configuration."
    )
    cluster_params["cluster_enabled"] = bool(cluster_enabled)

    # Keep scheduler/workers persisted even if disabled (don’t pop them)
    if cluster_enabled:
        # Helper to persist environment variables if the value changed
        def _persist_env_var(key: str, value: Optional[str]):
            normalized = "" if value is None else str(value)
            current = ""
            envars = getattr(AgiEnv, "envars", None)
            if isinstance(envars, dict):
                current = str(envars.get(key, "") or "")
            if normalized != current:
                AgiEnv.set_env_var(key, normalized)

        share_raw = env.agi_share_path
        share_display: str
        resolved_display: Optional[Path] = None
        is_symlink = False
        if share_raw:
            share_display = str(share_raw)
            try:
                share_root = env.share_root_path()
            except Exception:
                share_root = None
            if share_root is not None:
                resolved_display = share_root
                try:
                    is_symlink = share_root.is_symlink()
                    resolved_target = share_root.resolve(strict=False)
                except Exception:
                    resolved_target = share_root
                if resolved_target != share_root:
                    resolved_display = resolved_target
            if resolved_display and str(resolved_display) != share_display:
                share_display = f"{share_display} → {resolved_display}"
        else:
            share_display = (
                "not set. Set `AGI_SHARE_DIR` to a shared mount (or symlink to one) so remote workers can read outputs."
            )
        st.markdown(f"**agi_share_path:** {share_display}")

        # per-project widget key & seeding; do not also pass value=
        scheduler_widget_key = f"cluster_scheduler__{env.app}"
        if scheduler_widget_key not in st.session_state:
            st.session_state[scheduler_widget_key] = cluster_params.get("scheduler", "")
        user_widget_key = f"cluster_user__{env.app}"
        stored_user = cluster_params.get("user")
        if stored_user in (None, ""):
            stored_user = env.user or ""
        if user_widget_key not in st.session_state:
            st.session_state[user_widget_key] = stored_user
        auth_toggle_key = f"cluster_use_key__{env.app}"
        auth_method = cluster_params.get("auth_method")
        default_use_key = bool(cluster_params.get("ssh_key_path"))
        if isinstance(auth_method, str):
            default_use_key = auth_method.lower() == "ssh_key"
        if auth_toggle_key not in st.session_state:
            st.session_state[auth_toggle_key] = default_use_key

        auth_row = st.container()
        scheduler_col, user_col, credential_col, toggle_col = auth_row.columns(4, vertical_alignment="top")
        with scheduler_col:
            scheduler_input = st.text_input(
                "Scheduler IP Address",
                key=scheduler_widget_key,
                placeholder="e.g., 192.168.0.100 or 192.168.0.100:8786",
                help="Provide a scheduler IP address (optionally with :PORT).",
            )
        with user_col:
            user_input = st.text_input(
                "SSH User",
                key=user_widget_key,
                placeholder="e.g., ubuntu",
                help="Remote account used for cluster SSH connections.",
            )
        sanitized_user = (user_input or "").strip()
        if not sanitized_user and stored_user:
            sanitized_user = stored_user
            if user_input != sanitized_user:
                st.session_state[user_widget_key] = sanitized_user
        elif user_input != sanitized_user:
            st.session_state[user_widget_key] = sanitized_user

        env.user = sanitized_user
        cluster_params["user"] = sanitized_user
        if not sanitized_user:
            _persist_env_var("CLUSTER_CREDENTIALS", "")

        sanitized_key = None
        password_value = ""
        with toggle_col:
            use_ssh_key = st.toggle(
                "Use SSH key",
                key=auth_toggle_key,
                help="Toggle between SSH key-based auth (recommended) and password auth for cluster workers.",
            )
        cluster_params["auth_method"] = "ssh_key" if use_ssh_key else "password"

        if use_ssh_key:
            ssh_key_widget_key = f"cluster_ssh_key__{env.app}"
            stored_key = cluster_params.get("ssh_key_path")
            if stored_key in (None, ""):
                stored_key = env.ssh_key_path or ""
            if ssh_key_widget_key not in st.session_state:
                st.session_state[ssh_key_widget_key] = stored_key
            with credential_col:
                ssh_key_input = st.text_input(
                    "SSH Key Path",
                    key=ssh_key_widget_key,
                    placeholder="e.g., ~/.ssh/id_rsa",
                    help="Private key used for SSH authentication.",
                )
            sanitized_key = (ssh_key_input or "").strip()
            if not sanitized_key and stored_key:
                sanitized_key = stored_key
                if ssh_key_input != sanitized_key:
                    st.session_state[ssh_key_widget_key] = sanitized_key
            elif ssh_key_input != sanitized_key:
                st.session_state[ssh_key_widget_key] = sanitized_key
        else:
            password_widget_key = f"cluster_password__{env.app}"
            stored_password = cluster_params.get("password")
            if stored_password is None:
                stored_password = env.password or ""
            if password_widget_key not in st.session_state:
                st.session_state[password_widget_key] = stored_password
            with credential_col:
                password_input = st.text_input(
                    "SSH Password",
                    key=password_widget_key,
                    type="password",
                    placeholder="Enter SSH password",
                    help="Password for SSH authentication. Leave blank if workers use key-based auth.",
                )
            password_value = password_input or ""

        if use_ssh_key:
            cluster_params["ssh_key_path"] = sanitized_key
            env.password = None
            env.ssh_key_path = sanitized_key or None

            if sanitized_user:
                _persist_env_var("CLUSTER_CREDENTIALS", sanitized_user)
            _persist_env_var("AGI_SSH_KEY_PATH", sanitized_key)
        else:
            cluster_params.pop("password", None)
            env.password = password_value or None
            env.ssh_key_path = None

            if sanitized_user:
                credentials_value = sanitized_user if not password_value else f"{sanitized_user}:{password_value}"
                _persist_env_var("CLUSTER_CREDENTIALS", credentials_value)
            else:
                _persist_env_var("CLUSTER_CREDENTIALS", "")
            _persist_env_var("AGI_SSH_KEY_PATH", "")
        if scheduler_input:
            scheduler = parse_and_validate_scheduler(scheduler_input)
            if scheduler:
                cluster_params["scheduler"] = scheduler

        workers_widget_key = f"cluster_workers__{env.app}"
        workers_dict = cluster_params.get("workers", {})
        if workers_widget_key not in st.session_state:
            st.session_state[workers_widget_key] = json.dumps(workers_dict, indent=2) if isinstance(workers_dict, dict) else "{}"
        workers_input = st.text_area(
            "Workers Configuration",
            key=workers_widget_key,
            placeholder='e.g., {"192.168.0.1": 2, "192.168.0.2": 3}',
            help="Provide a dictionary of worker IP addresses and capacities.",
        )
        if workers_input:
            workers = parse_and_validate_workers(workers_input)
            if workers:
                cluster_params["workers"] = workers
    else:
        cluster_params.pop("scheduler", None)
        cluster_params.pop("workers", None)

    st.session_state.dask = cluster_enabled
    benchmark_enabled = st.session_state.get("benchmark", False)

    run_mode_label = [
        "0: python", "1: pool of process", "2: cython", "3: pool and cython",
        "4: dask", "5: dask and pool", "6: dask and cython", "7: dask and pool and cython",
        "8: rapids", "9: rapids and pool", "10: rapids and cython", "11: rapids and pool and cython",
        "12: rapids and dask", "13: rapids and dask and pool", "14: rapids and dask and cython",
        "15: rapids and dask and pool and cython"
    ]

    if benchmark_enabled:
        st.session_state["mode"] = None
        st.info("Run mode benchmark (all modes)")
    else:
        mode_value = (
            int(cluster_params.get("pool", False))
            + int(cluster_params.get("cython", False)) * 2
            + int(cluster_enabled) * 4
            + int(cluster_params.get("rapids", False)) * 8
        )
        st.session_state["mode"] = mode_value
        st.info(f"Run mode {run_mode_label[mode_value]}")
    st.session_state.app_settings["cluster"] = cluster_params

    # Persist to TOML
    with open(env.app_settings_file, "wb") as file:
        tomli_w.dump(st.session_state.app_settings, file)
    try:
        load_toml_file.clear()
    except Exception:
        pass

def toggle_select_all():
    if st.session_state.check_all:
        st.session_state.selected_cols = st.session_state.df_cols.copy()
    else:
        st.session_state.selected_cols = []

def update_select_all():
    all_selected = all(st.session_state.get(f"export_col_{i}", False) for i in range(len(st.session_state.df_cols)))
    st.session_state.check_all = all_selected
    st.session_state.selected_cols = [
        col for i, col in enumerate(st.session_state.df_cols) if st.session_state.get(f"export_col_{i}", False)
    ]

def _draw_distribution(graph, partition_key, show_leaf_list, title):
    """
    Shared drawing routine for distribution or DAG graphs.
    """
    # Determine multipartite layout
    pos = nx.multipartite_layout(graph, subset_key="level", align="horizontal")
    # Invert axes for better top-down view
    pos = {k: (-x, -y) for k, (x, y) in pos.items()}

    # Classify nodes by level
    ip_nodes = [n for n, d in graph.nodes(data=True) if d.get("level") == 0]
    worker_nodes = [n for n, d in graph.nodes(data=True) if d.get("level") == 1]
    partition_nodes = [n for n, d in graph.nodes(data=True) if d.get("level") == 2]
    leaf_nodes = [n for n, d in graph.nodes(data=True) if d.get("level") == 3]

    plt.figure(figsize=(12, 8))
    plt.margins(x=0.1, y=0.1)

    # Draw nodes
    nx.draw_networkx_nodes(graph, pos, nodelist=ip_nodes, node_color="royalblue", node_shape="o", node_size=1500)
    nx.draw_networkx_nodes(graph, pos, nodelist=worker_nodes, node_color="skyblue", node_shape="o", node_size=1500)
    nx.draw_networkx_nodes(graph, pos, nodelist=partition_nodes, node_color="lightgreen", node_shape="s", node_size=1500)
    if show_leaf_list:
        nx.draw_networkx_nodes(graph, pos, nodelist=leaf_nodes, node_color="lightgrey", node_shape="s", node_size=1000)
    nx.draw_networkx_edges(graph, pos)

    # Label drawing
    ax = plt.gca()
    for node in graph.nodes():
        x, y = pos[node]
        # Rotate leaf labels if present
        if show_leaf_list and node in leaf_nodes:
            rotation, fontsize = 90, 7
        else:
            rotation, fontsize = 0, 7
        # Wrap long labels
        wrapped = textwrap.fill(node, width=12)
        ax.text(
            x, y, wrapped,
            horizontalalignment="center",
            verticalalignment="center",
            rotation=rotation,
            fontsize=fontsize,
            bbox=dict(facecolor="white", edgecolor="none", pad=1.0, alpha=1.0)
        )

    # Edge labels (weights)
    edge_labels = nx.get_edge_attributes(graph, "weight")
    if edge_labels:
        nx.draw_networkx_edge_labels(graph, pos, edge_labels=edge_labels, font_size=6)

    # Legend
    patches = [
        Patch(facecolor="royalblue", label="Host IP"),
        Patch(facecolor="skyblue", label="Worker"),
        Patch(facecolor="lightgreen", label=partition_key.title()),
    ]
    if show_leaf_list:
        patches.append(Patch(facecolor="lightgrey", label="Leaf List"))
    plt.legend(handles=patches, loc="center", bbox_to_anchor=(0.5, -0.05), ncol=len(patches))

    plt.tight_layout()
    plt.title(title)
    plt.axis("off")
    st.pyplot(plt, use_container_width=True)

def _extract_chunk_info(chunk, partition_key, weights_key):
    """Return (partition, size) for a chunk entry with flexible shapes."""

    if isinstance(chunk, dict):
        partition = (
            chunk.get(partition_key)
            or chunk.get(partition_key.replace(" ", "_"))
            or chunk.get("partition")
            or str(chunk)
        )
        size = chunk.get(weights_key)
        if size is None:
            size = chunk.get(weights_key.replace(" ", "_"))
        if size is None:
            size = chunk.get("size", 1)
        return partition, size

    if isinstance(chunk, (tuple, list)):
        if not chunk:
            return "unknown", 1
        if len(chunk) == 1 and isinstance(chunk[0], (tuple, list)):
            chunk = chunk[0]
        if chunk and isinstance(chunk[0], dict):
            data = chunk[0]
            partition = (
                data.get(partition_key)
                or data.get(partition_key.replace(" ", "_"))
                or data.get("partition")
                or str(data)
            )
            size = chunk[1] if len(chunk) > 1 else data.get(weights_key, 1)
            return partition, size
        partition = chunk[0]
        size = chunk[1] if len(chunk) > 1 else 1
        return partition, size

    return chunk, 1


def show_tree(workers, work_plan_metadata, work_plan, partition_key, weights_key, show_leaf_list=False):
    """
    Display the distribution tree of the workload, optionally including the leaf list.
    """
    total = 0
    total_per_host = defaultdict(int)
    workers_works = defaultdict(list)

    for worker, chunks, files_list in zip(workers, work_plan_metadata, work_plan):
        ip = worker.split("-")[0]
        for chunk, files in zip(chunks, files_list):
            partition, size = _extract_chunk_info(chunk, partition_key, weights_key)
            if isinstance(size, numbers.Number):
                size_processed = size
            else:
                try:
                    size_processed = float(size)
                except (TypeError, ValueError):
                    size_processed = 1
                    st.warning(
                        f"Non-numeric size '{size}' for partition '{partition}' treated as 1.".replace("\n", " ")
                    )
            total += size_processed
            total_per_host[ip] += size_processed
            workers_works[worker].append((partition, size_processed, len(files), files))

    if not workers_works:
        st.warning("No workers with assigned chunks found.")
        return

    min_size = min(sum(sz for _, sz, _, _ in w) for w in workers_works.values())
    graph = nx.Graph()

    for worker, works in workers_works.items():
        try:
            ip, wnum = worker.split("-")
        except ValueError:
            st.error(f"Worker identifier '{worker}' is not in the expected 'ip-number' format.")
            continue
        host_load = round(100 * total_per_host[ip] / total) if total else 0
        host_node = f"{ip}\n{host_load}%"
        graph.add_node(host_node, level=0)
        wsize = sum(sz for _, sz, _, _ in works)
        wload = round(100 * wsize / total) if total else 0
        worker_node = f"{wnum}\n{ip}\n{wload}%"
        graph.add_node(worker_node, level=1)
        graph.add_edge(host_node, worker_node, weight=round(wsize / min_size, 1))
        for partition, sz, nfiles, files in works:
            part_node = f"{partition}\n{nfiles} {weights_key}"
            graph.add_node(part_node, level=2)
            graph.add_edge(worker_node, part_node, weight=sz)
            if show_leaf_list and files:
                for leaf in files:
                    graph.add_node(leaf, level=3)
                    graph.add_edge(part_node, leaf)

    _draw_distribution(graph, partition_key, show_leaf_list, title="Distribution Tree")


def show_graph(workers, work_plan_metadata, work_plan, partition_key, weights_key, show_leaf_list=False):
    """
    Display a directed acyclic graph (DAG) based on distribution tree data.
    """
    total = 0
    total_per_host = defaultdict(int)
    workers_works = defaultdict(list)

    for worker, chunks, tree in zip(workers, work_plan_metadata, work_plan):
        ip = worker.split("-")[0]
        for chunk, item in zip(chunks, tree):
            partition, size = _extract_chunk_info(chunk, partition_key, weights_key)
            node, deps = (item[0], item[1]) if len(item) == 2 else (item[0], [])
            size_processed = size if isinstance(size, numbers.Number) else 1
            total += size_processed
            total_per_host[ip] += size_processed
            workers_works[worker].append((partition, size_processed, node, deps))

    if not workers_works:
        st.warning("No workers with assigned chunks found.")
        return

    min_size = min(sum(sz for _, sz, _, _ in w) for w in workers_works.values())
    graph = nx.DiGraph()

    for worker, works in workers_works.items():
        try:
            ip, wnum = worker.split("-")
        except ValueError:
            st.error(f"Worker identifier '{worker}' is not in the expected 'ip-number' format.")
            continue

        host_load = round(100 * total_per_host[ip] / total) if total else 0
        host_node = f"{ip}\n{host_load}%"
        graph.add_node(host_node, level=0)

        wsize = sum(sz for _, sz, _, _ in works)
        wload = round(100 * wsize / total) if total else 0
        worker_node = f"{wnum}\n{ip}\n{wload}%"
        graph.add_node(worker_node, level=1)
        graph.add_edge(host_node, worker_node, weight=round(wsize / min_size, 1))

        for partition, sz, node, deps in works:
            part_node = f"{partition}\nfiles: {len(deps)} {weights_key}"
            graph.add_node(part_node, level=2)
            graph.add_edge(worker_node, part_node, weight=sz)
            if show_leaf_list and deps:
                for leaf in deps:
                    graph.add_node(leaf, level=3)
                    graph.add_edge(part_node, leaf)

    _draw_distribution(graph, partition_key, show_leaf_list, title="Workplan")

def workload_barchart(workers, work_plan_metadata, partition_key, weights_key, weights_unit):
    """Display a workload bar chart using Plotly."""
    import plotly.graph_objects as go
    data = []
    for worker, chunks in zip(workers, work_plan_metadata):
        for chunk in chunks:
            partition, size = _extract_chunk_info(chunk, partition_key, weights_key)
            data.append({"worker": worker, "partition": partition, "size": size})
    df = pd.DataFrame(data)
    if df.empty:
        st.warning("No data available for workload distribution.")
        return
    fig = go.Figure()
    totals_dict = {}
    for worker in workers:
        worker_data = df[df["worker"] == worker]
        totals_dict[worker] = worker_data["size"].sum()
        for partition in worker_data["partition"].unique():
            partition_data = worker_data[worker_data["partition"] == partition]
            size_sum = partition_data["size"].sum()
            fig.add_trace(go.Bar(x=[worker], y=[size_sum], name=str(partition), text=[size_sum], textposition="auto"))
    fig.update_layout(
        barmode="stack",
        title={"text": "Distributed Workload", "x": 0.5, "xanchor": "center"},
        width=1000,
        height=500,
        xaxis_title="Workers",
        yaxis_title=f"{weights_key.title()} ({weights_unit})",
        legend_title=partition_key.title(),
        legend_traceorder="normal",
    )
    for worker, total in totals_dict.items():
        fig.add_annotation(x=worker, y=total, text=f"<b>{total}</b>", showarrow=False, yshift=10)
    st.plotly_chart(fig, use_container_width=True)

def _is_app_installed(env):
    venv_root = env.active_app / ".venv"
    return venv_root.exists()

# ===========================
# Main Application UI
# ===========================
async def page():
    if 'env' not in st.session_state or not getattr(st.session_state["env"], "init_done", True):
        page_module = importlib.import_module("AGILAB")
        page_module.main()
        st.rerun()
        return

    env = st.session_state["env"]
    current_app, changed_from_query = resolve_active_app(env)
    if changed_from_query:
        st.session_state["project_changed"] = True

    st.session_state["_env"] = env

    st.set_page_config(layout="wide", menu_items=get_about_content())
    inject_theme(env.st_resources)
    render_logo()

    if not st.session_state.get("server_started"):
        activate_mlflow(env)
        st.session_state["server_started"] = True

    # Define defaults for session state keys.
    defaults = {
        "profile_report_file": env.AGILAB_EXPORT_ABS / "profile_report.html",
        "preview_tree": False,
        "data_source": "file",
        "scheduler_ipport": {socket.gethostbyname("localhost"): 8786},
        "workers": {"127.0.0.1": 1},
        "learn": {0, None, None, None, 1},
        "args_input": {},
        "loaded_df": None,
        "df_cols": [],
        "selected_cols": [],
        "check_all": True,
        "export_tab_previous_project": None,
        "env": env,
        "_env": env,
        "TABLE_MAX_ROWS": env.TABLE_MAX_ROWS,
        "_experiment_reload_required": False,
        "dataframe_deleted": False,
    }

    init_session_state(defaults)
    projects = list(env.projects or [])
    if env.app and env.app not in projects:
        projects = [env.app] + projects
    # Seed the selectbox default without touching widget state
    current_project = current_app
    if "args_serialized" not in st.session_state:
        st.session_state["args_serialized"] = ""
    if current_project not in projects:
        current_project = projects[0] if projects else None
    previous_project = current_project
    select_project(projects, current_project)
    project_changed = st.session_state.pop("project_changed", False)
    if project_changed or env.app != previous_project:
        try:
            st.query_params["active_app"] = env.app
        except Exception:
            pass
        store_last_active_app(env.active_app)
        app_settings_snapshot = st.session_state.get("app_settings", {})
        # Clear generic & per-project keys to prevent bleed-through
        st.session_state.pop("cluster_enabled", None)
        st.session_state.pop(f"cluster_enabled__{previous_project}", None)
        st.session_state.pop(f"cluster_scheduler__{previous_project}", None)
        st.session_state.pop(f"cluster_workers__{previous_project}", None)
        st.session_state.pop("cluster_scheduler_value", None)  # legacy
        st.session_state.pop(f"deploy_expanded_{previous_project}", None)
        st.session_state.pop(f"optimize_expanded_{previous_project}", None)
        st.session_state.pop("app_settings", None)
        st.session_state.pop("args_project", None)
        st.session_state["args_serialized"] = ""
        st.session_state["run_log_cache"] = ""
        st.session_state.pop("log_text", None)
        st.session_state.pop("_benchmark_expand", None)
        st.session_state.pop("benchmark", None)
        args_override = None
        if st.session_state.get("is_args_from_ui") and st.session_state.get("args_project") == previous_project:
            state_args = app_settings_snapshot.get("args") if isinstance(app_settings_snapshot, dict) else None
            if state_args:
                args_override = state_args
        st.session_state.pop("is_args_from_ui", None)
        try:
            load_distribution.clear()
        except Exception:
            pass
        initialize_app_settings(args_override=args_override)
        st.rerun()

    module = env.target
    project_path = env.active_app
    export_abs_module = env.AGILAB_EXPORT_ABS / module
    export_abs_module.mkdir(parents=True, exist_ok=True)
    pyproject_file = env.active_app / "pyproject.toml"
    if pyproject_file.exists():
        pyproject_content = pyproject_file.read_text()
        st.session_state["rapids_default"] = ("-cu12" in pyproject_content) and os.name != "nt"
    else:
        st.session_state["rapids_default"] = False
    if "df_export_file" not in st.session_state:
        st.session_state["df_export_file"] = str(export_abs_module / "export.csv")
    if "loaded_df" not in st.session_state:
        st.session_state["loaded_df"] = None

    # Reload app settings after potential project change
    app_settings = st.session_state.get("app_settings")
    if not isinstance(app_settings, dict):
        initialize_app_settings()
        app_settings = st.session_state.get("app_settings")
        if not isinstance(app_settings, dict):
            app_settings = {"args": {}, "cluster": {}}
            st.session_state["app_settings"] = app_settings


    # Sidebar toggles for each page section
    if "show_install" not in st.session_state:
        st.session_state["show_install"] = True
    if "show_distribute" not in st.session_state:
        st.session_state["show_distribute"] = True
    if "show_run" not in st.session_state:
        st.session_state["show_run"] = _is_app_installed(env)
    if st.session_state.get("_show_run_app") != env.app:
        st.session_state["_show_run_app"] = env.app
        st.session_state["show_run"] = _is_app_installed(env)

    show_install = st.session_state["show_install"]
    show_distribute = st.session_state["show_distribute"]
    show_run = st.session_state["show_run"] if _is_app_installed(env) else False

    show_export = True

    cluster_params = app_settings.setdefault("cluster", {})
    cluster_params.setdefault("verbose", 1)
    verbosity_options = [0, 1, 2, 3]
    current_verbose = cluster_params.get("verbose", 1)
    if isinstance(current_verbose, bool):
        current_verbose = 1
    try:
        current_verbose = int(current_verbose)
    except (TypeError, ValueError):
        current_verbose = 1
    if current_verbose not in verbosity_options:
        current_verbose = 1

    user_override = st.session_state.get("_verbose_user_override", False)
    if not user_override:
        current_verbose = 1
        cluster_params["verbose"] = 1

    st.session_state.setdefault("cluster_verbose", current_verbose)

    selected_verbose = st.sidebar.selectbox(
        "Verbosity level",
        options=verbosity_options,
        key="cluster_verbose",
        help="Controls AgiEnv verbosity for generated install/distribute/run snippets.",
    )

    try:
        selected_verbose_int = int(selected_verbose)
    except (TypeError, ValueError):
        selected_verbose_int = 1

    if selected_verbose_int not in verbosity_options:
        selected_verbose_int = 1

    cluster_params["verbose"] = selected_verbose_int
    st.session_state["_verbose_user_override"] = selected_verbose_int != 1

    verbose = cluster_params.get('verbose', 1)
    with st.expander("Do deployment"):
        render_cluster_settings_ui()
        cluster_params = st.session_state.app_settings["cluster"]
        verbose = cluster_params.get('verbose', 1)

        if show_install:
            enabled = cluster_params.get("cluster_enabled", False)
            raw_scheduler = cluster_params.get("scheduler", "")
            scheduler = f'"{str(raw_scheduler)}"' if enabled and raw_scheduler else "None"
            raw_workers = cluster_params.get("workers", "")
            workers = str(raw_workers) if enabled and raw_workers else "None"
            cmd = f"""
import asyncio
from pathlib import Path
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

APPS_PATH = "{env.apps_path}"
APP = "{env.app}"

async def main():
    app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose={verbose})
    res = await AGI.install(app_env, 
                            modes_enabled={st.session_state.mode},
                            scheduler={scheduler}, 
                            workers={workers})
    print(res)
    return res

if __name__ == "__main__":
    asyncio.run(main())"""
            st.code(cmd, language="python")

            install_expanded = st.session_state.get("_install_logs_expanded", True)
            log_expander = st.expander("Install logs", expanded=install_expanded)
            with log_expander:
                log_placeholder = st.empty()
                existing_log = st.session_state.get("log_text", "").strip()
                if existing_log:
                    log_placeholder.code(existing_log, language="python")
            if st.button("INSTALL", key="install_btn", type="primary"):
                st.session_state["_install_logs_expanded"] = True
                _reset_traceback_skip()
                clear_log()
                venv = env.agi_cluster if (env.is_source_env or env.is_worker_env) else env.active_app.parents[1]
                install_command = cmd.replace("asyncio.run(main())", env.snippet_tail)
                context_lines = [
                    "=== Install request ===",
                    f"timestamp: {datetime.now().isoformat(timespec='seconds')}",
                    f"app: {env.app}",
                    f"env_flags: source={env.is_source_env}, worker={env.is_worker_env}",
                    f"cluster_enabled: {enabled}",
                    f"verbose: {verbose}",
                    f"modes_enabled: {st.session_state.get('mode', 'N/A')}",
                    f"scheduler: {raw_scheduler if enabled and raw_scheduler else 'None'}",
                    f"workers: {raw_workers if enabled and raw_workers else 'None'}",
                    f"venv: {venv}",
                    "=== Streaming install logs ===",
                ]
                local_log = []
                with log_expander:
                    log_placeholder.empty()
                    for line in context_lines:
                        _append_log_lines(local_log, line)
                log_placeholder.code(
                    "\n".join(local_log[-LOG_DISPLAY_MAX_LINES:]),
                    language="python",
                    height=INSTALL_LOG_HEIGHT,
                )
                with st.spinner("Installing worker..."):
                    _install_stdout = ""
                    install_stderr = ""
                    install_error: Exception | None = None
                    try:
                        _install_stdout, install_stderr = await env.run_agi(
                            install_command,
                            log_callback=lambda message: _append_log_lines(local_log, message),
                            venv=venv,
                        )
                    except Exception as exc:
                        install_error = exc
                        install_stderr = str(exc)
                        _append_log_lines(local_log, f"ERROR: {install_stderr}")

                    error_flag = bool(install_stderr.strip()) or install_error is not None
                    if not error_flag and _log_indicates_install_failure(local_log):
                        error_flag = True
                        if not install_stderr.strip():
                            install_stderr = "Detected connection failure in install logs."

                    status_line = (
                        "✅ Install complete."
                        if not error_flag
                        else "❌ Install finished with errors. Check logs above."
                    )
                    _append_log_lines(local_log, status_line)
                    with log_expander:
                        log_placeholder.code(
                            "\n".join(local_log[-LOG_DISPLAY_MAX_LINES:]),
                            language="python",
                            height=INSTALL_LOG_HEIGHT,
                        )
                    if error_flag:
                        st.error("Cluster installation failed.")
                    else:
                        st.success("Cluster installation completed.")
                        st.session_state["SET ARGS"] = True
                        st.session_state["show_run"] = True

    # ------------------
    # DISTRIBUTE Section
    # ------------------
    if show_distribute:
        with st.expander(f"{module} args", expanded=True):
            app_args_form = env.app_args_form

            snippet_exists = app_args_form.exists()
            snippet_not_empty = snippet_exists and app_args_form.stat().st_size > 1

            toggle_key = "toggle_edit_ui"
            if toggle_key not in st.session_state:
                st.session_state[toggle_key] = not snippet_not_empty

            st.toggle("Edit", key=toggle_key, on_change=init_custom_ui, args=[app_args_form])

            if st.session_state[toggle_key]:
                render_generic_ui()
                if not snippet_exists:
                    with open(app_args_form, "w") as st_src:
                        st_src.write("")
            else:
                if snippet_exists and snippet_not_empty:
                    try:
                        runpy.run_path(app_args_form, init_globals=globals())
                    except Exception as e:
                        st.warning(e)
                else:
                    render_generic_ui()
                    if not snippet_exists:
                        with open(app_args_form, "w") as st_src:
                            st_src.write("")

            cluster_params = st.session_state.app_settings.setdefault("cluster", {})
            cluster_enabled = bool(cluster_params.get("cluster_enabled", False))
            if cluster_enabled:
                # Refresh mount table cache each rerun (mounts can appear/disappear while Streamlit stays alive).
                try:
                    _mount_table.cache_clear()
                except Exception:
                    pass
                share_candidate = Path(env.agi_share_path)
                if not share_candidate.is_absolute():
                    share_candidate = Path(env.home_abs) / share_candidate
                share_candidate = share_candidate.expanduser()
                is_symlink = share_candidate.is_symlink()
                try:
                    share_resolved = share_candidate.resolve()
                except Exception:
                    share_resolved = share_candidate
                looks_shared = _looks_like_shared_path(share_candidate) or _looks_like_shared_path(share_resolved)
                if not is_symlink and not looks_shared:
                    fstype = _fstype_for_path(share_resolved) or _fstype_for_path(share_candidate) or "unknown"
                    hint = _macos_autofs_hint(share_candidate)
                    extra = f"\n\n{hint}" if hint else ""
                    st.warning(
                        f"Cluster is enabled but the data directory `{share_resolved}` appears local. "
                        f"(detected fstype: `{fstype}`) "
                        "Set `AGI_SHARE_DIR` to a shared mount (or symlink to one) so remote workers can read outputs."
                        f"{extra}",
                        icon="⚠️",
                    )

            args_serialized = ", ".join(
                [f'{key}="{value}"' if isinstance(value, str) else f"{key}={value}"
                 for key, value in st.session_state.app_settings["args"].items()]
            )
            st.session_state["args_serialized"] = args_serialized
            if st.session_state.get("args_reload_required"):
                del st.session_state["app_settings"]
                st.rerun()
        with st.expander("Check orchestration", expanded=False):
            cluster_params = st.session_state.app_settings["cluster"]
            enabled = cluster_params.get("cluster_enabled", False)
            scheduler = cluster_params.get("scheduler", "")
            scheduler = f'"{str(scheduler)}"' if enabled and scheduler else "None"
            workers = cluster_params.get("workers", {})
            workers = str(workers) if enabled and workers else "None"
            cmd = f"""
import asyncio
from pathlib import Path
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

APPS_PATH = "{env.apps_path}"
APP = "{env.app}"

async def main():
    app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose={verbose})
    res = await AGI.get_distrib(app_env,
                               scheduler={scheduler}, 
                               workers={workers},
                               {st.session_state.args_serialized})
    print(res)
    return res

if __name__ == "__main__":
    asyncio.run(main())"""
            st.code(cmd, language="python")
            if st.button("CHECK distribute", key="preview_btn", type="primary"):
                st.session_state.preview_tree = True
                with st.expander("Orchestration log", expanded=False):
                    dist_log: list[str] = []
                    live_log_placeholder = st.empty()
                    _reset_traceback_skip()
                    with st.spinner("Building distribution..."):
                        stdout, stderr = await env.run_agi(
                            cmd.replace("asyncio.run(main())", env.snippet_tail),
                            log_callback=lambda message: _append_log_lines(dist_log, message),
                            venv=project_path
                        )
                    if stderr:
                        _append_log_lines(dist_log, stderr)
                    if stdout:
                        _append_log_lines(dist_log, stdout)
                    live_log_placeholder.code(
                        "\n".join(dist_log[-LOG_DISPLAY_MAX_LINES:]),
                        language="python",
                        height=LIVE_LOG_MIN_HEIGHT,
                    )
                    if not stderr:
                        st.success("Distribution built successfully.")

            with st.expander("Workplan", expanded=False):
                if st.session_state.get("preview_tree"):
                    dist_tree_path = env.wenv_abs / "distribution.json"
                    if dist_tree_path.exists():
                        workers, work_plan_metadata, work_plan = load_distribution(dist_tree_path)
                        partition_key = "Partition"
                        weights_key = "Units"
                        weights_unit = "Unit"
                        tabs = st.tabs(["Tree", "Workload"])
                        with tabs[0]:
                            if env.base_worker_cls.endswith('dag-worker'):
                                show_graph(workers, work_plan_metadata, work_plan, partition_key, weights_key,
                                       show_leaf_list=st.checkbox("Show leaf nodes", value=False))
                            else:
                                show_tree(workers, work_plan_metadata, work_plan, partition_key, weights_key,
                                       show_leaf_list=st.checkbox("Show leaf nodes", value=False))
                        with tabs[1]:
                            workload_barchart(workers, work_plan_metadata, partition_key, weights_key, weights_unit)
                        unused_workers = [worker for worker, chunks in zip(workers, work_plan_metadata) if not chunks]
                        if unused_workers:
                            st.warning(f"**{len(unused_workers)} Unused workers:** " + ", ".join(unused_workers))
                        st.markdown("**Modify Distribution:**")
                        ncols = 2
                        cols = st.columns([10, 1, 10])
                        count = 0
                        for i, chunks in enumerate(work_plan_metadata):
                            for j, chunk in enumerate(chunks):
                                partition, size = chunk
                                with cols[0 if count % ncols == 0 else 2]:
                                    b1, b2 = st.columns(2)
                                    b1.text(f"{partition_key.title()} {partition} ({weights_key}: {size} {weights_unit})")
                                    key = f"worker_partition_{partition}_{i}_{j}"
                                    b2.selectbox("Worker", options=workers, key=key, index=i if i < len(workers) else 0)
                                count += 1
                        if st.button("Apply", key="apply_btn", type="primary"):
                            new_work_plan_metadata = [[] for _ in workers]
                            new_work_plan = [[] for _ in workers]
                            for i, (chunks, files_tree) in enumerate(zip(work_plan_metadata, work_plan)):
                                for j, (chunk, files) in enumerate(zip(chunks, files_tree)):
                                    key = f"worker_partition{chunk[0]}"
                                    selected_worker = st.session_state.get(key)
                                    if selected_worker and selected_worker in workers:
                                        idx = workers.index(selected_worker)
                                        new_work_plan_metadata[idx].append(chunk)
                                        new_work_plan[idx].append(files)
                            # Read & update the original JSON dict (avoid writing to the workers list)
                            with open(dist_tree_path, "r") as f:
                                data = json.load(f)
                            data["target_args"] = st.session_state.app_settings["args"]
                            data["work_plan_metadata"] = new_work_plan_metadata
                            data["work_plan"] = new_work_plan
                            with open(dist_tree_path, "w") as f:
                                json.dump(data, f)
                            st.rerun()

    # ------------------
    # RUN Section
    # ------------------
    run_clicked = False
    existing_run_log = st.session_state.get("run_log_cache", "").strip()
    run_log_expander = None
    log_container = None
    cmd = None
    if show_run:
        # Reset run log state when switching between projects so the expander starts closed
        prev_app_key = "execute_prev_app"
        if st.session_state.get(prev_app_key) != env.app:
            st.session_state[prev_app_key] = env.app
            st.session_state["run_log_cache"] = ""
            st.session_state.pop("log_text", None)
            st.session_state.pop("_benchmark_expand", None)
            st.session_state.pop("_force_export_open", None)
        st.session_state.setdefault("run_log_cache", "")
        cmd = None
        with st.expander("Optimize execution"):
            # Benchmark toggle
            st.session_state.setdefault("benchmark", False)
            if st.session_state.pop("benchmark_reset_pending", False):
                st.session_state["benchmark"] = False
            # ---- Compute run_mode exactly once (single source of truth)
            cluster_params = st.session_state.app_settings["cluster"]
            cluster_enabled = bool(cluster_params.get("cluster_enabled", False))

            benchmark_prereqs_met = cluster_enabled and all(
                cluster_params.get(flag, False) for flag in ("pool", "cython")
            )
            if not benchmark_prereqs_met and st.session_state.get("benchmark"):
                st.session_state["benchmark"] = False

            requested_benchmark = st.toggle(
                "Benchmark all modes",
                key="benchmark",
                help="Run the snippet once per mode and report timings for each path",
                disabled=not benchmark_prereqs_met,
            )

            if benchmark_prereqs_met:
                benchmark_enabled = requested_benchmark
            else:
                benchmark_enabled = False
                st.warning(
                    "Benchmark requires Cluster, Pool, and Cython to be enabled together."
                )

            def _compute_mode():
                # 0/1 pool + 0/2 cython + 0/4 dask + 0/8 rapids
                return (
                    int(cluster_params.get("pool", False))
                    + int(cluster_params.get("cython", False)) * 2
                    + int(cluster_enabled) * 4
                    + int(cluster_params.get("rapids", False)) * 8
                )

            if benchmark_enabled:
                run_mode = None
                info_label = "Run mode benchmark (all modes)"
            else:
                run_mode = _compute_mode()
                run_mode_label = [
                    "0: python", "1: pool of process", "2: cython", "3: pool and cython",
                    "4: dask", "5: dask and pool", "6: dask and cython", "7: dask and pool and cython",
                    "8: rapids", "9: rapids and pool", "10: rapids and cython", "11: rapids and pool and cython",
                    "12: rapids and dask", "13: rapids and dask and pool", "14: rapids and dask and cython",
                    "15: rapids and dask and pool and cython"
                ]
                info_label = f"Run mode {run_mode_label[run_mode]}"

            # Keep session_state in sync (for any other code that reads it)
            st.session_state["mode"] = run_mode
            st.info(info_label)

            verbose = cluster_params.get('verbose', 1)
            enabled = cluster_enabled
            scheduler = f'"{cluster_params.get("scheduler")}"' if enabled and cluster_params.get("scheduler") else "None"
            workers = str(cluster_params.get("workers")) if enabled and cluster_params.get("workers") else "None"
            cmd = f"""
import asyncio
from pathlib import Path
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

APPS_PATH = "{env.apps_path}"
APP = "{env.app}"

async def main():
    app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose={verbose})
    res = await AGI.run(app_env, 
                        mode={run_mode if run_mode is not None else "None"}, 
                        scheduler={scheduler}, 
                        workers={workers}, 
                        {st.session_state.args_serialized})
    print(res)
    return res

if __name__ == "__main__":
    asyncio.run(main())"""
            st.code(cmd, language="python")

            expand_benchmark = st.session_state.pop("_benchmark_expand", False)
            with st.expander("Benchmark results", expanded=expand_benchmark):
                try:
                    if env.benchmark.exists():
                        with open(env.benchmark, "r") as f:
                            raw = json.load(f) or {}

                        # Pull out a date if present, so it doesn't break the DF shape
                        date_value = str(raw.pop("date", "") or "").strip()

                        benchmark_df = pd.DataFrame.from_dict(raw, orient='index')

                        df_nonempty = benchmark_df.dropna(how='all')
                        if not df_nonempty.empty:
                            df_nonempty = df_nonempty.loc[:, df_nonempty.notna().any(axis=0)]
                        if not df_nonempty.empty and df_nonempty.shape[1] > 0:
                            if not date_value:
                                try:
                                    ts = os.path.getmtime(env.benchmark)
                                    date_value = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                                except Exception:
                                    date_value = ""

                            if date_value:
                                st.caption(f"Benchmark date: {date_value}")

                            st.dataframe(df_nonempty)
                        else:
                            st.info("Benchmark file is present but empty. Run the benchmark to collect data.")
                    else:
                        st.info("No benchmark results yet. Enable 'Benchmark all modes' and run EXECUTE to gather data.")

                except json.JSONDecodeError as e:
                    st.warning(f"Error decoding JSON: {e}")

        existing_run_log = st.session_state.get("run_log_cache", "").strip()
        run_log_expander = None
        log_container = None

        def _ensure_run_log_expander(*, expanded: bool):
            nonlocal run_log_expander, log_container
            if run_log_expander is None:
                if log_container is None:
                    log_container = st.container()
                with log_container:
                    run_log_expander = st.expander("Run logs", expanded=expanded)
            return run_log_expander

        async def _execute_with_logging(current_expander, label: str):
            """Run the configured AGI command and surface logs inside an expander."""
            clear_log()
            st.session_state["run_log_cache"] = ""
            target_expander = current_expander or _ensure_run_log_expander(expanded=True)
            with target_expander:
                log_placeholder = st.empty()
            _reset_traceback_skip()
            log_dir = Path(env.runenv or (Path.home() / "log" / "execute" / env.app))
            log_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_file_path = log_dir / f"run_{timestamp}.log"
            st.session_state["last_run_log_path"] = str(log_file_path)

            async def _run_and_stream():
                nonlocal log_file_path
                with log_file_path.open("w", encoding="utf-8") as log_file:
                    def _fanout(message: str) -> None:
                        clean = strip_ansi(message or "").rstrip()
                        if clean:
                            log_file.write(clean + "\n")
                            log_file.flush()
                        update_log(log_placeholder, message)

                    _, stderr_text = await env.run_agi(
                        cmd.replace("asyncio.run(main())", env.snippet_tail),
                        log_callback=_fanout,
                        venv=project_path,
                    )
                    return stderr_text

            with st.spinner("Running AGI..."):
                stderr = await _run_and_stream()
                st.session_state["run_log_cache"] = st.session_state.get("log_text", "")
            with target_expander:
                log_placeholder.empty()
                display_log(st.session_state["run_log_cache"], stderr)
                st.caption(f"Logs saved to {log_file_path}")
            st.session_state["dataframe_deleted"] = False
            return target_expander

        run_col, load_col, delete_col = st.columns(3)
        run_label = "RUN benchmark" if st.session_state.get("benchmark") else "EXECUTE"
        if cmd:
            run_clicked = run_col.button(
                run_label,
                key="run_btn",
                type="primary",
                use_container_width=True,
            )
        else:
            run_col.button(
                run_label,
                key="run_btn_disabled",
                type="primary",
                disabled=True,
                help="Configure the run snippet to enable execution",
                use_container_width=True,
            )

        load_clicked = load_col.button(
            "LOAD dataframe",
            key="load_data_main",
            type="primary",
            use_container_width=True,
            help="Fetch the latest dataframe preview for export",
        )
        if st.session_state.pop("_combo_load_trigger", False):
            load_clicked = True

        delete_clicked = delete_col.button(
            "DELETE dataframe",
            key="delete_data_main",
            type="secondary",
            use_container_width=True,
            help="Clear the cached dataframe preview so the next load reflects a fresh EXECUTE run.",
        )

        if load_clicked:
            if st.session_state.get("dataframe_deleted"):
                st.info("Dataframe preview was deleted. Run EXECUTE again before loading a new export.")
            else:
                candidate_roots: list[Path] = []

                def _attach_root(raw_path: Optional[Path | str]) -> None:
                    if not raw_path:
                        return
                    path = Path(raw_path).expanduser()
                    if not path.is_absolute():
                        path = Path.home() / path
                    candidate_roots.append(path)

                _attach_root(env.dataframe_path)
                _attach_root(env.app_data_rel)

                active_args = st.session_state.app_settings.get("args", {})
                _attach_root(active_args.get("data_in"))
                _attach_root(active_args.get("data_out"))

                # Remove duplicates while preserving order
                unique_roots: list[Path] = []
                seen_roots = set()
                for root in candidate_roots:
                    key = str(root.resolve()) if root.exists() else str(root)
                    if key not in seen_roots:
                        seen_roots.add(key)
                        unique_roots.append(root)

                target_file: Optional[Path] = None
                search_files: list[Path] = []
                for root in unique_roots:
                    if root.is_dir():
                        search_files.extend(
                            list(root.rglob("*.parquet"))
                            + list(root.rglob("*.csv"))
                            + list(root.rglob("*.json"))
                            + list(root.rglob("*.gml"))
                        )
                    elif root.is_file():
                        search_files.append(root)

                if search_files:
                    try:
                        target_file = max(search_files, key=lambda file: file.stat().st_mtime)
                    except FileNotFoundError:
                        target_file = None
                # Filter out metadata stubs like `._file.csv` and empty artefacts before loading.
                search_files = [
                    file_path
                    for file_path in search_files
                    if file_path.is_file()
                    and not file_path.name.startswith("._")
                    and file_path.stat().st_size > 0
                ]
                if target_file and target_file not in search_files:
                    target_file = max(search_files, key=lambda file: file.stat().st_mtime) if search_files else None

                if not target_file:
                    st.warning("No dataframe export found yet. Run EXECUTE to generate a fresh output.")
                else:
                    st.session_state["loaded_source_path"] = target_file
                    suffix = target_file.suffix.lower()
                    try:
                        if suffix in {".csv", ".parquet"}:
                            # Gather the most recent batch of files so multi-flight runs remain intact.
                            latest_mtime = target_file.stat().st_mtime
                            batch_window = st.session_state.get("export_batch_window_seconds", 600)
                            try:
                                batch_window = int(batch_window)
                            except (TypeError, ValueError):
                                batch_window = 600

                            candidate_batch = sorted(
                                {
                                    file_path
                                    for file_path in search_files
                                    if file_path.suffix.lower() == suffix
                                    and file_path.parent == target_file.parent
                                    and abs(latest_mtime - file_path.stat().st_mtime) <= batch_window
                                },
                                key=lambda p: p.stat().st_mtime,
                            )

                            if not candidate_batch:
                                candidate_batch = [target_file]

                            frames = []
                            for file_path in candidate_batch:
                                df_piece = cached_load_df(file_path, with_index=False, nrows=0)
                                if isinstance(df_piece, pd.DataFrame) and not df_piece.empty:
                                    df_piece = df_piece.copy()
                                    df_piece["__source__"] = file_path.name
                                    frames.append(df_piece)

                            loaded_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

                            if isinstance(loaded_df, pd.DataFrame) and not loaded_df.empty:
                                st.session_state["loaded_df"] = loaded_df
                                st.session_state["_force_export_open"] = True
                                st.session_state.pop("loaded_graph", None)
                                if len(candidate_batch) > 1:
                                    st.success(f"Loaded dataframe preview from {len(candidate_batch)} files (latest: {target_file.name}).")
                                else:
                                    st.success(f"Loaded dataframe preview from {target_file.name}.")
                            else:
                                st.warning(f"{target_file.name} is empty; nothing to preview.")
                        elif suffix == ".json":
                            payload = json.loads(target_file.read_text())
                            if isinstance(payload, dict) and "nodes" in payload and "links" in payload:
                                graph = json_graph.node_link_graph(payload, directed=payload.get("directed", True))
                                st.session_state["loaded_df"] = None
                                st.session_state["_force_export_open"] = False
                                st.session_state["loaded_graph"] = graph
                                st.success(f"Loaded network graph from {target_file.name}.")
                            else:
                                loaded_df = pd.json_normalize(payload)
                                st.session_state["loaded_df"] = loaded_df
                                st.session_state["_force_export_open"] = True
                                st.session_state.pop("loaded_graph", None)
                                st.info(f"Parsed JSON payload as tabular data from {target_file.name}.")
                        elif suffix == ".gml":
                            graph = nx.read_gml(target_file)
                            edge_df = nx.to_pandas_edgelist(graph)
                            if not edge_df.empty:
                                st.session_state["loaded_df"] = edge_df
                                st.session_state["_force_export_open"] = True
                                st.session_state["loaded_graph"] = graph
                                st.success(f"Loaded topology edges from {target_file.name}.")
                            else:
                                node_df = pd.DataFrame(
                                    [(node, data) for node, data in graph.nodes(data=True)],
                                    columns=["node", "attributes"],
                                )
                                if node_df.empty:
                                    st.warning(f"{target_file.name} did not contain edges or node attributes to display.")
                                else:
                                    st.session_state["loaded_df"] = node_df
                                    st.session_state["_force_export_open"] = True
                                    st.session_state["loaded_graph"] = graph
                                    st.info(f"Showing node metadata from {target_file.name}.")
                        else:
                            st.warning(f"Unsupported file format: {target_file.suffix}")
                    except json.JSONDecodeError as exc:
                        st.error(f"Failed to decode JSON from {target_file.name}: {exc}")
                    except Exception as exc:
                        st.error(f"Unable to load {target_file.name}: {exc}")

        if delete_clicked:
            st.session_state["dataframe_deleted"] = True
            source_path = st.session_state.pop("loaded_source_path", None)
            st.session_state["loaded_df"] = None
            st.session_state.pop("df_cols", None)
            st.session_state.pop("selected_cols", None)
            st.session_state["check_all"] = False
            st.session_state["_force_export_open"] = False
            st.session_state.pop("loaded_graph", None)

            deleted = False
            if source_path:
                file_path = Path(source_path)
                try:
                    if file_path.exists():
                        file_path.unlink()
                        try:
                            cached_load_df.clear()
                        except Exception:
                            pass
                        try:
                            find_files.clear()
                        except Exception:
                            pass
                        st.success(f"Deleted {file_path.name} from disk.")
                        deleted = True
                    else:
                        st.info("Loaded file already removed from disk.")
                except Exception as exc:
                    st.error(f"Failed to delete {file_path}: {exc}")

            if not deleted:
                st.info("Dataframe preview cleared. Run EXECUTE then LOAD to refresh with new output.")


    if run_clicked and cmd:
        run_log_expander = await _execute_with_logging(run_log_expander, "Run logs")
        if st.session_state.get("benchmark"):
            st.session_state["_benchmark_expand"] = True
            st.rerun()

    combo_clicked = False
    if cmd:
        combo_clicked = st.button(
            "EXECUTE → LOAD → EXPORT",
            key="combo_exec_load_export",
            type="primary",
            help="Run EXECUTE, LOAD dataframe, and EXPORT output in one click.",
            use_container_width=True,
        )

    if combo_clicked:
        if cmd:
            run_log_expander = await _execute_with_logging(run_log_expander, "Run logs")
        else:
            st.error("No EXECUTE command configured; please configure it first.")

        st.session_state["_combo_load_trigger"] = True
        st.session_state["_combo_export_trigger"] = True
        st.rerun()

    if existing_run_log and run_log_expander is None:
        expander = _ensure_run_log_expander(expanded=False)
        with expander:
            st.code(existing_run_log, language="python")

    df_preview = st.session_state.get("loaded_df")
    graph_preview = st.session_state.get("loaded_graph")
    source_preview_path = st.session_state.get("loaded_source_path")
    source_preview_name = None
    if source_preview_path:
        try:
            source_preview_name = Path(source_preview_path).name
        except Exception:
            source_preview_name = str(source_preview_path)
    if isinstance(df_preview, pd.DataFrame) and not df_preview.empty:
        st.dataframe(df_preview)
        if source_preview_name:
            st.caption(f"Previewing {source_preview_name}")
    elif isinstance(graph_preview, nx.Graph):
        st.caption("Graph preview generated from JSON output")
        fig, ax = plt.subplots(figsize=(8, 6))
        pos = nx.spring_layout(graph_preview, seed=42)
        node_colors = "skyblue"
        nx.draw_networkx_nodes(graph_preview, pos, node_color=node_colors, ax=ax)
        nx.draw_networkx_edges(graph_preview, pos, ax=ax, alpha=0.5)
        nx.draw_networkx_labels(graph_preview, pos, ax=ax, font_size=9)
        ax.axis("off")
        st.pyplot(fig, use_container_width=True)
        plt.close(fig)
        if source_preview_name:
            st.caption(f"Source: {source_preview_name}")

    export_expanded = st.session_state.pop("_force_export_open", False)
    loaded_df = st.session_state.get("loaded_df")

    if isinstance(loaded_df, pd.DataFrame) and not loaded_df.empty:
        expander = st.expander("Prepare data for experiment and exploration", expanded=export_expanded)
        with expander:
            loaded_df.columns = [
                col if col.strip() != "" else f"Unnamed Column {idx}"
                for idx, col in enumerate(loaded_df.columns)
            ]

            if ("export_tab_previous_project" not in st.session_state or
                    st.session_state.export_tab_previous_project != env.app or
                    st.session_state.get("df_cols") != (loaded_df.columns.tolist() if loaded_df is not None else [])):

                st.session_state.export_tab_previous_project = env.app
                st.session_state.df_cols = loaded_df.columns.tolist()
                st.session_state.selected_cols = loaded_df.columns.tolist()
                st.session_state.check_all = True

            if st.session_state.pop("_reset_export_checkboxes", False):
                st.session_state.selected_cols = st.session_state.df_cols.copy()
                st.session_state.check_all = True
                for idx in range(len(st.session_state.df_cols)):
                    st.session_state[f"export_col_{idx}"] = True
                st.session_state["_force_export_open"] = True

            def on_select_all_changed():
                st.session_state.selected_cols = st.session_state.df_cols.copy() if st.session_state.check_all else []
                for idx in range(len(st.session_state.df_cols)):
                    st.session_state[f"export_col_{idx}"] = st.session_state.check_all
                st.session_state["_force_export_open"] = True

            st.checkbox("Select All", key="check_all", on_change=on_select_all_changed)

            def on_individual_checkbox_change(col_name, state_key):
                if st.session_state.get(state_key):
                    if col_name not in st.session_state.selected_cols:
                        st.session_state.selected_cols.append(col_name)
                else:
                    if col_name in st.session_state.selected_cols:
                        st.session_state.selected_cols.remove(col_name)
                st.session_state.check_all = len(st.session_state.selected_cols) == len(st.session_state.df_cols)
                st.session_state["_force_export_open"] = True

            cols_layout = st.columns(5)
            for idx, col in enumerate(st.session_state.df_cols):
                label = col if col.strip() != "" else f"Unnamed Column {idx}"
                state_key = f"export_col_{idx}"
                st.session_state.setdefault(state_key, col in st.session_state.selected_cols)
                with cols_layout[idx % 5]:
                    st.checkbox(
                        label,
                        key=state_key,
                        on_change=on_individual_checkbox_change,
                        args=(col, state_key)
                    )

            export_file_input = st.text_input(
                "Export to filename:",
                value=st.session_state.df_export_file,
                key="input_df_export_file_main"
            )
            st.session_state.df_export_file = export_file_input.strip()

            action_col_stats, action_col_export = st.columns([1, 1])
            with action_col_stats:
                stats_clicked = st.button("STATS report", key="stats_report_main", type="primary", use_container_width=True)
            with action_col_export:
                export_clicked_manual = st.button("EXPORT dataframe", key="export_df_main", type="primary", use_container_width=True, help="Save the current run output to export/export.csv so Experiment/Explore can load it.")
            combo_export_trigger = st.session_state.pop("_combo_export_trigger", False)
            export_clicked = export_clicked_manual or combo_export_trigger

            if stats_clicked:
                profile_file = st.session_state.profile_report_file
                if not profile_file.exists():
                    profile = generate_profile_report(loaded_df)
                    with st.spinner("Generating profile report..."):
                        profile.to_file(profile_file, silent=False)
                open_new_tab(profile_file.as_uri())

            if export_clicked:
                target_path = st.session_state.df_export_file
                if not st.session_state.selected_cols:
                    st.warning("No columns selected for export.")
                elif not target_path:
                    st.warning("Please provide a filename for the export.")
                else:
                    exported_df = loaded_df[st.session_state.selected_cols]
                    if save_csv(exported_df, target_path):
                        st.success(f"Dataframe exported successfully to {target_path}.")
                        st.session_state["_reset_export_checkboxes"] = True
                        st.session_state["_experiment_reload_required"] = True

                if st.session_state.profile_report_file.exists():
                    os.remove(st.session_state.profile_report_file)
    else:
        st.session_state.df_cols = []
        st.session_state.selected_cols = []
        st.session_state.check_all = False
        st.info("No data loaded yet. Click 'LOAD dataframe' in Execute to populate it before export.")

# ===========================
# Main Entry Point
# ===========================
async def main():
    try:
        await page()
    except Exception as e:
        st.error(f"An error occurred: {e}")
        import traceback
        st.code(f"```\n{traceback.format_exc()}\n```")

if __name__ == "__main__":
    asyncio.run(main())
