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
from agi_gui.pagelib import render_logo

RUN_SELECTION_KEY = "relay_resilience_selected_runs"
DETAIL_RUN_KEY = "relay_resilience_detail_run"
REFERENCE_RUN_KEY = "relay_resilience_reference_run"


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
    except (OSError, RuntimeError, TypeError, ValueError):
        return []


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _peer_csv(path: Path, suffix: str) -> Path:
    stem = path.name.removesuffix("_summary_metrics.json")
    return path.with_name(f"{stem}_{suffix}.csv")


def _safe_metric(value: Any) -> str:
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError, OverflowError):
        return "n/a"


def _relative_summary_label(path: Path, artifact_root: Path) -> str:
    try:
        return str(path.relative_to(artifact_root))
    except (RuntimeError, TypeError, ValueError):
        return path.name


def _coerce_selection(saved_value: Any, options: list[str], *, fallback: str | None = None) -> list[str]:
    if isinstance(saved_value, str):
        candidates = [saved_value]
    elif isinstance(saved_value, (list, tuple, set)):
        candidates = [str(value) for value in saved_value]
    else:
        candidates = []
    selected = [value for value in candidates if value in options]
    if selected:
        return selected
    if fallback and fallback in options:
        return [fallback]
    return options[-1:] if options else []


def _comparison_row(summary_path: Path, artifact_root: Path) -> dict[str, Any]:
    summary = _load_json(summary_path)
    return {
        "run_label": _relative_summary_label(summary_path, artifact_root),
        "scenario": summary.get("scenario", ""),
        "routing_policy": summary.get("routing_policy", ""),
        "bond_mode": summary.get("bond_mode", "single"),
        "source_rate_pps": summary.get("source_rate_pps"),
        "random_seed": summary.get("random_seed"),
        "pdr": summary.get("pdr"),
        "mean_e2e_delay_ms": summary.get("mean_e2e_delay_ms"),
        "mean_queue_wait_ms": summary.get("mean_queue_wait_ms"),
        "max_queue_depth_pkts": summary.get("max_queue_depth_pkts"),
        "bottleneck_relay": summary.get("bottleneck_relay", ""),
    }


def _build_comparison_frame(selected_paths: dict[str, Path], artifact_root: Path, reference_label: str) -> pd.DataFrame:
    rows = [_comparison_row(path, artifact_root) for path in selected_paths.values()]
    if not rows:
        return pd.DataFrame()
    comparison_df = pd.DataFrame(rows)
    numeric_columns = [
        "source_rate_pps",
        "random_seed",
        "pdr",
        "mean_e2e_delay_ms",
        "mean_queue_wait_ms",
        "max_queue_depth_pkts",
    ]
    for column in numeric_columns:
        comparison_df[column] = pd.to_numeric(comparison_df[column], errors="coerce")
    if reference_label in comparison_df["run_label"].values:
        reference_row = comparison_df.loc[comparison_df["run_label"] == reference_label].iloc[0]
        comparison_df["delta_pdr_vs_ref"] = comparison_df["pdr"] - reference_row["pdr"]
        comparison_df["delta_delay_ms_vs_ref"] = (
            comparison_df["mean_e2e_delay_ms"] - reference_row["mean_e2e_delay_ms"]
        )
        comparison_df["delta_queue_wait_ms_vs_ref"] = (
            comparison_df["mean_queue_wait_ms"] - reference_row["mean_queue_wait_ms"]
        )
        comparison_df["delta_max_queue_vs_ref"] = (
            comparison_df["max_queue_depth_pkts"] - reference_row["max_queue_depth_pkts"]
        )
    ordered_columns = [
        "run_label",
        "scenario",
        "routing_policy",
        "bond_mode",
        "source_rate_pps",
        "random_seed",
        "pdr",
        "mean_e2e_delay_ms",
        "mean_queue_wait_ms",
        "max_queue_depth_pkts",
        "bottleneck_relay",
        "delta_pdr_vs_ref",
        "delta_delay_ms_vs_ref",
        "delta_queue_wait_ms_vs_ref",
        "delta_max_queue_vs_ref",
    ]
    return comparison_df[[column for column in ordered_columns if column in comparison_df.columns]]


def _build_max_queue_comparison_frame(selected_paths: dict[str, Path]) -> pd.DataFrame:
    queue_frames: list[pd.Series] = []
    for label, summary_path in selected_paths.items():
        queue_path = _peer_csv(summary_path, "queue_timeseries")
        if not queue_path.is_file():
            continue
        queue_df = pd.read_csv(queue_path)
        if "time_s" not in queue_df.columns or "queue_depth_pkts" not in queue_df.columns:
            continue
        queue_series = (
            queue_df.groupby("time_s", dropna=False)["queue_depth_pkts"].max().sort_index().rename(label)
        )
        queue_frames.append(queue_series)
    if not queue_frames:
        return pd.DataFrame()
    return pd.concat(queue_frames, axis=1).sort_index()


st.set_page_config(layout="wide")

if "env" not in st.session_state:
    active_app_path = _resolve_active_app()
    env = AgiEnv(apps_path=active_app_path.parent, app=active_app_path.name, verbose=0)
    env.init_done = True
    st.session_state["env"] = env
else:
    env = st.session_state["env"]

