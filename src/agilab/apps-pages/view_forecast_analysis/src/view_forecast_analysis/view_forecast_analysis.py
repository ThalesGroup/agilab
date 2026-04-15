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
    return Path(env.AGILAB_EXPORT_ABS) / env.target / "forecast_analysis"


def _discover_files(base: Path, pattern: str) -> list[Path]:
    try:
        return sorted([path for path in base.glob(pattern) if path.is_file()], key=lambda p: p.as_posix())
    except Exception:
        return []


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _load_metrics(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_predictions(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "date" not in df.columns and "ds" in df.columns:
        df = df.rename(columns={"ds": "date"})
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


st.set_page_config(layout="wide")

if "env" not in st.session_state:
    active_app_path = _resolve_active_app()
    env = AgiEnv(apps_path=active_app_path.parent, app=active_app_path.name, verbose=0)
    env.init_done = True
    st.session_state["env"] = env
else:
    env = st.session_state["env"]

render_logo("Forecast Analysis")
st.title("Forecast analysis")
st.caption(
    "Use exported metrics and prediction files to compare runs without reopening the notebooks."
)

default_root = _default_artifact_root(env)
artifact_root_value = st.sidebar.text_input(
    "Artifact directory",
    value=st.session_state.setdefault("forecast_analysis_datadir", str(default_root)),
    key="forecast_analysis_datadir",
)
artifact_root = Path(artifact_root_value).expanduser()

metrics_pattern = st.sidebar.text_input(
    "Metrics glob",
    value=st.session_state.setdefault("forecast_metrics_glob", "**/forecast_metrics.json"),
    key="forecast_metrics_glob",
)
predictions_pattern = st.sidebar.text_input(
    "Predictions glob",
    value=st.session_state.setdefault("forecast_predictions_glob", "**/forecast_predictions.csv"),
    key="forecast_predictions_glob",
)

metrics_files = _discover_files(artifact_root, metrics_pattern) if artifact_root.exists() else []
prediction_files = _discover_files(artifact_root, predictions_pattern) if artifact_root.exists() else []

if not artifact_root.exists():
    st.warning(f"Artifact directory does not exist yet: {artifact_root}")
    st.stop()

if not metrics_files:
    st.warning(f"No metrics file found in {artifact_root} with pattern {metrics_pattern!r}.")
    st.stop()

if not prediction_files:
    st.warning(f"No predictions file found in {artifact_root} with pattern {predictions_pattern!r}.")
    st.stop()

metrics_path = st.sidebar.selectbox(
    "Metrics file",
    options=metrics_files,
    format_func=lambda path: str(Path(path).relative_to(artifact_root)),
)
predictions_path = st.sidebar.selectbox(
    "Predictions file",
    options=prediction_files,
    format_func=lambda path: str(Path(path).relative_to(artifact_root)),
)

metrics = _load_metrics(Path(metrics_path))
predictions = _load_predictions(Path(predictions_path))

meta_left, meta_right = st.columns([2, 1])
with meta_left:
    st.subheader("Migration value")
    st.markdown(
        "- notebook outputs become stable exported artifacts\n"
        "- the same analysis page can be reused across runs\n"
        "- metrics and predictions are visible without re-running the notebook kernel"
    )
with meta_right:
    st.subheader("Run metadata")
    meta_fields = {
        "scenario": metrics.get("scenario", ""),
        "station": metrics.get("station", ""),
        "target": metrics.get("target", ""),
        "model": metrics.get("model_name", ""),
        "horizon_days": metrics.get("horizon_days", ""),
    }
    st.json({k: v for k, v in meta_fields.items() if v not in ("", None)})

metric_columns = st.columns(3)
metric_specs = [
    ("MAE", metrics.get("mae")),
    ("RMSE", metrics.get("rmse")),
    ("MAPE", metrics.get("mape")),
]
for col, (label, raw_value) in zip(metric_columns, metric_specs):
    value = _safe_float(raw_value)
    col.metric(label, f"{value:.2f}" if value is not None else "n/a")

if "date" in predictions.columns and {"y_true", "y_pred"}.issubset(predictions.columns):
    chart_df = predictions.copy().sort_values("date").set_index("date")[["y_true", "y_pred"]]
    st.subheader("Observed vs predicted")
    st.line_chart(chart_df)

st.subheader("Predictions table")
st.dataframe(predictions, width="stretch", hide_index=True)

notes = str(metrics.get("notes", "") or "").strip()
if notes:
    st.subheader("Notes")
    st.info(notes)
