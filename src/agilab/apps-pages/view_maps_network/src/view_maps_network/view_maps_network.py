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
    df.loc[:, link_column] = df[link_column].apply(
        lambda s: ast.literal_eval(s) if pd.notnull(s) else None
    )
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
                    edges_list.append(
                        {
                            "source": source_pos[["long", "lat", "alt"]].values[0].tolist(),
                            "target": target_pos[["long", "lat", "alt"]].values[0].tolist(),
                        }
                    )
    return pd.DataFrame(edges_list)

def create_layers_geomap(selected_links, df, current_positions):
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
                return [tuple(item) for item in list_of_tuples if isinstance(item, tuple)]
            else:
                st.warning(f"Expected a list but got: {list_of_tuples}")
                return []
        except (ValueError, SyntaxError) as e:
            st.warning(f"Failed to parse tuples from string: {value}. Error: {e}")
            return []
    elif isinstance(value, list):
        return [tuple(item) for item in value if isinstance(item, tuple)]
    else:
        st.warning(f"Unexpected value type: {value}")
        return []

def parse_edges(column):
    edges = []
    for item in column:
        tuples = convert_to_tuples(item)
        for edge in tuples:
            if isinstance(edge, tuple) and len(edge) == 2 and all(isinstance(x, (int, np.int64)) for x in edge):
                edges.append(edge)
            else:
                st.warning(f"Unexpected tuple in edge column: {edge}")
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

@st.cache_data
def create_network_graph(df, pos, show_nodes, show_edges, edge_types, metric_type):
    G = nx.Graph()
    G.add_nodes_from(pos.keys())
    edge_columns = ["satcom_link", "optical_link", "legacy_link", "ivbl_link"]
    edges = filter_edges(df, edge_columns)
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
                hover_text = f"Link Type: {data['type']}<br>Normalized Capacity: {normalized_value}"
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
    node_x = [pos[node][0] for node in G.nodes()]
    node_y = [pos[node][1] for node in G.nodes()]
    node_texts = [f"ID: {node}" for node in G.nodes()]
    unique_nodes = list(G.nodes())
    node_color_map = plt.get_cmap("tab20", len(unique_nodes))
    node_colors = {node: mcolors.rgb2hex(node_color_map(i % 20)) for i, node in enumerate(unique_nodes)}
    legend_traces = []
    for node, color in node_colors.items():
        legend_traces.append(go.Scatter(
            x=[None],
            y=[None],
            mode="markers",
            marker=dict(color=color, size=15, line=dict(width=0)),
            name=f"Flight ID: {node}",
        ))
    node_traces = []
    if show_nodes:
        node_traces = [go.Scatter(
            x=node_x,
            y=node_y,
            mode="markers",
            hoverinfo="text",
            marker=dict(
                showscale=False,
                color=[node_colors[node] for node in G.nodes()],
                size=30,
                line_width=1,
            ),
            text=node_texts,
            name="Nodes",
        )]
    fig = go.Figure(
        data=edge_traces + node_traces + legend_traces,
        layout=go.Layout(
            showlegend=True,
            legend=dict(x=1, y=1, traceorder="normal", font=dict(size=15)),
            hovermode="closest",
            autosize=False,
            width=1000,
            height=600,
            margin=dict(b=90, l=5, r=5, t=0),
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        ),
    )
    return fig

def increment_time(unique_timestamps):
    current_index = unique_timestamps.index(st.session_state.selected_time)
    if current_index < len(unique_timestamps) - 1:
        st.session_state.selected_time = unique_timestamps[current_index + 1]

