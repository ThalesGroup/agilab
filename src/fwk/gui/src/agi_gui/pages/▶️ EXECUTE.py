# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the
# following conditions are met:
#
#   ... (license text continues) ...

import time
from agi_gui.pagelib import env  # CAUTION: Place it at the first line to avoid other pagelib import instabilities
import streamlit as st
from agi_gui.pagelib import get_about_content, render_logo

# Set page configuration and render logo
st.set_page_config(layout="wide", menu_items=get_about_content())
render_logo("Execute your Application")

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
from collections import defaultdict
from pathlib import Path

# Third-Party lightweight imports
import tomli         # For reading TOML files
import tomli_w       # For writing TOML files
import pandas as pd
import pydantic

# Project Libraries:
from agi_gui.pagelib import (
    load_df,
    save_csv,
    init_custom_ui,
    select_project,
    open_new_tab,
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
}
init_session_state(defaults)

#####################################
# Helper function for displaying logs
#####################################
def display_log(stdout, stderr):
    """
    Clean and display log messages.
    If either stdout or stderr contains "warning:" (case-insensitive),
    display the combined log using st.warning; if stderr contains other messages,
    display them as errors. Otherwise, display stdout.
    """
    # Remove ANSI escape codes for clarity
    clean_stdout = re.sub(r'\x1b\[[0-9;]*m', '', stdout or "")
    clean_stderr = re.sub(r'\x1b\[[0-9;]*m', '', stderr or "")
    # Combine both outputs for checking
    combined = clean_stdout + "\n" + clean_stderr
    if "warning:" in combined.lower():
        st.warning("Warnings occurred during cluster installation:")
        st.code(combined)
    elif clean_stderr.strip():
        st.error("Errors occurred during cluster installation:")
        st.code(clean_stderr)
    else:
        st.code(clean_stdout or "No logs available")

# ===========================
# Utility and Helper Functions
# ===========================
def update_log(log, message: str):
    """Update a log placeholder with a message."""
    log.text(message)

def parse_benchmark(benchmark_str):
    """Parse a benchmark string into a dictionary."""
    json_str = re.sub(r'([{,]\s*)(\d+):', r'\1"\2":', benchmark_str)
    json_str = json_str.replace("'", '"')
    data = json.loads(json_str)
    data = {int(k): v for k, v in data.items()}
    return data

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
    scheduler = scheduler_input.strip()
    if not scheduler:
        st.error("Scheduler must be provided as a valid IP address.")
        return None
    if not env.is_valid_ip(scheduler):
        st.error(f"The scheduler IP address '{scheduler}' is invalid.")
        return None
    return scheduler

def parse_and_validate_workers(workers_input):
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
    if "app_settings" not in st.session_state:
        st.session_state.app_settings = load_toml_file(env.app_settings_file)
    st.session_state.app_settings.setdefault("args", {})
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
def cached_load_df(path):
    return load_df(path, with_index=False)

@st.cache_data(show_spinner=False)
def load_distribution_tree(file_path):
    with open(file_path, "r") as f:
        data = json.load(f)
    workers = [f"{ip}-{i}" for ip, count in data.get("workers", {}).items() for i in range(1, count + 1)]
    return workers, data.get("workers_chunks", []), data.get("workers_tree", [])

@st.cache_data(show_spinner=False)
def generate_profile_report(df):
    from ydata_profiling.profile_report import ProfileReport
    return ProfileReport(df, minimal=True)

# ===========================
# UI Rendering Functions
# ===========================
def render_generic_ui():
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
        st.experimental_rerun()

    if arg_valid and st.session_state.get("args_add_arg_button"):
        st.experimental_rerun()

    if arg_valid:
        st.session_state.app_settings["args"] = args_input

def render_cluster_settings_ui():
    cluster_params = st.session_state.app_settings["cluster"]

    cluster_enabled = st.checkbox(
        "Enable Cluster",
        value=cluster_params.get("cluster_enabled", False),
        key="cluster_enabled",
        help="Enable cluster: provide a scheduler IP and workers configuration."
    )
    cluster_params["cluster_enabled"] = cluster_enabled

    if cluster_enabled:
        scheduler_dict = cluster_params.get("scheduler", {})
        scheduler_value = next(iter(scheduler_dict), "") if isinstance(scheduler_dict, dict) else ""
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
                cluster_params["scheduler"] = {scheduler: True}

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

