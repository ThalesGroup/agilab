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
    return Path(env.AGILAB_EXPORT_ABS) / env.target / "shap_explanation"


def _discover_files(base: Path, pattern: str) -> list[Path]:
    try:
        return sorted([path for path in base.glob(pattern) if path.is_file()], key=lambda p: p.as_posix())
    except (OSError, RuntimeError, TypeError, ValueError):
        return []


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


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
    if path is None:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


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

if "env" not in st.session_state:
    active_app_path = _resolve_active_app()
    env = AgiEnv(apps_path=active_app_path.parent, app=active_app_path.name, verbose=0)
    env.init_done = True
    st.session_state["env"] = env
else:
    env = st.session_state["env"]

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
