# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

from __future__ import annotations

import ast
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import tomllib
from agi_pages.runtime import (
    ensure_repo_on_path as _page_ensure_repo_on_path,
    resolve_active_app_path,
    reset_scoped_session_state,
)


PAGE_KEY = "view_routing_model_comparison"
APP_SCOPE_KEY = f"{PAGE_KEY}_active_app_path"
MIN_MEANINGFUL_DELIVERY_MBPS = 1e-9
FULFILLED_THRESHOLD = 0.99
TIME_STEP_S = 60.0

MODEL_FILES = {
    "ILP": "trainer_fcas_routing_ilp/allocations_steps.json",
    "PPO-GNN": "trainer_fcas_routing_ppo_gnn/allocations_steps.json",
    "Path-AC": "trainer_fcas_routing_path_ac/allocations_steps.json",
}
MODEL_ORDER = list(MODEL_FILES)
MODEL_COLORS = {
    "ILP": "#2563eb",
    "PPO-GNN": "#f59e0b",
    "Path-AC": "#16a34a",
}
OUTCOME_ORDER = ["unrouted", "partial", "fulfilled", "unknown"]
OUTCOME_COLORS = {
    "unrouted": "#dc2626",
    "partial": "#f97316",
    "fulfilled": "#16a34a",
    "unknown": "#9ca3af",
}


def _ensure_repo_on_path() -> None:
    _page_ensure_repo_on_path(__file__)


_ensure_repo_on_path()

from agi_env import AgiEnv  # noqa: E402
from agi_gui.pagelib import render_logo  # noqa: E402


def _resolve_active_app() -> Path:
    return resolve_active_app_path(error_fn=st.error, stop_fn=st.stop)


def _ensure_app_scoped_env() -> AgiEnv:
    active_app_path = _resolve_active_app()
    reset_scoped_session_state(
        st.session_state,
        APP_SCOPE_KEY,
        active_app_path,
        prefixes=(f"{PAGE_KEY}_",),
    )

    env = st.session_state.get("env")
    if env is not None:
        return env

    try:
        env = AgiEnv.current()
    except RuntimeError:
        env = getattr(AgiEnv, "for_app", AgiEnv)(apps_path=active_app_path.parent, app=active_app_path.name, verbose=0)
    env.init_done = True
    st.session_state["env"] = env
    return env


def _load_app_settings(active_app_path: Path) -> dict[str, Any]:
    settings_path = active_app_path / "src" / "app_settings.toml"
    if not settings_path.exists():
        return {}
    try:
        with settings_path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _page_defaults(settings: dict[str, Any]) -> dict[str, Any]:
    pages = settings.get("pages")
    if not isinstance(pages, dict):
        return {}
    defaults = pages.get(PAGE_KEY)
    return defaults if isinstance(defaults, dict) else {}


def _default_pipeline_root(env: AgiEnv, defaults: dict[str, Any]) -> Path:
    custom_base = str(defaults.get("dataset_custom_base") or "").strip()
    subpath = str(defaults.get("dataset_subpath") or "sb3_trainer/pipeline").strip()
    if custom_base:
        base = Path(custom_base).expanduser()
    else:
        base = Path(getattr(env, "agi_share_path_abs", Path.home() / "clustershare" / "agi"))
    return (base / subpath).expanduser()


def safe_float(value: Any) -> float:
    try:
        if value is None or isinstance(value, bool):
            return math.nan
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def safe_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "y"}:
            return True
        if text in {"0", "false", "no", "n"}:
            return False
    return bool(value)


def parse_list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return [value] if value.strip() else []
        return list(parsed) if isinstance(parsed, (list, tuple)) else []
    return list(value) if isinstance(value, (list, tuple)) else []


def is_edge_list_path(path: list[Any]) -> bool:
    return bool(path) and all(
        isinstance(edge, (list, tuple)) and len(edge) >= 2 for edge in path
    )


