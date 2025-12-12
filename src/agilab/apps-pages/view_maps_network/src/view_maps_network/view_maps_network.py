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
import re
import tomllib
try:
    import tomli_w as _toml_writer  # type: ignore[import-not-found]

    def _dump_toml(data: dict, handle) -> None:
        _toml_writer.dump(data, handle)

except ModuleNotFoundError:  # pragma: no cover - fallback for lightweight envs
    try:
        from tomlkit import dumps as _tomlkit_dumps

        def _dump_toml(data: dict, handle) -> None:
            handle.write(_tomlkit_dumps(data).encode("utf-8"))

    except Exception as _toml_exc:  # pragma: no cover - defensive guard
        _tomlkit_dumps = None  # type: ignore

        def _dump_toml(data: dict, handle) -> None:
            raise RuntimeError(
                "Writing settings requires the 'tomli-w' or 'tomlkit' package"
            ) from _toml_exc
from datetime import datetime
import time
from streamlit.runtime.scriptrunner import RerunException
from typing import Optional
from agi_env.agi_logger import AgiLogger

logger = AgiLogger.get_logger(__name__)


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


def _ensure_app_settings_loaded(env: AgiEnv) -> None:
    if "app_settings" in st.session_state:
        return
    path = Path(env.app_settings_file)
    if path.exists():
        try:
            with open(path, "rb") as handle:
                st.session_state["app_settings"] = tomllib.load(handle)
                return
        except Exception:
            pass
    st.session_state["app_settings"] = {}


def _persist_app_settings(env: AgiEnv) -> None:
    settings = st.session_state.get("app_settings")
    if not isinstance(settings, dict):
        return
    path = Path(env.app_settings_file)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as handle:
            _dump_toml(settings, handle)
    except Exception as exc:
        logger.warning(f"Unable to persist app_settings to {path}: {exc}")


def _get_view_maps_settings() -> dict:
    app_settings = st.session_state.setdefault("app_settings", {})
    vm_settings = app_settings.get("view_maps_network")
    if not isinstance(vm_settings, dict):
        vm_settings = {}
        app_settings["view_maps_network"] = vm_settings
    return vm_settings


def _read_query_param(key: str) -> Optional[str]:
    value = st.query_params.get(key)
    if isinstance(value, list):
        return value[-1] if value else None
    return value


def _list_subdirectories(base: Path) -> list[str]:
    try:
        if base.exists():
            return sorted(
                [
                    entry.name
                    for entry in base.iterdir()
                    if entry.is_dir() and not entry.name.startswith(".")
                ]
            )
    except Exception as exc:
        st.sidebar.warning(f"Unable to list directories under {base}: {exc}")
    return []


st.title(":world_map: Maps Network Graph")

if 'env' not in st.session_state:
    active_app_path = _resolve_active_app()
    app_name = active_app_path.name
    env = AgiEnv(apps_path=active_app_path.parent, app=app_name, verbose=0)
    env.init_done = True
    st.session_state['env'] = env
    st.session_state['IS_SOURCE_ENV'] = env.is_source_env
    st.session_state['IS_WORKER_ENV'] = env.is_worker_env
    st.session_state['apps_path'] = str(active_app_path.parent)
    st.session_state['app'] = app_name
else:
    env = st.session_state['env']

_ensure_app_settings_loaded(env)

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
_DEFAULT_LINK_ORDER = ["satcom_link", "optical_link", "legacy_link", "ivbl_link"]
_LINK_LABELS = {
    "satcom_link": "SAT",
    "optical_link": "OPT",
    "legacy_link": "LEG",
    "ivbl_link": "IVDL",
}

def _label_for_link(column: str) -> str:
    if column in _LINK_LABELS:
        return _LINK_LABELS[column]
    label = column
    if label.endswith("_link"):
        label = label[: -len("_link")]
    return label.replace("_", " ").upper()

def _candidate_edges_paths(bases: list[Path]) -> list[Path]:
    seen = set()
    candidates: list[Path] = []
    for base in bases:
        if not base or not base.exists():
            continue
        for pattern in ("edges.parquet", "edges.json", "edges.*.parquet", "edges.*.json"):
            for p in base.glob(f"**/{pattern}"):
                if p in seen:
                    continue
                seen.add(p)
                candidates.append(p)
    return candidates

def _color_to_rgb(color_str: str, idx: int = 0) -> list[int]:
    try:
        rgba = mcolors.to_rgba(color_str)
        return [int(rgba[0] * 255), int(rgba[1] * 255), int(rgba[2] * 255), 255]
    except Exception:
        cmap = plt.get_cmap("tab10")
        rgba = cmap(idx % cmap.N)
        return [int(rgba[0] * 255), int(rgba[1] * 255), int(rgba[2] * 255), 255]


