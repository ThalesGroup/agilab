import asyncio
import time
import streamlit as st

# ===========================
# Standard Imports (lightweight)
# ===========================
import os
import socket
import webbrowser
import runpy
import ast
import re
import json
import numbers
from collections import defaultdict
from pathlib import Path
import importlib

# Third-Party imports
import networkx as nx
import matplotlib.pyplot as plt
import textwrap
from matplotlib.patches import Patch
from collections import defaultdict
import streamlit as st
import tomli         # For reading TOML files
import tomli_w       # For writing TOML files
import pandas as pd
import pydantic
# Project Libraries:
from agilab.pagelib import (
    get_about_content, render_logo, activate_mlflow, save_csv, init_custom_ui, select_project, open_new_tab,
    cached_load_df
)

from agi_env import AgiEnv, normalize_path

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
    # Strip ANSI color codes before any processing
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

    Args:
        benchmark_str (str): The benchmark string to parse.

    Returns:
        dict: A dictionary with numeric keys as integers.

    Raises:
        ValueError: If the input is not a string or the benchmark string cannot be parsed.
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

    # Convert keys that represent numbers to integers, leave others as-is
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
    env = st.session_state["env"]
    scheduler = scheduler_input.strip()
    if not scheduler:
        st.error("Scheduler must be provided as a valid IP address.")
        return None
    if not env.is_valid_ip(scheduler):
        st.error(f"The scheduler IP address '{scheduler}' is invalid.")
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

def initialize_app_settings():
    env = st.session_state["env"]
    if "app_settings" not in st.session_state:
        st.session_state.app_settings = load_toml_file(env.app_settings_file)
    if "args" not in st.session_state.app_settings:
        st.session_state.app_settings.setdefault("args", {})
    if "cluster" not in st.session_state.app_settings:
        st.session_state.app_settings.setdefault("cluster", {})

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
        with file_path.open("rb") as f:
            return tomli.load(f)
    return {}

@st.cache_data(show_spinner=False)
def load_distribution_tree(file_path):
    with open(file_path, "r") as f:
        data = json.load(f)
    workers = [f"{ip}-{i}" for ip, count in data.get("workers", {}).items() for i in range(1, count + 1)]
    return workers, data.get("workers_chunks", []), data.get("workers_tree", [])

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
    cluster_params = st.session_state.app_settings["cluster"]

    cluster_enabled = st.checkbox(
        "Enable Cluster",
        value=cluster_params.get("cluster_enabled", False),
        key="cluster_enabled",
        help="Enable cluster: provide a scheduler IP and workers configuration."
    )
    cluster_params["cluster_enabled"] = cluster_enabled

    if cluster_enabled:
        scheduler_value = cluster_params.get("scheduler", "")
        scheduler_input = st.text_input(
            "Scheduler IP Address",
            value=scheduler_value,
            placeholder="e.g., 192.168.0.100",
            help="Provide a scheduler IP address.",
            key="cluster_scheduler"
        )
        if scheduler_input:
            scheduler = parse_and_validate_scheduler(scheduler_input)
            if scheduler:
                cluster_params["scheduler"] = scheduler

        workers_dict = cluster_params.get("workers", {})
        workers_value = json.dumps(workers_dict, indent=2) if isinstance(workers_dict, dict) else "{}"
        workers_input = st.text_area(
            "Workers Configuration",
            value=workers_value,
            placeholder='e.g., {"192.168.0.1": 2, "192.168.0.2": 3}',
            help="Provide a dictionary of worker IP addresses and capacities.",
            key="cluster_workers"
        )
        if workers_input:
            workers = parse_and_validate_workers(workers_input)
            if workers:
                cluster_params["workers"] = workers
    else:
        cluster_params.pop("scheduler", None)
        cluster_params.pop("workers", None)

    boolean_params = ["verbose", "cython", "pool"]
    if AgiEnv.is_managed_pc:
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

    st.session_state.dask = cluster_enabled
    st.session_state["mode"] = (
        int(cluster_params.get("pool", False))
        + int(cluster_params.get("cython", False)) * 2
        + int(cluster_enabled) * 4
        + int(cluster_params.get("rapids", False)) * 8
    )
    run_mode_label = [
        "0: python", "1: pool of process", "2: cython", "3: pool and cython",
        "4: dask", "5: dask and pool", "6: dask and cython", "7: dask and pool and cython",
        "8: rapids", "9: rapids and pool", "10: rapids and cython", "11: rapids and pool and cython",
        "12: rapids and dask", "13: rapids and dask and pool", "14: rapids and dask and cython",
        "15: rapids and dask and pool and cython"
    ]
    st.info(f"Run mode: {run_mode_label[st.session_state['mode']]}")
    st.session_state.app_settings["cluster"] = cluster_params

    with open(env.app_settings_file, "wb") as file:
        tomli_w.dump(st.session_state.app_settings, file)

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
        data = graph.nodes[node]
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

