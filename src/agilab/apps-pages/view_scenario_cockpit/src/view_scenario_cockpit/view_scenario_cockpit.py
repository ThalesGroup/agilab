# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

from __future__ import annotations

import argparse
import importlib.util
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


RUN_SELECTION_KEY = "scenario_cockpit_selected_runs"
BASELINE_RUN_KEY = "scenario_cockpit_baseline_run"
CANDIDATE_RUN_KEY = "scenario_cockpit_candidate_run"
DATA_DIR_KEY = "scenario_cockpit_datadir"
SUMMARY_GLOB_KEY = "scenario_cockpit_summary_glob"

def _load_page_meta() -> tuple[str, str]:
    if __package__:
        from .page_meta import PAGE_LOGO, PAGE_TITLE

        return PAGE_LOGO, PAGE_TITLE

    _meta_path = Path(__file__).with_name("page_meta.py")
    _meta_spec = importlib.util.spec_from_file_location("view_scenario_cockpit_page_meta", _meta_path)
    if _meta_spec is None or _meta_spec.loader is None:  # pragma: no cover - defensive fallback
        raise RuntimeError(f"Unable to load page metadata from {_meta_path}")
    _meta_module = importlib.util.module_from_spec(_meta_spec)
    _meta_spec.loader.exec_module(_meta_module)
    return _meta_module.PAGE_LOGO, _meta_module.PAGE_TITLE


def _load_evidence_helpers():
    if __package__:
        from . import evidence

        return evidence

    _evidence_path = Path(__file__).with_name("evidence.py")
    _evidence_spec = importlib.util.spec_from_file_location(
        "view_scenario_cockpit_evidence",
        _evidence_path,
    )
    if _evidence_spec is None or _evidence_spec.loader is None:  # pragma: no cover - defensive fallback
        raise RuntimeError(f"Unable to load evidence helpers from {_evidence_path}")
    _evidence_module = importlib.util.module_from_spec(_evidence_spec)
    _evidence_spec.loader.exec_module(_evidence_module)
    return _evidence_module


PAGE_LOGO, PAGE_TITLE = _load_page_meta()


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


def _coerce_selection(saved_value: Any, options: list[str], *, fallback: list[str] | None = None) -> list[str]:
    if isinstance(saved_value, str):
        candidates = [saved_value]
    elif isinstance(saved_value, (list, tuple, set)):
        candidates = [str(value) for value in saved_value]
    else:
        candidates = []
    selected = [value for value in candidates if value in options]
    if selected:
        return selected
    if fallback:
        return [value for value in fallback if value in options]
    return options[-2:] if len(options) >= 2 else options[-1:]


def _safe_metric(value: Any) -> str:
    numeric = _safe_float(value)
    if numeric is None:
        return "n/a"
    return f"{numeric:.3f}"


_evidence_helpers = _load_evidence_helpers()
EVIDENCE_SCHEMA = _evidence_helpers.EVIDENCE_SCHEMA
PEER_ARTIFACT_SUFFIXES = _evidence_helpers.PEER_ARTIFACT_SUFFIXES
PIPELINE_ARTIFACTS = _evidence_helpers.PIPELINE_ARTIFACTS
_discover_files = _evidence_helpers.discover_files
_load_json = _evidence_helpers.load_json
_peer_file = _evidence_helpers.peer_file
_relative_label = _evidence_helpers.relative_label
_scenario_row = _evidence_helpers.scenario_row
_build_comparison_frame = _evidence_helpers.build_comparison_frame
_safe_float = _evidence_helpers.safe_float
_json_safe = _evidence_helpers.json_safe
_hash_file = _evidence_helpers.hash_file
_artifact_record = _evidence_helpers.artifact_record
_evidence_artifacts = _evidence_helpers.evidence_artifacts
_candidate_gate = _evidence_helpers.candidate_gate
_build_evidence_bundle = _evidence_helpers.build_evidence_bundle


st.set_page_config(layout="wide")

if "env" not in st.session_state:
    active_app_path = _resolve_active_app()
    env = AgiEnv(apps_path=active_app_path.parent, app=active_app_path.name, verbose=0)
    env.init_done = True
    st.session_state["env"] = env
else:
    env = st.session_state["env"]

render_logo(PAGE_LOGO)
st.title(PAGE_TITLE)
st.caption(
    "Compare exported scenario runs, choose a baseline and candidate, then download a hashed evidence bundle "
    "that explains the promotion decision."
)
st.info(
    "This page reuses the queue-analysis artifact contract exported by the UAV queue and relay demos. "
    "It does not rerun the scenario; it packages existing evidence for review."
)

