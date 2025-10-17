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
import streamlit as st
import pandas as pd
import pydeck as pdk
import ast
import networkx as nx
import numpy as np
import plotly.graph_objects as go
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from pathlib import Path


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

st.title(":world_map: Maps Network Graph")

# Build env from CLI, env var, or session fallback
if 'env' not in st.session_state:
    import argparse, os
    parser = argparse.ArgumentParser(description="Run the AGI Streamlit View with optional parameters.")
    parser.add_argument("--active-app", dest="active_app", type=str,
                        help="Active app path (e.g. src/agilab/apps/flight_project)", default=None)
    args, _ = parser.parse_known_args()

    active_app: Path | None
    if args.active_app is None:
        env_app = os.environ.get("AGILAB_APP")
        active_app = Path(env_app).expanduser() if env_app else None
    else:
        active_app = Path(args.active_app)

    if active_app is not None:
        app = active_app.name
        env = AgiEnv(apps_dir=active_app.parent, app=app, verbose=0)
        env.init_done = True
        st.session_state['env'] = env
        st.session_state['IS_SOURCE_ENV'] = env.is_source_env
        st.session_state['IS_WORKER_ENV'] = env.is_worker_env
        st.session_state['apps_dir'] = str(active_app.parent)
    else:
        # Fallback: use session apps_dir only
        apps_dir_value = st.session_state.get("apps_dir")
        env = AgiEnv(apps_dir=Path(apps_dir_value).expanduser() if apps_dir_value else None, verbose=0)
        env.init_done = True
        st.session_state['env'] = env
        st.session_state['IS_SOURCE_ENV'] = env.is_source_env
        st.session_state['IS_WORKER_ENV'] = env.is_worker_env
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
    node_texts = [f"Flight ID: {node}" for node in G.nodes()]
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
    if "datadir" not in st.session_state:
        datadir = env.AGILAB_EXPORT_ABS / env.target
        datadir.mkdir(parents=True, exist_ok=True)
        st.session_state.datadir = datadir

    st.sidebar.text_input(
        "Data Directory",
        value=str(st.session_state.datadir),
        key="input_datadir",
        on_change=update_datadir,
        args=("datadir", "input_datadir"),
    )

    st.session_state.csv_files = find_files(st.session_state.datadir)
    if not st.session_state.csv_files:
        st.warning("A dataset is required to proceed. Please add via menu execute/export.")
        st.stop()

    csv_files_rel = sorted([Path(file).relative_to(st.session_state.datadir).as_posix() for file in st.session_state.csv_files])

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

    st.write("DataFrame columns:", df.columns.tolist())

    # Check and fix flight_id presence
    if "flight_id" not in df.columns:
        # Try resetting index if flight_id is in index
        if "flight_id" in df.index.names:
            df = df.reset_index()
            st.session_state.loaded_df = df
        else:
            st.error("The dataset must contain a 'flight_id' column.")
            st.stop()

    # Ensure datetime column
    if "datetime" not in df.columns:
        try:
            df["datetime"] = pd.to_datetime(df.index)
        except Exception:
            st.error("No 'datetime' column found and failed to convert index to datetime.")
            st.stop()

    df = df.sort_values(by=["flight_id", "datetime"])

    if df.empty:
        st.warning("The dataset is empty. Please select a valid data file.")
        return

    selected_links = st.multiselect(
        "Select Link Types to Display",
        options=["satcom_link", "optical_link", "legacy_link", "ivbl_link"],
        default=["satcom_link"],
        key="link_multiselect",
    )

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

    metrics = {}
    for col in ["bandwidth", "throughput"]:
        if col in df:
            metrics[col] = normalize_values(extract_metrics(df, col))
        else:
            metrics[col] = []

    unique_timestamps = sorted(df["datetime"].unique())
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
                format_func=lambda x: x.strftime("%Y-%m-%d %H:%M:%S"),
                key="time_slider",
            )
        with colc:
            if st.button("▷", key="increment_button"):
                increment_time(unique_timestamps)

    latest_time = df[df["datetime"] <= st.session_state.selected_time]["datetime"].max()
    df_positions = df[df["datetime"] == latest_time]
    current_positions = df_positions.groupby("flight_id").last().reset_index()

    if current_positions.empty:
        st.warning("No data available for the selected time.")
        st.stop()

    if "color_map" not in st.session_state:
        flight_ids = df["flight_id"].unique()
        color_map = plt.get_cmap("tab20", len(flight_ids))
        st.session_state.color_map = {flight_id: mcolors.rgb2hex(color_map(i % 20)) for i, flight_id in enumerate(flight_ids)}

    current_positions["color"] = current_positions["flight_id"].map(st.session_state.color_map).apply(hex_to_rgba)

    col1, col2 = st.columns([4, 4])

    with col1:
        layers = create_layers_geomap(selected_links, df_positions, current_positions)
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
                "html": "<b>Flight ID:</b> {flight_id}<br>"
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

    with col2:
        pos = get_fixed_layout(df, layout=layout_type)
        fig = create_network_graph(
            df_positions,
            pos,
            show_nodes=True,
            show_edges=True,
            edge_types=selected_links,
            metric_type=selected_metric,
        )
        st.plotly_chart(fig)

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