def show_tree(workers, workers_chunks, workers_tree, partition_key, weights_key, show_leaf_list=False):
    """
    Display the distribution tree of the workload, optionally including the leaf list.
    """
    total = 0
    total_per_host = defaultdict(int)
    workers_works = defaultdict(list)

    # Build workload mapping
    for worker, chunks, files_list in zip(workers, workers_chunks, workers_tree):
        ip = worker.split("-")[0]
        for (partition, size), files in zip(chunks, files_list):
            # Normalize size
            if isinstance(size, numbers.Number):
                size_processed = size
            else:
                size_processed = 1
                st.warning(f"Non-numeric size '{size}' for partition '{partition}' treated as 1.")
            total += size_processed
            total_per_host[ip] += size_processed
            workers_works[worker].append((partition, size_processed, len(files), files))

    if not workers_works:
        st.warning("No workers with assigned chunks found.")
        return

    # Determine minimum for relative weights
    min_size = min(sum(sz for _, sz, _, _ in w) for w in workers_works.values())
    graph = nx.Graph()

    # Populate nodes and edges
    for worker, works in workers_works.items():
        try:
            ip, wnum = worker.split("-")
        except ValueError:
            st.error(f"Worker identifier '{worker}' is not in the expected 'ip-number' format.")
            continue
        # Host node
        host_load = round(100 * total_per_host[ip] / total) if total else 0
        host_node = f"{ip}\n{host_load}%"
        graph.add_node(host_node, level=0)
        # Worker node
        wsize = sum(sz for _, sz, _, _ in works)
        wload = round(100 * wsize / total) if total else 0
        worker_node = f"{wnum}\n{ip}\n{wload}%"
        graph.add_node(worker_node, level=1)
        graph.add_edge(host_node, worker_node, weight=round(wsize / min_size, 1))
        # Partition and leaves
        for partition, sz, nfiles, files in works:
            part_node = f"{partition}\n{nfiles} {weights_key}"
            graph.add_node(part_node, level=2)
            graph.add_edge(worker_node, part_node, weight=sz)
            if show_leaf_list and files:
                for leaf in files:
                    graph.add_node(leaf, level=3)
                    graph.add_edge(part_node, leaf)

    _draw_distribution(graph, partition_key, show_leaf_list, title="Distribution Tree")


def show_graph(workers, workers_chunks, workers_tree, partition_key, weights_key, show_leaf_list=False):
    """
    Display a directed acyclic graph (DAG) based on distribution tree data.
    """
    total = 0
    total_per_host = defaultdict(int)
    workers_works = defaultdict(list)

    for worker, chunks, tree in zip(workers, workers_chunks, workers_tree):
        ip = worker.split("-")[0]
        for (partition, size), item in zip(chunks, tree):
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

    _draw_distribution(graph, partition_key, show_leaf_list, title="Orchestration View")

