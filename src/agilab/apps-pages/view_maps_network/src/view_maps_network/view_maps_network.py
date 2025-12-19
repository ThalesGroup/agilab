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
from urllib.parse import quote, urlencode
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
from typing import Any, Optional
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

def _svg_data_url(svg: str) -> str:
    return "data:image/svg+xml;charset=utf-8," + quote(svg.strip())

# IconLayer expects raster images; keep a small embedded PNG for reliability.
_PLANE_ICON_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAABE0lEQVR42u2YQQ6DMAwEMcqfmv+f6KvcQ0GqEJVIiGNDxkcOgZ2dQMQ0+c/iefN5YnzbV1X1tAADvNvfxssCDIjQvqcFGBClfS8LMCBS+x4WDG8AWyCa/r23AQZEbL+nBRgQtf1eFmBA5PZ7WIAB0du3tmC+2Z/e5uuKxYOp6stKKxF57y5lDwDdAlsDkZrQnoELgeQrAMK0bGmHPClwDRDZgj8x8Bkgsn6vhwvPSRAA30mWL5qWW8tq3dTwjbr/1Fgch/N678O1a8CkC2Gzo7n5z3MupVBSYavRJ5+B8gsm7YLfJWgzW9JDQ58GwzkAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABglPkADvzdm7Xeo4UAAAAASUVORK5CYII="
)

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
    known_relative = (
        Path("pipeline/flows/topology.json"),
        Path("pipeline/topology.gml"),
        Path("pipeline/ilp_topology.gml"),
        Path("pipeline/routing_edges.jsonl"),
    )
    patterns = (
        # Common routing exports
        "routing_edges.jsonl",
        "routing_edges.ndjson",
        "routing_edges.json",
        "routing_edges.parquet",
        # Generic edge exports
        "edges.parquet",
        "edges.json",
        "edges.jsonl",
        "edges.ndjson",
        "edges.*.parquet",
        "edges.*.json",
        "edges.*.jsonl",
        "edges.*.ndjson",
        # Common topology exports (GML-format files often named .json)
        "topology.json",
        "topology.gml",
        "ilp_topology.gml",
    )
    for base in bases:
        if not base or not base.exists():
            continue
        # Fast path: check known default locations (avoids expensive globbing on large shares).
        for rel in known_relative:
            p = (base / rel).expanduser()
            if p.exists() and p.is_file() and p not in seen:
                if not any(part.startswith(".") for part in p.parts):
                    seen.add(p)
                    candidates.append(p)
        for pattern in patterns:
            for p in base.glob(f"**/{pattern}"):
                if p in seen:
                    continue
                if any(part.startswith(".") for part in p.parts):
                    continue
                seen.add(p)
                candidates.append(p)
    candidates.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)
    return candidates

def _quick_share_edges_paths(share_root: Path) -> list[Path]:
    seen: set[Path] = set()
    candidates: list[Path] = []
    known_relative = (
        Path("pipeline/flows/topology.json"),
        Path("pipeline/topology.gml"),
        Path("pipeline/ilp_topology.gml"),
        Path("pipeline/routing_edges.jsonl"),
        Path("pipeline/routing_edges.parquet"),
        Path("pipeline/edges.parquet"),
        Path("pipeline/edges.json"),
        Path("pipeline/edges.jsonl"),
        Path("pipeline/edges.ndjson"),
        Path("pipeline/topology.json"),
        Path("pipeline/ilp_topology.json"),
    )
    if not share_root.exists():
        return []
    roots = [share_root]
    try:
        roots.extend(
            [
                entry
                for entry in sorted(share_root.iterdir())
                if entry.is_dir() and not entry.name.startswith(".")
            ]
        )
    except Exception:
        roots = [share_root]
    for root in roots:
        for rel in known_relative:
            p = (root / rel).expanduser()
            if p.exists() and p.is_file():
                try:
                    resolved = p.resolve(strict=False)
                except Exception:
                    resolved = p
                if resolved in seen:
                    continue
                seen.add(resolved)
                candidates.append(p)
    candidates.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)
    return candidates


def _quick_share_traj_globs(share_root: Path) -> list[str]:
    share_root = share_root.expanduser()
    candidates = [
        str(share_root / "flight_trajectory" / "pipeline" / "*.parquet"),
        str(share_root / "flight_trajectory" / "pipeline" / "*.csv"),
        str(share_root / "sat_trajectory" / "pipeline" / "*.parquet"),
        str(share_root / "sat_trajectory" / "pipeline" / "*.csv"),
        str(share_root / "*_trajectory" / "pipeline" / "*.parquet"),
        str(share_root / "*_trajectory" / "pipeline" / "*.csv"),
    ]
    return [c for c in candidates if glob.glob(str(Path(c).expanduser()))]


def _normalize_node_id_series(series: pd.Series) -> pd.Series:
    """Normalize node IDs for consistent matching and drop invalid placeholders."""
    raw = series.copy()
    num = pd.to_numeric(raw, errors="coerce")
    out = raw.astype("string").fillna("").astype(str).str.strip()
    mask_int = num.notna() & np.isclose(num % 1, 0.0)
    if mask_int.any():
        out.loc[mask_int] = num.loc[mask_int].round().astype(int).astype(str)
    invalid = out.str.lower().isin({"", "nan", "none", "nat", "<na>"})
    out.loc[invalid] = ""
    return out


def _normalize_node_id_value(value: Any) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none", "nat", "<na>"}:
        return ""
    try:
        num = float(s)
        if np.isfinite(num) and np.isclose(num % 1, 0.0):
            return str(int(round(num)))
    except Exception:
        pass
    return s


def _candidate_node_ids(value: Any) -> list[str]:
    base = _normalize_node_id_value(value)
    if not base:
        return []
    candidates = [base]
    prefixes = ("plane_", "sat_", "uav_", "node_")
    lowered = base.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            stripped = _normalize_node_id_value(base[len(prefix) :])
            if stripped:
                candidates.append(stripped)
            break
    for prefix in prefixes:
        candidates.append(prefix + base)
    deduped: list[str] = []
    seen: set[str] = set()
    for cand in candidates:
        if cand and cand not in seen:
            seen.add(cand)
            deduped.append(cand)
    return deduped


def _resolve_node_id(value: Any, node_set: set[str]) -> str | None:
    for cand in _candidate_node_ids(value):
        if cand in node_set:
            return cand
    return None


def _preview_edge_count(df: pd.DataFrame, col: str) -> int:
    if col not in df.columns:
        return 0
    sample = None
    try:
        for v in df[col].head(50).tolist():
            if v is None:
                continue
            if isinstance(v, float) and np.isnan(v):
                continue
            if isinstance(v, str) and not v.strip():
                continue
            sample = v
            break
    except Exception:
        sample = None
    if sample is None:
        return 0
    try:
        return len(convert_to_tuples(sample))
    except Exception:
        return 0