def _to_plotly_color(color) -> str:
    """Normalize user-supplied colors to Plotly-friendly rgb strings."""
    if isinstance(color, (list, tuple)):
        if len(color) >= 3:
            r, g, b = (int(color[0]), int(color[1]), int(color[2]))
            return f"rgb({r},{g},{b})"
    try:
        rgba = mcolors.to_rgba(color)
        return f"rgb({int(rgba[0]*255)},{int(rgba[1]*255)},{int(rgba[2]*255)})"
    except Exception:
        return "#888"


def _detect_link_columns(df: pd.DataFrame) -> list[str]:
    skip = {"long", "lat", "alt", "longitude", "latitude", "altitude", "alt_m", "time_col", "id_col", "flight_id", "datetime"}
    candidates: list[str] = []
    for col in df.columns:
        if col in skip:
            continue
        sample = df[col].dropna().head(8)
        if sample.empty:
            continue
        looks_like_links = False
        for val in sample:
            if isinstance(val, (list, tuple)) and len(val) > 0:
                looks_like_links = True
                break
            if isinstance(val, str) and any(ch in val for ch in ("(", "[", ",")):
                looks_like_links = True
                break
        if looks_like_links:
            candidates.append(col)
    ordered = [c for c in _DEFAULT_LINK_ORDER if c in candidates]
    remaining = [c for c in candidates if c not in ordered]
    ordered.extend(sorted(remaining))
    if not ordered:
        ordered = _DEFAULT_LINK_ORDER.copy()
    return ordered

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
    label_text = _label_for_link(link_column)
    for _, row in link_edges.iterrows():
        links = row[link_column]
        if links is not None:
            if isinstance(links, tuple):
                links = [links]
            for source, target in links:
                source_id = str(source)
                target_id = str(target)
                source_pos = current_positions.loc[current_positions["flight_id"] == source_id]
                target_pos = current_positions.loc[current_positions["flight_id"] == target_id]
                if not source_pos.empty and not target_pos.empty:
                    mid_long = (source_pos["long"].values[0] + target_pos["long"].values[0]) / 2
                    mid_lat = (source_pos["lat"].values[0] + target_pos["lat"].values[0]) / 2
                    mid_alt = (source_pos["alt"].values[0] + target_pos["alt"].values[0]) / 2
                    edges_list.append(
                        {
                            "source": source_pos[["long", "lat", "alt"]].values[0].tolist(),
                            "target": target_pos[["long", "lat", "alt"]].values[0].tolist(),
                            "label": label_text,
                            "midpoint": [mid_long, mid_lat, mid_alt],
                        }
                    )
    return pd.DataFrame(edges_list)

