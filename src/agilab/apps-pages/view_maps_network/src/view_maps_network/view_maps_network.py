# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
# 3. Neither the name of Jean-Pierre Morard nor the names of its contributors, or THALES SIX GTS France SAS, may be used to endorse or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import sys
import argparse
from pathlib import Path

import streamlit as st
import pandas as pd
import pydeck as pdk
import ast
import networkx as nx
import numpy as np
import plotly.graph_objects as go
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import glob
import json
from datetime import datetime
import time
from streamlit.runtime.scriptrunner import RerunException
from typing import Optional


def _ensure_repo_on_path() -> None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "agilab"
        if candidate.is_dir():
            src_root = candidate.parent
            repo_root = src_root.parent
            for entry in (str(src_root), str(repo_root)):
                if entry not in sys.path:
                    sys.path.insert(0, entry)
            break


_ensure_repo_on_path()

from agi_env import AgiEnv
from agi_env.pagelib import find_files, load_df, render_logo


def _resolve_active_app() -> Path:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--active-app",
        dest="active_app",
        type=str,
        required=True,
    )
    args, _ = parser.parse_known_args()
    active_app_path = Path(args.active_app).expanduser()
    if not active_app_path.exists():
        st.error(f"Provided --active-app path not found: {active_app_path}")
        st.stop()
    return active_app_path


_LAST_SUBDIR_FILE = Path.home() / ".local" / "share" / "agilab" / "view_maps_network_last_subdir"


def _load_last_subdir() -> str:
    try:
        if _LAST_SUBDIR_FILE.exists():
            return _LAST_SUBDIR_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


def _store_last_subdir(value: str) -> None:
    try:
        _LAST_SUBDIR_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LAST_SUBDIR_FILE.write_text(value, encoding="utf-8")
    except Exception:
        pass


st.title(":world_map: Maps Network Graph")

if 'env' not in st.session_state:
    active_app_path = _resolve_active_app()
    app_name = active_app_path.name
    env = AgiEnv(apps_dir=active_app_path.parent, app=app_name, verbose=0)
    env.init_done = True
    st.session_state['env'] = env
    st.session_state['IS_SOURCE_ENV'] = env.is_source_env
    st.session_state['IS_WORKER_ENV'] = env.is_worker_env
    st.session_state['apps_dir'] = str(active_app_path.parent)
    st.session_state['app'] = app_name
else:
    env = st.session_state['env']

if "TABLE_MAX_ROWS" not in st.session_state:
    st.session_state["TABLE_MAX_ROWS"] = env.TABLE_MAX_ROWS
if "GUI_SAMPLING" not in st.session_state:
    st.session_state["GUI_SAMPLING"] = env.GUI_SAMPLING
render_logo("Cartography Visualisation")

MAPBOX_API_KEY = "pk.eyJ1Ijoic2FsbWEtZWxnOSIsImEiOiJjbHkyc3BnbjcwMHE0MmpzM2dyd3RyaDI2In0.9Q5rjICLWC1yThpxSVWX6w"
TERRAIN_IMAGE = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
SURFACE_IMAGE = f"https://api.mapbox.com/v4/mapbox.satellite/{{z}}/{{x}}/{{y}}@4x.png?access_token={MAPBOX_API_KEY}"

ELEVATION_DECODER = {
    "rScaler": 256,
    "gScaler": 1,
    "bScaler": 1 / 256,
    "offset": -32768,
}

terrain_layer = pdk.Layer(
    "TerrainLayer",
    elevation_decoder=ELEVATION_DECODER,
    texture=SURFACE_IMAGE,
    elevation_data=TERRAIN_IMAGE,
    min_zoom=0,
    max_zoom=23,
    strategy="no-overlap",
    opacity=0.3,
    visible=True,
)

st.markdown("<h1 style='text-align: center;'>🌐 Network Topology</h1>", unsafe_allow_html=True)

link_colors_plotly = {
    "satcom_link": "rgb(0, 200, 255)",
    "optical_link": "rgb(0, 128, 0)",
    "legacy_link": "rgb(128, 0, 128)",
    "ivbl_link": "rgb(255, 69, 0)",
}

def hex_to_rgba(hex_color: str):
    hex_color = hex_color.lstrip("#")
    r, g, b = bytes.fromhex(hex_color)
    return [r, g, b, 255]

def create_edges_geomap(df, link_column, current_positions):
    def _parse_entry(val):
        if val is None:
            return None
        try:
            if isinstance(val, str):
                return ast.literal_eval(val)
            return val
        except Exception:
            return None

    df.loc[:, link_column] = df[link_column].apply(_parse_entry)
    link_edges = df.loc[
        df[link_column].notna() & df["flight_id"].notna(),
        [link_column, "flight_id", "long", "lat", "alt"],
    ]
    edges_list = []
    for _, row in link_edges.iterrows():
        links = row[link_column]
        if links is not None:
            if isinstance(links, tuple):
                links = [links]
            for source, target in links:
                source_pos = current_positions.loc[current_positions["flight_id"] == source]
                target_pos = current_positions.loc[current_positions["flight_id"] == target]
                if not source_pos.empty and not target_pos.empty:
                    mid_long = (source_pos["long"].values[0] + target_pos["long"].values[0]) / 2
                    mid_lat = (source_pos["lat"].values[0] + target_pos["lat"].values[0]) / 2
                    mid_alt = (source_pos["alt"].values[0] + target_pos["alt"].values[0]) / 2
                    edges_list.append(
                        {
                            "source": source_pos[["long", "lat", "alt"]].values[0].tolist(),
                            "target": target_pos[["long", "lat", "alt"]].values[0].tolist(),
                            "label": f"{source}->{target}",
                            "midpoint": [mid_long, mid_lat, mid_alt],
                        }
                    )
    return pd.DataFrame(edges_list)

