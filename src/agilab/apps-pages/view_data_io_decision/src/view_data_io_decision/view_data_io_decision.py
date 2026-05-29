# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from agi_pages.runtime import (
    artifact_root as _page_artifact_root,
    discover_files as _page_discover_files,
    ensure_repo_on_path as _page_ensure_repo_on_path,
    relative_label as _page_relative_label,
    resolve_active_app_path,
)


def _ensure_repo_on_path() -> None:
    _page_ensure_repo_on_path(__file__)


_ensure_repo_on_path()

from agi_env import AgiEnv
from agi_gui.pagelib import render_logo

ARTIFACT_ROOT_KEY = "decision_evidence_artifact_root"
RUN_SELECTION_KEY = "decision_evidence_selected_run"
SUMMARY_GLOB_KEY = "decision_evidence_summary_glob"
APP_SCOPE_KEY = "decision_evidence_active_app_scope"
APP_SCOPED_SESSION_DEFAULT_KEYS = (
    ARTIFACT_ROOT_KEY,
    RUN_SELECTION_KEY,
    SUMMARY_GLOB_KEY,
)


def _resolve_active_app() -> Path:
    return resolve_active_app_path(error_fn=st.error, stop_fn=st.stop)


def _default_artifact_root(env: AgiEnv) -> Path:
    return _page_artifact_root(env, "data_io_decision")


def _reset_app_scoped_session_defaults(active_app_path: Path) -> bool:
    """Clear persisted Decision Evidence defaults when the active app changes."""

    app_scope = str(active_app_path.resolve())
    if st.session_state.get(APP_SCOPE_KEY) == app_scope:
        return False
    for key in APP_SCOPED_SESSION_DEFAULT_KEYS:
        st.session_state.pop(key, None)
    st.session_state[APP_SCOPE_KEY] = app_scope
    return True


def _discover_files(base: Path, pattern: str) -> list[Path]:
    return _page_discover_files(base, pattern)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _peer_path(summary_path: Path, suffix: str, extension: str) -> Path:
    stem = summary_path.name.removesuffix("_summary_metrics.json")
    return summary_path.with_name(f"{stem}_{suffix}.{extension}")


def _relative_summary_label(path: Path, artifact_root: Path) -> str:
    return _page_relative_label(path, artifact_root)


def _format_delta(value: Any, *, suffix: str = "%") -> str | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    sign = "+" if numeric > 0 else ""
    return f"{sign}{numeric:.1f}{suffix}"


