# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from agi_pages.queue_resilience import (
    load_queue_resilience_run,
    load_queue_summary as _load_json,
    peer_csv_path as _peer_csv,
    prepare_queue_resilience_page,
    render_queue_resilience_run,
)
from agi_pages.runtime import (
    ensure_repo_on_path as _page_ensure_repo_on_path,
    relative_label as _page_relative_label,
    safe_metric as _safe_metric,
)


def _ensure_repo_on_path() -> None:
    _page_ensure_repo_on_path(__file__)


_ensure_repo_on_path()

from agi_env import AgiEnv  # noqa: E402

RUN_SELECTION_KEY = "relay_resilience_selected_runs"
DETAIL_RUN_KEY = "relay_resilience_detail_run"
REFERENCE_RUN_KEY = "relay_resilience_reference_run"
DATA_DIR_KEY = "relay_resilience_datadir"
SUMMARY_GLOB_KEY = "relay_resilience_summary_glob"
APP_SCOPE_KEY = "relay_resilience_active_app_scope"
APP_SCOPED_SESSION_DEFAULT_KEYS = (
    RUN_SELECTION_KEY,
    DETAIL_RUN_KEY,
    REFERENCE_RUN_KEY,
    DATA_DIR_KEY,
    SUMMARY_GLOB_KEY,
)


def _relative_summary_label(path: Path, artifact_root: Path) -> str:
    return _page_relative_label(path, artifact_root)


def _coerce_selection(
    saved_value: Any, options: list[str], *, fallback: str | None = None
) -> list[str]:
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


