# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


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
from agi_env.pagelib import render_logo


def _resolve_active_app() -> Path:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--active-app", dest="active_app", type=str, required=True)
    args, _ = parser.parse_known_args()
    active_app_path = Path(args.active_app).expanduser().resolve()
    if not active_app_path.exists():
        st.error(f"Provided --active-app path not found: {active_app_path}")
        st.stop()
    return active_app_path


def _default_artifact_root(env: AgiEnv) -> Path:
    return Path(env.AGILAB_EXPORT_ABS) / env.target / "queue_analysis"


def _discover_files(base: Path, pattern: str) -> list[Path]:
    try:
        return sorted([path for path in base.glob(pattern) if path.is_file()], key=lambda p: p.as_posix())
    except Exception:
        return []


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _peer_csv(path: Path, suffix: str) -> Path:
    stem = path.name.removesuffix("_summary_metrics.json")
    return path.with_name(f"{stem}_{suffix}.csv")


def _safe_metric(value: Any) -> str:
    try:
        return f"{float(value):.3f}"
    except Exception:
        return "n/a"


st.set_page_config(layout="wide")

if "env" not in st.session_state:
    active_app_path = _resolve_active_app()
    env = AgiEnv(apps_path=active_app_path.parent, app=active_app_path.name, verbose=0)
    env.init_done = True
    st.session_state["env"] = env
else:
    env = st.session_state["env"]

render_logo("UAV Queue Analysis")
st.title("UAV queue analysis")
st.caption(
    "Use exported queue telemetry to compare routing policies, queue hotspots, and delivery outcomes "
    "without reopening the simulator code."
)
st.info(
    "Each run also writes `pipeline/topology.gml`, `pipeline/allocations_steps.csv`, "
    "`pipeline/_trajectory_summary.json`, and per-node trajectory CSVs so the same result "
    "can be explored in `view_maps_network`."
)

default_root = _default_artifact_root(env)
artifact_root_value = st.sidebar.text_input(
    "Artifact directory",
    value=st.session_state.setdefault("uav_queue_analysis_datadir", str(default_root)),
    key="uav_queue_analysis_datadir",
)
artifact_root = Path(artifact_root_value).expanduser()

metrics_pattern = st.sidebar.text_input(
    "Summary glob",
    value=st.session_state.setdefault("uav_queue_summary_glob", "**/*_summary_metrics.json"),
    key="uav_queue_summary_glob",
)

summary_files = _discover_files(artifact_root, metrics_pattern) if artifact_root.exists() else []

if not artifact_root.exists():
    st.warning(f"Artifact directory does not exist yet: {artifact_root}")
    st.stop()

if not summary_files:
    st.warning(f"No summary metrics file found in {artifact_root} with pattern {metrics_pattern!r}.")
    st.stop()

summary_path = st.sidebar.selectbox(
    "Run summary",
    options=summary_files,
    format_func=lambda path: str(Path(path).relative_to(artifact_root)),
)

summary = _load_json(Path(summary_path))
queue_path = _peer_csv(Path(summary_path), "queue_timeseries")
packet_path = _peer_csv(Path(summary_path), "packet_events")
positions_path = _peer_csv(Path(summary_path), "node_positions")
routing_path = _peer_csv(Path(summary_path), "routing_summary")

missing = [path for path in (queue_path, packet_path, positions_path, routing_path) if not path.is_file()]
if missing:
    st.error("Related queue artifacts are missing for the selected summary:")
    for path in missing:
        st.code(str(path))
    st.stop()

queue_df = pd.read_csv(queue_path)
packet_df = pd.read_csv(packet_path)
positions_df = pd.read_csv(positions_path)
routing_df = pd.read_csv(routing_path)

intro_left, intro_right = st.columns([1.6, 1.2])
with intro_left:
    st.subheader("Why this is a good AGILAB demo")
    st.markdown(
        "- one scenario file becomes a reproducible project\n"
        "- one routing knob changes queue buildup and delivery outcomes\n"
        "- the exported packet and queue telemetry stays explorable across reruns\n"
        "- the internal simulator can later be swapped for a fuller UavNetSim adapter"
    )
with intro_right:
    st.subheader("Run metadata")
    st.json(
        {
            "scenario": summary.get("scenario"),
            "routing_policy": summary.get("routing_policy"),
            "source_rate_pps": summary.get("source_rate_pps"),
            "random_seed": summary.get("random_seed"),
            "bottleneck_relay": summary.get("bottleneck_relay"),
        }
    )

metric_columns = st.columns(4)
metric_specs = [
    ("PDR", summary.get("pdr")),
    ("Mean delay (ms)", summary.get("mean_e2e_delay_ms")),
    ("Queue wait (ms)", summary.get("mean_queue_wait_ms")),
    ("Max queue", summary.get("max_queue_depth_pkts")),
]
for col, (label, value) in zip(metric_columns, metric_specs):
    col.metric(label, _safe_metric(value))

st.subheader("Queue occupancy over time")
queue_chart = (
    queue_df.pivot_table(index="time_s", columns="relay", values="queue_depth_pkts", aggfunc="last")
    .sort_index()
)
st.line_chart(queue_chart)

relay_positions = positions_df.loc[positions_df["role"] == "relay"].copy()
if not relay_positions.empty:
    st.subheader("Relay mobility trace (y axis)")
    relay_chart = relay_positions.pivot_table(index="time_s", columns="node", values="y_m", aggfunc="last").sort_index()
    st.line_chart(relay_chart)

if not routing_df.empty:
    st.subheader("Route usage")
    route_metrics = routing_df.set_index("relay")[["packets_delivered", "packets_dropped"]]
    st.bar_chart(route_metrics)
    st.dataframe(routing_df, use_container_width=True, hide_index=True)

source_packets = packet_df.loc[packet_df["origin_kind"] == "source"].copy()
delivered_packets = source_packets.loc[source_packets["status"] == "delivered"].copy()
if not delivered_packets.empty:
    st.subheader("Highest-delay source packets")
    slowest = delivered_packets.sort_values("e2e_delay_ms", ascending=False).head(30)
    st.dataframe(slowest, use_container_width=True, hide_index=True)
else:
    st.info("No delivered source packet is available in this run.")

notes = str(summary.get("notes", "") or "").strip()
if notes:
    st.subheader("Notes")
    st.info(notes)