def _candidate_allocation_paths(bases: list[Path]) -> list[Path]:
    seen = set()
    candidates: list[Path] = []
    known_relative = (
        Path("pipeline/allocations_steps.parquet"),
        Path("pipeline/allocations_steps.json"),
        Path("pipeline/allocations_steps.jsonl"),
        Path("dataframe/allocations_steps.parquet"),
        Path("dataframe/allocations_steps.json"),
        Path("dataframe/allocations_steps.jsonl"),
        Path("trainer_routing/allocations_steps.parquet"),
        Path("trainer_routing/allocations_steps.json"),
        Path("trainer_gnn/allocations_steps.parquet"),
        Path("trainer_gnn/allocations_steps.json"),
        Path("trainer_ilp_stepper/allocations_steps.parquet"),
        Path("trainer_ilp_stepper/allocations_steps.json"),
    )
    patterns = (
        "allocations_steps.parquet",
        "allocations_steps.json",
        "allocations_steps.jsonl",
        "allocations_steps.ndjson",
        "allocations*.parquet",
        "allocations*.json",
        "allocations*.jsonl",
        "allocations*.ndjson",
    )
    for base in bases:
        if not base or not base.exists():
            continue
        for rel in known_relative:
            p = (base / rel).expanduser()
            if p.exists() and p.is_file() and p not in seen:
                if not any(part.startswith(".") for part in p.parts):
                    seen.add(p)
                    candidates.append(p)
        for pattern in patterns:
            for p in base.glob(f"**/{pattern}"):
                if p in seen:
                    continue
                if any(part.startswith(".") for part in p.parts):
                    continue
                seen.add(p)
                candidates.append(p)
    candidates.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)
    return candidates

def _is_baseline_alloc_path(path: Path) -> bool:
    lowered = str(path).lower()
    return ("baseline" in lowered) or ("ilp" in lowered) or ("stepper" in lowered)


_RGB_LIKE_RE = re.compile(
    r"^rgba?\(\s*(?P<r>[-+]?\d*\.?\d+)\s*,\s*(?P<g>[-+]?\d*\.?\d+)\s*,\s*(?P<b>[-+]?\d*\.?\d+)\s*(?:,\s*(?P<a>[-+]?\d*\.?\d+)\s*)?\)$",
    flags=re.IGNORECASE,
)


def _parse_rgb_like(value: str) -> tuple[int, int, int, int] | None:
    """Parse css/plotly rgb()/rgba() strings into 0-255 RGBA ints."""
    if not isinstance(value, str):
        return None
    match = _RGB_LIKE_RE.match(value.strip())
    if not match:
        return None

    def _to_255(component: str) -> int:
        num = float(component)
        if num <= 1.0:
            num *= 255.0
        return int(max(0, min(255, round(num))))

    r = _to_255(match.group("r"))
    g = _to_255(match.group("g"))
    b = _to_255(match.group("b"))
    a_raw = match.group("a")
    if a_raw is None:
        a = 255
    else:
        a_num = float(a_raw)
        if a_num <= 1.0:
            a = int(max(0, min(255, round(a_num * 255.0))))
        else:
            a = int(max(0, min(255, round(a_num))))
    return r, g, b, a


def _color_to_rgb(color_str: str, idx: int = 0) -> list[int]:
    parsed = _parse_rgb_like(color_str)
    if parsed is not None:
        r, g, b, a = parsed
        return [r, g, b, a]
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
    if isinstance(color, str):
        parsed = _parse_rgb_like(color)
        if parsed is not None:
            r, g, b, a = parsed
            if a < 255:
                return f"rgba({r},{g},{b},{a / 255.0:.3f})"
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

def hex_to_rgba(hex_color):
    """Convert a hex color string (e.g. '#RRGGBB') into a deck.gl-compatible RGBA list."""
    if not isinstance(hex_color, str):
        return [136, 136, 136, 255]
    cleaned = hex_color.strip()
    if not cleaned:
        return [136, 136, 136, 255]
    cleaned = cleaned.lstrip("#")
    try:
        r, g, b = bytes.fromhex(cleaned[:6])
    except Exception:
        return [136, 136, 136, 255]
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
    node_set = set(current_positions["flight_id"].astype(str).tolist())
    for _, row in link_edges.iterrows():
        links = row[link_column]
        if links is not None:
            if isinstance(links, tuple):
                links = [links]
            for source, target in links:
                source_id = _resolve_node_id(source, node_set)
                target_id = _resolve_node_id(target, node_set)
                if not source_id or not target_id:
                    continue
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

def create_layers_geomap(selected_links, df, current_positions, link_color_map, *, marker_style: str = "Dots"):
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

    marker_style_norm = (marker_style or "Dots").strip().lower()
    if marker_style_norm.startswith("plane"):
        nodes_df = current_positions.copy()
        angle_col = None
        for candidate in ("bearing_deg", "bearing", "heading_deg", "heading", "yaw_deg", "yaw"):
            if candidate in nodes_df.columns:
                angle_col = candidate
                break
        if angle_col:
            nodes_df["_angle"] = pd.to_numeric(nodes_df[angle_col], errors="coerce").fillna(0.0)
            get_angle = "_angle"
        else:
            get_angle = 0
        nodes_df["icon_data"] = [
            {
                "url": _PLANE_ICON_URL,
                "width": 64,
                "height": 64,
                "anchorX": 32,
                "anchorY": 32,
                "mask": True,
            }
        ] * len(nodes_df)
        nodes_layer = pdk.Layer(
            "IconLayer",
            data=nodes_df,
            get_icon="icon_data",
            get_position="[long,lat]",
            get_color="color",
            get_angle=get_angle,
            get_size=22,
            size_units="pixels",
            size_scale=1,
            billboard=True,
            auto_highlight=True,
            pickable=True,
            parameters={"depthTest": False},
        )
    else:
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
                t_now_s = step.get("t_now_s")
                if t_now_s is None:
                    t_now_s = step.get("time_s", step.get("t"))
                for alloc in step.get("allocations", []):
                    row = dict(alloc)
                    row["time_index"] = t_idx
                    if t_now_s is not None:
                        row["t_now_s"] = t_now_s
                    rows.append(row)
            return pd.DataFrame(rows)
        elif isinstance(data, dict):
            return pd.DataFrame([data])
    except Exception:
        return pd.DataFrame()
    return pd.DataFrame()


def _nearest_row(df: pd.DataFrame, t: float, time_col: str = "time_s") -> pd.DataFrame:
    if df.empty or time_col not in df.columns:
        return df
    series = pd.to_numeric(df[time_col], errors="coerce")
    if series.dropna().empty:
        return df.iloc[0:0]
    idx = (series - t).abs().idxmin()
    return df.loc[[idx]]


def _find_latest_allocations(base: Path, include: tuple[str, ...] = ()) -> Path | None:
    """Locate the most recent allocations file under a given base."""
    candidates: list[Path] = []
    for pattern in ("allocations*.parquet", "allocations*.json", "allocations*.jsonl", "allocations_steps.parquet"):
        candidates.extend(base.rglob(pattern))
    if not candidates:
        return None
    candidates = [p for p in candidates if p.is_file()]
    if include:
        lowered = [token.lower() for token in include if token]
        if lowered:
            candidates = [p for p in candidates if all(token in str(p).lower() for token in lowered)]
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
        df = None
    # Allow case-insensitive / synonym column names
    if df is not None:
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
            df = None

    if df is None:
        # Fallback: some exporters write GML (graph [ ... ]) even when the extension is .json.
        try:
            graph = nx.read_gml(path)
        except Exception:
            return {}

        edges_by_type: dict[str, list[tuple[int, int]]] = {}
        for u, v, attrs in graph.edges(data=True):
            bearer_raw = (
                attrs.get("bearer")
                or attrs.get("bearer_type")
                or attrs.get("link_type")
                or attrs.get("type")
                or attrs.get("link")
            )
            bearer = str(bearer_raw or "").strip().lower()
            if not bearer:
                bearer = "link"
            if "sat" in bearer:
                key = "satcom_link"
            elif "opt" in bearer:
                key = "optical_link"
            elif "legacy" in bearer or bearer == "leg":
                key = "legacy_link"
            elif "iv" in bearer:
                key = "ivbl_link"
            else:
                key = bearer.replace(" ", "_")
            edges_by_type.setdefault(key, []).append((str(u), str(v)))
        return {k: v for k, v in edges_by_type.items() if v}

    edges_by_type: dict[str, list[tuple[int, int]]] = {k: [] for k in _DEFAULT_LINK_ORDER}
    for _, row in df.iterrows():
        try:
            u = str(row[source_col])  # type: ignore[index]
            v = str(row[target_col])  # type: ignore[index]
            bearer_raw = str(row[bearer_col]).strip()  # type: ignore[index]
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
    return {k: v for k, v in edges_by_type.items() if v}

