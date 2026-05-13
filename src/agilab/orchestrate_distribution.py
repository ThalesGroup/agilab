import importlib
import numbers
import textwrap
from collections import defaultdict
from typing import Any

import pandas as pd
import streamlit as st

try:
    import networkx as nx
except ModuleNotFoundError as exc:
    nx = None  # type: ignore[assignment]
    _NETWORKX_IMPORT_ERROR = exc
else:
    _NETWORKX_IMPORT_ERROR = None

try:
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
except ModuleNotFoundError as exc:
    plt = None  # type: ignore[assignment]
    Patch = None  # type: ignore[assignment]
    _MATPLOTLIB_IMPORT_ERROR = exc
else:
    _MATPLOTLIB_IMPORT_ERROR = None


def _networkx_unavailable_message() -> str:
    return (
        f"networkx unavailable: {_NETWORKX_IMPORT_ERROR}. "
        "Install the UI dependencies with `pip install 'agilab[ui]'` or run `uv sync --extra ui`."
    )


def _require_networkx():
    if nx is None:
        raise RuntimeError(_networkx_unavailable_message())
    return nx


def import_plotly_graph_objects(import_module_fn=importlib.import_module):
    try:
        return import_module_fn("plotly.graph_objects")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "plotly unavailable: install the optional visualization dependencies with `pip install 'agilab[viz]'`."
        ) from exc


def draw_distribution(graph, partition_key, show_leaf_list, title) -> None:
    """Shared drawing routine for distribution or DAG graphs."""
    nx_module = _require_networkx()
    if plt is None or Patch is None:
        raise RuntimeError(
            f"matplotlib unavailable: {_MATPLOTLIB_IMPORT_ERROR}. "
            "Install the optional visualization dependencies with `pip install 'agilab[viz]'`."
        )

    pos = nx_module.multipartite_layout(graph, subset_key="level", align="horizontal")
    pos = {k: (-x, -y) for k, (x, y) in pos.items()}

    ip_nodes = [n for n, d in graph.nodes(data=True) if d.get("level") == 0]
    worker_nodes = [n for n, d in graph.nodes(data=True) if d.get("level") == 1]
    partition_nodes = [n for n, d in graph.nodes(data=True) if d.get("level") == 2]
    leaf_nodes = [n for n, d in graph.nodes(data=True) if d.get("level") == 3]

    plt.figure(figsize=(12, 8))
    plt.margins(x=0.1, y=0.1)

    nx_module.draw_networkx_nodes(graph, pos, nodelist=ip_nodes, node_color="royalblue", node_shape="o", node_size=1500)
    nx_module.draw_networkx_nodes(graph, pos, nodelist=worker_nodes, node_color="skyblue", node_shape="o", node_size=1500)
    nx_module.draw_networkx_nodes(
        graph, pos, nodelist=partition_nodes, node_color="lightgreen", node_shape="s", node_size=1500
    )
    if show_leaf_list:
        nx_module.draw_networkx_nodes(
            graph, pos, nodelist=leaf_nodes, node_color="lightgrey", node_shape="s", node_size=1000
        )
    nx_module.draw_networkx_edges(graph, pos)

    ax = plt.gca()
    for node in graph.nodes():
        x, y = pos[node]
        rotation, fontsize = (90, 7) if show_leaf_list and node in leaf_nodes else (0, 7)
        wrapped = textwrap.fill(node, width=12)
        ax.text(
            x,
            y,
            wrapped,
            horizontalalignment="center",
            verticalalignment="center",
            rotation=rotation,
            fontsize=fontsize,
            bbox=dict(facecolor="white", edgecolor="none", pad=1.0, alpha=1.0),
        )

    edge_labels = nx_module.get_edge_attributes(graph, "weight")
    if edge_labels:
        nx_module.draw_networkx_edge_labels(graph, pos, edge_labels=edge_labels, font_size=6)

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
    st.pyplot(plt, width="stretch")


def extract_chunk_info(chunk, partition_key, weights_key) -> tuple[Any, Any]:
    """Return `(partition, size)` for a chunk entry with flexible shapes."""
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


def show_tree(workers, work_plan_metadata, work_plan, partition_key, weights_key, show_leaf_list=False) -> None:
    """Display the distribution tree of the workload."""
    if nx is None:
        st.warning(_networkx_unavailable_message())
        return

    total = 0
    total_per_host = defaultdict(int)
    workers_works = defaultdict(list)

    for worker, chunks, files_list in zip(workers, work_plan_metadata, work_plan):
        ip = worker.split("-")[0]
        for chunk, files in zip(chunks, files_list):
            partition, size = extract_chunk_info(chunk, partition_key, weights_key)
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

    draw_distribution(graph, partition_key, show_leaf_list, title="Distribution Tree")


def show_graph(workers, work_plan_metadata, work_plan, partition_key, weights_key, show_leaf_list=False) -> None:
    """Display a directed acyclic graph based on workplan metadata."""
    if nx is None:
        st.warning(_networkx_unavailable_message())
        return

    total = 0
    total_per_host = defaultdict(int)
    workers_works = defaultdict(list)

    for worker, chunks, tree in zip(workers, work_plan_metadata, work_plan):
        ip = worker.split("-")[0]
        for chunk, item in zip(chunks, tree):
            partition, size = extract_chunk_info(chunk, partition_key, weights_key)
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

    draw_distribution(graph, partition_key, show_leaf_list, title="Workplan")


def workload_barchart(workers, work_plan_metadata, partition_key, weights_key, weights_unit) -> None:
    """Display a workload bar chart using Plotly."""
    go = import_plotly_graph_objects()

    data = []
    for worker, chunks in zip(workers, work_plan_metadata):
        for chunk in chunks:
            partition, size = extract_chunk_info(chunk, partition_key, weights_key)
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
    st.plotly_chart(fig, width="stretch")