render_logo("Relay Resilience Analysis")
st.title("Relay resilience analysis")
st.caption(
    "Use exported relay-queue telemetry to compare routing policies, queue hotspots, and delivery outcomes "
    "without reopening the producer code."
)
st.info(
    "Each run also writes `pipeline/topology.gml`, `pipeline/allocations_steps.csv`, "
    "`pipeline/_trajectory_summary.json`, and per-node trajectory CSVs so the same result "
    "can be explored in `view_maps_network`."
)

default_root = _default_artifact_root(env)
artifact_root_value = st.sidebar.text_input(
    "Artifact directory",
    value=st.session_state.setdefault("relay_resilience_datadir", str(default_root)),
    key="relay_resilience_datadir",
)
artifact_root = Path(artifact_root_value).expanduser()

metrics_pattern = st.sidebar.text_input(
    "Summary glob",
    value=st.session_state.setdefault("relay_resilience_summary_glob", "**/*_summary_metrics.json"),
    key="relay_resilience_summary_glob",
)

summary_files = _discover_files(artifact_root, metrics_pattern) if artifact_root.exists() else []

if not artifact_root.exists():
    st.warning(f"Artifact directory does not exist yet: {artifact_root}")
    st.stop()

if not summary_files:
    st.warning(f"No summary metrics file found in {artifact_root} with pattern {metrics_pattern!r}.")
    st.stop()

summary_label_to_path = {_relative_summary_label(path, artifact_root): path for path in summary_files}
summary_labels = list(summary_label_to_path.keys())

selected_run_labels = st.sidebar.multiselect(
    "Runs to compare",
    options=summary_labels,
    default=_coerce_selection(st.session_state.get(RUN_SELECTION_KEY), summary_labels),
    key=RUN_SELECTION_KEY,
)
if not selected_run_labels:
    st.info("Select at least one run in the sidebar.")
    st.stop()

detailed_run_label = st.sidebar.selectbox(
    "Detailed run",
    options=selected_run_labels,
    index=selected_run_labels.index(st.session_state.get(DETAIL_RUN_KEY))
    if st.session_state.get(DETAIL_RUN_KEY) in selected_run_labels
    else 0,
    key=DETAIL_RUN_KEY,
)

reference_run_label = detailed_run_label
if len(selected_run_labels) > 1:
    reference_run_label = st.sidebar.selectbox(
        "Reference run",
        options=selected_run_labels,
        index=selected_run_labels.index(st.session_state.get(REFERENCE_RUN_KEY))
        if st.session_state.get(REFERENCE_RUN_KEY) in selected_run_labels
        else 0,
        key=REFERENCE_RUN_KEY,
    )

selected_paths = {label: summary_label_to_path[label] for label in selected_run_labels}
comparison_df = _build_comparison_frame(selected_paths, artifact_root, reference_run_label)
max_queue_compare_df = _build_max_queue_comparison_frame(selected_paths)

if len(selected_run_labels) > 1 and not comparison_df.empty:
    st.subheader("Run comparison")
    st.caption(
        "Select several exported runs to compare routing policy, queue buildup, and delivery outcomes "
        "before drilling into one detailed run below."
    )
    best_pdr_idx = comparison_df["pdr"].idxmax() if comparison_df["pdr"].notna().any() else None
    lowest_delay_idx = (
        comparison_df["mean_e2e_delay_ms"].idxmin() if comparison_df["mean_e2e_delay_ms"].notna().any() else None
    )
    lowest_queue_idx = (
        comparison_df["mean_queue_wait_ms"].idxmin() if comparison_df["mean_queue_wait_ms"].notna().any() else None
    )
    comparison_cols = st.columns(4)
    comparison_cols[0].metric("Runs selected", str(len(selected_run_labels)))
    comparison_cols[1].metric(
        "Best PDR",
        _safe_metric(comparison_df.loc[best_pdr_idx, "pdr"]) if best_pdr_idx is not None else "n/a",
        comparison_df.loc[best_pdr_idx, "run_label"] if best_pdr_idx is not None else None,
    )
    comparison_cols[2].metric(
        "Lowest delay (ms)",
        _safe_metric(comparison_df.loc[lowest_delay_idx, "mean_e2e_delay_ms"])
        if lowest_delay_idx is not None
        else "n/a",
        comparison_df.loc[lowest_delay_idx, "run_label"] if lowest_delay_idx is not None else None,
    )
    comparison_cols[3].metric(
        "Lowest queue wait (ms)",
        _safe_metric(comparison_df.loc[lowest_queue_idx, "mean_queue_wait_ms"])
        if lowest_queue_idx is not None
        else "n/a",
        comparison_df.loc[lowest_queue_idx, "run_label"] if lowest_queue_idx is not None else None,
    )
    st.dataframe(comparison_df, width="stretch", hide_index=True)
    st.caption(
        f"Reference run: `{reference_run_label}`. Positive `delta_pdr_vs_ref` is better; negative "
        "`delta_delay_ms_vs_ref`, `delta_queue_wait_ms_vs_ref`, and `delta_max_queue_vs_ref` are better."
    )
    if not max_queue_compare_df.empty:
        st.subheader("Max queue depth by run")
        st.line_chart(max_queue_compare_df)

summary_path = selected_paths[detailed_run_label]

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

st.divider()
st.subheader(f"Detailed run: {detailed_run_label}")

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