def load_positions_at_time(traj_glob: str, t: float) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    patterns = [p.strip() for p in re.split(r"[,\n;]+", traj_glob or "") if p.strip()]
    if not patterns:
        return pd.DataFrame()

    for pattern in patterns:
        for fname in glob.glob(str(Path(pattern).expanduser())):
            df = _load_traj_file(fname)
            if df.empty:
                continue
            col_map = {c.lower(): c for c in df.columns}
            time_col = (
                col_map.get("time_s")
                or col_map.get("t_now_s")
                or col_map.get("time")
                or col_map.get("t")
                or col_map.get("time_index")
            )
            lat_col = col_map.get("latitude") or col_map.get("lat")
            lon_col = col_map.get("longitude") or col_map.get("lon") or col_map.get("long")
            alt_col = (
                col_map.get("alt_m")
                or col_map.get("altitude_m")
                or col_map.get("altitude")
                or col_map.get("alt")
            )
            if not (time_col and lat_col and lon_col):
                continue
            closest = _nearest_row(df, t, time_col=time_col)
            if closest.empty:
                continue
            row = closest.iloc[0]

            flight_id = None
            for id_key in (
                "plane_id",
                "satellite_id",
                "sat_id",
                "uav_id",
                "trajectory_id",
                "node_id",
                "flight_id",
                "id",
                "callsign",
                "call_sign",
            ):
                id_col = col_map.get(id_key)
                if not id_col:
                    continue
                raw_id = row.get(id_col)
                if pd.isna(raw_id):
                    continue
                try:
                    flight_id = str(int(raw_id))
                except Exception:
                    flight_id = str(raw_id)
                break
            if not flight_id:
                flight_id = Path(fname).stem

            records.append(
                {
                    "flight_id": str(flight_id),
                    "time_s": row.get(time_col, t),
                    "lat": row.get(lat_col),
                    "long": row.get(lon_col),
                    "alt": row.get(alt_col, 0.0) if alt_col else 0.0,
                }
            )
    return pd.DataFrame(records)