# ===========================
# Visualization Functions
# ===========================
def show_graph(workers, workers_chunks, workers_tree, partition_key, weights_key, show_leaf_list=False):
    """Display a directed acyclic graph (DAG) based on distribution tree data."""
    import networkx as nx
    import matplotlib.pyplot as plt
    import textwrap
    from matplotlib.patches import Patch

    graph = nx.DiGraph()
    total = 0
    total_per_host = defaultdict(int)
    workers_works = defaultdict(list)

    for worker, chunks, tree in zip(workers, workers_chunks, workers_tree):
        ip = worker.split("-")[0]
        for chunk, item in zip(chunks, tree):
            partition, size = chunk
            if len(item) == 2:
                node, dependencies = item
            else:
                node, dependencies = item[0], []
            size_processed = size if isinstance(size, (int, float)) else 1
            total += size_processed
            total_per_host[ip] += size_processed
            workers_works[worker].append((partition, size_processed, node, dependencies))

    if not workers_works:
        st.warning("No workers with assigned chunks found.")
        return

    min_size = min(sum(size for _, size, _, _ in works) for works in workers_works.values()) if workers_works else 1

    for worker, works in workers_works.items():
        try:
            ip, worker_num = worker.split("-")
        except ValueError:
            st.error(f"Worker identifier '{worker}' is not in the expected 'ip-number' format.")
            continue

        host_load = round((100 * total_per_host[ip] / total)) if total > 0 else 0
        host_node = f"{ip}\n{host_load}%"
        graph.add_node(host_node, level=0)

        worker_size = sum(size for _, size, _, _ in works)
        worker_load = round((100 * worker_size / total)) if total > 0 else 0
        worker_node = f"{worker_num}\n{ip}\n{worker_load}%"
        graph.add_node(worker_node, level=1)
        graph.add_edge(host_node, worker_node, weight=round(worker_size / min_size, 1))

        for partition, size, node, dependencies in works:
            partition_node = f"{partition}\nfiles: {len(dependencies)} {weights_key}"
            graph.add_node(partition_node, level=2)
            graph.add_edge(worker_node, partition_node, weight=size)
            if show_leaf_list and dependencies:
                for leaf in dependencies:
                    leaf_node = f"{leaf}"
                    graph.add_node(leaf_node, level=3)
                    graph.add_edge(partition_node, leaf_node)

    pos = nx.multipartite_layout(graph, subset_key="level", align="horizontal")
    pos = {k: (-x, -y) for k, (x, y) in pos.items()}
    ip_nodes = [node for node, data in graph.nodes(data=True) if data["level"] == 0]
    workers_nodes = [node for node, data in graph.nodes(data=True) if data["level"] == 1]
    partitions_nodes = [node for node, data in graph.nodes(data=True) if data["level"] == 2]
    leaf_nodes = [node for node, data in graph.nodes(data=True) if data["level"] == 3]

    plt.figure(figsize=(12, 8))
    plt.margins(x=0.1, y=0.1)
    nx.draw_networkx_nodes(graph, pos, nodelist=ip_nodes, node_color="royalblue", node_shape="o", node_size=1500)
    nx.draw_networkx_nodes(graph, pos, nodelist=workers_nodes, node_color="skyblue", node_shape="o", node_size=1500)
    nx.draw_networkx_nodes(graph, pos, nodelist=partitions_nodes, node_color="lightgreen", node_shape="s", node_size=1500)
    if show_leaf_list:
        nx.draw_networkx_nodes(graph, pos, nodelist=leaf_nodes, node_color="lightgrey", node_shape="s", node_size=1000)
    nx.draw_networkx_edges(graph, pos)
    ax = plt.gca()
    for node in graph.nodes():
        x, y = pos[node]
        if node in leaf_nodes and show_leaf_list:
            rotation = 90
            fontsize = 7
            wrapped_label = textwrap.fill(node, width=10)
        else:
            rotation = 0
            fontsize = 7
            wrapped_label = node
        ax.text(x, y, s=wrapped_label, horizontalalignment="center", verticalalignment="center", rotation=rotation,
                fontsize=fontsize, bbox=dict(facecolor="white", edgecolor="none", pad=1.0, alpha=1.0))
    edge_labels = nx.get_edge_attributes(graph, "weight")
    nx.draw_networkx_edge_labels(graph, pos, edge_labels=edge_labels, font_size=6)
    legend_patches = [
        Patch(facecolor="royalblue", label="Host IP"),
        Patch(facecolor="skyblue", label="Worker"),
        Patch(facecolor="lightgreen", label=partition_key.title()),
    ]
    if show_leaf_list:
        legend_patches.append(Patch(facecolor="lightgrey", label="Leaf List"))
    plt.legend(handles=legend_patches, loc="center", bbox_to_anchor=(0.5, -0.05), ncol=len(legend_patches))
    plt.tight_layout()
    plt.title("Orchestration View")
    plt.axis("off")
    st.pyplot(plt, use_container_width=True)

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