def decrement_time(unique_timestamps):
    current_index = unique_timestamps.index(st.session_state.selected_time)
    if current_index > 0:
        st.session_state.selected_time = unique_timestamps[current_index - 1]

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
    # Data directory + presets (base paths without app suffix)
    export_base = env.AGILAB_EXPORT_ABS
    share_base = Path(env.agi_share_dir) if getattr(env, "agi_share_dir", None) else export_base
    if "datadir" not in st.session_state:
        export_base.mkdir(parents=True, exist_ok=True)
        st.session_state.datadir = export_base
    base_choice = st.sidebar.radio(
        "Base directory",
        ["AGI_SHARE_DIR", "AGILAB_EXPORT", "Custom"],
        index=1,
        key="base_dir_choice",
    )
    if base_choice == "AGI_SHARE_DIR":
        st.session_state.datadir = share_base
        st.session_state["input_datadir"] = str(share_base)
    elif base_choice == "AGILAB_EXPORT":
        st.session_state.datadir = export_base
        st.session_state["input_datadir"] = str(export_base)
    else:
        custom_val = st.sidebar.text_input(
            "Custom data directory",
            value=st.session_state.get("input_datadir", str(export_base)),
            key="input_datadir",
            on_change=update_datadir,
            args=("datadir", "input_datadir"),
        )
        try:
            st.session_state.datadir = Path(custom_val).expanduser()
        except Exception:
            st.warning("Invalid custom path; falling back to export.")
            st.session_state.datadir = export_base
            st.session_state["input_datadir"] = str(export_base)
    # Optional relative subdir under the base
    rel_subdir = st.session_state.get("datadir_rel", env.target)
    rel_subdir = st.sidebar.text_input(
        "Relative subdir",
        value=rel_subdir,
        key="datadir_rel",
    ).strip()
    base_path = Path(st.session_state.datadir).expanduser()
    # Avoid doubling the app name: if both base and rel are the same app, drop rel
    if base_path.name == rel_subdir:
        final_path = base_path
    else:
        final_path = (base_path / rel_subdir) if rel_subdir else base_path
    final_path.mkdir(parents=True, exist_ok=True)
    st.session_state.datadir = final_path
    st.session_state["input_datadir"] = str(final_path)
    st.sidebar.caption(f"Resolved path: `{final_path}`")

    ext_options = ["csv", "parquet", "json", "all"]
    ext_choice = st.sidebar.selectbox("File type", ext_options, index=0, key="file_ext_choice")

    datadir_path = Path(st.session_state.datadir).expanduser()
    if ext_choice == "all":
        files = list(datadir_path.rglob("*.csv")) + list(datadir_path.rglob("*.parquet")) + list(datadir_path.rglob("*.json"))
    else:
        files = list(datadir_path.rglob(f"*.{ext_choice}"))

    st.session_state.csv_files = files
    if not st.session_state.csv_files:
        st.warning("A dataset is required to proceed. Please add via menu execute/export.")
        st.stop()

    csv_files_rel = sorted([Path(file).relative_to(datadir_path).as_posix() for file in st.session_state.csv_files])

    st.sidebar.selectbox(
        label="DataFrame",
        options=csv_files_rel,
        key="df_file",
        index=csv_files_rel.index(st.session_state.df_file) if "df_file" in st.session_state and st.session_state.df_file in csv_files_rel else 0,
    )

    if not st.session_state.get("df_file"):
        st.warning("Please select a dataset to proceed.")
        return

    df_file_abs = Path(st.session_state.datadir) / st.session_state.df_file
    try:
        st.session_state.loaded_df = load_df(df_file_abs, with_index=True)
    except Exception as e:
        st.error(f"Error loading data: {e}")
        st.warning("The selected data file could not be loaded. Please select a valid file.")
        return

    df = st.session_state.loaded_df

    st.sidebar.markdown("### Columns")
    all_cols = list(df.columns)
    flight_col = st.sidebar.selectbox(
        "ID column",
        options=all_cols,
        index=all_cols.index("flight_id") if "flight_id" in all_cols else 0,
        key="flight_id_col",
    )
    time_col = st.sidebar.selectbox(
        "Timestamp column",
        options=all_cols,
        index=all_cols.index("datetime") if "datetime" in all_cols else 0,
        key="time_col",
    )

    # Check and fix flight_id presence
    if flight_col not in df.columns:
        st.error(f"The dataset must contain a '{flight_col}' column.")
        st.stop()

    # Ensure datetime column
    if time_col not in df.columns:
        try:
            df[time_col] = pd.to_datetime(df.index)
        except Exception:
            st.error(f"No '{time_col}' column found and failed to convert index to datetime.")
            st.stop()
    else:
        try:
            df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
        except Exception:
            st.error(f"Failed to convert '{time_col}' to datetime.")
            st.stop()
    if df[time_col].isna().all():
        st.error(f"No valid timestamps found in '{time_col}'.")
        st.stop()

    df = df.sort_values(by=[flight_col, time_col])
    # Normalize to standard column names for downstream helpers
    df_std = df.rename(columns={flight_col: "id_col", time_col: "time_col"}, errors="ignore")

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
    st.session_state.selected_time = st.session_state.get("selected_time", unique_timestamps[0])

    with st.container():
        cola, colb, colc = st.columns([0.3, 9, 0.3])
        with cola:
            if st.button("◁", key="decrement_button"):
                decrement_time(unique_timestamps)
        with colb:
            st.session_state.selected_time = st.select_slider(
                "Time",
                options=unique_timestamps,
                value=st.session_state.selected_time,
                format_func=lambda x: x.strftime("%Y-%m-%d %H:%M:%S") if hasattr(x, "strftime") else str(x),
                key="time_slider",
            )
        with colc:
            if st.button("▷", key="increment_button"):
                increment_time(unique_timestamps)

    latest_time = df[df[time_col] <= st.session_state.selected_time][time_col].max()
    df_positions = df[df[time_col] == latest_time]
    df_positions_std = df_positions.rename(columns={flight_col: "id_col", time_col: "time_col"}, errors="ignore")
    if df_positions.empty:
        st.warning("No rows found at the selected time.")
        st.stop()
    current_positions = df_positions_std.groupby("id_col").last().reset_index()

    if current_positions.empty:
        st.warning("No data available for the selected time.")
        st.stop()

    if "color_map" not in st.session_state or st.session_state.get("color_map_key") != flight_col:
        flight_ids = df_std["id_col"].unique()
        color_map = plt.get_cmap("tab20", len(flight_ids))
        st.session_state.color_map = {flight_id: mcolors.rgb2hex(color_map(i % 20)) for i, flight_id in enumerate(flight_ids)}
        st.session_state.color_map_key = flight_col

    current_positions["color"] = current_positions["id_col"].map(st.session_state.color_map).apply(hex_to_rgba)

    # Layout containers based on toggles
    if show_map and show_graph:
        col1, col2 = st.columns([4, 4])
    else:
        col1 = st.container()
        col2 = None

    if show_map:
        with col1:
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

    if show_graph:
        target_col = col2 if col2 is not None else st.container()
        with target_col:
            pos = get_fixed_layout(df_std, layout=layout_type)
            fig = create_network_graph(
                df_positions_std,
                pos,
                show_nodes=True,
                show_edges=True,
                edge_types=selected_links,
                metric_type=selected_metric,
            )
            st.plotly_chart(fig)

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