def _build_comparison_frame(
    selected_paths: dict[str, Path], artifact_root: Path, reference_label: str
) -> pd.DataFrame:
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
        reference_row = comparison_df.loc[
            comparison_df["run_label"] == reference_label
        ].iloc[0]
        comparison_df["delta_pdr_vs_ref"] = comparison_df["pdr"] - reference_row["pdr"]
        comparison_df["delta_delay_ms_vs_ref"] = (
            comparison_df["mean_e2e_delay_ms"] - reference_row["mean_e2e_delay_ms"]
        )
        comparison_df["delta_queue_wait_ms_vs_ref"] = (
            comparison_df["mean_queue_wait_ms"] - reference_row["mean_queue_wait_ms"]
        )
        comparison_df["delta_max_queue_vs_ref"] = (
            comparison_df["max_queue_depth_pkts"]
            - reference_row["max_queue_depth_pkts"]
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
    return comparison_df[
        [column for column in ordered_columns if column in comparison_df.columns]
    ]


def _build_max_queue_comparison_frame(selected_paths: dict[str, Path]) -> pd.DataFrame:
    queue_frames: list[pd.Series] = []
    for label, summary_path in selected_paths.items():
        queue_path = _peer_csv(summary_path, "queue_timeseries")
        if not queue_path.is_file():
            continue
        queue_df = pd.read_csv(queue_path)
        if (
            "time_s" not in queue_df.columns
            or "queue_depth_pkts" not in queue_df.columns
        ):
            continue
        queue_series = (
            queue_df.groupby("time_s", dropna=False)["queue_depth_pkts"]
            .max()
            .sort_index()
            .rename(label)
        )
        queue_frames.append(queue_series)
    if not queue_frames:
        return pd.DataFrame()
    return pd.concat(queue_frames, axis=1).sort_index()


def _create_env(active_app_path: Path) -> AgiEnv:
    env = AgiEnv.session_for_app(
        apps_path=active_app_path.parent,
        app=active_app_path.name,
        verbose=0,
    )
    env.init_done = True
    return env


page_context = prepare_queue_resilience_page(
    st,
    env_factory=_create_env,
    title="Relay resilience analysis",
    logo_title="Relay Resilience Analysis",
    caption=(
        "Use exported relay-queue telemetry to compare routing policies, queue hotspots, and delivery outcomes "
        "without reopening the producer code."
    ),
    data_dir_key=DATA_DIR_KEY,
    summary_glob_key=SUMMARY_GLOB_KEY,
    app_scope_key=APP_SCOPE_KEY,
    app_scoped_keys=APP_SCOPED_SESSION_DEFAULT_KEYS,
)

summary_label_to_path = {
    _relative_summary_label(path, page_context.artifact_root): path
    for path in page_context.summary_files
}
summary_labels = list(summary_label_to_path.keys())
default_selection = summary_labels[-1:] if summary_labels else []
if RUN_SELECTION_KEY in st.session_state:
    saved_selection = st.session_state.get(RUN_SELECTION_KEY)
    if isinstance(saved_selection, (list, tuple, set)) and not saved_selection:
        st.session_state[RUN_SELECTION_KEY] = []
    else:
        st.session_state[RUN_SELECTION_KEY] = _coerce_selection(
            saved_selection,
            summary_labels,
            fallback=default_selection[0] if default_selection else None,
        )
else:
    st.session_state[RUN_SELECTION_KEY] = default_selection

selected_run_labels = st.sidebar.multiselect(
    "Runs to compare",
    options=summary_labels,
    key=RUN_SELECTION_KEY,
)
if not selected_run_labels:
    st.info("Select at least one run in the sidebar.")
    st.stop()

if st.session_state.get(DETAIL_RUN_KEY) not in selected_run_labels:
    st.session_state[DETAIL_RUN_KEY] = selected_run_labels[0]
detailed_run_label = st.sidebar.selectbox(
    "Detailed run",
    options=selected_run_labels,
    key=DETAIL_RUN_KEY,
)

reference_run_label = detailed_run_label
if len(selected_run_labels) > 1:
    if st.session_state.get(REFERENCE_RUN_KEY) not in selected_run_labels:
        st.session_state[REFERENCE_RUN_KEY] = selected_run_labels[0]
    reference_run_label = st.sidebar.selectbox(
        "Reference run",
        options=selected_run_labels,
        key=REFERENCE_RUN_KEY,
    )

selected_paths = {label: summary_label_to_path[label] for label in selected_run_labels}
comparison_df = _build_comparison_frame(
    selected_paths,
    page_context.artifact_root,
    reference_run_label,
)
max_queue_compare_df = _build_max_queue_comparison_frame(selected_paths)

if len(selected_run_labels) > 1 and not comparison_df.empty:
    st.subheader("Run comparison")
    st.caption(
        "Select several exported runs to compare routing policy, queue buildup, and delivery outcomes "
        "before drilling into one detailed run below."
    )
    best_pdr_idx = (
        comparison_df["pdr"].idxmax() if comparison_df["pdr"].notna().any() else None
    )
    lowest_delay_idx = (
        comparison_df["mean_e2e_delay_ms"].idxmin()
        if comparison_df["mean_e2e_delay_ms"].notna().any()
        else None
    )
    lowest_queue_idx = (
        comparison_df["mean_queue_wait_ms"].idxmin()
        if comparison_df["mean_queue_wait_ms"].notna().any()
        else None
    )
    comparison_cols = st.columns(4)
    comparison_cols[0].metric("Runs selected", str(len(selected_run_labels)))
    comparison_cols[1].metric(
        "Best PDR",
        _safe_metric(comparison_df.loc[best_pdr_idx, "pdr"])
        if best_pdr_idx is not None
        else "n/a",
        comparison_df.loc[best_pdr_idx, "run_label"]
        if best_pdr_idx is not None
        else None,
    )
    comparison_cols[2].metric(
        "Lowest delay (ms)",
        _safe_metric(comparison_df.loc[lowest_delay_idx, "mean_e2e_delay_ms"])
        if lowest_delay_idx is not None
        else "n/a",
        comparison_df.loc[lowest_delay_idx, "run_label"]
        if lowest_delay_idx is not None
        else None,
    )
    comparison_cols[3].metric(
        "Lowest queue wait (ms)",
        _safe_metric(comparison_df.loc[lowest_queue_idx, "mean_queue_wait_ms"])
        if lowest_queue_idx is not None
        else "n/a",
        comparison_df.loc[lowest_queue_idx, "run_label"]
        if lowest_queue_idx is not None
        else None,
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
run = load_queue_resilience_run(
    st,
    Path(summary_path),
    csv_loader=pd.read_csv,
)

st.divider()
st.subheader(f"Detailed run: {detailed_run_label}")
render_queue_resilience_run(st, run)
