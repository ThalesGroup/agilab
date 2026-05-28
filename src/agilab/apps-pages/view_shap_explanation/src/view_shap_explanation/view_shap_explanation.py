# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from agi_pages.runtime import (
    artifact_root as _page_artifact_root,
    discover_files as _page_discover_files,
    ensure_repo_on_path as _page_ensure_repo_on_path,
    load_json_object,
    resolve_active_app_path,
    safe_float,
)


FEATURE_ALIASES = ("feature", "feature_name", "column", "name")
SHAP_VALUE_ALIASES = ("shap_value", "value", "contribution", "phi", "importance")
FEATURE_VALUE_ALIASES = ("feature_value", "input_value", "raw_value", "actual_value")
WIDE_EXCLUDE_COLUMNS = {
    "base_value",
    "expected_value",
    "instance_id",
    "model_name",
    "prediction",
    "target",
}


def _ensure_repo_on_path() -> None:
    _page_ensure_repo_on_path(__file__)


_ensure_repo_on_path()

from agi_env import AgiEnv
from agi_gui.pagelib import render_logo


PAGE_KEY = "view_shap_explanation"
APP_SCOPE_KEY = f"{PAGE_KEY}_active_app_path"
APP_SCOPED_SESSION_KEYS = (
    "env",
    "shap_explanation_datadir",
    "shap_values_glob",
    "shap_feature_values_glob",
    "shap_metadata_glob",
)


def _resolve_active_app() -> Path:
    return resolve_active_app_path(error_fn=st.error, stop_fn=st.stop)


def _env_app_scope_key(env: Any) -> str | None:
    app_path = getattr(env, "app_path", None)
    if app_path:
        return str(Path(app_path).resolve())
    apps_path = getattr(env, "apps_path", None)
    app = getattr(env, "app", None)
    if apps_path and app:
        return str((Path(apps_path) / str(app)).resolve())
    return None


def _ensure_app_scoped_env() -> AgiEnv:
    env = st.session_state.get("env")
    scope_key = st.session_state.get(APP_SCOPE_KEY)
    if env is not None and scope_key is None:
        inferred_scope_key = _env_app_scope_key(env)
        if inferred_scope_key is None:
            return env
        st.session_state[APP_SCOPE_KEY] = inferred_scope_key
        scope_key = inferred_scope_key

    active_app_path = _resolve_active_app()
    active_app_key = str(active_app_path.resolve())
    if scope_key != active_app_key:
        for key in APP_SCOPED_SESSION_KEYS:
            st.session_state.pop(key, None)
        st.session_state[APP_SCOPE_KEY] = active_app_key

    if "env" not in st.session_state:
        env = AgiEnv(apps_path=active_app_path.parent, app=active_app_path.name, verbose=0)
        env.init_done = True
        st.session_state["env"] = env
    return st.session_state["env"]


def _default_artifact_root(env: AgiEnv) -> Path:
    return _page_artifact_root(env, "shap_explanation")


def _discover_files(base: Path, pattern: str) -> list[Path]:
    return _page_discover_files(base, pattern)


def _safe_float(value: Any) -> float | None:
    return safe_float(value)


def _first_existing_column(df: pd.DataFrame, aliases: tuple[str, ...]) -> str | None:
    lower_to_original = {str(column).casefold(): str(column) for column in df.columns}
    for alias in aliases:
        column = lower_to_original.get(alias.casefold())
        if column is not None:
            return column
    return None


def _load_table(path: Path) -> pd.DataFrame:
    if path.suffix.casefold() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _load_json(path: Path | None) -> dict[str, Any]:
    return load_json_object(path)


def _coerce_shap_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["feature", "shap_value", "abs_shap_value"])

    feature_col = _first_existing_column(df, FEATURE_ALIASES)
    shap_col = _first_existing_column(df, SHAP_VALUE_ALIASES)
    feature_value_col = _first_existing_column(df, FEATURE_VALUE_ALIASES)
    if feature_col and shap_col:
        result = pd.DataFrame(
            {
                "feature": df[feature_col].astype(str),
                "shap_value": pd.to_numeric(df[shap_col], errors="coerce"),
            }
        )
        if feature_value_col:
            result["feature_value"] = df[feature_value_col]
    else:
        first_row = df.iloc[0]
        rows: list[dict[str, Any]] = []
        for column, raw_value in first_row.items():
            if str(column).casefold() in WIDE_EXCLUDE_COLUMNS:
                continue
            value = _safe_float(raw_value)
            if value is None:
                continue
            rows.append({"feature": str(column), "shap_value": value})
        result = pd.DataFrame(rows)

    if result.empty:
        return pd.DataFrame(columns=["feature", "shap_value", "abs_shap_value"])
    result = result.dropna(subset=["shap_value"]).copy()
    result["abs_shap_value"] = result["shap_value"].abs()
    return result.sort_values(["abs_shap_value", "feature"], ascending=[False, True]).reset_index(drop=True)


def _coerce_feature_values(df: pd.DataFrame) -> pd.DataFrame:
    feature_col = _first_existing_column(df, FEATURE_ALIASES)
    value_col = _first_existing_column(df, FEATURE_VALUE_ALIASES)
    if feature_col and value_col:
        return pd.DataFrame({"feature": df[feature_col].astype(str), "feature_value": df[value_col]})
    if df.empty:
        return pd.DataFrame(columns=["feature", "feature_value"])
    first_row = df.iloc[0]
    return pd.DataFrame(
        [{"feature": str(column), "feature_value": value} for column, value in first_row.items()]
    )