def create_layers_geomap(selected_links, df, current_positions):
    required = ["flight_id", "long", "lat", "alt"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        st.warning(f"Missing required columns for map view: {missing}.")
        return []

    layers = [terrain_layer]
    if "satcom_link" in selected_links:
        satcom_edges_df = create_edges_geomap(df, "satcom_link", current_positions)
        if not satcom_edges_df.empty:
            satcom_layer = pdk.Layer(
                "LineLayer",
                data=satcom_edges_df,
                get_source_position="source",
                get_target_position="target",
                get_color=[0, 200, 255],
                get_width=1.5,
                opacity=0.7,
            )
            layers.append(satcom_layer)
            text_layer = pdk.Layer(
                "TextLayer",
                data=satcom_edges_df,
                get_position="midpoint",
                get_text="label",
                get_size=16,
                get_color=[0, 200, 255],
                get_alignment_baseline="'bottom'",
            )
            layers.append(text_layer)
    if "optical_link" in selected_links:
        optical_edges_df = create_edges_geomap(df, "optical_link", current_positions)
        optical_layer = pdk.Layer(
            "LineLayer",
            data=optical_edges_df,
            get_source_position="source",
            get_target_position="target",
            get_color=[0, 128, 0],
            get_width=1.5,
            opacity=0.7,
        )
        layers.append(optical_layer)
        if not optical_edges_df.empty:
            layers.append(
                pdk.Layer(
                    "TextLayer",
                    data=optical_edges_df,
                    get_position="midpoint",
                    get_text="label",
                    get_size=16,
                    get_color=[0, 128, 0],
                    get_alignment_baseline="'bottom'",
                )
            )
    if "legacy_link" in selected_links:
        legacy_edges_df = create_edges_geomap(df, "legacy_link", current_positions)
        legacy_layer = pdk.Layer(
            "LineLayer",
            data=legacy_edges_df,
            get_source_position="source",
            get_target_position="target",
            get_color=[128, 0, 128],
            get_width=1.5,
            opacity=1.0,
        )
        layers.append(legacy_layer)
        if not legacy_edges_df.empty:
            layers.append(
                pdk.Layer(
                    "TextLayer",
                    data=legacy_edges_df,
                    get_position="midpoint",
                    get_text="label",
                    get_size=16,
                    get_color=[128, 0, 128],
                    get_alignment_baseline="'bottom'",
                )
            )
    if "ivbl_link" in selected_links:
        ivbl_edges_df = create_edges_geomap(df, "ivbl_link", current_positions)
        ivbl_layer = pdk.Layer(
            "LineLayer",
            data=ivbl_edges_df,
            get_source_position="source",
            get_target_position="target",
            get_color=[255, 0, 0],
            get_width=1.5,
            opacity=0.7,
        )
        layers.append(ivbl_layer)
        if not ivbl_edges_df.empty:
            layers.append(
                pdk.Layer(
                    "TextLayer",
                    data=ivbl_edges_df,
                    get_position="midpoint",
                    get_text="label",
                    get_size=16,
                    get_color=[255, 0, 0],
                    get_alignment_baseline="'bottom'",
                )
            )

    nodes_layer = pdk.Layer(
        "PointCloudLayer",
        data=current_positions,
        get_position="[long,lat,alt]",
        get_color="color",
        point_size=13,
        elevation_scale=500,
        auto_highlight=True,
        opacity=3.0,
        pickable=True,
    )
    layers.append(nodes_layer)
    return layers

def get_fixed_layout(df, layout="spring"):
    G = nx.Graph()
    nodes = df["flight_id"].unique()
    G.add_nodes_from(nodes)
    if layout == "bipartite":
        pos = nx.bipartite_layout(G, nodes)
    elif layout == "circular":
        pos = nx.circular_layout(G)
    elif layout == "planar":
        pos = nx.planar_layout(G)
    elif layout == "random":
        pos = nx.random_layout(G)
    elif layout == "rescale":
        pos = nx.spring_layout(G)
        pos = nx.rescale_layout_dict(pos)
    elif layout == "shell":
        pos = nx.shell_layout(G)
    elif layout == "spring":
        pos = nx.spring_layout(G, seed=43)
    elif layout == "spiral":
        pos = spiral_layout(G)
    else:
        raise ValueError("Unsupported layout type")
    return pos

def spiral_layout(G, scale=1.0, center=(0, 0), dim=2):
    nodes = list(G.nodes())
    pos = {}
    num_nodes = len(nodes)
    theta = np.linspace(0, 4 * np.pi, num_nodes)
    r = np.linspace(0, 1, num_nodes) * scale
    for i, node in enumerate(nodes):
        x = r[i] * np.cos(theta[i]) + center[0]
        y = r[i] * np.sin(theta[i]) + center[1]
        pos[node] = (x, y)
    return pos

def convert_to_tuples(value):
    if isinstance(value, str):
        try:
            list_of_tuples = ast.literal_eval(value)
            if isinstance(list_of_tuples, list):
                return [tuple(item) for item in list_of_tuples if isinstance(item, (list, tuple)) and len(item) == 2]
            else:
                st.warning(f"Expected a list but got: {list_of_tuples}")
                return []
        except (ValueError, SyntaxError) as e:
            st.warning(f"Failed to parse tuples from string: {value}. Error: {e}")
            return []
    elif isinstance(value, list):
        return [tuple(item) for item in value if isinstance(item, (list, tuple)) and len(item) == 2]
    else:
        st.warning(f"Unexpected value type: {value}")
        return []

def parse_edges(column):
    edges = []
    for item in column:
        tuples = convert_to_tuples(item)
        for edge in tuples:
            if len(edge) != 2:
                continue
            try:
                u = int(edge[0])
                v = int(edge[1])
                edges.append((u, v))
            except Exception:
                continue
    return edges

def filter_edges(df, edge_columns):
    filtered_edges = {}
    for edge_type in edge_columns:
        edge_list = df[edge_type].dropna().tolist()
        filtered_edges[edge_type] = parse_edges(edge_list)
    return filtered_edges

# ----------------------------
# Live allocations helpers
# ----------------------------
def load_allocations(path: Path) -> pd.DataFrame:
    path = path.expanduser()
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        try:
            return pd.read_parquet(path)
        except Exception:
            pass
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = []
        if isinstance(data, list):
            for step in data:
                t_idx = step.get("time_index", 0)
                for alloc in step.get("allocations", []):
                    row = dict(alloc)
                    row["time_index"] = t_idx
                    rows.append(row)
            return pd.DataFrame(rows)
        elif isinstance(data, dict):
            return pd.DataFrame([data])
    except Exception:
        return pd.DataFrame()
    return pd.DataFrame()

def _nearest_row(df: pd.DataFrame, t: float) -> pd.DataFrame:
    if df.empty or "time_s" not in df.columns:
        return df
    idx = (df["time_s"] - t).abs().idxmin()
    return df.loc[[idx]]

# ----------------------------
# Optional edges loader (from synthetic topology export)
# ----------------------------
def load_edges_file(path: Path) -> dict[str, list[tuple[int, int]]]:
    path = path.expanduser()
    if not path.exists():
        return {}
    try:
        if path.suffix.lower() in {".parquet", ".pq", ".parq"}:
            df = pd.read_parquet(path)
        else:
            df = pd.read_json(path)
    except Exception:
        return {}
    edges_by_type: dict[str, list[tuple[int, int]]] = {
        "satcom_link": [],
        "optical_link": [],
        "legacy_link": [],
        "ivbl_link": [],
    }
    if {"source", "target", "bearer"}.issubset(df.columns):
        for _, row in df.iterrows():
            try:
                u = int(row["source"])
                v = int(row["target"])
                bearer = str(row["bearer"]).lower()
            except Exception:
                continue
            if "sat" in bearer:
                edges_by_type["satcom_link"].append((u, v))
            elif "opt" in bearer:
                edges_by_type["optical_link"].append((u, v))
            elif "legacy" in bearer:
                edges_by_type["legacy_link"].append((u, v))
            elif "iv" in bearer:
                edges_by_type["ivbl_link"].append((u, v))
    return edges_by_type

def load_positions_at_time(traj_glob: str, t: float) -> pd.DataFrame:
    records = []
    for fname in glob.glob(str(Path(traj_glob).expanduser())):
        try:
            df = pd.read_parquet(fname)
        except Exception:
            try:
                df = pd.read_csv(fname)
            except Exception:
                continue
        if not {"time_s", "latitude", "longitude"}.issubset(df.columns):
            continue
        closest = _nearest_row(df, t)
        if closest.empty:
            continue
        row = closest.iloc[0]
        records.append(
            {
                "flight_id": Path(fname).stem,
                "time_s": row.get("time_s", t),
                "lat": row.get("latitude"),
                "long": row.get("longitude"),
                "alt": row.get("alt_m", 0.0),
            }
        )
    return pd.DataFrame(records)

def build_allocation_layers(alloc_df: pd.DataFrame, positions: pd.DataFrame):
    if alloc_df.empty or positions.empty:
        return []
    edges = []
    for _, row in alloc_df.iterrows():
        src = str(row.get("source"))
        dst = str(row.get("destination"))
        src_pos = positions.loc[positions["flight_id"] == f"plane_{src}"]
        if src_pos.empty:
            src_pos = positions.loc[positions["flight_id"] == src]
        dst_pos = positions.loc[positions["flight_id"] == f"plane_{dst}"]
        if dst_pos.empty:
            dst_pos = positions.loc[positions["flight_id"] == dst]
        if src_pos.empty or dst_pos.empty:
            continue
        edges.append(
            {
                "source": src_pos[["long", "lat", "alt"]].values[0].tolist(),
                "target": dst_pos[["long", "lat", "alt"]].values[0].tolist(),
                "bandwidth": row.get("bandwidth", 0),
                "delivered": row.get("delivered_bandwidth", row.get("capacity_mbps", 0)),
            }
        )
    if not edges:
        return []
    edge_df = pd.DataFrame(edges)
    width_norm = edge_df["delivered"].fillna(0)
    if not width_norm.empty and width_norm.max() > 0:
        width_norm = 2 + 8 * (width_norm / width_norm.max())
    else:
        width_norm = 2
    edge_df["width"] = width_norm
    return [
        pdk.Layer(
            "LineLayer",
            data=edge_df,
            get_source_position="source",
            get_target_position="target",
            get_color=[255, 140, 0],
            get_width="width",
            opacity=0.8,
            pickable=True,
        )
    ]

def bezier_curve(x1, y1, x2, y2, control_points=20, offset=0.2):
    t = np.linspace(0, 1, control_points)
    x_mid = (x1 + x2) / 2
    y_mid = (y1 + y2) / 2
    x_control = x_mid + offset * (y2 - y1)
    y_control = y_mid + offset * (x1 - x2)
    x_bezier = (1 - t) ** 2 * x1 + 2 * (1 - t) * t * x_control + t ** 2 * x2
    y_bezier = (1 - t) ** 2 * y1 + 2 * (1 - t) * t * y_control + t ** 2 * y2
    return x_bezier, y_bezier

def create_network_graph(df, pos, show_nodes, show_edges, edge_types, metric_type, color_map=None, symbol_map=None):
    G = nx.Graph()
    G.add_nodes_from(pos.keys())
    edge_columns = ["satcom_link", "optical_link", "legacy_link", "ivbl_link"]
    edges = filter_edges(df, edge_columns)
    for edge_type, tuples in edges.items():
        for (u, v) in tuples:
            if u in pos and v in pos:
                G.add_edge(u, v, type=edge_type, label=f"{u}->{v}")

    edge_traces = []
    normalized_metrics = {}
    if metric_type in ["bandwidth", "throughput"]:
        metrics = extract_metrics(df, metric_type)
        normalized_metrics = {et: normalize_values(metrics.get(et, [])) for et in edge_types}
    else:
        normalized_metrics = {et: [] for et in edge_types}

    for edge_type in edge_types:
        edge_x, edge_y, edge_texts = [], [], []
        link_index = 0
        for u, v, data in G.edges(data=True):
            if data.get("type") == edge_type:
                x0, y0 = pos[u]
                x1, y1 = pos[v]
                x_bezier, y_bezier = bezier_curve(x0, y0, x1, y1)
                edge_x.extend(x_bezier)
                edge_y.extend(y_bezier)
                edge_x.append(None)
                edge_y.append(None)
                normalized_value = normalized_metrics.get(edge_type, [5])[link_index] if link_index < len(normalized_metrics.get(edge_type, [])) else 5
                link_index += 1
                hover_text = f"Link {u}->{v}<br>Type: {data['type']}<br>Normalized Capacity: {normalized_value}"
                edge_texts.extend([hover_text] * len(x_bezier))
                edge_texts.append(None)
                edge_width = normalized_value if normalized_value is not None else 5
                edge_trace = go.Scatter(
                    x=edge_x,
                    y=edge_y,
                    line=dict(width=edge_width, color=link_colors_plotly.get(edge_type, "#888")),
                    hoverinfo="text",
                    text=edge_texts,
                    mode="lines",
                    name=f"{edge_type.replace('_', ' ').capitalize()}",
                    opacity=1.0,
                )
                edge_traces.append(edge_trace)
                # Edge label at midpoint
                mx, my = (x0 + x1) / 2, (y0 + y1) / 2
                edge_traces.append(
                    go.Scatter(
                        x=[mx],
                        y=[my],
                        mode="text",
                        text=[f"{u}->{v}"],
                        textposition="middle center",
                        hoverinfo="skip",
                        showlegend=False,
                    )
                )
    node_x = [pos[node][0] for node in G.nodes()]
    node_y = [pos[node][1] for node in G.nodes()]
    node_texts = [f"ID: {node}" for node in G.nodes()]
    unique_nodes = list(G.nodes())
    node_symbols = {}
    symbol_cycle = ["circle", "square", "diamond", "triangle-up", "triangle-down", "cross", "x"]
    for i, node in enumerate(sorted(unique_nodes, key=lambda x: str(x))):
        base_symbol = None
        if symbol_map:
            base_symbol = symbol_map.get(node) or symbol_map.get(str(node))
        node_symbols[node] = base_symbol if base_symbol else symbol_cycle[i % len(symbol_cycle)]

    if color_map:
        node_colors = {}
        for node in unique_nodes:
            color = color_map.get(node, color_map.get(str(node)))
            node_colors[node] = color if color else "#888"
    else:
        node_color_map = plt.get_cmap("tab20", len(unique_nodes))
        node_colors = {node: mcolors.rgb2hex(node_color_map(i % 20)) for i, node in enumerate(unique_nodes)}
    legend_traces = []
    for node, color in node_colors.items():
        legend_traces.append(go.Scatter(
            x=[None],
            y=[None],
            mode="markers",
            marker=dict(color=color, size=15, line=dict(width=0), symbol=node_symbols.get(node, "circle")),
            name=f"Flight ID: {node}",
        ))
    node_traces = []
    if show_nodes:
        symbols = [node_symbols[node] for node in G.nodes()]
        node_traces = []
        # Plot each symbol group separately to ensure Plotly applies symbols (workaround when mixing symbol + color arrays)
        for symbol in sorted(set(symbols)):
            group_nodes = [n for n in G.nodes() if node_symbols.get(n) == symbol]
            node_traces.append(
                go.Scatter(
                    x=[pos[n][0] for n in group_nodes],
                    y=[pos[n][1] for n in group_nodes],
                    mode="markers",
                    hoverinfo="text",
                    marker_symbol=symbol,
                    marker=dict(
                        showscale=False,
                        color=[node_colors[n] for n in group_nodes],
                        size=30,
                        line=dict(width=1, color="#333"),
                    ),
                    text=[f"ID: {n}" for n in group_nodes],
                    name=f"Nodes ({symbol})",
                    showlegend=False,
                )
            )
    fig = go.Figure(
        data=edge_traces + node_traces + legend_traces,
        layout=go.Layout(
            showlegend=True,
            legend=dict(x=1, y=1, traceorder="normal", font=dict(size=15)),
            hovermode="closest",
            autosize=True,
            height=700,
            margin=dict(b=90, l=5, r=5, t=0),
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, autorange=True, automargin=True),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, autorange=True, automargin=True),
        ),
    )
    return fig