# ===========================
# Main Application UI
# ===========================
def page():
    export_abs = env.AGILAB_EXPORT_ABS
    initialize_app_settings()
    projects = env.projects
    st.session_state["projects"] = projects
    current_project = env.app
    if "args_serialized" not in st.session_state:
        st.session_state["args_serialized"] = ""
    if current_project not in projects:
        current_project = projects[0] if projects else None
        st.session_state["project"] = current_project
    project = select_project(projects, current_project)
    module = env.target
    project_path = env.apps_root / project
    export_abs_module = env.AGILAB_EXPORT_ABS / module
    export_abs_module.mkdir(parents=True, exist_ok=True)
    pyproject_file = env.app_path / "pyproject.toml"
    if pyproject_file.exists():
        pyproject_content = pyproject_file.read_text()
        st.session_state["rapids_default"] = ("-cu12" in pyproject_content) and os.name != "nt"
    else:
        st.session_state["rapids_default"] = False
    if "df_export_file" not in st.session_state:
        st.session_state["df_export_file"] = export_abs_module / "export.csv"
    if "loaded_df" not in st.session_state:
        st.session_state["loaded_df"] = None
    init_custom_ui(env.args_ui_snippet)

    # Sidebar toggles for each page section
    show_install = st.sidebar.checkbox("INSTALL", value=True)
    show_distribute = st.sidebar.checkbox("DISTRIBUTE", value=False)
    show_run = st.sidebar.checkbox("RUN", value=False)
    show_export = st.sidebar.checkbox("EXPORT DATA", value=False)

    # ------------------
    # INSTALL Section
    # ------------------
    if show_install:
        st.markdown("### INSTALL")
        with st.expander("Cluster settings:", expanded=True):
            render_cluster_settings_ui()
        with st.expander("Install snippet"):
            cluster_params = st.session_state.app_settings["cluster"]
            enabled = cluster_params.get("cluster_enabled", False)
            scheduler = cluster_params.get("scheduler", "")
            scheduler = f'"{next(iter(scheduler), "")}"' if enabled and scheduler else "None"
            workers = cluster_params.get("workers", "")
            workers = str(workers) if enabled and workers else "None"
            cmd = f"""
import asyncio
from agi_core.managers.agi_runner import AGI

async def main():
    res = await AGI.install('{module}', modes_enabled={st.session_state.mode},
    verbose={cluster_params.get('verbose', 2)}, 
    scheduler={scheduler}, workers={workers})
    print(res)
    return res

if __name__ == '__main__':
    asyncio.run(main())
            """
            st.code(cmd, language="python")
        if st.button("Install", key="install_btn", type="primary",
                     help="Run the install snippet to set up your .venv for Manager and Worker"):
            live_log_placeholder = st.empty()
            with st.spinner("Installing worker..."):
                stdout, stderr = env.run_agi_sync(
                    cmd,
                    log_callback=lambda message: update_log(live_log_placeholder, message),
                    venv=env.core_root
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
        st.markdown("### DISTRIBUTE")
        with st.expander(f"{module} settings:", expanded=True):
            args_ui_snippet = env.args_ui_snippet
            toggle_custom = st.checkbox("Custom UI", key="toggle_custom", value=st.session_state.toggle_custom,
                                        on_change=init_custom_ui, args=[args_ui_snippet])
            if toggle_custom and args_ui_snippet.exists() and args_ui_snippet.stat().st_size > 0:
                try:
                    runpy.run_path(args_ui_snippet, init_globals=globals())
                except ValueError as e:
                    st.warning(e)
            else:
                render_generic_ui()
                if not args_ui_snippet.exists():
                    with open(args_ui_snippet, "w") as st_src:
                        st_src.write("")
            args_serialized = ", ".join(
                [f'{key}="{value}"' if isinstance(value, str) else f"{key}={value}"
                 for key, value in st.session_state.app_settings["args"].items()]
            )
            st.session_state["args_serialized"] = args_serialized
            if st.session_state.get("args_reload_required"):
                del st.session_state["app_settings"]
                st.experimental_rerun()
        with st.expander("Distribute snippet"):
            cluster_params = st.session_state.app_settings["cluster"]
            enabled = cluster_params.get("cluster_enabled", False)
            scheduler = cluster_params.get("scheduler", "")
            scheduler = f'"{next(iter(scheduler), "")}"' if enabled and scheduler else "None"
            workers = cluster_params.get("workers", {})
            workers = str(workers) if enabled and workers else "None"
            cmd = f"""
import asyncio
from agi_core.managers.agi_runner import AGI

async def main():
    res = await AGI.distribute('{module}', verbose={cluster_params.get('verbose', 2)}, 
    scheduler={scheduler}, workers={workers}, {st.session_state.args_serialized})
    print(res)
    return res

if __name__ == '__main__':
    asyncio.run(main())
            """
            st.code(cmd, language="python")
        if st.button("Preview", key="preview_btn", type="primary",
                     help="Run the snippet and display your distribution tree"):
            st.session_state.preview_tree = True
            with st.expander("Orchestration log:", expanded=True):
                live_log_placeholder = st.empty()
                with st.spinner("Building distribution..."):
                    stdout, stderr = env.run_agi_sync(
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
                        show_graph(workers, workers_chunks, workers_tree, partition_key, weights_key,
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
                        st.experimental_rerun()

    # ------------------
    # RUN Section
    # ------------------
    if show_run:
        st.markdown("### RUN")
        with st.expander("Run snippet", expanded=True):
            cluster_params = st.session_state.app_settings["cluster"]
            enabled = cluster_params.get("cluster_enabled", False)
            scheduler = f'"{cluster_params.get("scheduler")}"' if enabled else "None"
            workers = str(cluster_params.get("workers")) if enabled else "None"
            cmd = f"""
import asyncio
from agi_core.managers.agi_runner import AGI

async def main():
    res = await AGI.run('{module}', mode={st.session_state.mode}, 
    scheduler={scheduler}, workers={workers}, 
    verbose={cluster_params.get('verbose', 2)}, {st.session_state.args_serialized})
    print(res)
    return res

if __name__ == '__main__':
    asyncio.run(main())
            """
            st.code(cmd, language="python")
        if st.button("Run", key="run_btn", type="primary", help="Run your snippet with your cluster and app settings"):
            live_log_placeholder = st.empty()
            with st.spinner("Running AGI..."):
                stdout, stderr = env.run_agi_sync(
                    cmd,
                    log_callback=lambda message: update_log(live_log_placeholder, message),
                    venv=project_path
                )
                live_log_placeholder.empty()
                display_log(stdout, stderr)
                run_log = stdout

            if st.session_state.mode is None:
                st.text("Benchmark result:")
                try:
                    benchmark_str = run_log.split("\n")[-2:-1][0]
                    benchmark_data = parse_benchmark(benchmark_str)
                    benchmark_df = pd.DataFrame.from_dict(benchmark_data, orient='index')
                    st.dataframe(benchmark_df)
                except Exception:
                    st.code(f"```\n{run_log}\n```")
            st.session_state["loaded_df"] = cached_load_df(env.dataframes_path)

        if st.sidebar.button("Load Data", key="load_data", type="primary"):
            st.session_state["loaded_df"] = cached_load_df(env.dataframes_path)
        loaded_df = st.session_state.get("loaded_df")
        if isinstance(loaded_df, pd.DataFrame) and not loaded_df.empty:
            st.dataframe(loaded_df)
        else:
            st.info("No data loaded yet. Click 'Run' to load dataset.")

    # ------------------
    # EXPORT-COLUMNS Section
    # ------------------
    if show_export:
        st.markdown("### EXPORT DATA")
        loaded_df = st.session_state.get("loaded_df")
        if "export_tab_previous_project" not in st.session_state or \
                st.session_state.export_tab_previous_project != st.session_state.get("project") or \
                st.session_state.get("df_cols") != (loaded_df.columns.tolist() if loaded_df is not None else []):
            st.session_state.export_tab_previous_project = st.session_state.get("project")
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
                if st.session_state[f"export_col_{col_name}"]:
                    if col_name not in st.session_state.selected_cols:
                        st.session_state.selected_cols.append(col_name)
                else:
                    if col_name in st.session_state.selected_cols:
                        st.session_state.selected_cols.remove(col_name)
                st.session_state.check_all = len(st.session_state.selected_cols) == len(st.session_state.df_cols)

            cols_layout = st.columns(5)
            for idx, col in enumerate(st.session_state.df_cols):
                with cols_layout[idx % 5]:
                    st.checkbox(
                        col,
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
def main():
    try:
        page()
    except Exception as e:
        st.error(f"An error occurred: {e}")
        import traceback
        st.code(f"```\n{traceback.format_exc()}\n```")

if __name__ == "__main__":
    main()