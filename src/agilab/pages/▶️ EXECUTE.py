import asyncio

# ===========================
# Standard Imports (lightweight)
# ===========================
import os
import socket
import runpy
import ast
import re
import json
import numbers
import logging
from pathlib import Path
import importlib
from datetime import datetime

# Third-Party imports
import networkx as nx
import matplotlib.pyplot as plt
import textwrap
from matplotlib.patches import Patch
from collections import defaultdict
import tomli         # For reading TOML files
import tomli_w       # For writing TOML files
import pandas as pd
# Theme configuration
os.environ.setdefault("STREAMLIT_CONFIG_FILE", str(Path(__file__).resolve().parents[1] / "resources" / "config.toml"))
import streamlit as st
# Project Libraries:
from agi_env.pagelib import (
    get_about_content, render_logo, activate_mlflow, save_csv, init_custom_ui, select_project, open_new_tab,
    cached_load_df, inject_theme
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
    if clean_msg:
        st.session_state["log_text"] += clean_msg + "\n"

    # Keep only last max_lines lines to avoid huge memory/logs
    lines = st.session_state["log_text"].splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
        st.session_state["log_text"] = "\n".join(lines) + "\n"

    # Calculate height in pixels roughly: 20px per line, capped at 500px
    height_px = min(20 * len(lines), 500)

    live_log_placeholder.code(st.session_state["log_text"], language="python", height=height_px)



def strip_ansi(text: str) -> str:
    if not text:
        return ""
    ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
    return ansi_escape.sub('', text)


def display_log(stdout, stderr):
    # Use cached log if stdout empty
    if not stdout.strip() and "log_text" in st.session_state:
        stdout = st.session_state["log_text"]

    # Strip ANSI color codes from both stdout and stderr
    clean_stdout = strip_ansi(stdout or "")
    clean_stderr = strip_ansi(stderr or "")

    # Clean up extra blank lines
    clean_stdout = "\n".join(line for line in clean_stdout.splitlines() if line.strip())
    clean_stderr = "\n".join(line for line in clean_stderr.splitlines() if line.strip())

    combined = "\n".join([clean_stdout, clean_stderr]).strip()

    if "warning:" in combined.lower():
        st.warning("Warnings occurred during cluster installation:")
        st.code(combined, language="python", height=400)
    elif clean_stderr:
        st.error("Errors occurred during cluster installation:")
        st.code(clean_stderr, language="python", height=400)
    else:
        st.code(clean_stdout or "No logs available", language="python", height=400)


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

def parse_and_validate_scheduler(scheduler_input):
    """
    Accept IP or IP:PORT. Validate IP via env.is_valid_ip(host) and optional numeric port.
    """
    apps_dir_value = st.session_state.get("apps_dir")
    env = st.session_state.setdefault(
        "env",
        AgiEnv(
            apps_dir=Path(apps_dir_value).expanduser() if apps_dir_value else None,
            verbose=0,
        ),
    )
    scheduler = (scheduler_input or "").strip()
    if not scheduler:
        st.error("Scheduler must be provided as a valid IP address (optionally with :PORT).")
        return None

    host, sep, port = scheduler.partition(":")
    if not env.is_valid_ip(host):
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
        invalid_ips = [ip for ip in workers.keys() if not env.is_valid_ip(ip)]
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
                return tomli.load(f)
        except tomli.TOMLDecodeError as exc:
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
        # per-project widget key & seeding; do not also pass value=
        scheduler_widget_key = f"cluster_scheduler__{env.app}"
        if scheduler_widget_key not in st.session_state:
            st.session_state[scheduler_widget_key] = cluster_params.get("scheduler", "")
        scheduler_input = st.text_input(
            "Scheduler IP Address",
            key=scheduler_widget_key,
            placeholder="e.g., 192.168.0.100 or 192.168.0.100:8786",
            help="Provide a scheduler IP address (optionally with :PORT).",
        )
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
    st.session_state["_env"] = env

    st.set_page_config(layout="wide", menu_items=get_about_content())
    inject_theme(env.st_resources)
    render_logo("Execute your Application")

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
        "TABLE_MAX_ROWS": getattr(env, "TABLE_MAX_ROWS", None),
        "_experiment_reload_required": False,
    }

    init_session_state(defaults)
    projects = env.projects
    current_project = env.app
    if "args_serialized" not in st.session_state:
        st.session_state["args_serialized"] = ""
    if current_project not in projects:
        current_project = projects[0] if projects else None
    previous_project = current_project
    select_project(projects, current_project)
    project_changed = st.session_state.pop("project_changed", False)
    if project_changed or env.app != previous_project:
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
    deploy_state_key = f"deploy_expanded_{env.app}"
    with st.expander(
        "Do deployment",
        expanded=st.session_state.get(deploy_state_key, False),
    ):
        st.session_state[deploy_state_key] = True
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
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

APPS_DIR = "{env.apps_dir}"
APP = "{env.app}"

async def main():
    app_env = AgiEnv(apps_dir=APPS_DIR, app=APP, verbose={verbose})
    res = await AGI.install(app_env, 
                            modes_enabled={st.session_state.get('mode', 0)},
                            scheduler={scheduler}, 
                            workers={workers})
    print(res)
    return res