def has_path(allocation: dict[str, Any]) -> bool:
    explicit = safe_bool(allocation.get("path_found"))
    if explicit is not None:
        return explicit
    if parse_list_value(allocation.get("path")):
        return True
    if parse_list_value(allocation.get("path_labels")):
        return True
    routed = safe_bool(allocation.get("routed"))
    if routed is not None:
        return routed
    delivered = safe_float(allocation.get("delivered_bandwidth"))
    return math.isfinite(delivered) and delivered > MIN_MEANINGFUL_DELIVERY_MBPS


def is_routed(allocation: dict[str, Any]) -> bool:
    explicit = safe_bool(allocation.get("routed"))
    if explicit is not None:
        return explicit
    delivered = safe_float(allocation.get("delivered_bandwidth"))
    served = safe_float(allocation.get("served_fraction"))
    return has_path(allocation) and (
        (math.isfinite(delivered) and delivered > MIN_MEANINGFUL_DELIVERY_MBPS)
        or (math.isfinite(served) and served > 0)
    )


def get_satisfaction(allocation: dict[str, Any]) -> float:
    served = safe_float(allocation.get("served_fraction"))
    if math.isfinite(served):
        return served
    delivered = safe_float(allocation.get("delivered_bandwidth"))
    requested = safe_float(allocation.get("bandwidth"))
    if math.isfinite(delivered) and math.isfinite(requested) and requested > 0:
        return delivered / requested
    return math.nan


def get_latency_ms(allocation: dict[str, Any]) -> float:
    for key in ("latency_ms", "latency"):
        value = safe_float(allocation.get(key))
        if math.isfinite(value):
            return value
    return math.nan


def get_latency_target_ms(allocation: dict[str, Any]) -> float:
    for key in ("latency_target_ms", "latency_target", "max_latency"):
        value = safe_float(allocation.get(key))
        if math.isfinite(value):
            return value
    return math.nan


def hop_count(allocation: dict[str, Any]) -> int:
    path = parse_list_value(allocation.get("path"))
    path_labels = parse_list_value(allocation.get("path_labels"))
    if not path and not path_labels:
        return 0
    if is_edge_list_path(path):
        return len(path)
    if path_labels:
        return max(0, len(path_labels) - 1)
    return max(0, len(path) - 1)


def normalize_bearer(value: Any) -> str:
    text = str(value or "").strip().upper()
    if "SAT" in text:
        return "SAT"
    if "IVDL" in text or "IVD" in text:
        return "IVDL"
    return text or "UNKNOWN"


def demand_outcome(routed: bool, satisfaction: float) -> str:
    if not routed:
        return "unrouted"
    if not math.isfinite(satisfaction):
        return "unknown"
    if satisfaction >= FULFILLED_THRESHOLD:
        return "fulfilled"
    return "partial"


def step_time_s(step: dict[str, Any]) -> float:
    if "time_s" in step:
        return safe_float(step["time_s"])
    if "t_now_s" in step:
        return safe_float(step["t_now_s"])
    return safe_float(step.get("time_index")) * TIME_STEP_S


def load_steps(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, list) else []