default_root = _default_artifact_root(env)
st.session_state.setdefault(DATA_DIR_KEY, str(default_root))
artifact_root_value = st.sidebar.text_input("Artifact directory", key=DATA_DIR_KEY)
artifact_root = Path(artifact_root_value).expanduser()

st.session_state.setdefault(SUMMARY_GLOB_KEY, "**/*_summary_metrics.json")
metrics_pattern = st.sidebar.text_input("Summary glob", key=SUMMARY_GLOB_KEY)

summary_files = _discover_files(artifact_root, metrics_pattern) if artifact_root.exists() else []

if not artifact_root.exists():
    st.warning(f"Artifact directory does not exist yet: {artifact_root}")
    st.stop()

if not summary_files:
    st.warning(f"No summary metrics file found in {artifact_root} with pattern {metrics_pattern!r}.")
    st.stop()

summary_label_to_path = {_relative_label(path, artifact_root): path for path in summary_files}
summary_labels = list(summary_label_to_path.keys())
default_selection = summary_labels[-2:] if len(summary_labels) >= 2 else summary_labels[-1:]

if RUN_SELECTION_KEY in st.session_state:
    st.session_state[RUN_SELECTION_KEY] = _coerce_selection(
        st.session_state.get(RUN_SELECTION_KEY),
        summary_labels,
        fallback=default_selection,
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

for key, default in (
    (BASELINE_RUN_KEY, selected_run_labels[0]),
    (CANDIDATE_RUN_KEY, selected_run_labels[-1]),
):
    if st.session_state.get(key) not in selected_run_labels:
        st.session_state[key] = default

baseline_run_label = st.sidebar.selectbox("Baseline run", options=selected_run_labels, key=BASELINE_RUN_KEY)
candidate_run_label = st.sidebar.selectbox("Candidate run", options=selected_run_labels, key=CANDIDATE_RUN_KEY)

selected_paths = {label: summary_label_to_path[label] for label in selected_run_labels}
comparison_df = _build_comparison_frame(selected_paths, artifact_root, baseline_run_label)
gate = _candidate_gate(comparison_df, candidate_run_label)
candidate_row = (
    comparison_df.loc[comparison_df["run_label"] == candidate_run_label].iloc[0]
    if not comparison_df.empty and candidate_run_label in set(comparison_df["run_label"])
    else None
)

header_columns = st.columns(4)
header_columns[0].metric("Runs selected", str(len(selected_run_labels)))
header_columns[1].metric("Decision", gate["status"])
header_columns[2].metric(
    "PDR delta",
    _safe_metric(candidate_row.get("delta_pdr_vs_baseline")) if candidate_row is not None else "n/a",
)
header_columns[3].metric(
    "Delay delta (ms)",
    _safe_metric(candidate_row.get("delta_delay_ms_vs_baseline")) if candidate_row is not None else "n/a",
)

st.subheader("Scenario comparison")
st.caption(
    f"Baseline run: `{baseline_run_label}`. Candidate run: `{candidate_run_label}`. "
    "Positive PDR delta is better; negative delay, queue wait, and max queue deltas are better."
)
st.dataframe(comparison_df.drop(columns=["summary_path"], errors="ignore"), width="stretch", hide_index=True)

chart_columns = [
    column
    for column in ("pdr", "mean_e2e_delay_ms", "mean_queue_wait_ms", "max_queue_depth_pkts")
    if column in comparison_df.columns
]
if chart_columns:
    st.subheader("Run metrics")
    chart_df = comparison_df.set_index("run_label")[chart_columns]
    st.bar_chart(chart_df)

st.subheader("Candidate gate")
st.json(gate)

evidence_bundle = _build_evidence_bundle(
    selected_paths=selected_paths,
    artifact_root=artifact_root,
    comparison_df=comparison_df,
    baseline_label=baseline_run_label,
    candidate_label=candidate_run_label,
)
bundle_json = json.dumps(evidence_bundle, indent=2, sort_keys=True)

st.download_button(
    "Download scenario evidence bundle",
    data=bundle_json,
    file_name="scenario_evidence_bundle.json",
    mime="application/json",
)

artifact_df = pd.DataFrame(evidence_bundle["artifacts"])
if not artifact_df.empty:
    st.subheader("Artifact traceability")
    st.dataframe(artifact_df, width="stretch", hide_index=True)
    missing = artifact_df.loc[~artifact_df["exists"].astype(bool), "relative_path"].tolist()
    if missing:
        st.warning("Some optional peer artifacts are missing from the evidence bundle.")
        st.code("\n".join(missing), language="text")