if __name__ == "__main__":
    asyncio.run(main())"""
            st.code(cmd, language="python")

            log_expander = st.expander("Install logs", expanded=False)
            with log_expander:
                log_placeholder = st.empty()
                existing_log = st.session_state.get("log_text", "").strip()
                if existing_log:
                    log_placeholder.code(existing_log, language="python")
            if st.button("INSTALL", key="install_btn", type="primary",
                         help="Run the install snippet to set up your .venv for Manager and Worker"):
                clear_log()
                venv = env.cluster_root if (env.is_source_env or env.is_worker_env) else env.active_app.parents[1]
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
                with log_expander:
                    log_placeholder.empty()
                    for line in context_lines:
                        update_log(log_placeholder, line)
                with st.spinner("Installing worker..."):
                    _stdout, stderr = await env.run_agi(
                        install_command,
                        log_callback=lambda message: update_log(log_placeholder, message),
                        venv=venv
                    )

                    with log_expander:
                        status_line = "✅ Install finished without errors." if not stderr else "❌ Install finished with errors. Check logs above."
                        update_log(log_placeholder, status_line)
                        log_placeholder.empty()
                        display_log(st.session_state.get("log_text", ""), stderr)
                    if not stderr:
                        st.success("Cluster installation completed.")
                        st.session_state["SET ARGS"] = True
                        st.session_state["show_run"] = True
                        st.rerun()

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
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

APPS_DIR = "{env.apps_dir}"
APP = "{env.app}"

async def main():
    app_env = AgiEnv(apps_dir=APPS_DIR, app=APP, verbose={verbose})
    res = await AGI.get_distrib(app_env,
                               scheduler={scheduler}, 
                               workers={workers},
                               {st.session_state.args_serialized})
    print(res)
    return res

if __name__ == "__main__":
    asyncio.run(main())"""
            st.code(cmd, language="python")
            if st.button("CHECK distribute", key="preview_btn", type="primary",
                         help="Run the snippet and display your distribution tree"):
                st.session_state.preview_tree = True
                with st.expander("Orchestration log", expanded=False):
                    clear_log()
                    live_log_placeholder = st.empty()
                    with st.spinner("Building distribution..."):
                        stdout, stderr = await env.run_agi(
                            cmd.replace("asyncio.run(main())", env.snippet_tail),
                            log_callback=lambda message: update_log(live_log_placeholder, message),
                            venv=project_path
                        )
                    live_log_placeholder.empty()
                    display_log(stdout, stderr)
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
    if show_run:
        st.session_state.setdefault("run_log_cache", "")
        cmd = None
        optimize_state_key = f"optimize_expanded_{env.app}"
        with st.expander("Optimize execution", expanded=st.session_state.get(optimize_state_key, False)):
            st.session_state[optimize_state_key] = True
            # Benchmark toggle
            st.session_state.setdefault("benchmark", False)
            if st.session_state.pop("benchmark_reset_pending", False):
                st.session_state["benchmark"] = False
            benchmark_enabled = st.toggle(
                "Benchmark all modes",
                key="benchmark",
                help="Run the snippet once per mode and report timings for each path",
            )

            # ---- Compute run_mode exactly once (single source of truth)
            cluster_params = st.session_state.app_settings["cluster"]
            cluster_enabled = bool(cluster_params.get("cluster_enabled", False))

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
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

APPS_DIR = "{env.apps_dir}"
APP = "{env.app}"

async def main():
    app_env = AgiEnv(apps_dir=APPS_DIR, app=APP, verbose={verbose})
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
                if run_mode is None:
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
                            st.error("program abort before all mode have been run")
                            st.session_state['benchmark_reset_pending'] = True

                    except json.JSONDecodeError as e:
                        st.warning(f"Error decoding JSON: {e}")

        existing_run_log = st.session_state.get("run_log_cache", "").strip()
        run_log_expander = None
        run_log_placeholder = None
        if existing_run_log:
            run_log_expander = st.expander("Run logs", expanded=False)
            with run_log_expander:
                run_log_placeholder = st.empty()
                run_log_placeholder.code(existing_run_log, language="python")

        run_col, load_col = st.columns(2)
        run_clicked = False
        run_label = "RUN benchmark" if st.session_state.get("benchmark") else "EXECUTE"
        if cmd:
            run_clicked = run_col.button(
                run_label,
                key="run_btn",
                type="primary",
                help="Run your snippet with your cluster and app settings",
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

        if load_clicked:
            st.session_state["loaded_df"] = cached_load_df(Path().home() / env.dataframe_path, with_index=False)
            st.session_state["_force_export_open"] = True

        if run_clicked and cmd:
            clear_log()
            st.session_state["run_log_cache"] = ""
            if run_log_expander is None:
                run_log_expander = st.expander("Run logs", expanded=True)
            with run_log_expander:
                run_log_placeholder = st.empty()
            with st.spinner("Running AGI..."):
                stdout, stderr = await env.run_agi(
                    cmd.replace("asyncio.run(main())", env.snippet_tail),
                    log_callback=lambda message: update_log(run_log_placeholder, message),
                    venv=project_path
                )
                st.session_state["run_log_cache"] = st.session_state.get("log_text", "")
            with run_log_expander:
                run_log_placeholder.empty()
                display_log(st.session_state["run_log_cache"], stderr)
                if st.session_state.get("benchmark"):
                    st.session_state["_benchmark_expand"] = True
                    st.rerun()

    df_preview = st.session_state.get("loaded_df")
    if isinstance(df_preview, pd.DataFrame) and not df_preview.empty:
        st.dataframe(df_preview)

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
                export_clicked = st.button("EXPORT dataframe", key="export_df_main", type="primary", use_container_width=True, help="Save the current run output to export/export.csv so Experiment/Explore can load it.")

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
