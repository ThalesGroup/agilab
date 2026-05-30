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
    active_app_scope_value,
    artifact_root as _page_artifact_root,
    configure_streamlit_page,
    discover_files as _page_discover_files,
    env_app_scope_value,
    ensure_repo_on_path as _page_ensure_repo_on_path,
    render_streamlit_page_header,
    resolve_active_app_path,
    reset_scoped_session_state,
    safe_float,
)


def _ensure_repo_on_path() -> None:
    _page_ensure_repo_on_path(__file__)


_ensure_repo_on_path()

from agi_env import AgiEnv


PAGE_KEY = "view_forecast_analysis"
APP_SCOPE_KEY = f"{PAGE_KEY}_active_app_path"
APP_SCOPED_SESSION_KEYS = (
    "env",
    "forecast_analysis_datadir",
    "forecast_metrics_glob",
    "forecast_predictions_glob",
)


def _resolve_active_app() -> Path:
    return resolve_active_app_path(error_fn=st.error, stop_fn=st.stop)


def _ensure_app_scoped_env() -> AgiEnv:
    env = st.session_state.get("env")
    scope_key = st.session_state.get(APP_SCOPE_KEY)
    if env is not None and scope_key is None:
        inferred_scope_key = env_app_scope_value(env)
        if inferred_scope_key is None:
            return env
        st.session_state[APP_SCOPE_KEY] = inferred_scope_key
        scope_key = inferred_scope_key

    active_app_path = _resolve_active_app()
    if scope_key != active_app_scope_value(active_app_path):
        reset_scoped_session_state(
            st.session_state,
            APP_SCOPE_KEY,
            active_app_path,
            keys=APP_SCOPED_SESSION_KEYS,
        )

    if "env" not in st.session_state:
        env = getattr(AgiEnv, "for_app", AgiEnv)(apps_path=active_app_path.parent, app=active_app_path.name, verbose=0)
        env.init_done = True
        st.session_state["env"] = env
    return st.session_state["env"]


def _default_artifact_root(env: AgiEnv) -> Path:
    return _page_artifact_root(env, "forecast_analysis")


def _discover_files(base: Path, pattern: str) -> list[Path]:
    return _page_discover_files(base, pattern)


def _safe_float(value: Any) -> float | None:
    return safe_float(value)


def _load_metrics(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_predictions(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "date" not in df.columns and "ds" in df.columns:
        df = df.rename(columns={"ds": "date"})
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


configure_streamlit_page(st, title="Forecast analysis")

env = _ensure_app_scoped_env()

render_streamlit_page_header(
    st,
    title="Forecast analysis",
    logo_title="Forecast Analysis",
    caption="Use exported metrics and prediction files to compare runs without reopening the notebooks.",
)

default_root = _default_artifact_root(env)
st.session_state.setdefault("forecast_analysis_datadir", str(default_root))
artifact_root_value = st.sidebar.text_input(
    "Artifact directory",
    key="forecast_analysis_datadir",
)
artifact_root = Path(artifact_root_value).expanduser()

st.session_state.setdefault("forecast_metrics_glob", "**/forecast_metrics.json")
metrics_pattern = st.sidebar.text_input(
    "Metrics glob",
    key="forecast_metrics_glob",
)
st.session_state.setdefault("forecast_predictions_glob", "**/forecast_predictions.csv")
predictions_pattern = st.sidebar.text_input(
    "Predictions glob",
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