@st.cache_data(show_spinner=False)
def load_allocations(file_signatures: tuple[tuple[str, str, int], ...]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model, path_text, _mtime_ns in file_signatures:
        path = Path(path_text)
        if not path.exists():
            continue
        for step in load_steps(path):
            time_index = int(step.get("time_index", -1))
            time_s = step_time_s(step)
            for allocation in step.get("allocations", []):
                if not isinstance(allocation, dict):
                    continue
                source_label = allocation.get("source_label") or allocation.get("source")
                destination_label = (
                    allocation.get("destination_label")
                    or allocation.get("destination")
                )
                requested = safe_float(allocation.get("bandwidth"))
                delivered = safe_float(allocation.get("delivered_bandwidth"))
                satisfaction = get_satisfaction(allocation)
                routed = is_routed(allocation)
                bearers = [
                    normalize_bearer(bearer)
                    for bearer in parse_list_value(allocation.get("bearers"))
                ]
                rows.append(
                    {
                        "model": model,
                        "time_index": time_index,
                        "time_s": time_s,
                        "source_label": str(source_label),
                        "destination_label": str(destination_label),
                        "demand": f"{source_label} -> {destination_label}",
                        "requested_mbps": requested,
                        "delivered_mbps": delivered,
                        "satisfaction_ratio": satisfaction,
                        "routed": routed,
                        "outcome": demand_outcome(routed, satisfaction),
                        "latency_ms": get_latency_ms(allocation),
                        "latency_target_ms": get_latency_target_ms(allocation),
                        "hop_count": hop_count(allocation),
                        "sat_edge_count": sum(bearer == "SAT" for bearer in bearers),
                        "ivdl_edge_count": sum(bearer == "IVDL" for bearer in bearers),
                        "bearers": " -> ".join(bearers),
                        "path": str(allocation.get("path") or allocation.get("path_labels") or ""),
                    }
                )
    return pd.DataFrame(rows)


def add_latency_targets(alloc_df: pd.DataFrame) -> pd.DataFrame:
    if alloc_df.empty:
        return alloc_df
    join_keys = ["time_index", "source_label", "destination_label"]
    target_reference = (
        alloc_df.loc[
            alloc_df["latency_target_ms"].notna(),
            join_keys + ["latency_target_ms"],
        ]
        .groupby(join_keys, as_index=False, observed=False)["latency_target_ms"]
        .first()
        .rename(columns={"latency_target_ms": "latency_target_used_ms"})
    )
    if target_reference.empty:
        alloc_df["latency_target_used_ms"] = alloc_df["latency_target_ms"]
    else:
        alloc_df = alloc_df.merge(target_reference, on=join_keys, how="left")
        alloc_df["latency_target_used_ms"] = alloc_df["latency_target_ms"].where(
            alloc_df["latency_target_ms"].notna(),
            alloc_df["latency_target_used_ms"],
        )
    alloc_df["latency_violation"] = (
        alloc_df["routed"]
        & alloc_df["latency_ms"].notna()
        & alloc_df["latency_target_used_ms"].notna()
        & (alloc_df["latency_ms"] > alloc_df["latency_target_used_ms"])
    )
    alloc_df["latency_target_margin_ms"] = (
        alloc_df["latency_target_used_ms"] - alloc_df["latency_ms"]
    )
    return alloc_df


def build_summary(alloc_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model, group in alloc_df.groupby("model", observed=False):
        requested_total = group["requested_mbps"].sum(skipna=True)
        delivered_total = group["delivered_mbps"].sum(skipna=True)
        routed = group[group["routed"]]
        latency_checked = group[
            group["routed"]
            & group["latency_ms"].notna()
            & group["latency_target_used_ms"].notna()
        ]
        outcome_rates = group["outcome"].value_counts(normalize=True).to_dict()
        rows.append(
            {
                "model": model,
                "total_requested_mbps": requested_total,
                "total_delivered_mbps": delivered_total,
                "served_bandwidth_ratio": (
                    delivered_total / requested_total if requested_total > 0 else math.nan
                ),
                "mean_satisfaction_ratio": group["satisfaction_ratio"].mean(skipna=True),
                "latency_violation_rate": latency_checked["latency_violation"].mean()
                if len(latency_checked)
                else math.nan,
                "mean_latency_ms": routed["latency_ms"].mean(skipna=True),
                "mean_hop_count": routed["hop_count"].mean(skipna=True),
                "routed_count": int(group["routed"].sum()),
                "unrouted_rate": outcome_rates.get("unrouted", 0.0),
                "partial_rate": outcome_rates.get("partial", 0.0),
                "fulfilled_rate": outcome_rates.get("fulfilled", 0.0),
                "sat_edge_count": int(group["sat_edge_count"].sum()),
                "ivdl_edge_count": int(group["ivdl_edge_count"].sum()),
            }
        )
    summary_df = pd.DataFrame(rows)
    if summary_df.empty:
        return summary_df
    summary_df["model"] = pd.Categorical(summary_df["model"], categories=MODEL_ORDER, ordered=True)
    return summary_df.sort_values("model").reset_index(drop=True)


def available_file_signatures(base_dir: Path) -> tuple[tuple[str, str, int], ...]:
    signatures: list[tuple[str, str, int]] = []
    for model, rel_path in MODEL_FILES.items():
        path = base_dir / rel_path
        mtime_ns = path.stat().st_mtime_ns if path.exists() else 0
        signatures.append((model, str(path), mtime_ns))
    return tuple(signatures)


def render_metric_row(summary_df: pd.DataFrame) -> None:
    if summary_df.empty:
        return
    best_served = summary_df.sort_values("served_bandwidth_ratio", ascending=False).iloc[0]
    lowest_latency = (
        summary_df.dropna(subset=["mean_latency_ms"])
        .sort_values("mean_latency_ms")
        .head(1)
    )
    lowest_violation = (
        summary_df.dropna(subset=["latency_violation_rate"])
        .sort_values("latency_violation_rate")
        .head(1)
    )
    total_decisions = int(summary_df["routed_count"].sum())
    cols = st.columns(4)
    cols[0].metric(
        "Best served ratio",
        str(best_served["model"]),
        f"{best_served['served_bandwidth_ratio']:.3f}",
    )
    if not lowest_latency.empty:
        row = lowest_latency.iloc[0]
        cols[1].metric("Lowest mean latency", str(row["model"]), f"{row['mean_latency_ms']:.1f} ms")
    if not lowest_violation.empty:
        row = lowest_violation.iloc[0]
        cols[2].metric(
            "Lowest violation rate",
            str(row["model"]),
            f"{row['latency_violation_rate']:.3f}",
        )
    cols[3].metric("Routed decisions", f"{total_decisions:,}")


def build_overview_figure(
    alloc_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    models: list[str],
) -> go.Figure:
    fig = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=(
            "Satisfaction Ratio Distribution",
            "Demand Outcome Rates",
            "Latency Distribution for Routed Demands",
            "Latency Target Violation Rate",
        ),
    )
    for model in models:
        model_rows = alloc_df[alloc_df["model"] == model]
        fig.add_trace(
            go.Box(
                y=model_rows["satisfaction_ratio"].dropna(),
                name=model,
                marker_color=MODEL_COLORS.get(model, "#64748b"),
                showlegend=False,
            ),
            row=1,
            col=1,
        )

    outcome_rates = (
        alloc_df.groupby(["model", "outcome"], observed=False)
        .size()
        .div(alloc_df.groupby("model", observed=False).size(), level="model")
        .reset_index(name="rate")
    )
    outcome_pivot = (
        outcome_rates.pivot(index="model", columns="outcome", values="rate")
        .fillna(0.0)
        .reindex(index=models, columns=OUTCOME_ORDER, fill_value=0.0)
    )
    for outcome in OUTCOME_ORDER:
        fig.add_trace(
            go.Bar(
                x=models,
                y=outcome_pivot[outcome],
                name=outcome,
                marker_color=OUTCOME_COLORS.get(outcome, "#9ca3af"),
                legendgroup="outcome",
            ),
            row=1,
            col=2,
        )

    for model in models:
        model_rows = alloc_df[
            (alloc_df["model"] == model)
            & alloc_df["routed"]
            & alloc_df["latency_ms"].notna()
        ]
        fig.add_trace(
            go.Box(
                y=model_rows["latency_ms"],
                name=model,
                marker_color=MODEL_COLORS.get(model, "#64748b"),
                showlegend=False,
            ),
            row=2,
            col=1,
        )

    visible_summary = summary_df.set_index("model").reindex(models).reset_index()
    fig.add_trace(
        go.Bar(
            x=models,
            y=visible_summary["latency_violation_rate"],
            marker_color=[MODEL_COLORS.get(model, "#64748b") for model in models],
            showlegend=False,
        ),
        row=2,
        col=2,
    )

    fig.update_layout(
        height=780,
        barmode="stack",
        margin=dict(l=20, r=20, t=70, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(range=[0, 1.05], row=1, col=1, title_text="Delivered / requested")
    fig.update_yaxes(range=[0, 1.05], row=1, col=2, title_text="Proportion of demand outcomes")
    fig.update_yaxes(title_text="Latency (ms)", row=2, col=1)
    fig.update_yaxes(title_text="Violation rate", row=2, col=2)
    return fig


def build_time_figure(alloc_df: pd.DataFrame, models: list[str]) -> go.Figure:
    time_df = alloc_df.copy()
    time_df["latency_ms_routed"] = time_df["latency_ms"].where(time_df["routed"])
    time_kpi = (
        time_df.groupby(["model", "time_index"], as_index=False, observed=False)
        .agg(
            mean_satisfaction=("satisfaction_ratio", "mean"),
            total_delivered_mbps=("delivered_mbps", "sum"),
            mean_latency_ms=("latency_ms_routed", "mean"),
            latency_violation_rate=("latency_violation", "mean"),
        )
    )
    fig = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=(
            "Mean Satisfaction Over Time",
            "Total Delivered Bandwidth Over Time",
            "Mean Latency Over Time",
            "Latency Violation Rate Over Time",
        ),
    )
    for model in models:
        group = time_kpi[time_kpi["model"] == model]
        color = MODEL_COLORS.get(model, "#64748b")
        fig.add_trace(
            go.Scatter(
                x=group["time_index"],
                y=group["mean_satisfaction"],
                mode="lines",
                name=model,
                line=dict(color=color),
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=group["time_index"],
                y=group["total_delivered_mbps"],
                mode="lines",
                showlegend=False,
                line=dict(color=color),
            ),
            row=1,
            col=2,
        )
        fig.add_trace(
            go.Scatter(
                x=group["time_index"],
                y=group["mean_latency_ms"],
                mode="lines",
                showlegend=False,
                line=dict(color=color),
            ),
            row=2,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=group["time_index"],
                y=group["latency_violation_rate"],
                mode="lines",
                showlegend=False,
                line=dict(color=color),
            ),
            row=2,
            col=2,
        )
    fig.update_layout(height=720, margin=dict(l=20, r=20, t=70, b=30))
    fig.update_yaxes(range=[0, 1.05], row=1, col=1, title_text="Mean delivered / requested")
    fig.update_yaxes(title_text="Delivered bandwidth (Mbps)", row=1, col=2)
    fig.update_yaxes(title_text="Latency (ms)", row=2, col=1)
    fig.update_yaxes(range=[0, 1.05], row=2, col=2, title_text="Violation rate")
    fig.update_xaxes(title_text="Time index")
    return fig


def build_path_figure(alloc_df: pd.DataFrame, models: list[str]) -> go.Figure:
    routed = alloc_df[alloc_df["routed"] & alloc_df["hop_count"].notna()].copy()
    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=("Hop Count Distribution", "Bearer Edge Counts"),
    )
    if not routed.empty:
        routed["hop_count"] = routed["hop_count"].astype(int)
        hop_counts = sorted(routed["hop_count"].unique())
        hop_pivot = (
            routed.groupby(["model", "hop_count"], observed=False)
            .size()
            .unstack(fill_value=0)
            .reindex(index=models, columns=hop_counts, fill_value=0)
        )
        hop_pivot = hop_pivot.div(hop_pivot.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
        palette = ["#0f766e", "#2563eb", "#7c3aed", "#db2777", "#64748b"]
        for index, hop in enumerate(hop_counts):
            fig.add_trace(
                go.Bar(
                    x=models,
                    y=hop_pivot[hop],
                    name=f"{hop} hop" if hop == 1 else f"{hop} hops",
                    marker_color=palette[index % len(palette)],
                    legendgroup="hop",
                ),
                row=1,
                col=1,
            )

    bearer_summary = (
        alloc_df.groupby("model", as_index=False, observed=False)
        .agg(sat_edge_count=("sat_edge_count", "sum"), ivdl_edge_count=("ivdl_edge_count", "sum"))
        .set_index("model")
        .reindex(models)
        .fillna(0)
    )
    fig.add_trace(
        go.Bar(
            x=models,
            y=bearer_summary["sat_edge_count"],
            name="SAT",
            marker_color="#2563eb",
        ),
        row=1,
        col=2,
    )
    fig.add_trace(
        go.Bar(
            x=models,
            y=bearer_summary["ivdl_edge_count"],
            name="IVDL",
            marker_color="#f59e0b",
        ),
        row=1,
        col=2,
    )
    fig.update_layout(height=430, barmode="stack", margin=dict(l=20, r=20, t=65, b=30))
    fig.update_yaxes(range=[0, 1.05], row=1, col=1, title_text="Proportion of routed demands")
    fig.update_yaxes(title_text="Selected bearer edges", row=1, col=2)
    return fig


def build_failure_table(alloc_df: pd.DataFrame) -> pd.DataFrame:
    table = alloc_df.copy()
    table["latency_over_target_ms"] = table["latency_ms"] - table["latency_target_used_ms"]
    failures = table[
        (table["outcome"] != "fulfilled")
        | (table["latency_violation"])
    ].copy()
    columns = [
        "model",
        "time_index",
        "source_label",
        "destination_label",
        "outcome",
        "requested_mbps",
        "delivered_mbps",
        "satisfaction_ratio",
        "latency_ms",
        "latency_target_used_ms",
        "latency_over_target_ms",
        "hop_count",
        "bearers",
        "path",
    ]
    if failures.empty:
        return failures[columns]
    return failures.sort_values(
        ["latency_violation", "satisfaction_ratio", "latency_over_target_ms"],
        ascending=[False, True, False],
    )[columns]


def _format_summary(summary_df: pd.DataFrame) -> pd.DataFrame:
    return summary_df.set_index("model").T


def main() -> None:
    st.set_page_config(page_title="Routing Model Comparison", layout="wide")
    env = _ensure_app_scoped_env()
    active_app_path = _resolve_active_app()
    settings = _load_app_settings(active_app_path)
    defaults = _page_defaults(settings)
    default_root = _default_pipeline_root(env, defaults)

    render_logo()
    st.title("Routing Model Comparison")

    pipeline_dir_text = st.sidebar.text_input(
        "Pipeline directory",
        value=str(default_root),
        key=f"{PAGE_KEY}_pipeline_dir",
    )
    base_dir = Path(pipeline_dir_text).expanduser()
    file_signatures = available_file_signatures(base_dir)
    available_models = [
        model for model, path_text, _mtime in file_signatures if Path(path_text).exists()
    ]
    selected_models = st.sidebar.multiselect(
        "Models",
        options=MODEL_ORDER,
        default=available_models or MODEL_ORDER,
        key=f"{PAGE_KEY}_selected_models",
    )
    limit_failures = st.sidebar.number_input(
        "Failure rows",
        min_value=10,
        max_value=500,
        value=100,
        step=10,
        key=f"{PAGE_KEY}_failure_rows",
    )

    missing_files = [
        f"{model}: {path_text}"
        for model, path_text, _mtime in file_signatures
        if not Path(path_text).exists()
    ]
    if missing_files:
        with st.expander("Missing allocation files", expanded=False):
            st.write("\n".join(missing_files))

    alloc_df = load_allocations(file_signatures)
    if alloc_df.empty:
        st.warning("No allocation data was loaded from the selected pipeline directory.")
        st.stop()

    alloc_df = add_latency_targets(alloc_df)
    if selected_models:
        alloc_df = alloc_df[alloc_df["model"].isin(selected_models)].copy()
    if alloc_df.empty:
        st.warning("No allocation rows match the selected model filter.")
        st.stop()

    summary_df = build_summary(alloc_df)
    models = [model for model in MODEL_ORDER if model in set(alloc_df["model"])]

    render_metric_row(summary_df)

    summary_tab, dashboard_tab, time_tab, path_tab, failures_tab = st.tabs(
        ["Summary", "Dashboard", "Over Time", "Paths", "Failures"]
    )
    with summary_tab:
        st.subheader("Model Summary")
        st.dataframe(_format_summary(summary_df), use_container_width=True)
        st.caption(f"Loaded {len(alloc_df):,} allocation decisions from {base_dir}.")

    with dashboard_tab:
        st.plotly_chart(
            build_overview_figure(alloc_df, summary_df, models),
            use_container_width=True,
        )

    with time_tab:
        st.plotly_chart(build_time_figure(alloc_df, models), use_container_width=True)

    with path_tab:
        st.plotly_chart(build_path_figure(alloc_df, models), use_container_width=True)

    with failures_tab:
        failures = build_failure_table(alloc_df)
        st.dataframe(failures.head(int(limit_failures)), use_container_width=True)


if __name__ == "__main__":
    main()