def create_layers_geomap(selected_links, df, current_positions, link_color_map):
    required = ["flight_id", "long", "lat", "alt"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        st.warning(f"Missing required columns for map view: {missing}.")
        return []

    layers = [terrain_layer]
    for idx, link_col in enumerate(selected_links):
        edges_df = create_edges_geomap(df, link_col, current_positions)
        if edges_df.empty:
            continue
        rgb_color = _color_to_rgb(link_color_map.get(link_col, link_colors_plotly.get(link_col, f"C{idx}")), idx=idx)
        line_layer = pdk.Layer(
            "LineLayer",
            data=edges_df,
            get_source_position="source",
            get_target_position="target",
            get_color=rgb_color,
            get_width=1.5,
            opacity=0.7,
        )
        text_layer = pdk.Layer(
            "TextLayer",
            data=edges_df,
            get_position="midpoint",
            get_text="label",
            get_size=16,
            get_color=rgb_color[:3],
            get_alignment_baseline="'bottom'",
            billboard=True,
            get_angle=0,
            get_text_anchor='"middle"',
            pickable=False,
        )
        layers.extend([line_layer, text_layer])

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
    elif isinstance(value, tuple):
        return [tuple(value)] if len(value) == 2 else []
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
                u = str(edge[0])
                v = str(edge[1])
                edges.append((u, v))
            except Exception:
                continue
    return edges

def filter_edges(df, edge_columns):
    filtered_edges = {}
    for edge_type in edge_columns:
        if edge_type not in df:
            continue
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


def _find_latest_allocations(base: Path) -> Path | None:
    """Locate the most recent allocations file under a given base."""
    candidates: list[Path] = []
    for pattern in ("allocations*.parquet", "allocations*.json", "allocations*.jsonl", "allocations_steps.parquet"):
        candidates.extend(base.rglob(pattern))
    if not candidates:
        return None
    candidates = [p for p in candidates if p.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)

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
            read_kwargs = {}
            if path.suffix.lower() in {".jsonl", ".ndjson"}:
                read_kwargs["lines"] = True
            df = pd.read_json(path, **read_kwargs)
    except Exception:
        return {}
    # Allow case-insensitive / synonym column names
    col_map = {c.lower(): c for c in df.columns}
    source_col = col_map.get("source") or col_map.get("src") or col_map.get("from")
    target_col = col_map.get("target") or col_map.get("dst") or col_map.get("to")
    bearer_col = (
        col_map.get("bearer")
        or col_map.get("link_type")
        or col_map.get("type")
        or col_map.get("link")
    )
    if not (source_col and target_col and bearer_col):
        return {}

    edges_by_type: dict[str, list[tuple[int, int]]] = {k: [] for k in _DEFAULT_LINK_ORDER}
    for _, row in df.iterrows():
        try:
            u = str(row[source_col])
            v = str(row[target_col])
            bearer_raw = str(row[bearer_col]).strip()
        except Exception:
            continue
        if not u or not v or not bearer_raw:
            continue
        bearer = bearer_raw.lower()
        if "sat" in bearer:
            key = "satcom_link"
        elif "opt" in bearer:
            key = "optical_link"
        elif "legacy" in bearer:
            key = "legacy_link"
        elif "iv" in bearer:
            key = "ivbl_link"
        else:
            key = bearer.replace(" ", "_")
        key = key or "link"
        edges_by_type.setdefault(key, []).append((u, v))
    # Drop empty groups
    edges_by_type = {k: v for k, v in edges_by_type.items() if v}
    return edges_by_type

def load_positions_at_time(traj_glob: str, t: float) -> pd.DataFrame:
    records = []
    for fname in glob.glob(str(Path(traj_glob).expanduser())):
        df = None
        try:
            df = pd.read_parquet(fname)
        except Exception:
            try:
                df = pd.read_csv(fname, encoding="utf-8")
            except UnicodeDecodeError:
                try:
                    df = pd.read_csv(fname, encoding="latin-1")
                except Exception:
                    continue
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

def build_allocation_layers(alloc_df: pd.DataFrame, positions: pd.DataFrame, *, color=None):
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
    line_color = color if color is not None else [255, 140, 0]
    return [
        pdk.Layer(
            "LineLayer",
            data=edge_df,
            get_source_position="source",
            get_target_position="target",
            get_color=line_color,
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

def create_network_graph(df, pos, show_nodes, show_edges, edge_types, metric_type, color_map=None, symbol_map=None, link_color_map=None):
    G = nx.Graph()
    G.add_nodes_from(pos.keys())
    edges = filter_edges(df, edge_types)
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
                edge_color = _to_plotly_color((link_color_map or link_colors_plotly).get(edge_type, "#888"))
                edge_trace = go.Scatter(
                    x=edge_x,
                    y=edge_y,
                    line=dict(width=edge_width, color=edge_color),
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
            node_colors[node] = _to_plotly_color(color) if color else "#888"
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
    vm_settings = _get_view_maps_settings()
    base_seed = vm_settings.get("base_dir_choice")
    input_seed = vm_settings.get("input_datadir")
    rel_seed = vm_settings.get("datadir_rel", "")
    if base_seed and "base_dir_choice" not in st.session_state:
        st.session_state["base_dir_choice"] = base_seed
    if input_seed and "input_datadir" not in st.session_state:
        st.session_state["input_datadir"] = input_seed
    if rel_seed and "datadir_rel" not in st.session_state:
        st.session_state["datadir_rel"] = rel_seed
    for key in (
        "file_ext_choice",
        # flight/time columns are detected per file, so don't restore stale values
        "link_multiselect",
        "show_map",
        "show_graph",
        "show_metrics",
        "df_select_mode",
        "df_file_regex",
        "df_files",
    ):
        if key in vm_settings and key not in st.session_state:
            st.session_state[key] = vm_settings[key]
    if "df_file" in vm_settings and "df_file" not in st.session_state:
        st.session_state["df_file"] = vm_settings["df_file"]

    qp_base = _read_query_param("base_dir_choice")
    qp_input = _read_query_param("input_datadir")
    qp_rel = _read_query_param("datadir_rel")

    # Data directory + presets (base paths without app suffix)
    export_base = env.AGILAB_EXPORT_ABS
    share_base = env.share_root_path()
    base_options = ["AGI_SHARE_DIR", "AGILAB_EXPORT", "Custom"]
    base_default = qp_base or st.session_state.get("base_dir_choice") or base_seed or "AGILAB_EXPORT"
    if base_default not in base_options:
        base_default = "AGILAB_EXPORT"
    base_choice = st.sidebar.radio(
        "Base directory",
        base_options,
        index=base_options.index(base_default),
        key="base_dir_choice",
    )

    base_path: Path
    custom_base_warning = None
    if base_choice == "AGI_SHARE_DIR":
        base_path = share_base
    elif base_choice == "AGILAB_EXPORT":
        base_path = export_base
        base_path.mkdir(parents=True, exist_ok=True)
    else:
        custom_default = qp_input or st.session_state.get("input_datadir") or input_seed or str(export_base)
        custom_val = st.sidebar.text_input(
            "Custom data directory",
            value=custom_default,
            key="input_datadir",
        )
        try:
            base_path = Path(custom_val).expanduser()
        except Exception:
            base_path = export_base
            custom_base_warning = "Invalid custom path; using AGILAB_EXPORT."
        if custom_base_warning:
            st.sidebar.warning(custom_base_warning)
        elif not base_path.exists():
            st.sidebar.info(f"{base_path} does not exist. Adjust the path or create it before exploring data.")

    rel_default = (
        qp_rel
        if qp_rel not in (None, "")
        else st.session_state.get("datadir_rel") or rel_seed or ""
    )
    subdir_options = [""] + _list_subdirectories(base_path)
    if rel_default and rel_default not in subdir_options:
        subdir_options.append(rel_default)
    rel_index = subdir_options.index(rel_default) if rel_default in subdir_options else 0
    rel_subdir = st.sidebar.selectbox(
        "Relative subdir",
        options=subdir_options,
        index=rel_index,
        key="datadir_rel_select",
        format_func=lambda v: v if v else "(root)",
    )
    if base_choice == "Custom":
        custom_rel_default = rel_subdir if rel_subdir else rel_default
        rel_override = st.sidebar.text_input(
            "Custom relative subdir",
            value=custom_rel_default,
            key="datadir_rel_custom",
        ).strip()
        if rel_override:
            rel_subdir = rel_override
    else:
        st.session_state.pop("datadir_rel_custom", None)
    st.session_state["datadir_rel"] = rel_subdir

    # Persist selection for reloads / share links
    try:
        st.query_params["base_dir_choice"] = base_choice
        st.query_params["input_datadir"] = st.session_state.get("input_datadir", "") if base_choice == "Custom" else ""
        st.query_params["datadir_rel"] = rel_subdir
    except Exception:
        pass

    final_path = (base_path / rel_subdir).expanduser() if rel_subdir else base_path.expanduser()
    if base_choice == "AGILAB_EXPORT":
        final_path.mkdir(parents=True, exist_ok=True)
    elif not final_path.exists():
        st.sidebar.info(f"{final_path} does not exist yet.")
    prev_datadir = Path(st.session_state.get("datadir", final_path)).expanduser()
    if "datadir" not in st.session_state:
        st.session_state.datadir = final_path
    elif prev_datadir != final_path:
        st.session_state.datadir = final_path
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
    new_vm_settings = {
        "base_dir_choice": st.session_state.get("base_dir_choice", "AGILAB_EXPORT"),
        "input_datadir": st.session_state.get("input_datadir", ""),
        "datadir_rel": st.session_state.get("datadir_rel", ""),
        "file_ext_choice": st.session_state.get("file_ext_choice", "all"),
        "id_col": st.session_state.get("id_col", st.session_state.get("flight_id_col", "")),
        "time_col": st.session_state.get("time_col", ""),
        "link_multiselect": st.session_state.get("link_multiselect", []),
        "show_map": st.session_state.get("show_map", True),
        "show_graph": st.session_state.get("show_graph", True),
        "show_metrics": st.session_state.get("show_metrics", False),
        "df_file": st.session_state.get("df_file", ""),
        "df_select_mode": st.session_state.get("df_select_mode", "Single file"),
        "df_file_regex": st.session_state.get("df_file_regex", ""),
        "df_files": st.session_state.get("df_files", []),
    }
    vm_mutated = False
    for key, value in new_vm_settings.items():
        if vm_settings.get(key) != value:
            vm_settings[key] = value
            vm_mutated = True
    if vm_mutated:
        _persist_app_settings(env)

    datadir_path = Path(st.session_state.datadir).expanduser()
    def _visible_only(paths):
        visible = []
        for path in paths:
            try:
                rel_parts = path.relative_to(datadir_path).parts
            except ValueError:
                rel_parts = path.parts
            if any(part.startswith(".") for part in rel_parts):
                continue
            visible.append(path)
        return visible

    if ext_choice == "all":
        files = (
            list(datadir_path.rglob("*.csv"))
            + list(datadir_path.rglob("*.parquet"))
            + list(datadir_path.rglob("*.json"))
        )
    else:
        files = list(datadir_path.rglob(f"*.{ext_choice}"))
    files = _visible_only(files)

    if not files:
        st.session_state.pop("csv_files", None)
        st.session_state.pop("df_file", None)
        st.session_state.pop("id_col", None)
        st.session_state.pop("flight_id_col", None)
        st.session_state.pop("time_col", None)
        st.warning(f"No files found under {datadir_path} (filter: {ext_choice}). Please choose a directory with data or export from Execute.")
        return

    # datadir may have changed via fallback; refresh path base
    datadir_path = Path(st.session_state.datadir).expanduser()
    st.session_state.csv_files = files

    csv_files_rel = sorted([Path(file).relative_to(datadir_path).as_posix() for file in st.session_state.csv_files])

    prev_files_rel = st.session_state.get("_prev_csv_files_rel")
    if prev_files_rel != csv_files_rel:
        # Prune stale selections when the file list changes.
        if st.session_state.get("df_file") not in csv_files_rel:
            st.session_state.pop("df_file", None)
        if isinstance(st.session_state.get("df_files"), list):
            st.session_state["df_files"] = [
                f for f in st.session_state["df_files"] if f in csv_files_rel
            ]

    df_mode_options = ["Single file", "Regex (multi)"]
    df_mode = st.sidebar.radio(
        "DataFrame selection",
        options=df_mode_options,
        index=df_mode_options.index(st.session_state.get("df_select_mode", df_mode_options[0]))
        if st.session_state.get("df_select_mode") in df_mode_options
        else 0,
        key="df_select_mode",
    )

    selected_files_rel: list[str] = []
    if df_mode == "Regex (multi)":
        regex_raw = st.sidebar.text_input(
            "DataFrame filename regex",
            value=st.session_state.get("df_file_regex", ""),
            key="df_file_regex",
            help="Python regex applied to the relative file path. Leave empty to match all files.",
        ).strip()
        regex_ok = True
        pattern = None
        if regex_raw:
            try:
                pattern = re.compile(regex_raw)
            except re.error as exc:
                regex_ok = False
                st.sidebar.error(f"Invalid regex: {exc}")
        matching = (
            [f for f in csv_files_rel if pattern.search(f)]
            if (regex_ok and pattern is not None)
            else (csv_files_rel if not regex_raw else [])
        )
        st.sidebar.caption(f"{len(matching)} / {len(csv_files_rel)} files match")
        if st.sidebar.button(
            f"Select all matching ({len(matching)})",
            disabled=not matching,
            key="df_regex_select_all",
        ):
            st.session_state["df_files"] = matching

        if "df_files" not in st.session_state:
            # Preserve the current single-file selection when switching modes.
            seed = st.session_state.get("df_file")
            if seed in csv_files_rel:
                st.session_state["df_files"] = [seed]
            else:
                st.session_state["df_files"] = [csv_files_rel[0]] if csv_files_rel else []

        st.sidebar.multiselect(
            label="DataFrames",
            options=csv_files_rel,
            key="df_files",
        )
        if isinstance(st.session_state.get("df_files"), list):
            selected_files_rel = [f for f in st.session_state["df_files"] if f in csv_files_rel]
            st.session_state["df_files"] = selected_files_rel
        st.sidebar.caption(f"{len(selected_files_rel)} selected")
        if selected_files_rel:
            st.session_state["df_file"] = selected_files_rel[0]
    else:
        if csv_files_rel and st.session_state.get("df_file") not in csv_files_rel:
            st.session_state["df_file"] = csv_files_rel[0]
        st.sidebar.selectbox(
            label="DataFrame",
            options=csv_files_rel,
            key="df_file",
            index=csv_files_rel.index(st.session_state.df_file)
            if "df_file" in st.session_state and st.session_state.df_file in csv_files_rel
            else 0,
        )
        if st.session_state.get("df_file"):
            selected_files_rel = [st.session_state.get("df_file")]

    selection_sig = (df_mode, tuple(selected_files_rel))
    if st.session_state.get("_prev_df_selection_sig") != selection_sig:
        st.session_state.pop("loaded_df", None)
        st.session_state.pop("id_col", None)
        st.session_state.pop("flight_id_col", None)
        st.session_state.pop("time_col", None)
        st.session_state["_prev_df_selection_sig"] = selection_sig
    st.session_state["_prev_csv_files_rel"] = csv_files_rel

    if not selected_files_rel:
        st.warning("Please select at least one dataset to proceed.")
        return

    df_paths_abs = [datadir_path / rel for rel in selected_files_rel]
    try:
        frames: list[pd.DataFrame] = []
        load_errors: list[str] = []
        for rel, abs_path in zip(selected_files_rel, df_paths_abs):
            cache_buster = None
            try:
                cache_buster = abs_path.stat().st_mtime
            except Exception:
                pass
            try:
                loaded = load_df(abs_path, with_index=True, cache_buster=cache_buster)
            except Exception as exc:
                load_errors.append(f"{rel}: {exc}")
                continue
            if loaded is None:
                load_errors.append(f"{rel}: returned None")
                continue
            if not isinstance(loaded, pd.DataFrame):
                load_errors.append(f"{rel}: unexpected type {type(loaded)}")
                continue
            loaded = loaded.copy()
            if "source_file" not in loaded.columns:
                loaded.insert(0, "source_file", rel)
            frames.append(loaded)

        if load_errors:
            st.sidebar.warning("Some selected files failed to load; continuing with the rest.")
            with st.sidebar.expander("Load errors", expanded=False):
                for err in load_errors[:50]:
                    st.write(err)
                if len(load_errors) > 50:
                    st.write(f"... ({len(load_errors) - 50} more)")

        if not frames:
            st.error("No selected dataframes could be loaded.")
            return

        st.session_state.loaded_df = frames[0] if len(frames) == 1 else pd.concat(frames, ignore_index=True)
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

    # Migrate legacy state key
    if "flight_id_col" in st.session_state and "id_col" not in st.session_state:
        st.session_state["id_col"] = st.session_state.pop("flight_id_col")

    st.sidebar.markdown("### Columns")
    all_cols = list(df.columns)
    lower_map = {c.lower(): c for c in all_cols}
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

    def _pick_col(preferred: list[str], fallback_exclude: list[str]) -> str:
        for key in preferred:
            if key in all_cols:
                return key
            if key.lower() in lower_map:
                return lower_map[key.lower()]
        # fallback to first column not excluded
        for c in all_cols:
            if c not in fallback_exclude and c.lower() not in {v.lower() for v in fallback_exclude}:
                return c
        return all_cols[0] if all_cols else ""

    if st.session_state.get("id_col") not in all_cols:
        st.session_state["id_col"] = _pick_col(id_pref, time_pref)
    if st.session_state.get("time_col") not in all_cols:
        st.session_state["time_col"] = _pick_col(time_pref, id_pref)

    # With session state primed above, avoid passing index/defaults to prevent Streamlit warnings
    flight_col = st.sidebar.selectbox(
        "ID column",
        options=all_cols,
        key="id_col",
    )
    time_col = st.sidebar.selectbox(
        "Timestamp column",
        options=all_cols,
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
    df_std["id_col"] = df_std["id_col"].astype(str)
    if "flight_id" not in df_std.columns:
        df_std["flight_id"] = df_std["id_col"]
    else:
        df_std["flight_id"] = df_std["flight_id"].astype(str)
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
    default_edges_candidates = _candidate_edges_paths(
        [
            env.share_root_path(),
            env.AGILAB_EXPORT_ABS,
            Path(st.session_state.datadir),
            env.share_root_path() / "example_app" / "dataframe",
            env.share_root_path() / "example_app" / "dataframe",
        ]
    )
    example_edges_path = str(env.share_root_path() / "example_app/pipeline/routing_edges.jsonl")
    edges_placeholder = f"e.g. {example_edges_path}"
    edges_file = st.sidebar.text_input(
        "Edges file (optional, JSON/Parquet with source/target/bearer)",
        value=st.session_state.get("edges_file_input", ""),
        placeholder=edges_placeholder,
        key="edges_file_input",
    )
    if default_edges_candidates:
        detected_opt = ["(none)"] + [str(p) for p in default_edges_candidates]
        detected_choice = st.sidebar.selectbox("Detected edges files", detected_opt, index=0, key="edges_detected_select")
        if detected_choice != "(none)":
            st.session_state["edges_file_input"] = detected_choice
            edges_file = detected_choice
    edges_clean = edges_file.strip()
    if edges_clean == example_edges_path and not Path(edges_clean).expanduser().exists():
        edges_clean = ""
        st.session_state["edges_file_input"] = ""
    edges_path = Path(edges_clean).expanduser() if edges_clean else None
    loaded_edges = {}
    if edges_path and edges_path.exists():
        loaded_edges = load_edges_file(edges_path)
        if not loaded_edges:
            st.sidebar.info(
                "Edges file loaded but no valid 'source/target/bearer' rows were detected. "
                "Ensure the file includes those columns."
            )
    if edges_clean and edges_path and not edges_path.exists():
        st.sidebar.warning(f"Edges file not found: {edges_path}")

    link_options = _detect_link_columns(df_std)
    if loaded_edges:
        for col, edges in loaded_edges.items():
            df_std[col] = [edges] * len(df_std)
            df[col] = df_std[col]
            if col not in link_options:
                link_options.append(col)
    link_options = list(dict.fromkeys(link_options))
    link_color_map = {**link_colors_plotly}
    for idx, col in enumerate(link_options):
        link_color_map.setdefault(col, f"C{idx}")
    link_default = st.session_state.get("link_multiselect")
    if not link_default:
        present_defaults = [c for c in _DEFAULT_LINK_ORDER if c in link_options]
        link_default = present_defaults if present_defaults else link_options[:4]
    selected_links = st.sidebar.multiselect(
        "Link columns",
        options=link_options,
        default=link_default,
        key="link_multiselect",
    )
    show_map = st.sidebar.checkbox("Show map view", value=st.session_state.get("show_map", True), key="show_map")
    show_graph = st.sidebar.checkbox("Show topology graph", value=st.session_state.get("show_graph", True), key="show_graph")
    jitter_overlap = st.sidebar.checkbox("Separate overlapping nodes", value=False, key="jitter_overlap")
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

    # Ensure link columns exist to avoid KeyError
    for col in link_options:
        if col not in df:
            df[col] = None
        if col not in df_std:
            df_std[col] = None

    if jitter_overlap:
        dup_mask = df_std.duplicated(subset=["long", "lat"], keep=False)
        if dup_mask.any():
            jitter_scale = max(1e-5, float(df_std[dup_mask]["lat"].std() or 0.0) * 0.01) or 1e-3
            noise = np.random.default_rng(42).normal(loc=0.0, scale=jitter_scale, size=(dup_mask.sum(), 2))
            df_std.loc[dup_mask, ["long", "lat"]] += noise

    for col in ["bandwidth", "throughput"]:
        if col in df:
            df[col] = df[col].apply(safe_literal_eval)
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
    # Initialize selected time once; keep user choice on reruns
    if "selected_time" not in st.session_state or st.session_state.selected_time not in unique_timestamps:
        # Default to the latest timestamp so all nodes (flights/satellites) are visible initially.
        st.session_state.selected_time = unique_timestamps[-1]
    # Track index explicitly to avoid equality drift with numpy types
    if "selected_time_idx" not in st.session_state or st.session_state.selected_time not in unique_timestamps:
        st.session_state.selected_time_idx = (
            unique_timestamps.index(st.session_state.selected_time)
            if st.session_state.selected_time in unique_timestamps
            else len(unique_timestamps) - 1
        )

    # Time controls
    with st.container():
        cola, colb, colc = st.columns([0.3, 7.5, 0.6])
        with cola:
            if st.button("◁", key="decrement_button"):
                decrement_time(unique_timestamps)
        with colb:
            selected_val = st.select_slider(
                "Time",
                options=unique_timestamps,
                value=st.session_state.selected_time,
                format_func=lambda x: x.strftime("%Y-%m-%d %H:%M:%S") if hasattr(x, "strftime") else str(x),
                key="time_slider_control",
            )
            st.session_state.selected_time = selected_val
            st.caption(f"Selected: {st.session_state.selected_time}")
            idx_now = st.session_state.get("selected_time_idx", len(unique_timestamps) - 1)
            prog = idx_now / (len(unique_timestamps) - 1) if len(unique_timestamps) > 1 else 1.0
            st.progress(prog)
            if st.session_state.selected_time in unique_timestamps:
                st.session_state.selected_time_idx = unique_timestamps.index(st.session_state.selected_time)
        with colc:
            if st.button("▷", key="increment_button"):
                increment_time(unique_timestamps)

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
    df_positions_std["id_col"] = df_positions_std["id_col"].astype(str)
    if "flight_id" not in df_positions_std.columns:
        df_positions_std["flight_id"] = df_positions_std["id_col"]
    else:
        df_positions_std["flight_id"] = df_positions_std["flight_id"].astype(str)
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
    current_positions["flight_id"] = current_positions["flight_id"].astype(str)

    if current_positions.empty:
        st.warning("No data available for the selected time.")
        st.stop()

    if "color_map" not in st.session_state or st.session_state.get("color_map_key") != flight_col:
        flight_ids = df_std["id_col"].astype(str).unique()
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
            layers = create_layers_geomap(selected_links, df_positions_std, current_positions, link_color_map)
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
                link_color_map=link_color_map,
            )
            st.plotly_chart(fig, use_container_width=True)

    if show_metrics:
        metric_cols = [c for c in [flight_col, time_col, "bearer_type", "throughput", "bandwidth"] if c in df_positions.columns]
        if metric_cols:
            st.markdown("### Metrics snapshot")
            st.dataframe(df_positions[metric_cols].sort_values(flight_col), use_container_width=True)

    # Live allocations overlay (routing/ILP trainers)
    st.markdown("### 📡 Live allocations (routing/ILP)")
    alloc_root = env.share_root_path()
    alloc_candidates = [
        alloc_root / "example_app/pipeline/trainer_routing/allocations_steps.parquet",
        alloc_root / "example_app/dataframe/trainer_routing/allocations_steps.parquet",
    ]
    alloc_path_default = next((p for p in alloc_candidates if p.exists()), alloc_candidates[0])
    alloc_path = st.text_input(
        "Allocations file (JSON or Parquet)",
        value=str(alloc_path_default),
        key="alloc_path_input",
    ).strip()
    alloc_path_obj = Path(alloc_path).expanduser()
    if not alloc_path_obj.exists():
        fallback_alloc = _find_latest_allocations(alloc_root / "example_app")
        if fallback_alloc:
            st.info(f"Allocations file not found, using latest detected: {fallback_alloc}")
            alloc_path_obj = fallback_alloc
            st.session_state["alloc_path_input"] = str(fallback_alloc)
        else:
            st.info("No allocations found at the specified path.")
    baseline_candidates = [
        alloc_root / "example_app/pipeline/trainer_ilp_stepper/allocations_steps.parquet",
        alloc_root / "example_app/dataframe/trainer_ilp_stepper/allocations_steps.parquet",
        alloc_root / "example_app/pipeline/trainer_ilp_stepper/allocations_steps.json",
    ]
    baseline_default = next((p for p in baseline_candidates if p.exists()), baseline_candidates[0])
    baseline_path_input = st.text_input(
        "Baseline (ILP) allocations file (optional)",
        value=str(baseline_default),
        key="baseline_alloc_path_input",
    ).strip()
    baseline_path_obj = Path(baseline_path_input).expanduser()
    if baseline_path_obj and not baseline_path_obj.exists():
        fallback_base = _find_latest_allocations(alloc_root / "example_app")
        if fallback_base and "ilp" in fallback_base.name.lower():
            st.info(f"Baseline file not found, using detected baseline: {fallback_base}")
            baseline_path_obj = fallback_base
            st.session_state["baseline_alloc_path_input"] = str(fallback_base)
    traj_glob_default = env.share_root_path() / "example_app/dataframe/flight_simulation/*.parquet"
    traj_glob = st.text_input(
        "Trajectory glob",
        value=str(traj_glob_default),
        key="traj_glob_input",
    )
    alloc_df = load_allocations(alloc_path_obj)
    baseline_df = load_allocations(baseline_path_obj) if baseline_path_obj.exists() else pd.DataFrame()
    if alloc_df.empty:
        st.info("No allocations found at the specified path.")
    else:
        times = sorted(alloc_df["time_index"].unique())
        t_sel = st.slider("Time index", min_value=int(min(times)), max_value=int(max(times)), value=int(min(times)))
        alloc_step = alloc_df[alloc_df["time_index"] == t_sel]
        baseline_step = baseline_df[baseline_df["time_index"] == t_sel] if not baseline_df.empty else pd.DataFrame()
        positions_live = load_positions_at_time(traj_glob, t_sel)
        st.dataframe(alloc_step)
        if not baseline_step.empty:
            st.caption("Baseline (ILP) allocations at the same timestep")
            st.dataframe(baseline_step)
            try:
                merged = alloc_step.merge(
                    baseline_step,
                    on=["source", "destination", "time_index"],
                    how="outer",
                    suffixes=("_rl", "_ilp"),
                )
                if not merged.empty:
                    merged["delivered_delta"] = merged.get("delivered_bandwidth_rl", np.nan) - merged.get("delivered_bandwidth_ilp", np.nan)
                    st.caption("RL vs ILP (delta delivered_bandwidth)")
                    st.dataframe(merged[["source", "destination", "time_index", "delivered_bandwidth_rl", "delivered_bandwidth_ilp", "delivered_delta"]])
            except Exception:
                st.info("Unable to compute RL vs ILP diff; showing raw tables instead.")
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
        if not baseline_step.empty:
            layers_live.extend(build_allocation_layers(baseline_step, positions_live, color=[0, 180, 255]))
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