def _read_csv_if_present(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


st.set_page_config(layout="wide")

active_app_path = _resolve_active_app()
app_scope_changed = _reset_app_scoped_session_defaults(active_app_path)
if "env" not in st.session_state or app_scope_changed:
    env = getattr(AgiEnv, "for_app", AgiEnv)(apps_path=active_app_path.parent, app=active_app_path.name, verbose=0)
    env.init_done = True
    st.session_state["env"] = env
else:
    env = st.session_state["env"]

render_logo("Decision Evidence")
st.title("Decision evidence")
st.caption(
    "Inspect exported decision artifacts: pipeline generation, failure injection, "
    "re-planning, and final evidence."
)

default_root = _default_artifact_root(env)
st.session_state.setdefault(ARTIFACT_ROOT_KEY, str(default_root))
artifact_root_value = st.sidebar.text_input(
    "Artifact directory",
    key=ARTIFACT_ROOT_KEY,
)
artifact_root = Path(artifact_root_value).expanduser()

st.session_state.setdefault(SUMMARY_GLOB_KEY, "**/*_summary_metrics.json")
summary_pattern = st.sidebar.text_input(
    "Summary glob",
    key=SUMMARY_GLOB_KEY,
)

if not artifact_root.exists():
    st.warning(f"Artifact directory does not exist yet: {artifact_root}")
    st.stop()

summary_files = _discover_files(artifact_root, summary_pattern)
if not summary_files:
    st.warning(f"No summary metrics file found in {artifact_root} with pattern {summary_pattern!r}.")
    st.stop()

summary_label_to_path = {_relative_summary_label(path, artifact_root): path for path in summary_files}
summary_labels = list(summary_label_to_path.keys())
if st.session_state.get(RUN_SELECTION_KEY) not in summary_labels:
    st.session_state[RUN_SELECTION_KEY] = summary_labels[-1]
selected_label = st.sidebar.selectbox(
    "Run",
    options=summary_labels,
    key=RUN_SELECTION_KEY,
)
summary_path = summary_label_to_path[selected_label]
summary = _load_json(summary_path)

st.subheader("Final decision")
metric_cols = st.columns(4)
metric_cols[0].metric("Selected strategy", str(summary.get("selected_strategy", "n/a")))
metric_cols[1].metric(
    "Latency selected",
    f"{float(summary.get('latency_ms_selected', 0.0)):.1f} ms",
    _format_delta(summary.get("latency_delta_pct_vs_no_replan")),
    delta_color="inverse",
)
metric_cols[2].metric(
    "Cost selected",
    f"{float(summary.get('cost_selected', 0.0)):.1f}",
    _format_delta(summary.get("cost_delta_pct_vs_no_replan")),
    delta_color="inverse",
)
metric_cols[3].metric(
    "Reliability selected",
    f"{float(summary.get('reliability_selected', 0.0)):.3f}",
    _format_delta(summary.get("reliability_delta_pct_vs_no_replan")),
)

st.caption(
    "Deltas are measured against the no-replan outcome after the injected mission event. "
    "Negative latency/cost and positive reliability indicate useful adaptation."
)

with st.expander("Summary metrics", expanded=False):
    st.json(summary)

pipeline_path = _peer_path(summary_path, "generated_pipeline", "json")
decision_path = _peer_path(summary_path, "mission_decision", "json")
pipeline = _load_json(pipeline_path) if pipeline_path.is_file() else {}
decision = _load_json(decision_path) if decision_path.is_file() else {}

left, right = st.columns([1.1, 1.0])
with left:
    st.subheader("Generated pipeline")
    stages = pipeline.get("stages", []) if isinstance(pipeline, dict) else []
    if stages:
        st.dataframe(pd.DataFrame(stages), width="stretch", hide_index=True)
    else:
        st.info("No generated pipeline artifact found for this run.")
with right:
    st.subheader("Mission event")
    events = decision.get("applied_events", []) if isinstance(decision, dict) else []
    if events:
        st.dataframe(pd.DataFrame(events), width="stretch", hide_index=True)
    else:
        st.info("No selected failure event was applied.")

st.subheader("Route scoring")
routes_df = _read_csv_if_present(_peer_path(summary_path, "candidate_routes", "csv"))
if routes_df.empty:
    st.info("No candidate route table found.")
else:
    st.dataframe(routes_df, width="stretch", hide_index=True)

st.subheader("Decision timeline")
timeline_df = _read_csv_if_present(_peer_path(summary_path, "decision_timeline", "csv"))
if timeline_df.empty:
    st.info("No decision timeline found.")
else:
    st.dataframe(timeline_df, width="stretch", hide_index=True)

with st.expander("Input stream and feature evidence", expanded=False):
    sensor_df = _read_csv_if_present(_peer_path(summary_path, "sensor_stream", "csv"))
    feature_df = _read_csv_if_present(_peer_path(summary_path, "feature_table", "csv"))
    if not sensor_df.empty:
        st.markdown("Sensor and event stream")
        st.dataframe(sensor_df, width="stretch", hide_index=True)
    if not feature_df.empty:
        st.markdown("Feature table")
        st.dataframe(feature_df, width="stretch", hide_index=True)
    if sensor_df.empty and feature_df.empty:
        st.info("No stream or feature evidence artifacts found.")
