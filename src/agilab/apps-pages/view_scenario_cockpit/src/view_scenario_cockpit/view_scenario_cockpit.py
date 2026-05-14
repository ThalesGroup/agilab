# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import importlib.util
import json
import math
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

EVIDENCE_SCHEMA = "agilab.scenario_evidence_bundle.v1"
PEER_ARTIFACT_SUFFIXES = (
    "queue_timeseries",
    "packet_events",
    "node_positions",
    "routing_summary",
)
PIPELINE_ARTIFACTS = (
    "pipeline/topology.gml",
    "pipeline/allocations_steps.csv",
    "pipeline/_trajectory_summary.json",
)


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


def _discover_files(base: Path, pattern: str) -> list[Path]:
    try:
        return sorted([path for path in base.glob(pattern) if path.is_file()], key=lambda p: p.as_posix())
    except (OSError, RuntimeError, TypeError, ValueError):
        return []


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _peer_file(path: Path, suffix: str) -> Path:
    stem = path.name.removesuffix("_summary_metrics.json")
    return path.with_name(f"{stem}_{suffix}.csv")


def _relative_label(path: Path, artifact_root: Path) -> str:
    try:
        return str(path.relative_to(artifact_root))
    except (RuntimeError, TypeError, ValueError):
        return path.name


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


def _scenario_row(summary_path: Path, artifact_root: Path) -> dict[str, Any]:
    summary = _load_json(summary_path)
    return {
        "run_label": _relative_label(summary_path, artifact_root),
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
        "summary_path": str(summary_path),
    }


def _build_comparison_frame(selected_paths: dict[str, Path], artifact_root: Path, baseline_label: str) -> pd.DataFrame:
    rows = [_scenario_row(path, artifact_root) for path in selected_paths.values()]
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
    if baseline_label in comparison_df["run_label"].values:
        baseline_row = comparison_df.loc[comparison_df["run_label"] == baseline_label].iloc[0]
        comparison_df["delta_pdr_vs_baseline"] = comparison_df["pdr"] - baseline_row["pdr"]
        comparison_df["delta_delay_ms_vs_baseline"] = (
            comparison_df["mean_e2e_delay_ms"] - baseline_row["mean_e2e_delay_ms"]
        )
        comparison_df["delta_queue_wait_ms_vs_baseline"] = (
            comparison_df["mean_queue_wait_ms"] - baseline_row["mean_queue_wait_ms"]
        )
        comparison_df["delta_max_queue_vs_baseline"] = (
            comparison_df["max_queue_depth_pkts"] - baseline_row["max_queue_depth_pkts"]
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
        "delta_pdr_vs_baseline",
        "delta_delay_ms_vs_baseline",
        "delta_queue_wait_ms_vs_baseline",
        "delta_max_queue_vs_baseline",
        "summary_path",
    ]
    return comparison_df[[column for column in ordered_columns if column in comparison_df.columns]]


def _safe_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def _safe_metric(value: Any) -> str:
    numeric = _safe_float(value)
    if numeric is None:
        return "n/a"
    return f"{numeric:.3f}"


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if pd.isna(value):
        return None
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    return str(value)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_record(path: Path, artifact_root: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": str(path),
        "relative_path": _relative_label(path, artifact_root),
        "exists": path.is_file(),
    }
    if path.is_file():
        record["sha256"] = _hash_file(path)
        record["bytes"] = path.stat().st_size
    return record


def _evidence_artifacts(summary_path: Path, artifact_root: Path) -> list[dict[str, Any]]:
    run_dir = summary_path.parent
    artifact_paths = [summary_path]
    artifact_paths.extend(_peer_file(summary_path, suffix) for suffix in PEER_ARTIFACT_SUFFIXES)
    artifact_paths.extend(run_dir / relative for relative in PIPELINE_ARTIFACTS)
    for trajectory in _discover_files(run_dir / "pipeline", "*_trajectory*.csv"):
        if trajectory not in artifact_paths:
            artifact_paths.append(trajectory)
    return [_artifact_record(path, artifact_root) for path in artifact_paths]


def _candidate_gate(comparison_df: pd.DataFrame, candidate_label: str) -> dict[str, Any]:
    if comparison_df.empty or candidate_label not in set(comparison_df.get("run_label", [])):
        return {
            "candidate": candidate_label,
            "status": "missing-candidate",
            "checks": [],
        }
    candidate = comparison_df.loc[comparison_df["run_label"] == candidate_label].iloc[0]
    check_specs = [
        ("pdr_not_lower", candidate.get("delta_pdr_vs_baseline"), "greater_or_equal"),
        ("delay_not_higher", candidate.get("delta_delay_ms_vs_baseline"), "less_or_equal"),
        ("queue_wait_not_higher", candidate.get("delta_queue_wait_ms_vs_baseline"), "less_or_equal"),
        ("max_queue_not_higher", candidate.get("delta_max_queue_vs_baseline"), "less_or_equal"),
    ]
    checks: list[dict[str, Any]] = []
    for name, raw_value, direction in check_specs:
        value = _safe_float(raw_value)
        if value is None:
            passed = False
        elif direction == "greater_or_equal":
            passed = value >= 0
        else:
            passed = value <= 0
        checks.append(
            {
                "name": name,
                "delta": value,
                "direction": direction,
                "passed": passed,
            }
        )
    status = "promotable" if checks and all(check["passed"] for check in checks) else "needs-review"
    return {
        "candidate": candidate_label,
        "status": status,
        "checks": checks,
    }


def _build_evidence_bundle(
    *,
    selected_paths: dict[str, Path],
    artifact_root: Path,
    comparison_df: pd.DataFrame,
    baseline_label: str,
    candidate_label: str,
) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    for path in selected_paths.values():
        artifacts.extend(_evidence_artifacts(path, artifact_root))
    selected_runs = comparison_df.drop(columns=["summary_path"], errors="ignore").to_dict(orient="records")
    return _json_safe(
        {
            "schema": EVIDENCE_SCHEMA,
            "generated_at": datetime.now(UTC).isoformat(),
            "source_page": "view_scenario_cockpit",
            "artifact_root": str(artifact_root),
            "baseline_run": baseline_label,
            "candidate_run": candidate_label,
            "gate": _candidate_gate(comparison_df, candidate_label),
            "selected_runs": selected_runs,
            "artifacts": artifacts,
        }
    )


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