@st.cache_data(show_spinner=False)
def _load_traj_file(path_str: str) -> pd.DataFrame:
    p = Path(path_str).expanduser()
    if not p.exists():
        return pd.DataFrame()
    if p.suffix.lower() in {".parquet", ".pq", ".parq"}:
        try:
            return pd.read_parquet(p)
        except Exception:
            return pd.DataFrame()
    try:
        return pd.read_csv(p, encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return pd.read_csv(p, encoding="latin-1")
        except Exception:
            return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

def build_allocation_layers(alloc_df: pd.DataFrame, positions: pd.DataFrame, *, color=None):
    if alloc_df.empty or positions.empty:
        return []
    positions_idx = positions.copy()
    positions_idx["flight_id"] = positions_idx["flight_id"].astype(str)

    def _lookup_position(node_id: Any) -> pd.Series | None:
        node_str = str(node_id)
        for cand in (f"plane_{node_str}", node_str, f"sat_{node_str}"):
            match = positions_idx.loc[positions_idx["flight_id"] == cand]
            if not match.empty:
                return match.iloc[0]
        return None

    def _as_list(value: Any) -> list[Any]:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, str):
            parsed = safe_literal_eval(value)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, tuple):
                return list(parsed)
        return []

    def _blend(rgb: list[int], tint: list[int] | None, *, alpha: float = 0.45) -> list[int]:
        if tint is None:
            return rgb
        return [int(round((1 - alpha) * rgb[i] + alpha * tint[i])) for i in range(3)]

    def _bearer_rgb(bearer: Any) -> list[int]:
        b = str(bearer or "").strip().lower()
        if "sat" in b:
            return _blend([0, 120, 255], color)
        if "iv" in b:
            return _blend([255, 140, 0], color)
        if "opt" in b:
            return _blend([0, 180, 90], color)
        if "legacy" in b:
            return _blend([160, 160, 160], color)
        if color is not None:
            return color
        return [200, 200, 200]

    edges = []
    for _, row in alloc_df.iterrows():
        src = row.get("source")
        dst = row.get("destination")
        delivered = row.get("delivered_bandwidth", row.get("capacity_mbps", 0))
        bandwidth = row.get("bandwidth", 0)
        path_edges = _as_list(row.get("path"))
        path_bearers = _as_list(row.get("bearers")) or _as_list(row.get("bearer"))

        if path_edges:
            for i, hop in enumerate(path_edges):
                hop_list = _as_list(hop)
                if len(hop_list) < 2:
                    continue
                u = hop_list[0]
                v = hop_list[1]
                u_pos = _lookup_position(u)
                v_pos = _lookup_position(v)
                if u_pos is None or v_pos is None:
                    continue
                bearer = path_bearers[i] if i < len(path_bearers) else row.get("bearer")
                edges.append(
                    {
                        "source": [u_pos["long"], u_pos["lat"], u_pos.get("alt", 0.0)],
                        "target": [v_pos["long"], v_pos["lat"], v_pos.get("alt", 0.0)],
                        "bandwidth": bandwidth,
                        "delivered": delivered,
                        "bearer": bearer,
                        "color": _bearer_rgb(bearer),
                        "demand": f"{src}→{dst}",
                    }
                )
        else:
            src_pos = _lookup_position(src)
            dst_pos = _lookup_position(dst)
            if src_pos is None or dst_pos is None:
                continue
            edges.append(
                {
                    "source": [src_pos["long"], src_pos["lat"], src_pos.get("alt", 0.0)],
                    "target": [dst_pos["long"], dst_pos["lat"], dst_pos.get("alt", 0.0)],
                    "bandwidth": bandwidth,
                    "delivered": delivered,
                    "bearer": row.get("bearer"),
                    "color": _bearer_rgb(row.get("bearer")),
                    "demand": f"{src}→{dst}",
                }
            )

    if not edges:
        return []

    edge_df = pd.DataFrame(edges)
    width_norm = pd.to_numeric(edge_df["delivered"], errors="coerce").fillna(0)
    if not width_norm.empty and width_norm.max() > 0:
        edge_df["width"] = 2 + 8 * (width_norm / width_norm.max())
    else:
        edge_df["width"] = 2

    return [
        pdk.Layer(
            "LineLayer",
            data=edge_df,
            get_source_position="source",
            get_target_position="target",
            get_color="color",
            get_width="width",
            opacity=0.85,
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
    node_set = set(map(str, pos.keys()))
    edges = filter_edges(df, edge_types)
    for edge_type, tuples in edges.items():
        for (u, v) in tuples:
            uu = _resolve_node_id(u, node_set)
            vv = _resolve_node_id(v, node_set)
            if uu is None or vv is None or uu == vv:
                continue
            if uu in pos and vv in pos:
                G.add_edge(uu, vv, type=edge_type, label=f"{uu}->{vv}")

    edge_traces = []
    normalized_metrics = {}
    if metric_type in ["bandwidth", "throughput"]:
        metrics = extract_metrics(df, metric_type)
        normalized_metrics = {et: normalize_values(metrics.get(et, [])) for et in edge_types}
    else:
        normalized_metrics = {et: [] for et in edge_types}

    for edge_type in edge_types:
        link_index = 0
        legend_added = False
        label = _label_for_link(edge_type)
        edge_color = _to_plotly_color((link_color_map or link_colors_plotly).get(edge_type, "#888"))
        for u, v, data in G.edges(data=True):
            if data.get("type") != edge_type:
                continue
            x0, y0 = pos[u]
            x1, y1 = pos[v]
            x_bezier, y_bezier = bezier_curve(x0, y0, x1, y1)
            edge_x = list(x_bezier) + [None]
            edge_y = list(y_bezier) + [None]
            normalized_value = (
                normalized_metrics.get(edge_type, [5])[link_index]
                if link_index < len(normalized_metrics.get(edge_type, []))
                else 5
            )
            link_index += 1
            edge_width = normalized_value if normalized_value is not None else 5
            hover_text = f"Link {u}->{v}<br>Type: {label}<br>Normalized Capacity: {normalized_value}"
            edge_texts = [hover_text] * len(x_bezier) + [None]
            edge_traces.append(
                go.Scatter(
                    x=edge_x,
                    y=edge_y,
                    line=dict(width=edge_width, color=edge_color),
                    hoverinfo="text",
                    text=edge_texts,
                    mode="lines",
                    name=label,
                    showlegend=not legend_added,
                    opacity=1.0,
                )
            )
            legend_added = True

            # Edge label at midpoint (type label)
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            edge_traces.append(
                go.Scatter(
                    x=[mx],
                    y=[my],
                    mode="text",
                    text=[label],
                    textfont=dict(color=edge_color, size=12),
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

    symbol_labels = {
        "triangle-up": "Satellite",
        "circle": "Aircraft",
        "square": "HRC",
        "diamond": "LRC",
    }
    used_symbols = sorted(set(node_symbols.values()), key=lambda s: str(s))
    symbol_legend_traces = [
        go.Scatter(
            x=[None],
            y=[None],
            mode="markers",
            marker=dict(color="#444", size=15, symbol=symbol),
            name=f"Type: {symbol_labels.get(symbol, symbol)}",
            showlegend=True,
        )
        for symbol in used_symbols
        if symbol in symbol_labels
    ]
    legend_traces = []
    for node, color in node_colors.items():
        legend_traces.append(go.Scatter(
            x=[None],
            y=[None],
            mode="markers",
            marker=dict(color=color, size=15, line=dict(width=0), symbol=node_symbols.get(node, "circle")),
            name=f"Node: {node}",
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
        data=edge_traces + node_traces + symbol_legend_traces + legend_traces,
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

def _shift_selected_time(delta: int) -> None:
    """Adjust the current selected time by +/- 1 without mutating widget state mid-run."""
    unique_timestamps = st.session_state.get("_time_options") or []
    if not unique_timestamps:
        return
    current = st.session_state.get("selected_time")
    try:
        current_index = unique_timestamps.index(current)
    except Exception:
        current_index = len(unique_timestamps) - 1
    new_index = max(0, min(current_index + int(delta), len(unique_timestamps) - 1))
    st.session_state["selected_time_idx"] = new_index
    st.session_state["selected_time"] = unique_timestamps[new_index]


def increment_time() -> None:
    _shift_selected_time(+1)


def decrement_time() -> None:
    _shift_selected_time(-1)

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
        "jitter_overlap",
        "show_metrics",
        "map_marker_style",
        "df_select_mode",
        "df_file_regex",
        "df_files",
        "edges_file",
        "allocations_file",
        "baseline_allocations_file",
        "traj_glob",
        "layout_type_select",
        "metric_type_select",
    ):
        if key in vm_settings and key not in st.session_state:
            st.session_state[key] = vm_settings[key]
    if "df_file" in vm_settings and "df_file" not in st.session_state:
        st.session_state["df_file"] = vm_settings["df_file"]

    qp_base = _read_query_param("base_dir_choice")
    qp_input = _read_query_param("input_datadir")
    qp_rel = _read_query_param("datadir_rel")
    qp_edges = _read_query_param("edges_file")
    if qp_edges is not None and qp_edges.strip():
        st.session_state["edges_file"] = qp_edges.strip()
    qp_alloc = _read_query_param("allocations_file")
    if qp_alloc is not None and qp_alloc.strip():
        st.session_state["allocations_file"] = qp_alloc.strip()
    qp_baseline = _read_query_param("baseline_allocations_file")
    if qp_baseline is not None and qp_baseline.strip():
        st.session_state["baseline_allocations_file"] = qp_baseline.strip()
    qp_traj = _read_query_param("traj_glob")
    if qp_traj is not None and qp_traj.strip():
        st.session_state["traj_glob"] = qp_traj.strip()
    qp_alloc_time = _read_query_param("alloc_time_index")
    if qp_alloc_time is not None and qp_alloc_time.strip():
        st.session_state["_alloc_time_index_qp"] = qp_alloc_time.strip()
    qp_alloc_pair = _read_query_param("alloc_pair")
    if qp_alloc_pair is not None and qp_alloc_pair.strip():
        st.session_state["_alloc_pair_qp"] = qp_alloc_pair.strip()

    # Data directory + presets (base paths without app suffix)
    export_base = env.AGILAB_EXPORT_ABS
    share_base = env.share_root_path()
    base_options = ["AGI_SHARE_DIR", "AGILAB_EXPORT", "Custom"]
    base_default = qp_base or st.session_state.get("base_dir_choice") or base_seed or "AGILAB_EXPORT"
    if base_default not in base_options:
        base_default = "AGILAB_EXPORT"
    if st.session_state.get("base_dir_choice") not in base_options:
        st.session_state["base_dir_choice"] = base_default
    base_choice = st.sidebar.radio(
        "Base directory",
        base_options,
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
        if not st.session_state.get("input_datadir"):
            st.session_state["input_datadir"] = custom_default
        custom_val = st.sidebar.text_input(
            "Custom data directory",
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
    if st.session_state.get("datadir_rel_select") not in subdir_options:
        st.session_state["datadir_rel_select"] = rel_default if rel_default in subdir_options else ""
    rel_subdir = st.sidebar.selectbox(
        "Relative subdir",
        options=subdir_options,
        key="datadir_rel_select",
        format_func=lambda v: v if v else "(root)",
    )
    if base_choice == "Custom":
        custom_rel_default = rel_subdir if rel_subdir else rel_default
        if "datadir_rel_custom" not in st.session_state:
            st.session_state["datadir_rel_custom"] = custom_rel_default
        rel_override = st.sidebar.text_input(
            "Custom relative subdir",
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
    if ext_default not in ext_options:
        ext_default = "all"
    if st.session_state.get("file_ext_choice") not in ext_options:
        st.session_state["file_ext_choice"] = ext_default
    ext_choice = st.sidebar.selectbox(
        "File type",
        ext_options,
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
        "edges_file": st.session_state.get("edges_file", ""),
        "allocations_file": st.session_state.get("allocations_file", ""),
        "baseline_allocations_file": st.session_state.get("baseline_allocations_file", ""),
        "traj_glob": st.session_state.get("traj_glob", ""),
        "link_multiselect": st.session_state.get("link_multiselect", []),
        "show_map": st.session_state.get("show_map", True),
        "show_graph": st.session_state.get("show_graph", True),
        "jitter_overlap": st.session_state.get("jitter_overlap", False),
        "show_metrics": st.session_state.get("show_metrics", False),
        "map_marker_style": st.session_state.get("map_marker_style", "Plane icons"),
        "df_file": st.session_state.get("df_file", ""),
        "df_select_mode": st.session_state.get("df_select_mode", "Single file"),
        "df_file_regex": st.session_state.get("df_file_regex", ""),
        "df_files": st.session_state.get("df_files", []),
        "layout_type_select": st.session_state.get("layout_type_select", "spring"),
        "metric_type_select": st.session_state.get("metric_type_select", ""),
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
    if st.session_state.get("df_select_mode") not in df_mode_options:
        st.session_state["df_select_mode"] = df_mode_options[0]
    df_mode = st.sidebar.radio(
        "DataFrame selection",
        options=df_mode_options,
        key="df_select_mode",
    )

    selected_files_rel: list[str] = []
    if df_mode == "Regex (multi)":
        if "df_file_regex" not in st.session_state:
            st.session_state["df_file_regex"] = ""
        regex_raw = st.sidebar.text_input(
            "DataFrame filename regex",
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

        df_files_seed: list[str] = []
        current_df_files = st.session_state.get("df_files")
        if isinstance(current_df_files, list):
            df_files_seed = [f for f in current_df_files if f in csv_files_rel]
        if not df_files_seed:
            # Preserve the current single-file selection when switching modes.
            seed = st.session_state.get("df_file")
            if seed in csv_files_rel:
                df_files_seed = [seed]
            elif csv_files_rel:
                df_files_seed = [csv_files_rel[0]]
        st.session_state["df_files"] = df_files_seed

        st.sidebar.multiselect(
            label="DataFrames",
            options=csv_files_rel,
            key="df_files",
        )
        current_df_files = st.session_state.get("df_files")
        if isinstance(current_df_files, list):
            selected_files_rel = [f for f in current_df_files if f in csv_files_rel]
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
    # Internal metadata columns inserted by this page should not be used as ID/time defaults.
    meta_cols = {"source_file"}
    col_options = [c for c in all_cols if c not in meta_cols] or all_cols
    lower_map = {c.lower(): c for c in col_options}
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
    time_pref = [
        "datetime",
        "timestamp",
        "time",
        "t",
        "step",
        "decision",
        "time_index",
        "time_idx",
        "time_s",
        "time_ms",
        "time_us",
        "date",
    ]

    def _pick_col(preferred: list[str], fallback_exclude: list[str]) -> str:
        for key in preferred:
            if key in col_options:
                return key
            if key.lower() in lower_map:
                return lower_map[key.lower()]
        # fallback to first column not excluded
        exclude_lower = {v.lower() for v in fallback_exclude}
        for c in col_options:
            if c not in fallback_exclude and c.lower() not in exclude_lower:
                return c
        return col_options[0] if col_options else (all_cols[0] if all_cols else "")

    if st.session_state.get("id_col") not in col_options:
        st.session_state["id_col"] = _pick_col(id_pref, time_pref)
    if st.session_state.get("time_col") not in col_options:
        st.session_state["time_col"] = _pick_col(time_pref, id_pref)

    # With session state primed above, avoid passing index/defaults to prevent Streamlit warnings
    flight_col = st.sidebar.selectbox(
        "ID column",
        options=col_options,
        key="id_col",
    )
    time_col = st.sidebar.selectbox(
        "Timestamp column",
        options=col_options,
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
        # Allow static datasets (no timestamps) to render by falling back to a single synthetic step.
        original_time_col = time_col
        synthetic_time_col = "__static_time"
        if synthetic_time_col not in df.columns:
            df[synthetic_time_col] = 0
        time_col = synthetic_time_col
        st.sidebar.warning(
            f"No valid timestamps found in '{original_time_col}'. "
            f"Using synthetic '{synthetic_time_col}'=0 for a static snapshot."
        )

    df = df.sort_values(by=[flight_col, time_col])
    # Normalize to standard column names for downstream helpers (keep aliases for backward helpers)
    df_std = df.rename(columns={flight_col: "id_col", time_col: "time_col"}, errors="ignore")
    if "id_col" not in df_std.columns:
        df_std["id_col"] = df[flight_col]
    if "time_col" not in df_std.columns:
        df_std["time_col"] = df[time_col]
    id_norm = _normalize_node_id_series(df_std["id_col"])
    invalid_ids = id_norm.eq("")
    if invalid_ids.any():
        dropped = int(invalid_ids.sum())
        df = df.loc[~invalid_ids].copy()
        df_std = df_std.loc[~invalid_ids].copy()
        id_norm = id_norm.loc[~invalid_ids]
        st.sidebar.warning(f"Dropped {dropped} rows with missing node IDs.")

    df_std["id_col"] = id_norm
    df_std["flight_id"] = id_norm
    # Keep selected ID column consistent for downstream groupbys / set comparisons
    df[flight_col] = id_norm
    # Ensure base df has flight_id for downstream map/edge helpers
    df["flight_id"] = id_norm
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
    share_root = env.share_root_path()
    default_edges_candidates = _candidate_edges_paths(
        [
            env.AGILAB_EXPORT_ABS,
            Path(st.session_state.datadir),
        ]
    )
    default_edges_candidates.extend(_quick_share_edges_paths(share_root))
    default_edges_candidates = sorted(
        {p.resolve(strict=False): p for p in default_edges_candidates}.values(),
        key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
        reverse=True,
    )
    datadir_path = Path(st.session_state.datadir)
    example_edges_candidates = [
        datadir_path / "pipeline" / "edges.jsonl",
        datadir_path / "pipeline" / "edges.parquet",
        datadir_path / "pipeline" / "topology.json",
    ]
    example_edges_path = next(
        (p for p in example_edges_candidates if p.exists()),
        example_edges_candidates[0],
    )
    edges_placeholder = f"e.g. {example_edges_path}"

    if "edges_file" not in st.session_state:
        legacy_val = (st.session_state.get("edges_file_input") or "").strip()
        if legacy_val:
            st.session_state["edges_file"] = legacy_val

    edges_prev = (st.session_state.get("edges_file") or "").strip()
    edges_candidates = [str(p) for p in default_edges_candidates]
    custom_label = "(custom path…)"
    picker_options = ["(none)"] + edges_candidates + [custom_label]

    if st.session_state.get("edges_file_choice") not in picker_options:
        if edges_prev and edges_prev in edges_candidates:
            st.session_state["edges_file_choice"] = edges_prev
        elif edges_prev:
            st.session_state["edges_file_choice"] = custom_label
            if "edges_file_custom" not in st.session_state:
                st.session_state["edges_file_custom"] = edges_prev
        else:
            st.session_state["edges_file_choice"] = edges_candidates[0] if edges_candidates else "(none)"

    edges_choice = st.sidebar.selectbox(
        "Edges file picker",
        picker_options,
        key="edges_file_choice",
        help="Pick a topology/edges export (GML/JSON/Parquet) that includes edge bearer/type information.",
    )
    if edges_choice == custom_label:
        edges_clean = (
            st.sidebar.text_input(
                "Custom edges file path",
                placeholder=edges_placeholder,
                key="edges_file_custom",
            ).strip()
        )
    elif edges_choice == "(none)":
        edges_clean = ""
    else:
        edges_clean = edges_choice.strip()

    if edges_clean == str(example_edges_path) and not Path(edges_clean).expanduser().exists():
        edges_clean = ""
    st.session_state["edges_file"] = edges_clean
    try:
        st.query_params["edges_file"] = edges_clean
    except Exception:
        pass
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

    if vm_settings.get("edges_file") != edges_clean:
        vm_settings["edges_file"] = edges_clean
        _persist_app_settings(env)

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

    present_defaults = [c for c in _DEFAULT_LINK_ORDER if c in link_options]
    if loaded_edges:
        present_defaults = [c for c in loaded_edges.keys() if c in link_options] or present_defaults
    link_default = present_defaults if present_defaults else link_options[:4]

    current_links = st.session_state.get("link_multiselect")
    if isinstance(current_links, list):
        current_links = [c for c in current_links if c in link_options]
    else:
        current_links = []
    if current_links and loaded_edges:
        try:
            has_edges = any(_preview_edge_count(df_std, c) > 0 for c in current_links)
        except Exception:
            has_edges = False
        if not has_edges and link_default:
            current_links = link_default
            st.sidebar.info("Reset link selection to detected topology edge types.")
    if not current_links:
        current_links = link_default
    st.session_state["link_multiselect"] = current_links
    selected_links = st.sidebar.multiselect(
        "Link columns",
        options=link_options,
        key="link_multiselect",
    )
    st.session_state.setdefault("show_map", True)
    st.session_state.setdefault("show_graph", True)
    st.session_state.setdefault("jitter_overlap", False)
    st.session_state.setdefault("show_metrics", False)
    show_map = st.sidebar.checkbox("Show map view", key="show_map")
    show_graph = st.sidebar.checkbox("Show topology graph", key="show_graph")
    jitter_overlap = st.sidebar.checkbox("Separate overlapping nodes", key="jitter_overlap")
    show_metrics = st.sidebar.checkbox("Show metrics table", key="show_metrics")
    marker_options = ["Dots", "Plane icons"]
    if st.session_state.get("map_marker_style") not in marker_options:
        st.session_state["map_marker_style"] = "Plane icons"
    map_marker_style = st.sidebar.selectbox(
        "Map markers",
        options=marker_options,
        key="map_marker_style",
    )

    layout_options = ["bipartite", "circular", "planar", "random", "rescale", "shell", "spring", "spiral"]
    if st.session_state.get("layout_type_select") not in layout_options:
        st.session_state["layout_type_select"] = "spring"
    layout_type = st.selectbox(
        "Select Layout Type",
        options=layout_options,
        key="layout_type_select",
    )

    st.session_state.df_cols = df.columns.tolist()
    available_metrics = [st.session_state.df_cols[-2], st.session_state.df_cols[-1]]
    metric_key = "metric_type_select"
    if not available_metrics:
        st.warning("No metrics columns detected.")
        selected_metric = ""
    else:
        if st.session_state.get(metric_key) not in available_metrics:
            st.session_state[metric_key] = available_metrics[0]
        selected_metric = st.selectbox("Select Metric for Link Weight", available_metrics, key=metric_key)

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
    st.session_state["_time_options"] = unique_timestamps
    single_time = len(unique_timestamps) <= 1
    with st.container():
        cola, colb, colc = st.columns([0.3, 7.5, 0.6])
        with cola:
            st.button("◁", key="decrement_button", on_click=decrement_time, disabled=single_time)
        with colb:
            if single_time:
                selected_val = unique_timestamps[0]
                st.session_state.selected_time = selected_val
                st.session_state.selected_time_idx = 0
                st.caption(f"Selected: {selected_val}")
            else:
                selected_val = st.select_slider(
                    "Time",
                    options=unique_timestamps,
                    format_func=lambda x: x.strftime("%Y-%m-%d %H:%M:%S") if hasattr(x, "strftime") else str(x),
                    key="selected_time",
                )
                if selected_val in unique_timestamps:
                    st.session_state.selected_time_idx = unique_timestamps.index(selected_val)
                st.caption(f"Selected: {selected_val}")
            idx_now = st.session_state.get("selected_time_idx", len(unique_timestamps) - 1)
            prog = idx_now / (len(unique_timestamps) - 1) if len(unique_timestamps) > 1 else 1.0
            st.progress(prog)
        with colc:
            st.button("▷", key="increment_button", on_click=increment_time, disabled=single_time)

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

    color_map_sig = (flight_col, st.session_state.get("_prev_df_selection_sig"))
    if "color_map" not in st.session_state or st.session_state.get("color_map_key") != color_map_sig:
        flight_ids = df_std["id_col"].astype(str).unique()
        color_map = plt.get_cmap("tab20", len(flight_ids))
        st.session_state.color_map = {flight_id: mcolors.rgb2hex(color_map(i % 20)) for i, flight_id in enumerate(flight_ids)}
        st.session_state.color_map_key = color_map_sig

    color_series = current_positions["id_col"].map(st.session_state.color_map)
    if hasattr(color_series, "fillna"):
        color_series = color_series.fillna("#888")
    current_positions["color"] = color_series.apply(hex_to_rgba)

    # Quick dual-screen links
    base_params: dict[str, str] = {}
    for k, v in st.query_params.items():
        if isinstance(v, list):
            if v:
                base_params[k] = str(v[-1])
        elif v is not None:
            base_params[k] = str(v)
    map_href = "?" + urlencode({**base_params, "view": "map"})
    graph_href = "?" + urlencode({**base_params, "view": "graph"})
    st.markdown(
        f"""
        <div style="padding:8px 0;">
          <strong>Dual-screen:</strong>
          <a href="{map_href}" target="_blank">Open map view</a> |
          <a href="{graph_href}" target="_blank">Open graph view</a>
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
            layers = create_layers_geomap(
                selected_links,
                df_positions_std,
                current_positions,
                link_color_map,
                marker_style=map_marker_style,
            )
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
            st.caption(
                "Symbol key: ▲ Satellite, ● Aircraft, ■ HRC, ◆ LRC "
                "(driven by `type`/`node_type`/`nodeType`; fallback: high altitude or `sat` in ID)."
            )
            if not selected_links:
                st.warning("No link columns selected. Pick at least one under **Link columns** in the sidebar.")
            else:
                counts = {col: _preview_edge_count(df_positions_std, col) for col in selected_links}
                if any(counts.values()):
                    summary = ", ".join(f"{k}={v}" for k, v in counts.items() if v)
                    st.caption(f"Edge counts (preview): {summary}")
                else:
                    st.warning(
                        "No edges parsed from the selected link columns. "
                        "Confirm the **Edges file picker** is set (or your dataframe includes edge columns)."
                    )
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

    # Live allocations overlay (optional)
    st.markdown("### 📡 Live allocations")
    share_root = env.share_root_path()
    target_name = getattr(env, "share_target_name", env.target)
    target_root = (share_root / str(target_name)).expanduser()
    alloc_candidate_bases = [
        target_root,
        target_root / "pipeline",
        target_root / "dataframe",
        datadir_path,
        datadir_path / "pipeline",
        datadir_path / "dataframe",
        env.AGILAB_EXPORT_ABS,
    ]
    alloc_candidates = _candidate_allocation_paths([p for p in alloc_candidate_bases if p.exists()])
    baseline_candidates = [p for p in alloc_candidates if _is_baseline_alloc_path(p)]
    routing_candidates = [p for p in alloc_candidates if not _is_baseline_alloc_path(p)]
    if not alloc_candidates:
        st.info(
            f"No allocation exports detected under {target_root} yet. "
            "Run a routing/baseline step or point the pickers to an existing allocations_steps.{json,parquet} file."
        )
    elif baseline_candidates and not routing_candidates:
        st.info(
            "Baseline allocations detected (ILP), but no routing allocations yet. "
            "Run `sb3_trainer` routing (e.g. `trainer_routing` / `trainer_gnn`) to generate allocations."
        )

    if "allocations_file" not in st.session_state:
        legacy_val = (st.session_state.get("alloc_path_input") or "").strip()
        if legacy_val:
            st.session_state["allocations_file"] = legacy_val
    alloc_prev = (st.session_state.get("allocations_file") or "").strip()

    alloc_placeholder = target_root / "trainer_routing" / "allocations_steps.parquet"
    alloc_options = ["(none)"] + [str(p) for p in routing_candidates] + ["(custom path…)"]
    if st.session_state.get("allocations_file_choice") not in alloc_options:
        if alloc_prev and alloc_prev in alloc_options:
            st.session_state["allocations_file_choice"] = alloc_prev
        elif alloc_prev:
            st.session_state["allocations_file_choice"] = "(custom path…)"
            if "allocations_file_custom" not in st.session_state:
                st.session_state["allocations_file_custom"] = alloc_prev
        else:
            st.session_state["allocations_file_choice"] = (
                str(routing_candidates[0]) if routing_candidates else "(none)"
            )

    alloc_choice = st.selectbox(
        "Allocations file picker (routing/RL)",
        options=alloc_options,
        key="allocations_file_choice",
        help="Per-step routing allocations (typically from `trainer_routing` / `trainer_gnn`).",
    )
    if alloc_choice == "(custom path…)":
        alloc_clean = st.text_input(
            "Custom allocations file path",
            key="allocations_file_custom",
            placeholder=f"e.g. {alloc_placeholder}",
        ).strip()
    elif alloc_choice == "(none)":
        alloc_clean = ""
    else:
        alloc_clean = alloc_choice.strip()
    st.session_state["allocations_file"] = alloc_clean
    try:
        st.query_params["allocations_file"] = alloc_clean
    except Exception:
        pass
    alloc_path = alloc_clean
    try:
        alloc_path_obj = Path(alloc_path).expanduser() if alloc_path else None
    except Exception:
        alloc_path_obj = None
    if alloc_path_obj is not None and alloc_path and not alloc_path_obj.exists():
        st.info("Allocations file not found. Update the path or generate allocations.")

    if "baseline_allocations_file" not in st.session_state:
        legacy_val = (st.session_state.get("baseline_alloc_path_input") or "").strip()
        if legacy_val:
            st.session_state["baseline_allocations_file"] = legacy_val
    baseline_prev = (st.session_state.get("baseline_allocations_file") or "").strip()

    baseline_placeholder = target_root / "trainer_ilp_stepper" / "allocations_steps.json"
    baseline_options = ["(none)"] + [str(p) for p in baseline_candidates] + ["(custom path…)"]
    if st.session_state.get("baseline_alloc_file_choice") not in baseline_options:
        if baseline_prev and baseline_prev in baseline_options:
            st.session_state["baseline_alloc_file_choice"] = baseline_prev
        elif baseline_prev:
            st.session_state["baseline_alloc_file_choice"] = "(custom path…)"
            if "baseline_alloc_file_custom" not in st.session_state:
                st.session_state["baseline_alloc_file_custom"] = baseline_prev
        else:
            st.session_state["baseline_alloc_file_choice"] = (
                str(baseline_candidates[0]) if baseline_candidates else "(none)"
            )

    baseline_choice = st.selectbox(
        "Baseline allocations file picker (ILP)",
        options=baseline_options,
        key="baseline_alloc_file_choice",
        help="Per-step baseline allocations (typically from `trainer_ilp_stepper`).",
    )
    if baseline_choice == "(custom path…)":
        baseline_clean = st.text_input(
            "Custom baseline allocations file path",
            key="baseline_alloc_file_custom",
            placeholder=f"e.g. {baseline_placeholder}",
        ).strip()
    elif baseline_choice == "(none)":
        baseline_clean = ""
    else:
        baseline_clean = baseline_choice.strip()
    st.session_state["baseline_allocations_file"] = baseline_clean
    try:
        st.query_params["baseline_allocations_file"] = baseline_clean
    except Exception:
        pass
    baseline_path_input = baseline_clean
    try:
        baseline_path_obj = Path(baseline_path_input).expanduser() if baseline_path_input else None
    except Exception:
        baseline_path_obj = None
    if baseline_path_obj is not None and baseline_path_input and not baseline_path_obj.exists():
        st.info("Baseline allocations file not found. Update the path or generate a baseline.")
    traj_glob_candidates = [
        str(datadir_path / "pipeline" / "*.parquet"),
        str(datadir_path / "pipeline" / "*.csv"),
        str(datadir_path / "dataframe" / "*.parquet"),
        str(datadir_path / "dataframe" / "*.csv"),
    ]
    traj_glob_candidates.extend(_quick_share_traj_globs(share_root))
    traj_glob_candidates = list(dict.fromkeys([c for c in traj_glob_candidates if c]))
    traj_glob_default = next(
        (c for c in traj_glob_candidates if glob.glob(str(Path(c).expanduser()))),
        str(datadir_path / "dataframe" / "*.parquet"),
    )

    if "traj_glob" not in st.session_state:
        legacy_val = (st.session_state.get("traj_glob_input") or "").strip()
        st.session_state["traj_glob"] = legacy_val or traj_glob_default

    traj_prev = (st.session_state.get("traj_glob") or "").strip()
    traj_candidates_existing = [
        c for c in traj_glob_candidates if glob.glob(str(Path(c).expanduser()))
    ]
    traj_custom_label = "(custom glob…)"
    traj_picker_options = ["(none)"] + traj_candidates_existing + [traj_custom_label]
    if st.session_state.get("traj_glob_choice") not in traj_picker_options:
        if traj_prev and traj_prev in traj_candidates_existing:
            st.session_state["traj_glob_choice"] = traj_prev
        elif traj_prev:
            st.session_state["traj_glob_choice"] = traj_custom_label
            if "traj_glob_custom" not in st.session_state:
                st.session_state["traj_glob_custom"] = traj_prev
        else:
            st.session_state["traj_glob_choice"] = traj_glob_default if traj_candidates_existing else "(none)"

    traj_choice = st.selectbox(
        "Trajectory data picker (for map overlay)",
        options=traj_picker_options,
        key="traj_glob_choice",
        help="Pick a trajectory glob for node positions. Use custom to provide one or more globs (comma/semicolon/newline separated).",
    )
    traj_placeholder = str(share_root / "flight_trajectory" / "pipeline" / "*.csv")
    if traj_choice == traj_custom_label:
        traj_clean = st.text_input(
            "Custom trajectory glob(s)",
            key="traj_glob_custom",
            placeholder=f"e.g. {traj_placeholder}",
        ).strip()
    elif traj_choice == "(none)":
        traj_clean = ""
    else:
        traj_clean = traj_choice.strip()

    st.session_state["traj_glob"] = traj_clean
    try:
        st.query_params["traj_glob"] = traj_clean
    except Exception:
        pass
    traj_glob_clean = traj_clean
    if (
        vm_settings.get("allocations_file") != alloc_clean
        or vm_settings.get("baseline_allocations_file") != baseline_clean
        or vm_settings.get("traj_glob") != traj_clean
    ):
        vm_settings["allocations_file"] = alloc_clean
        vm_settings["baseline_allocations_file"] = baseline_clean
        vm_settings["traj_glob"] = traj_clean
        _persist_app_settings(env)
    alloc_df = (
        load_allocations(alloc_path_obj)
        if alloc_path_obj is not None and alloc_path_obj.exists()
        else pd.DataFrame()
    )
    baseline_df = (
        load_allocations(baseline_path_obj)
        if baseline_path_obj is not None and baseline_path_obj.exists()
        else pd.DataFrame()
    )

    def _demand_pairs(df_in: pd.DataFrame) -> list[tuple[int, int]]:
        if df_in.empty or not {"source", "destination"}.issubset(df_in.columns):
            return []
        src_series = pd.to_numeric(df_in["source"], errors="coerce")
        dst_series = pd.to_numeric(df_in["destination"], errors="coerce")
        pairs: set[tuple[int, int]] = set()
        for src, dst in zip(src_series.tolist(), dst_series.tolist()):
            if pd.isna(src) or pd.isna(dst):
                continue
            pairs.add((int(src), int(dst)))
        return sorted(pairs)

    def _filter_by_pair(df_in: pd.DataFrame, pair: tuple[int, int] | None) -> pd.DataFrame:
        if df_in.empty or pair is None or not {"source", "destination"}.issubset(df_in.columns):
            return df_in
        src, dst = pair
        src_series = pd.to_numeric(df_in["source"], errors="coerce")
        dst_series = pd.to_numeric(df_in["destination"], errors="coerce")
        return df_in[(src_series == src) & (dst_series == dst)]

    all_pairs = sorted(set(_demand_pairs(alloc_df)) | set(_demand_pairs(baseline_df)))
    selected_pair: tuple[int, int] | None = None
    if all_pairs:
        alloc_pair_qp = (st.session_state.pop("_alloc_pair_qp", "") or "").strip()
        if alloc_pair_qp:
            parts = [p for p in re.split(r"[,:\\-]+", alloc_pair_qp) if p.strip()]
            if len(parts) >= 2:
                try:
                    qp_pair = (int(parts[0]), int(parts[1]))
                except Exception:
                    qp_pair = None
                if qp_pair and qp_pair in all_pairs:
                    st.session_state["alloc_demand_pair_focus"] = qp_pair

        selected_pair = st.selectbox(
            "Focus demand (optional)",
            options=[None] + all_pairs,
            format_func=lambda p: "All demands" if p is None else f"{p[0]} → {p[1]}",
            key="alloc_demand_pair_focus",
        )
        try:
            st.query_params["alloc_pair"] = "" if selected_pair is None else f"{selected_pair[0]}-{selected_pair[1]}"
        except Exception:
            pass

    alloc_df_view = _filter_by_pair(alloc_df, selected_pair)
    baseline_df_view = _filter_by_pair(baseline_df, selected_pair)

    def _time_values(df_in: pd.DataFrame) -> list[int]:
        if df_in.empty:
            return []
        if "time_index" not in df_in.columns:
            return [0]
        series = pd.to_numeric(df_in["time_index"], errors="coerce").dropna()
        if series.empty:
            return [0]
        return sorted({int(x) for x in series.tolist()})

    times = sorted(set(_time_values(alloc_df_view)) | set(_time_values(baseline_df_view)))
    if not times:
        st.info("No allocations found yet (routing or baseline).")
    else:
        alloc_time_qp = (st.session_state.pop("_alloc_time_index_qp", "") or "").strip()
        if alloc_time_qp:
            try:
                qp_time = int(float(alloc_time_qp))
            except Exception:
                qp_time = None
            if qp_time is not None and qp_time in times:
                st.session_state["alloc_time_index"] = qp_time
        if st.session_state.get("alloc_time_index") not in times:
            st.session_state["alloc_time_index"] = times[0]
        if len(times) <= 1:
            t_sel = times[0]
            st.session_state["alloc_time_index"] = t_sel
            st.caption(f"Time index: {t_sel}")
        else:
            t_sel = st.select_slider("Time index", options=times, key="alloc_time_index")
        try:
            st.query_params["alloc_time_index"] = str(t_sel)
        except Exception:
            pass
        alloc_step = (
            alloc_df_view[alloc_df_view["time_index"] == t_sel]
            if (not alloc_df_view.empty and "time_index" in alloc_df_view.columns)
            else pd.DataFrame()
        )
        baseline_step = (
            baseline_df_view[baseline_df_view["time_index"] == t_sel]
            if (not baseline_df_view.empty and "time_index" in baseline_df_view.columns)
            else pd.DataFrame()
        )
        t_for_positions = float(t_sel)
        for df_step in (alloc_step, baseline_step):
            if df_step is None or df_step.empty or "t_now_s" not in df_step.columns:
                continue
            t_series = pd.to_numeric(df_step["t_now_s"], errors="coerce").dropna()
            if not t_series.empty:
                t_for_positions = float(t_series.iloc[0])
                break
        positions_live = load_positions_at_time(traj_glob_clean, t_for_positions) if traj_glob_clean else pd.DataFrame()

        if not alloc_step.empty:
            st.caption("Routing allocations at this timestep")
            st.dataframe(alloc_step)
        if not baseline_step.empty:
            st.caption("Baseline (ILP) allocations at this timestep")
            st.dataframe(baseline_step)
        if alloc_step.empty and baseline_step.empty:
            st.info("No allocations rows found for the selected timestep.")
            return

        if selected_pair is not None:
            def _bearer_path(cell: Any) -> str:
                if cell is None or (isinstance(cell, float) and np.isnan(cell)):
                    return ""
                if isinstance(cell, list):
                    return " → ".join(str(x) for x in cell if x is not None and str(x).strip())
                if isinstance(cell, tuple):
                    return " → ".join(str(x) for x in cell if x is not None and str(x).strip())
                if isinstance(cell, str):
                    parsed = safe_literal_eval(cell)
                    if isinstance(parsed, (list, tuple)):
                        return " → ".join(str(x) for x in parsed if x is not None and str(x).strip())
                    return cell.strip()
                return str(cell).strip()

            with st.expander("Demand timeline (selected demand)", expanded=True):
                if not alloc_df_view.empty and "time_index" in alloc_df_view.columns:
                    timeline = alloc_df_view.sort_values("time_index").copy()
                    if "bearers" in timeline.columns:
                        timeline["bearer_path"] = timeline["bearers"].apply(_bearer_path)
                    elif "bearer" in timeline.columns:
                        timeline["bearer_path"] = timeline["bearer"].apply(_bearer_path)
                    else:
                        timeline["bearer_path"] = ""
                    cols = [c for c in ["time_index", "bearer_path", "routed", "delivered_bandwidth", "latency"] if c in timeline.columns]
                    st.caption("Allocations timeline")
                    st.dataframe(timeline[cols], use_container_width=True)
                    sig = timeline["bearer_path"].fillna("")
                    sig_prev = sig.shift(1).fillna("")
                    changed = (sig != sig_prev) & sig.ne("") & sig_prev.ne("")
                    if changed.any():
                        switch_times = timeline.loc[changed, "time_index"].tolist()
                        st.info(f"Bearer switch detected at time indices: {', '.join(map(str, switch_times))}")

                if not baseline_df_view.empty and "time_index" in baseline_df_view.columns:
                    base_tl = baseline_df_view.sort_values("time_index").copy()
                    if "bearers" in base_tl.columns:
                        base_tl["bearer_path"] = base_tl["bearers"].apply(_bearer_path)
                    elif "bearer" in base_tl.columns:
                        base_tl["bearer_path"] = base_tl["bearer"].apply(_bearer_path)
                    else:
                        base_tl["bearer_path"] = ""
                    cols = [c for c in ["time_index", "bearer_path", "routed", "delivered_bandwidth", "latency"] if c in base_tl.columns]
                    st.caption("Baseline timeline")
                    st.dataframe(base_tl[cols], use_container_width=True)

        if not alloc_step.empty and not baseline_step.empty:
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

        layers_live: list[Any] = []
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
        if not alloc_step.empty:
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
            if not traj_glob_clean:
                st.info("No live overlay: select trajectory data (or provide a custom trajectory glob).")
            else:
                patterns = [p.strip() for p in re.split(r"[,\n;]+", traj_glob_clean) if p.strip()]
                matched = []
                for pattern in patterns:
                    matched.extend(glob.glob(str(Path(pattern).expanduser())))
                if not matched:
                    st.info(
                        "No node positions found: trajectory glob matched 0 files. "
                        f"Example: `{traj_placeholder}`"
                    )
                else:
                    st.info(
                        "No node positions found for this timestep. "
                        "Ensure trajectory files include `time_s` (or `t_now_s`) and `latitude/longitude` (or `lat/long`)."
                    )

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