def increment_time(unique_timestamps):
    current_index = unique_timestamps.index(st.session_state.selected_time)
    if current_index < len(unique_timestamps) - 1:
        st.session_state.selected_time_idx = current_index + 1
        st.session_state.selected_time = unique_timestamps[st.session_state.selected_time_idx]

def decrement_time(unique_timestamps):
    current_index = unique_timestamps.index(st.session_state.selected_time)
    if current_index > 0:
        st.session_state.selected_time_idx = current_index - 1
        st.session_state.selected_time = unique_timestamps[st.session_state.selected_time_idx]

def safe_literal_eval(value):
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return value

def extract_metrics(df, metric_column):
    metrics = {}
    for _, row in df.iterrows():
        metric_dict = row[metric_column]
        if isinstance(metric_dict, dict):
            for link_type, values in metric_dict.items():
                metrics.setdefault(link_type, []).extend(values)
    return metrics

def normalize_values(metrics, scale=10):
    normalized = {}
    all_values = [value for values in metrics.values() for value in values]
    if not all_values:
        return {k: [] for k in metrics.keys()}
    max_value = max(all_values)
    min_value = min(all_values)
    scale_factor = scale / (max_value - min_value) if max_value != min_value else 1
    for link_type, values in metrics.items():
        normalized[link_type] = [(value - min_value) * scale_factor for value in values]
    return normalized

