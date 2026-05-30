# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from agi_pages.runtime import (
    artifact_root as _page_artifact_root,
    discover_files as _page_discover_files,
    ensure_repo_on_path as _page_ensure_repo_on_path,
    resolve_active_app_path,
    reset_scoped_session_state,
    safe_metric,
)


def _ensure_repo_on_path() -> None:
    _page_ensure_repo_on_path(__file__)


_ensure_repo_on_path()

from agi_env import AgiEnv
from agi_gui.pagelib import render_logo


DATA_DIR_KEY = "queue_resilience_datadir"
SUMMARY_GLOB_KEY = "queue_resilience_summary_glob"
APP_SCOPE_KEY = "queue_resilience_active_app_scope"
APP_SCOPED_SESSION_DEFAULT_KEYS = (
    DATA_DIR_KEY,
    SUMMARY_GLOB_KEY,
)


def _load_page_meta() -> tuple[str, str]:
    if __package__:
        from .page_meta import PAGE_LOGO, PAGE_TITLE

        return PAGE_LOGO, PAGE_TITLE

    _meta_path = Path(__file__).with_name("page_meta.py")
    _meta_spec = importlib.util.spec_from_file_location("view_queue_resilience_page_meta", _meta_path)
    if _meta_spec is None or _meta_spec.loader is None:  # pragma: no cover - defensive fallback
        raise RuntimeError(f"Unable to load page metadata from {_meta_path}")
    _meta_module = importlib.util.module_from_spec(_meta_spec)
    _meta_spec.loader.exec_module(_meta_module)
    return _meta_module.PAGE_LOGO, _meta_module.PAGE_TITLE


PAGE_LOGO, PAGE_TITLE = _load_page_meta()


def _resolve_active_app() -> Path:
    return resolve_active_app_path(error_fn=st.error, stop_fn=st.stop)


def _default_artifact_root(env: AgiEnv) -> Path:
    return _page_artifact_root(env, "queue_analysis")


def _discover_files(base: Path, pattern: str) -> list[Path]:
    return _page_discover_files(base, pattern)


def _reset_app_scoped_session_defaults(active_app_path: Path) -> bool:
    """Clear persisted Queue Resilience defaults when the active app changes."""

    return reset_scoped_session_state(
        st.session_state,
        APP_SCOPE_KEY,
        active_app_path,
        keys=APP_SCOPED_SESSION_DEFAULT_KEYS,
    )


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _peer_csv(path: Path, suffix: str) -> Path:
    stem = path.name.removesuffix("_summary_metrics.json")
    return path.with_name(f"{stem}_{suffix}.csv")


def _safe_metric(value: Any) -> str:
    return safe_metric(value)


st.set_page_config(layout="wide")

active_app_path = _resolve_active_app()
app_scope_changed = _reset_app_scoped_session_defaults(active_app_path)
if "env" not in st.session_state or app_scope_changed:
    env = getattr(AgiEnv, "for_app", AgiEnv)(apps_path=active_app_path.parent, app=active_app_path.name, verbose=0)
    env.init_done = True
    st.session_state["env"] = env
else:
    env = st.session_state["env"]

render_logo(PAGE_LOGO)
st.title(PAGE_TITLE)
st.caption(
    "Use exported queue telemetry to inspect backlog, routing pressure, and delivery outcomes "
    "without reopening the producer code."
)
st.info(
    "Each run also writes `pipeline/topology.gml`, `pipeline/allocations_steps.csv`, "
    "`pipeline/_trajectory_summary.json`, and per-node trajectory CSVs so the same result "
    "can be explored in `view_maps_network`."
)

default_root = _default_artifact_root(env)
st.session_state.setdefault(DATA_DIR_KEY, str(default_root))
artifact_root_value = st.sidebar.text_input(
    "Artifact directory",
    key=DATA_DIR_KEY,
)
artifact_root = Path(artifact_root_value).expanduser()

st.session_state.setdefault(SUMMARY_GLOB_KEY, "**/*_summary_metrics.json")
metrics_pattern = st.sidebar.text_input(
    "Summary glob",
    key=SUMMARY_GLOB_KEY,
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
    st.subheader("Why this run is useful")
    st.markdown(
        "- one scenario file becomes a reproducible project\n"
        "- one routing knob changes queue buildup and delivery outcomes\n"
        "- the exported packet and queue telemetry stays explorable across reruns\n"
        "- the producer can later be swapped while preserving the analysis contract"
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
    st.dataframe(routing_df, width="stretch", hide_index=True)

source_packets = packet_df.loc[packet_df["origin_kind"] == "source"].copy()
delivered_packets = source_packets.loc[source_packets["status"] == "delivered"].copy()
if not delivered_packets.empty:
    st.subheader("Highest-delay source packets")
    slowest = delivered_packets.sort_values("e2e_delay_ms", ascending=False).head(30)
    st.dataframe(slowest, width="stretch", hide_index=True)
else:
    st.info("No delivered source packet is available in this run.")

notes = str(summary.get("notes", "") or "").strip()
if notes:
    st.subheader("Notes")
    st.info(notes)