def workload_barchart(workers, workers_chunks, partition_key, weights_key, weights_unit):
    """Display a workload bar chart using Plotly."""
    import plotly.graph_objects as go
    data = []
    for worker, chunks in zip(workers, workers_chunks):
        for partition, size in chunks:
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
        # Redirect back to the landing page and rerun immediately
        page_module = importlib.import_module("AGILAB")
        page_module.main()
        st.rerun()

    else:
        env = st.session_state["env"]

    # Set page configuration and render logo
    st.set_page_config(layout="wide", menu_items=get_about_content())
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
    }


    init_session_state(defaults)
    initialize_app_settings()
    projects = env.projects
    current_project = env.app
    if "args_serialized" not in st.session_state:
        st.session_state["args_serialized"] = ""
    if current_project not in projects:
        current_project = projects[0] if projects else None
    select_project(projects, current_project)
    module = env.target
    project_path = env.active_app
    export_abs_module = env.AGILAB_EXPORT_ABS / module
    export_abs_module.mkdir(parents=True, exist_ok=True)
    pyproject_file = env.app_abs / "pyproject.toml"
    if pyproject_file.exists():
        pyproject_content = pyproject_file.read_text()
        st.session_state["rapids_default"] = ("-cu12" in pyproject_content) and os.name != "nt"
    else:
        st.session_state["rapids_default"] = False
    if "df_export_file" not in st.session_state:
        st.session_state["df_export_file"] = export_abs_module / "export.csv"
    if "loaded_df" not in st.session_state:
        st.session_state["loaded_df"] = None


    # Sidebar toggles for each page section
    show_install = st.sidebar.checkbox("INSTALL", value=True)
    show_distribute = st.sidebar.checkbox("SET ARGS", value=False)
    if (st.session_state.get("args_serialized") or show_distribute) and _is_app_installed(env):
        show_run = st.sidebar.checkbox("RUN", value=False)
    else:
        show_run = False

    show_export = st.sidebar.checkbox("EXPORT DATA", value=False, help="")

    cluster_params = st.session_state.app_settings["cluster"]
    verbose = cluster_params.get('verbose', 2)
    with st.expander("System settings:", expanded=True):
        render_cluster_settings_ui()
    # ------------------
    # INSTALL Section
    # ------------------
    if show_install:

        with st.expander("Install snippet"):
            enabled = cluster_params.get("cluster_enabled", False)
            scheduler = cluster_params.get("scheduler", "")
            scheduler = f'"{str(scheduler)}"' if enabled and scheduler else "None"
            workers = cluster_params.get("workers", "")
            workers = str(workers) if enabled and workers else "None"
            cmd = f"""
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path
from pathlib import Path

async def main():
    app_env = AgiEnv(active_app=Path('{env.active_app}') ,install_type={env.install_type}, verbose={verbose})
    res = await AGI.install(app_env, modes_enabled={st.session_state.mode},
                            verbose={verbose}, 
                            scheduler={scheduler}, workers={workers})
    print(res)
    return res

if __name__ == '__main__':
    try:
        asyncio.get_running_loop().run_until_complete(main())
    except RuntimeError:
        asyncio.run(main())
            """
            st.code(cmd, language="python")
        if st.button("INSTALL", key="install_btn", type="primary",
                     help="Run the install snippet to set up your .venv for Manager and Worker"):
            clear_log()
            live_log_placeholder = st.empty()
            with st.spinner("Installing worker..."):
                venv = env.cluster_root if env.install_type else env.active_app.parents[1]
                stdout, stderr = await env.run_agi(
                    cmd,
                    log_callback=lambda message: update_log(live_log_placeholder, message),
                    venv=venv
                )

                live_log_placeholder.empty()
                # Use display_log to show warnings or errors appropriately
                display_log(stdout, stderr)
                if not stderr:
                    st.success("Cluster installation completed.")

    # ------------------
    # DISTRIBUTE Section
    # ------------------
    if show_distribute:
        with st.expander(f"{module} settings:", expanded=True):
            args_ui_snippet = env.args_ui_snippet

            # ---- PATCH: Set default unchecked if snippet is empty ----
            snippet_exists = args_ui_snippet.exists()
            snippet_not_empty = snippet_exists and args_ui_snippet.stat().st_size > 1

            # Only set default value if toggle_custom is not in session_state
            if "toggle_custom" not in st.session_state:
                st.session_state["toggle_custom"] = snippet_not_empty

            # Always use the current value in session_state
            st.checkbox("Custom UI", key="toggle_custom",
                        value=st.session_state["toggle_custom"],
                        on_change=init_custom_ui, args=[args_ui_snippet])

            if st.session_state["toggle_custom"] and snippet_exists and snippet_not_empty:
                try:
                    runpy.run_path(args_ui_snippet, init_globals=globals())
                except ValueError as e:
                    st.warning(e)
            else:
                render_generic_ui()
                if not snippet_exists:
                    with open(args_ui_snippet, "w") as st_src:
                        st_src.write("")

            args_serialized = ", ".join(
                [f'{key}="{value}"' if isinstance(value, str) else f"{key}={value}"
                 for key, value in st.session_state.app_settings["args"].items()]
            )
            st.session_state["args_serialized"] = args_serialized
            if st.session_state.get("args_reload_required"):
                del st.session_state["app_settings"]
                st.rerun()
        with st.expander("Distribute snippet"):
            cluster_params = st.session_state.app_settings["cluster"]
            enabled = cluster_params.get("cluster_enabled", False)
            scheduler = cluster_params.get("scheduler", "")
            scheduler = f'"{str(scheduler)}"' if enabled and scheduler else "None"
            workers = cluster_params.get("workers", {})
            workers = str(workers) if enabled and workers else "None"
            cmd = f"""
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path
from pathlib import Path

async def main():
    app_env = AgiEnv(active_app=Path('{env.active_app}'), install_type={env.install_type}, verbose={verbose})
    res = await AGI.distribute(app_env, verbose={verbose}, 
                                scheduler={scheduler}, workers={workers}, {st.session_state.args_serialized})
    print(res)
    return res

if __name__ == '__main__':
    try:
        asyncio.get_running_loop().run_until_complete(main())
    except RuntimeError:
        asyncio.run(main())
            """
            st.code(cmd, language="python")
        if st.button("TEST DISTRIBUTE", key="preview_btn", type="secondary",
                     help="Run the snippet and display your distribution tree"):
            st.session_state.preview_tree = True
            with st.expander("Orchestration log:", expanded=True):
                clear_log()
                live_log_placeholder = st.empty()
                with st.spinner("Building distribution..."):
                    stdout, stderr = await env.run_agi(
                        cmd,
                        log_callback=lambda message: update_log(live_log_placeholder, message),
                        venv=project_path
                    )
                live_log_placeholder.empty()
                display_log(stdout, stderr)
                if not stderr:
                    st.success("Distribution built successfully.")
        with st.expander("Orchestration view:", expanded=False):
            if st.session_state.get("preview_tree"):
                dist_tree_path = env.wenv_abs / "distribution_tree.json"
                if dist_tree_path.exists():
                    workers, workers_chunks, workers_tree = load_distribution_tree(dist_tree_path)
                    partition_key = "Partition"
                    weights_key = "Units"
                    weights_unit = "Unit"
                    tabs = st.tabs(["Tree", "Workload"])
                    with tabs[0]:
                        if env.base_worker_cls.endswith('dag-worker'):
                            show_graph(workers, workers_chunks, workers_tree, partition_key, weights_key,
                                   show_leaf_list=st.checkbox("Show leaf nodes", value=False))
                        else:
                            show_tree(workers, workers_chunks, workers_tree, partition_key, weights_key,
                                   show_leaf_list=st.checkbox("Show leaf nodes", value=False))
                    with tabs[1]:
                        workload_barchart(workers, workers_chunks, partition_key, weights_key, weights_unit)
                    unused_workers = [worker for worker, chunks in zip(workers, workers_chunks) if not chunks]
                    if unused_workers:
                        st.warning(f"**{len(unused_workers)} Unused workers:** " + ", ".join(unused_workers))
                    st.markdown("**Modify Distribution Tree:**")
                    ncols = 2
                    cols = st.columns([10, 1, 10])
                    count = 0
                    for i, chunks in enumerate(workers_chunks):
                        for j, chunk in enumerate(chunks):
                            partition, size = chunk
                            with cols[0 if count % ncols == 0 else 2]:
                                b1, b2 = st.columns(2)
                                b1.text(f"{partition_key.title()} {partition} ({weights_key}: {size} {weights_unit})")
                                key = f"worker_partition_{partition}_{i}_{j}"
                                b2.selectbox("Worker", options=workers, key=key, index=i if i < len(workers) else 0)
                            count += 1
                    if st.button("Apply", key="apply_btn", type="primary"):
                        new_workers_chunks = [[] for _ in workers]
                        new_workers_tree = [[] for _ in workers]
                        for i, (chunks, files_tree) in enumerate(zip(workers_chunks, workers_tree)):
                            for j, (chunk, files) in enumerate(zip(chunks, files_tree)):
                                key = f"worker_partition{chunk[0]}"
                                selected_worker = st.session_state.get(key)
                                if selected_worker and selected_worker in workers:
                                    idx = workers.index(selected_worker)
                                    new_workers_chunks[idx].append(chunk)
                                    new_workers_tree[idx].append(files)
                        data = load_distribution_tree(dist_tree_path)[0]
                        data["target_args"] = st.session_state.app_settings["args"]
                        data["workers_chunks"] = new_workers_chunks
                        data["workers_tree"] = new_workers_tree
                        with open(dist_tree_path, "w") as f:
                            json.dump(data, f)
                        st.rerun()

    # ------------------
    # RUN Section
    # ------------------
    if show_run:
        if st.checkbox("Benchmark all modes", value=False, key="benchmark",
                           help="This will run the snippet for each available mode and return a table with each run’s duration"):
            st.session_state["mode"] = None

        with st.expander("Run snippet", expanded=True):
            cluster_params = st.session_state.app_settings["cluster"]
            enabled = cluster_params.get("cluster_enabled", False)
            scheduler = f'"{cluster_params.get("scheduler")}"' if enabled else "None"
            workers = str(cluster_params.get("workers")) if enabled else "None"
            cmd = f"""
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path
from pathlib import Path

async def main():
    app_env = AgiEnv(active_app=Path('{env.active_app}'), install_type={env.install_type}, verbose={verbose}) 
    res = await AGI.run(app_env, mode={st.session_state["mode"]}, 
                        scheduler={scheduler}, workers={workers}, 
                        verbose={verbose}, {st.session_state.args_serialized})
    print(res)
    return res

if __name__ == '__main__':
    try:
        asyncio.get_running_loop().run_until_complete(main())
    except RuntimeError:
        asyncio.run(main())
            """
            st.code(cmd, language="python")
        if st.button("RUN", key="run_btn", type="primary", help="Run your snippet with your cluster and app settings"):
                clear_log()
                live_log_placeholder = st.empty()
                with st.spinner("Running AGI..."):
                    stdout, stderr = await env.run_agi(
                        cmd,
                        log_callback=lambda message: update_log(live_log_placeholder, message),
                        venv=project_path
                    )
                    #live_log_placeholder.empty()
                    display_log(stdout, stderr)
                    run_log = stdout

                if not st.session_state.get('mode'):
                    try:
                        if env.benchmark.exists():
                            with open(env.benchmark, "r") as f:
                                data = json.loads(f.read())
                                if data:
                                    benchmark_df = pd.DataFrame.from_dict(data, orient='index')
                                    st.text("Benchmark result:")
                                    st.dataframe(benchmark_df)
                        else:
                            st.error("program abort before all mode have been run")
                            st.session_state['mode'] = 0
                            st.session_state['bencchmark'] = False

                    except json.JSONDecodeError as e:
                        print("Error decoding JSON:", e)

                st.session_state["loaded_df"] = cached_load_df(Path().home() / env.dataframe_path,with_index=False)

        if st.sidebar.button("Load Data", key="load_data"):
            st.session_state["loaded_df"] = cached_load_df(Path().home() / env.dataframe_path,with_index=False)
        loaded_df = st.session_state.get("loaded_df")
        if isinstance(loaded_df, pd.DataFrame) and not loaded_df.empty:
            st.dataframe(loaded_df)
        else:
            st.info("No data loaded yet. Click 'Load Data' from the sidebar to load it.")

    # ------------------
    # EXPORT-COLUMNS Section
    # ------------------
    if show_export:
        loaded_df = st.session_state.get("loaded_df")

        # If loaded_df exists, make sure there are no empty column names.
        if isinstance(loaded_df, pd.DataFrame):
            # Rename any empty column names to a default value with an index.
            loaded_df.columns = [
                col if col.strip() != "" else f"Unnamed Column {idx}"
                for idx, col in enumerate(loaded_df.columns)
            ]

        # Check if we need to update the session state for export tab
        if ("export_tab_previous_project" not in st.session_state or
                st.session_state.export_tab_previous_project != env.app or
                st.session_state.get("df_cols") != (loaded_df.columns.tolist() if loaded_df is not None else [])):

            st.session_state.export_tab_previous_project = env.app
            if isinstance(loaded_df, pd.DataFrame) and not loaded_df.empty:
                st.session_state.df_cols = loaded_df.columns.tolist()
                st.session_state.selected_cols = loaded_df.columns.tolist()
                st.session_state.check_all = True
            else:
                st.session_state.df_cols = []
                st.session_state.selected_cols = []
                st.session_state.check_all = False

        if isinstance(loaded_df, pd.DataFrame) and not loaded_df.empty:
            def on_select_all_changed():
                st.session_state.selected_cols = st.session_state.df_cols.copy() if st.session_state.check_all else []

            st.checkbox("Select All", key="check_all", on_change=on_select_all_changed)

            def on_individual_checkbox_change(col_name):
                if st.session_state.get(f"export_col_{col_name}"):
                    if col_name not in st.session_state.selected_cols:
                        st.session_state.selected_cols.append(col_name)
                else:
                    if col_name in st.session_state.selected_cols:
                        st.session_state.selected_cols.remove(col_name)
                st.session_state.check_all = len(st.session_state.selected_cols) == len(st.session_state.df_cols)

            # Create 5 columns for checkboxes layout
            cols_layout = st.columns(5)
            for idx, col in enumerate(st.session_state.df_cols):
                # Provide a default label if the column name is empty.
                label = col if col.strip() != "" else f"Unnamed Column {idx}"
                with cols_layout[idx % 5]:
                    st.checkbox(
                        label,
                        key=f"export_col_{col}",
                        value=col in st.session_state.selected_cols,
                        on_change=on_individual_checkbox_change,
                        args=(col,)
                    )

            export_file_input = st.sidebar.text_input(
                "Export to filename:",
                value=str(st.session_state.df_export_file),
                key="input_df_export_file"
            )
            st.session_state.df_export_file = Path(export_file_input)

            if st.sidebar.button("Export-DF", key="export_df", use_container_width=True):
                if st.session_state.selected_cols:
                    exported_df = loaded_df[st.session_state.selected_cols]
                    save_csv(exported_df, st.session_state.df_export_file)
                    st.success(f"Dataframe exported successfully to {st.session_state.df_export_file}.")
                else:
                    st.warning("No columns selected for export.")

                if st.session_state.profile_report_file.exists():
                    os.remove(st.session_state.profile_report_file)

            if st.sidebar.button("Stats Report", key="stats_report", use_container_width=True, type="primary"):
                profile_file = st.session_state.profile_report_file
                if not profile_file.exists():
                    profile = generate_profile_report(loaded_df)
                    with st.spinner("Generating profile report..."):
                        profile.to_file(profile_file, silent=False)
                open_new_tab(profile_file.as_uri())
        else:
            st.warning("No dataset found for this project.")

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