def update_var(var_key, widget_key):
    st.session_state[var_key] = st.session_state[widget_key]

def update_datadir(var_key, widget_key):
    if "df_file" in st.session_state:
        del st.session_state["df_file"]
    if "csv_files" in st.session_state:
        del st.session_state["csv_files"]
    update_var(var_key, widget_key)

def page():
    if "project" not in st.session_state:
        st.session_state.project = env.target
    if "projects" not in st.session_state:
        st.session_state.projects = env.projects
    # Restore persisted sidebar settings if available
    vm_settings = st.session_state.get("app_settings", {}).get("view_maps_network", {})
    if vm_settings:
        for key in (
            "base_dir_choice",
            "input_datadir",
            "datadir_rel",
            "file_ext_choice",
            # flight/time columns are detected per file, so don't restore stale values
            "link_multiselect",
            "show_map",
            "show_graph",
            "show_metrics",
        ):
            if key in vm_settings and key not in st.session_state:
                st.session_state[key] = vm_settings[key]

    # Data directory + presets (base paths without app suffix)
    export_base = env.AGILAB_EXPORT_ABS
    share_base = Path(env.agi_share_dir) if getattr(env, "agi_share_dir", None) else export_base
    if "datadir" not in st.session_state:
        export_base.mkdir(parents=True, exist_ok=True)
        st.session_state.datadir = export_base
    qps = st.query_params
    qp_base = qps.get("base_dir_choice")
    if isinstance(qp_base, list):
        qp_base = qp_base[-1] if qp_base else None
    qp_input = qps.get("input_datadir")
    if isinstance(qp_input, list):
        qp_input = qp_input[-1] if qp_input else None
    qp_rel = qps.get("datadir_rel")
    if isinstance(qp_rel, list):
        qp_rel = qp_rel[-1] if qp_rel else None

    # Seed session defaults from query params before widgets are created
    if "base_dir_choice" not in st.session_state:
        st.session_state["base_dir_choice"] = qp_base or "AGILAB_EXPORT"
    if "input_datadir" not in st.session_state:
        st.session_state["input_datadir"] = qp_input or str(export_base)

    base_options = ["AGI_SHARE_DIR", "AGILAB_EXPORT", "Custom"]
    base_default = qp_base or st.session_state.get("base_dir_choice", "AGILAB_EXPORT")
    try:
        base_index = base_options.index(base_default)
    except ValueError:
        base_index = 1
    base_choice = st.sidebar.radio(
        "Base directory",
        base_options,
        index=base_index,
        key="base_dir_choice",
    )
    if base_choice == "AGI_SHARE_DIR":
        base_path = share_base
        st.session_state["input_datadir"] = str(share_base)
    elif base_choice == "AGILAB_EXPORT":
        base_path = export_base
        st.session_state["input_datadir"] = str(export_base)
    else:
        custom_val = st.sidebar.text_input(
            "Custom data directory",
            value=qp_input or st.session_state.get("input_datadir", str(export_base)),
            key="input_datadir",
        )
        try:
            base_path = Path(custom_val).expanduser()
        except Exception:
            st.warning("Invalid custom path; falling back to export.")
            base_path = export_base
            st.session_state["input_datadir"] = str(export_base)
    # Optional relative subdir under the base (prefer explicit query param; otherwise session or last stored)
    stored_rel = _load_last_subdir()
    rel_default = qp_rel if qp_rel not in (None, "") else (st.session_state.get("datadir_rel") or stored_rel)
    # If a query param is provided, ensure the selectbox key picks it up
    if qp_rel not in (None, "") and st.session_state.get("datadir_rel_select") != qp_rel:
        st.session_state["datadir_rel_select"] = qp_rel
    try:
        subdir_options = [""] + sorted([p.name for p in base_path.iterdir() if p.is_dir()])
    except FileNotFoundError:
        base_path.mkdir(parents=True, exist_ok=True)
        subdir_options = [""]
    if rel_default and rel_default not in subdir_options:
        subdir_options.append(rel_default)
    # Keep the selectbox value valid
    if "datadir_rel_select" in st.session_state and st.session_state["datadir_rel_select"] not in subdir_options:
        st.session_state["datadir_rel_select"] = rel_default if rel_default in subdir_options else subdir_options[0]
    rel_subdir = st.sidebar.selectbox(
        "Relative subdir",
        options=subdir_options,
        index=subdir_options.index(st.session_state.get("datadir_rel_select", rel_default)) if st.session_state.get("datadir_rel_select", rel_default) in subdir_options else 0,
        key="datadir_rel_select",
        format_func=lambda v: v if v else "(root)",
    )
    # Keep session in sync without touching the widget key
    st.session_state["datadir_rel"] = rel_subdir
    st.session_state.pop("datadir_rel_input", None)
    _store_last_subdir(rel_subdir)
    # Persist base, custom path, and rel subdir into query params for reloads
    try:
        st.query_params["base_dir_choice"] = base_choice
        st.query_params["input_datadir"] = st.session_state.get("input_datadir", "")
        st.query_params["datadir_rel"] = rel_subdir
    except Exception:
        pass
    # Avoid doubling the app name: if both base and rel are the same, drop rel
    if base_path.name == rel_subdir:
        final_path = base_path
    else:
        final_path = (base_path / rel_subdir) if rel_subdir else base_path
    final_path.mkdir(parents=True, exist_ok=True)
    prev_datadir = Path(st.session_state.get("datadir", final_path)).expanduser()
    if prev_datadir != final_path:
        st.session_state.datadir = final_path
        st.session_state["input_datadir"] = str(final_path)
        st.session_state.pop("df_file", None)
        st.session_state.pop("csv_files", None)
    st.sidebar.caption(f"Resolved path: {final_path}")

    ext_options = ["csv", "parquet", "json", "all"]
    ext_default = st.session_state.get("file_ext_choice", "all")
    try:
        ext_index = ext_options.index(ext_default)
    except ValueError:
        ext_index = 0
    ext_choice = st.sidebar.selectbox(
        "File type",
        ext_options,
        index=ext_index,
        key="file_ext_choice",
    )

    # Persist sidebar selections for reuse
    app_settings = st.session_state.setdefault("app_settings", {})
    app_settings["view_maps_network"] = {
        "base_dir_choice": st.session_state.get("base_dir_choice", "AGILAB_EXPORT"),
        "input_datadir": st.session_state.get("input_datadir", ""),
        "datadir_rel": st.session_state.get("datadir_rel", ""),
        "file_ext_choice": st.session_state.get("file_ext_choice", "all"),
        "flight_id_col": st.session_state.get("flight_id_col", ""),
        "time_col": st.session_state.get("time_col", ""),
        "link_multiselect": st.session_state.get("link_multiselect", []),
        "show_map": st.session_state.get("show_map", True),
        "show_graph": st.session_state.get("show_graph", True),
        "show_metrics": st.session_state.get("show_metrics", False),
    }

    datadir_path = Path(st.session_state.datadir).expanduser()
    if ext_choice == "all":
        files = list(datadir_path.rglob("*.csv")) + list(datadir_path.rglob("*.parquet")) + list(datadir_path.rglob("*.json"))
    else:
        files = list(datadir_path.rglob(f"*.{ext_choice}"))

    if not files:
        st.session_state.pop("csv_files", None)
        st.session_state.pop("df_file", None)
        st.session_state.pop("flight_id_col", None)
        st.session_state.pop("time_col", None)
        st.warning(f"No files found under {datadir_path} (filter: {ext_choice}). Please choose a directory with data or export from Execute.")
        return

    # datadir may have changed via fallback; refresh path base
    datadir_path = Path(st.session_state.datadir).expanduser()
    st.session_state.csv_files = files

    csv_files_rel = sorted([Path(file).relative_to(datadir_path).as_posix() for file in st.session_state.csv_files])

    prev_df_file = st.session_state.get("_prev_df_file")
    prev_files_rel = st.session_state.get("_prev_csv_files_rel")
    if prev_files_rel != csv_files_rel:
        st.session_state.pop("df_file", None)
    st.sidebar.selectbox(
        label="DataFrame",
        options=csv_files_rel,
        key="df_file",
        index=csv_files_rel.index(st.session_state.df_file) if "df_file" in st.session_state and st.session_state.df_file in csv_files_rel else 0,
    )
    if st.session_state.get("df_file") != prev_df_file:
        st.session_state.pop("loaded_df", None)
        st.session_state.pop("flight_id_col", None)
        st.session_state.pop("time_col", None)
        st.session_state["_prev_df_file"] = st.session_state.get("df_file")
    st.session_state["_prev_csv_files_rel"] = csv_files_rel

    if not st.session_state.get("df_file"):
        st.warning("Please select a dataset to proceed.")
        return

    df_file_abs = Path(st.session_state.datadir) / st.session_state.df_file
    try:
        cache_buster = None
        try:
            cache_buster = df_file_abs.stat().st_mtime
        except Exception:
            pass
        st.session_state.loaded_df = load_df(df_file_abs, with_index=True, cache_buster=cache_buster)
    except Exception as e:
        st.error(f"Error loading data: {e}")
        st.warning("The selected data file could not be loaded. Please select a valid file.")
        return

    df = st.session_state.loaded_df

    # Normalize common geo/altitude columns early
    rename_geo = {
        "longitude": "long",
        "lon": "long",
        "latitude": "lat",
        "alt_m": "alt",
        "altitude": "alt",
        "altitude_m": "alt",
    }
    for src, dest in rename_geo.items():
        if src in df.columns and dest not in df.columns:
            df[dest] = df[src]
    for coord in ("long", "lat", "alt"):
        if coord not in df.columns:
            df[coord] = 0.0

    st.sidebar.markdown("### Columns")
    all_cols = list(df.columns)
    # Ensure sensible defaults for ID and time columns (per-file detection)
    id_pref = [
        "flight_id",
        "plane_id",
        "id",
        "node_id",
        "vehicle_id",
        "callsign",
        "call_sign",
        "track_id",
    ]
    time_pref = ["datetime", "timestamp", "time", "time_s", "time_ms", "time_us", "date"]
    if st.session_state.get("flight_id_col") not in all_cols:
        picked_id = next((c for c in id_pref if c in all_cols), None)
        if not picked_id:
            # fallback to first non-time column if possible
            picked_id = next((c for c in all_cols if c not in time_pref), all_cols[0])
        st.session_state["flight_id_col"] = picked_id
    time_default = st.session_state.get("time_col")
    if time_default not in all_cols:
        time_default = next((c for c in time_pref if c in all_cols), all_cols[0])
        st.session_state["time_col"] = time_default
    flight_col = st.sidebar.selectbox(
        "ID column",
        options=all_cols,
        index=all_cols.index(st.session_state["flight_id_col"]),
        key="flight_id_col",
    )
    time_col = st.sidebar.selectbox(
        "Timestamp column",
        options=all_cols,
        index=all_cols.index(time_default),
        key="time_col",
    )

    # Check and fix flight_id presence
    if flight_col not in df.columns:
        st.error(f"The dataset must contain a '{flight_col}' column.")
        st.stop()

    # Ensure time column is usable; keep numeric durations as-is to avoid 1970 epoch
    if time_col not in df.columns:
        try:
            df[time_col] = pd.to_datetime(df.index)
        except Exception:
            st.error(f"No '{time_col}' column found and failed to convert index to datetime.")
            st.stop()
    else:
        try:
            if pd.api.types.is_datetime64_any_dtype(df[time_col]):
                df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
            elif pd.api.types.is_numeric_dtype(df[time_col]):
                # leave numeric durations as-is (seconds), avoid epoch conversion to 1970
                df[time_col] = pd.to_numeric(df[time_col], errors="coerce")
            else:
                df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
        except Exception:
            st.error(f"Failed to convert '{time_col}' to datetime.")
            st.stop()
    if df[time_col].isna().all():
        st.error(f"No valid timestamps found in '{time_col}'.")
        st.stop()

    df = df.sort_values(by=[flight_col, time_col])
    # Normalize to standard column names for downstream helpers (keep aliases for backward helpers)
    df_std = df.rename(columns={flight_col: "id_col", time_col: "time_col"}, errors="ignore")
    if "id_col" not in df_std.columns:
        df_std["id_col"] = df[flight_col]
    if "time_col" not in df_std.columns:
        df_std["time_col"] = df[time_col]
    if "flight_id" not in df_std.columns:
        df_std["flight_id"] = df_std["id_col"]
    # Ensure base df has flight_id for downstream map/edge helpers
    df["flight_id"] = df_std["id_col"]
    if "datetime" not in df_std.columns:
        df_std["datetime"] = df_std["time_col"]
    # Ensure geo columns present for downstream views
    for src, dest in (("longitude", "long"), ("lon", "long"), ("latitude", "lat"), ("alt_m", "alt"), ("altitude", "alt"), ("altitude_m", "alt")):
        if src in df_std.columns and dest not in df_std.columns:
            df_std[dest] = df_std[src]
    for coord in ("long", "lat", "alt"):
        if coord not in df_std.columns:
            df_std[coord] = 0.0
    if df.empty:
        st.warning("The dataset is empty. Please select a valid data file.")
        return

    st.sidebar.markdown("### Display options")
    selected_links = st.sidebar.multiselect(
        "Link types",
        options=["satcom_link", "optical_link", "legacy_link", "ivbl_link"],
        default=st.session_state.get("link_multiselect", ["satcom_link"]),
        key="link_multiselect",
    )
    show_map = st.sidebar.checkbox("Show map view", value=st.session_state.get("show_map", True), key="show_map")
    show_graph = st.sidebar.checkbox("Show topology graph", value=st.session_state.get("show_graph", True), key="show_graph")
    jitter_overlap = st.sidebar.checkbox("Separate overlapping nodes", value=False, key="jitter_overlap")
    edges_file = st.sidebar.text_input(
        "Edges file (optional, JSON/Parquet with source/target/bearer)",
        value=str((Path(env.agi_share_dir) / "example_app" / "edges.parquet").expanduser()),
        key="edges_file_input",
    )
    show_metrics = st.sidebar.checkbox("Show metrics table", value=st.session_state.get("show_metrics", False), key="show_metrics")

    layout_type = st.selectbox(
        "Select Layout Type",
        options=["bipartite", "circular", "planar", "random", "rescale", "shell", "spring", "spiral"],
        index=6,
        key="layout_type_select",
    )

    st.session_state.df_cols = df.columns.tolist()
    available_metrics = [st.session_state.df_cols[-2], st.session_state.df_cols[-1]]
    selected_metric = st.selectbox("Select Metric for Link Weight", available_metrics)

    # Optional: inject edges from external file when link columns are empty
    edge_cols = ["satcom_link", "optical_link", "legacy_link", "ivbl_link"]
    if edges_file:
        loaded = load_edges_file(Path(edges_file))
        if loaded:
            for col in edge_cols:
                df_std[col] = [loaded.get(col, [])] * len(df_std)
                df[col] = df_std[col]

    if jitter_overlap:
        dup_mask = df_std.duplicated(subset=["long", "lat"], keep=False)
        if dup_mask.any():
            jitter_scale = max(1e-5, float(df_std[dup_mask]["lat"].std() or 0.0) * 0.01) or 1e-3
            noise = np.random.default_rng(42).normal(loc=0.0, scale=jitter_scale, size=(dup_mask.sum(), 2))
            df_std.loc[dup_mask, ["long", "lat"]] += noise

    for col in ["bandwidth", "throughput"]:
        if col in df:
            df[col] = df[col].apply(safe_literal_eval)
    # Ensure link columns exist to avoid KeyError
    for col in ["satcom_link", "optical_link", "legacy_link", "ivbl_link"]:
        if col not in df:
            df[col] = None

    metrics = {}
    for col in ["bandwidth", "throughput"]:
        if col in df:
            metrics[col] = normalize_values(extract_metrics(df, col))
        else:
            metrics[col] = []

    unique_timestamps = sorted(df[time_col].dropna().unique())
    if not unique_timestamps:
        st.error(f"No timestamps found in '{time_col}'.")
        st.stop()
    # Initialize selected time once; keep user/autoplay choice on reruns
    if "selected_time" not in st.session_state or st.session_state.selected_time not in unique_timestamps:
        st.session_state.selected_time = unique_timestamps[0]
    # Track index explicitly to avoid equality drift with numpy types
    if "selected_time_idx" not in st.session_state or st.session_state.selected_time not in unique_timestamps:
        st.session_state.selected_time_idx = unique_timestamps.index(st.session_state.selected_time) if st.session_state.selected_time in unique_timestamps else 0

    # Time controls with optional autoplay
    if "auto_play" not in st.session_state:
        st.session_state.auto_play = False
    if "_auto_play_tick" not in st.session_state:
        st.session_state["_auto_play_tick"] = 0
    if "auto_step" not in st.session_state:
        st.session_state.auto_step = 1
    with st.container():
        cola, colb, colc, col_step, col_play = st.columns([0.3, 7.5, 0.6, 1.0, 0.8])
        with cola:
            if st.button("◁", key="decrement_button"):
                decrement_time(unique_timestamps)
        with colb:
            st.session_state.selected_time = st.select_slider(
                "Time",
                options=unique_timestamps,
                value=st.session_state.selected_time,
                format_func=lambda x: x.strftime("%Y-%m-%d %H:%M:%S") if hasattr(x, "strftime") else str(x),
                key="time_slider_control",
            )
            st.caption(f"Selected: {st.session_state.selected_time}")
            idx_now = st.session_state.get("selected_time_idx", 0)
            prog = idx_now / (len(unique_timestamps) - 1) if len(unique_timestamps) > 1 else 1.0
            st.progress(prog)
            if st.session_state.selected_time in unique_timestamps:
                st.session_state.selected_time_idx = unique_timestamps.index(st.session_state.selected_time)
        with colc:
            if st.button("▷", key="increment_button"):
                increment_time(unique_timestamps)
        with col_step:
            st.session_state.auto_step = st.number_input(
                "Step",
                min_value=1,
                max_value=len(unique_timestamps),
                value=st.session_state.auto_step,
                step=1,
                key="auto_step_input",
            )
        with col_play:
            play_label = "⏸" if st.session_state.auto_play else "▶️"
            if st.button(play_label, key="play_toggle"):
                st.session_state.auto_play = not st.session_state.auto_play

    # Autoplay: advance by step per rerun until the end
    if st.session_state.auto_play:
        idx = st.session_state.get("selected_time_idx", 0)
        step = st.session_state.get("auto_step", 1)
        next_idx = min(idx + step, len(unique_timestamps) - 1)
        if next_idx > idx:
            st.session_state.selected_time_idx = next_idx
            st.session_state.selected_time = unique_timestamps[next_idx]
            st.session_state["_auto_play_tick"] = st.session_state.get("_auto_play_tick", 0) + 1
            st.rerun()
        else:
            st.session_state.auto_play = False

    # Per-node latest position up to the selected time (avoid dropping sparse nodes); fall back to last known
    df_time_masked = df[df[time_col] <= st.session_state.selected_time]
    idx_list = []
    if not df_time_masked.empty:
        idx_list.append(df_time_masked.groupby(flight_col)[time_col].idxmax())
    missing_ids = set(df_std["id_col"].unique()) - set(df_time_masked[flight_col].unique())
    if missing_ids:
        fallback_idx = df[df[flight_col].isin(missing_ids)].groupby(flight_col)[time_col].idxmax()
        if not fallback_idx.empty:
            idx_list.append(fallback_idx)
    if not idx_list:
        st.warning("No rows found up to the selected time.")
        st.stop()
    idx = pd.concat(idx_list).unique()
    df_positions = df.loc[idx].copy()
    df_positions_std = df_positions.rename(columns={flight_col: "id_col", time_col: "time_col"}, errors="ignore")
    if "id_col" not in df_positions_std.columns:
        df_positions_std["id_col"] = df_positions[flight_col]
    if "time_col" not in df_positions_std.columns:
        df_positions_std["time_col"] = df_positions[time_col]
    if "flight_id" not in df_positions_std.columns:
        df_positions_std["flight_id"] = df_positions_std["id_col"]
    if "datetime" not in df_positions_std.columns:
        df_positions_std["datetime"] = df_positions_std["time_col"]
    for src, dest in (("longitude", "long"), ("lon", "long"), ("latitude", "lat"), ("alt_m", "alt"), ("altitude", "alt"), ("altitude_m", "alt")):
        if src in df_positions_std.columns and dest not in df_positions_std.columns:
            df_positions_std[dest] = df_positions_std[src]
    for coord in ("long", "lat", "alt"):
        if coord not in df_positions_std.columns:
            df_positions_std[coord] = 0.0
    if df_positions_std.empty:
        st.warning("No rows found at the selected time.")
        st.stop()
    current_positions = df_positions_std.groupby("id_col").last().reset_index()
    if "flight_id" not in current_positions.columns:
        current_positions["flight_id"] = current_positions["id_col"]

    if current_positions.empty:
        st.warning("No data available for the selected time.")
        st.stop()

    if "color_map" not in st.session_state or st.session_state.get("color_map_key") != flight_col:
        flight_ids = df_std["id_col"].unique()
        color_map = plt.get_cmap("tab20", len(flight_ids))
        st.session_state.color_map = {flight_id: mcolors.rgb2hex(color_map(i % 20)) for i, flight_id in enumerate(flight_ids)}
        st.session_state.color_map_key = flight_col

    current_positions["color"] = current_positions["id_col"].map(st.session_state.color_map).apply(hex_to_rgba)

    # Quick dual-screen links
    st.markdown(
        """
        <div style="padding:8px 0;">
          <strong>Dual-screen:</strong>
          <a href="?view=map" target="_blank">Open map view</a> |
          <a href="?view=graph" target="_blank">Open graph view</a>
          <span style="font-size: 12px; color: #666;">(open each in a separate window and place on different monitors)</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Layout containers based on toggles (side-by-side columns)
    map_container = graph_container = None
    qps = st.query_params
    view_param = (qps.get("view", [""])[0] if isinstance(qps.get("view"), list) else qps.get("view", "")) or ""
    view_param = view_param.lower()
    if view_param == "map":
        show_map, show_graph = True, False
    elif view_param == "graph":
        show_map, show_graph = False, True
    if show_map and show_graph:
        col1, col2 = st.columns([4, 4])
        map_container, graph_container = col1, col2
    elif show_map:
        map_container = st.container()
    elif show_graph:
        graph_container = st.container()

    if show_map and map_container is not None:
        with map_container:
            layers = create_layers_geomap(selected_links, df_positions_std, current_positions)
            view_state = pdk.ViewState(
                latitude=current_positions["lat"].mean(),
                longitude=current_positions["long"].mean(),
                zoom=3,
                pitch=-5,
                bearing=5,
                min_pitch=0,
                max_pitch=85,
            )
            r = pdk.Deck(
                layers=layers,
                initial_view_state=view_state,
                map_style=None,
                tooltip={
                    "html": "<b>ID:</b> {id_col}<br>"
                            "<b>Longitude:</b> {long}<br>"
                            "<b>Latitude:</b> {lat}<br>"
                            "<b>Altitude:</b> {alt}",
                    "style": {
                        "backgroundColor": "white",
                        "color": "black",
                        "fontSize": "12px",
                        "borderRadius": "2px",
                        "padding": "5px",
                    },
                },
            )
            st.pydeck_chart(r)

    if show_graph and graph_container is not None:
        with graph_container:
            pos = get_fixed_layout(df_std, layout=layout_type)
            symbol_map: dict[Any, str] = {}
            type_to_symbol = {
                "sat": "triangle-up",
                "satellite": "triangle-up",
                "plane": "circle",
                "ngf": "circle",
                "hrc": "square",
                "lrc": "diamond",
            }
            type_columns = ["type", "node_type", "nodeType"]
            for _, row in df_positions_std.iterrows():
                tval = ""
                for col in type_columns:
                    if col in row and pd.notna(row[col]):
                        tval = str(row[col]).lower()
                        break
                symbol = type_to_symbol.get(tval)
                if not symbol:
                    alt_val = row.get("alt", 0)
                    try:
                        alt_f = float(alt_val)
                    except Exception:
                        alt_f = 0.0
                    if alt_f > 10000:
                        symbol = "triangle-up"
                if not symbol:
                    nid = str(row.get("id_col", "")).lower()
                    if "sat" in nid:
                        symbol = "triangle-up"
                symbol_map[row["id_col"]] = symbol or "circle"
            if not symbol_map:
                symbol_cycle = ["circle", "square", "diamond", "triangle-up", "triangle-down", "cross", "x"]
                for i, node in enumerate(sorted(pos.keys(), key=lambda x: str(x))):
                    symbol_map[node] = symbol_cycle[i % len(symbol_cycle)]
            fig = create_network_graph(
                df_positions_std,
                pos,
                show_nodes=True,
                show_edges=True,
                edge_types=selected_links,
                metric_type=selected_metric,
                color_map=st.session_state.get("color_map"),
                symbol_map=symbol_map,
            )
            st.plotly_chart(fig, use_container_width=True)

    if show_metrics:
        metric_cols = [c for c in [flight_col, time_col, "bearer_type", "throughput", "bandwidth"] if c in df_positions.columns]
        if metric_cols:
            st.markdown("### Metrics snapshot")
            st.dataframe(df_positions[metric_cols].sort_values(flight_col), use_container_width=True)

    # Live allocations overlay (routing/ILP trainers)
    st.markdown("### 📡 Live allocations (routing/ILP)")
    alloc_path_default = Path(env.agi_share_dir) / "example_app/dataframe/trainer_routing/allocations_steps.parquet"
    alloc_path = st.text_input(
        "Allocations file (JSON or Parquet)",
        value=str(alloc_path_default),
        key="alloc_path_input",
    )
    traj_glob_default = Path(env.agi_share_dir) / "example_app/dataframe/flight_simulation/*.parquet"
    traj_glob = st.text_input(
        "Trajectory glob",
        value=str(traj_glob_default),
        key="traj_glob_input",
    )
    alloc_df = load_allocations(Path(alloc_path))
    if alloc_df.empty:
        st.info("No allocations found at the specified path.")
    else:
        times = sorted(alloc_df["time_index"].unique())
        t_sel = st.slider("Time index", min_value=int(min(times)), max_value=int(max(times)), value=int(min(times)))
        alloc_step = alloc_df[alloc_df["time_index"] == t_sel]
        positions_live = load_positions_at_time(traj_glob, t_sel)
        st.dataframe(alloc_step)
        layers_live = []
        if not positions_live.empty:
            nodes_layer_live = pdk.Layer(
                "PointCloudLayer",
                data=positions_live,
                get_position="[long,lat,alt]",
                get_color=[0, 128, 255, 160],
                point_size=12,
                elevation_scale=500,
                auto_highlight=True,
                pickable=True,
            )
            layers_live.append(nodes_layer_live)
        layers_live.extend(build_allocation_layers(alloc_step, positions_live))
        if layers_live:
            view_state_live = pdk.ViewState(
                longitude=positions_live["long"].mean() if not positions_live.empty else 0,
                latitude=positions_live["lat"].mean() if not positions_live.empty else 0,
                zoom=3,
                pitch=45,
                bearing=0,
            )
            st.pydeck_chart(
                pdk.Deck(
                    map_style="mapbox://styles/mapbox/light-v9",
                    initial_view_state=view_state_live,
                    layers=layers_live,
                )
            )
        else:
            st.info("No edges to display for this timestep.")

def main():
    try:
        page()
    except RerunException:
        # propagate Streamlit reruns
        raise
    except Exception as e:
        st.error(f"An error occurred: {e}")
        import traceback
        st.code(traceback.format_exc())

def update_var(var_key, widget_key):
    st.session_state[var_key] = st.session_state[widget_key]

def update_datadir(var_key, widget_key):
    if "df_file" in st.session_state:
        del st.session_state["df_file"]
    if "csv_files" in st.session_state:
        del st.session_state["csv_files"]
    update_var(var_key, widget_key)

if __name__ == "__main__":
    main()