def _merge_feature_values(shap_frame: pd.DataFrame, feature_frame: pd.DataFrame) -> pd.DataFrame:
    if shap_frame.empty or feature_frame.empty or "feature_value" in shap_frame.columns:
        return shap_frame
    values = _coerce_feature_values(feature_frame)
    if values.empty:
        return shap_frame
    return shap_frame.merge(values, on="feature", how="left")


def _metadata_value(metadata: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in metadata and metadata[key] not in ("", None):
            return metadata[key]
    return None


def _state_text_input(key: str, label: str, default_value: str) -> str:
    if key not in st.session_state:
        st.session_state[key] = default_value
    return st.sidebar.text_input(label, key=key)


st.set_page_config(layout="wide")

env = _ensure_app_scoped_env()

render_logo("SHAP Explanation")
st.title("SHAP explanation")
st.caption(
    "Inspect local feature attributions exported by SHAPKit, shap, or any compatible explainer."
)

default_root = _default_artifact_root(env)
artifact_root_value = _state_text_input(
    "shap_explanation_datadir",
    "Artifact directory",
    str(default_root),
)
artifact_root = Path(artifact_root_value).expanduser()

shap_pattern = _state_text_input(
    "shap_values_glob",
    "SHAP values glob",
    "**/shap_values.*",
)
feature_values_pattern = _state_text_input(
    "shap_feature_values_glob",
    "Feature values glob",
    "**/feature_values.*",
)
metadata_pattern = _state_text_input(
    "shap_metadata_glob",
    "Metadata glob",
    "**/explanation_summary.json",
)

if not artifact_root.exists():
    st.warning(f"Artifact directory does not exist yet: {artifact_root}")
    st.stop()

shap_files = _discover_files(artifact_root, shap_pattern)
feature_files = _discover_files(artifact_root, feature_values_pattern)
metadata_files = _discover_files(artifact_root, metadata_pattern)

if not shap_files:
    st.warning(f"No SHAP values file found in {artifact_root} with pattern {shap_pattern!r}.")
    st.stop()

shap_path = st.sidebar.selectbox(
    "SHAP values file",
    options=shap_files,
    format_func=lambda path: str(Path(path).relative_to(artifact_root)),
)
feature_path = st.sidebar.selectbox(
    "Feature values file",
    options=[*feature_files, None] if feature_files else [None],
    format_func=lambda path: "none" if path is None else str(Path(path).relative_to(artifact_root)),
)
metadata_path = st.sidebar.selectbox(
    "Metadata file",
    options=[*metadata_files, None] if metadata_files else [None],
    format_func=lambda path: "none" if path is None else str(Path(path).relative_to(artifact_root)),
)

metadata = _load_json(Path(metadata_path) if metadata_path else None)
shap_frame = _coerce_shap_frame(_load_table(Path(shap_path)))
feature_frame = _load_table(Path(feature_path)) if feature_path else pd.DataFrame()
shap_frame = _merge_feature_values(shap_frame, feature_frame)

if shap_frame.empty:
    st.warning("The selected SHAP values file does not contain previewable feature attributions.")
    st.stop()

top_feature = shap_frame.iloc[0]
prediction = _safe_float(_metadata_value(metadata, "prediction", "model_output", "predicted_value"))
base_value = _safe_float(_metadata_value(metadata, "base_value", "expected_value", "reference_value"))
delta = None if prediction is None or base_value is None else prediction - base_value

metric_columns = st.columns(4)
metric_columns[0].metric("Top driver", str(top_feature["feature"]))
metric_columns[1].metric("Top contribution", f"{float(top_feature['shap_value']):+.4f}")
metric_columns[2].metric("Prediction", f"{prediction:.4f}" if prediction is not None else "n/a")
metric_columns[3].metric("Prediction - base", f"{delta:+.4f}" if delta is not None else "n/a")

left, right = st.columns([2, 1])
with left:
    st.subheader("Feature contributions")
    chart_frame = shap_frame.set_index("feature")[["shap_value"]]
    st.bar_chart(chart_frame)
with right:
    st.subheader("Explanation metadata")
    metadata_view = {
        "model": _metadata_value(metadata, "model_name", "model"),
        "target": _metadata_value(metadata, "target", "class_name", "output_name"),
        "instance": _metadata_value(metadata, "instance_id", "sample_id", "row_id"),
        "explainer": _metadata_value(metadata, "explainer", "library"),
    }
    compact_metadata = {key: value for key, value in metadata_view.items() if value not in ("", None)}
    st.json(compact_metadata or {"status": "no metadata file selected"})

st.subheader("Attribution table")
display_columns = ["feature", "shap_value", "abs_shap_value"]
if "feature_value" in shap_frame.columns:
    display_columns.insert(1, "feature_value")
st.dataframe(shap_frame[display_columns], width="stretch", hide_index=True)

with st.expander("Producer contract"):
    st.markdown(
        "Export `shap_values.csv` with `feature` and `shap_value` columns. "
        "Optionally export `feature_values.csv` and `explanation_summary.json`. "
        "The producer can use SHAPKit, the modern `shap` package, or a custom explainer."
    )
