"""Promotion forecast lab - native Streamlit app.

An authorized adaptation of the official Chronos-2 quickstart notebook:

- repository: amazon-science/chronos-forecasting
- commit:     10afa9ebe016e514f9d7dc1aa873f66af57e116b
- notebook:   notebooks/chronos-2-quickstart.ipynb
  (https://github.com/amazon-science/chronos-forecasting/blob/10afa9ebe016e514f9d7dc1aa873f66af57e116b/notebooks/chronos-2-quickstart.ipynb)

The upstream notebook demonstrates Chronos-2 covariate forecasting on
downloaded Rossmann retail and electricity-price datasets. This app keeps the
same forecasting method but replaces those datasets with a fully synthetic
fixture (see forecast_core.make_fixture). It runs the Apache-2.0
autogluon/chronos-2-small model on CPU in float32. Outputs are scenario
forecasts on synthetic data: not causal estimates and not production-accuracy
claims.
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import forecast_core as fc

st.title("Promotion forecast lab")
st.caption(
    "Chronos-2 Small (autogluon/chronos-2-small, Apache-2.0) forecasting a "
    "synthetic daily sales series with a known promotion schedule. Adapted "
    "from the official Chronos-2 quickstart notebook in "
    "amazon-science/chronos-forecasting. All data below is synthetic."
)


def _context_table(data: dict) -> pd.DataFrame:
    context = list(data["context"])
    n = len(context)
    return pd.DataFrame(
        {
            "step": [n - 14 + i for i in range(14)],
            "sales": [round(v, 2) for v in context[-14:]],
            "promotion": [int(v) for v in data["past_promotion"][-14:]],
        }
    )


def _forecast_table(result: dict) -> pd.DataFrame:
    horizon = result["horizon"]
    return pd.DataFrame(
        {
            "step": list(range(1, horizon + 1)),
            "actual": [round(v, 2) for v in result["actual"]],
            "chronos_forecast": [round(v, 2) for v in result["forecast"]],
            "seasonal7_baseline": [round(v, 2) for v in result["baseline"]],
            "p10": [round(v, 2) for v in result["lower"]],
            "p90": [round(v, 2) for v in result["upper"]],
            "promotion": [int(v) for v in result["future_promotion"]],
        }
    )


def _chart(result: dict) -> alt.Chart:
    horizon = result["horizon"]
    context = list(result["context"])[-56:]
    rows: list[dict] = []
    offset = horizon - len(context)
    for i, v in enumerate(context):
        rows.append(
            {
                "step": offset + i,
                "kind": "context (last 56d)",
                "value": v,
            }
        )
    for i, v in enumerate(result["actual"], start=1):
        rows.append({"step": i, "kind": "actual", "value": v})
    for i, v in enumerate(result["forecast"], start=1):
        rows.append({"step": i, "kind": "chronos forecast", "value": v})
    for i, v in enumerate(result["baseline"], start=1):
        rows.append({"step": i, "kind": "seasonal-7 baseline", "value": v})
    series = pd.DataFrame(rows)

    band_df = pd.DataFrame(
        {
            "step": list(range(1, horizon + 1)),
            "lower": result["lower"],
            "upper": result["upper"],
        }
    )

    line = (
        alt.Chart(series)
        .mark_line()
        .encode(
            x=alt.X("step:Q", title="day (positive = future)"),
            y=alt.Y("value:Q", title="sales"),
            color=alt.Color("kind:N", scale=alt.Scale(domain=[
                "context (last 56d)",
                "actual",
                "chronos forecast",
                "seasonal-7 baseline",
            ])),
            tooltip=["step", "kind", alt.Tooltip("value:Q", format=".2f")],
        )
        .properties(height=340)
    )
    band = (
        alt.Chart(band_df)
        .mark_area(opacity=0.15, color="#7c3aed")
        .encode(
            x=alt.X("step:Q"),
            y=alt.Y("lower:Q"),
            y2=alt.Y2("upper:Q"),
        )
        .properties(height=340)
    )
    rule = (
        alt.Chart(pd.DataFrame([{"step": 0}]))
        .mark_rule(strokeDash=[4, 4], color="black")
        .encode(x=alt.X("step:Q"))
        .properties(height=340)
    )
    return (band + line + rule).interactive()


def _render_results() -> None:
    if "error" in st.session_state and st.session_state.get("result") is None:
        st.error(st.session_state["error"])
        return
    result = st.session_state["result"]
    mae = float(result["mae"])
    baseline_mae = float(result["baseline_mae"])
    coverage = float(result["coverage"])
    delta = baseline_mae - mae
    c1, c2, c3 = st.columns(3)
    c1.metric("MAE - Chronos-2", f"{mae:.3f}")
    c2.metric("MAE - seasonal-7 baseline", f"{baseline_mae:.3f}", delta=f"{delta:+.3f}")
    c3.metric("Observed p10-p90 coverage", f"{coverage:.0%}", delta=f"{(coverage - 0.8) * 100:+.0f} pts vs nominal 80%")

    st.markdown(
        "The nominal 80% interval (p10-p90) is **not calibrated** on this "
        "synthetic fixture, so observed coverage deviating from 80% is "
        "expected. This is a scenario forecast, not a causal estimate or a "
        "production-accuracy claim."
    )
    st.markdown("### Forecast vs actual vs baseline")
    st.altair_chart(_chart(result), width="stretch")
    st.markdown("### Series detail")
    st.dataframe(_forecast_table(result), width="stretch")
    st.markdown("### Run configuration")
    st.json(
        {
            "model": result["model"],
            "model_revision": result["model_revision"],
            "model_license": result["model_license"],
            "device": result["device"],
            "dtype": result["dtype"],
            "seed": result["seed"],
            "horizon": result["horizon"],
            "promotion_start": result["promotion_start"],
            "promotion_days": result["promotion_days"],
            "mae": mae,
            "baseline_mae": baseline_mae,
            "coverage": coverage,
        }
    )


st.markdown("### Scenario")
with st.form("scenario_form"):
    col_a, col_b = st.columns(2)
    with col_a:
        horizon = st.selectbox("Horizon (days)", (14, 28, 56), index=1)
        seed = st.number_input("Random seed", min_value=0, max_value=999999, value=42, step=1)
    with col_b:
        promotion_start = st.number_input(
            "Promotion start (first future day, 0-based)",
            min_value=0,
            max_value=55,
            value=7,
            step=1,
        )
        promotion_days = st.number_input(
            "Promotion duration (days)", min_value=1, max_value=56, value=7, step=1
        )
    run_clicked = st.form_submit_button("Run analysis")

st.markdown("### Context (shown before any model work)")
st.caption(
    f"Synthetic history: 256 days of trend + weekly and 28-day seasonality + "
    f"promotion lifts + noise (seed={seed}). Last 14 days shown below."
)
st.dataframe(_context_table(fc.make_fixture(seed=seed, horizon=horizon, promotion_start=promotion_start, promotion_days=promotion_days)), width="stretch")
st.caption("Click 'Run analysis' to load the pinned Chronos-2 Small model and run inference.")

if run_clicked:
    try:
        st.session_state["result"] = fc.run_analysis(
            seed=int(seed),
            horizon=int(horizon),
            promotion_start=int(promotion_start),
            promotion_days=int(promotion_days),
        )
        st.session_state.pop("error", None)
    except fc.ModelUnavailableError as exc:
        st.session_state["result"] = None
        st.session_state["error"] = (
            f"Chronos-2 inference is unavailable in this environment: {exc} "
            "Install chronos-forecasting and ensure the pinned model cache is "
            "present (or set CHRONOS_MODEL_PATH to a local model directory)."
        )
    except Exception as exc:  # surface a concise, actionable error
        st.session_state["result"] = None
        st.session_state["error"] = f"Analysis failed: {exc}"

if st.session_state.get("result") is not None or "error" in st.session_state:
    st.markdown("### Results")
    _render_results()

st.markdown(
    "---\n"
    "Source: adapted from the official Chronos-2 quickstart notebook, "
    "amazon-science/chronos-forecasting "
    "(commit 10afa9ebe016e514f9d7dc1aa873f66af57e116b). "
    "Model: autogluon/chronos-2-small (Apache-2.0). "
    "Data: synthetic fixture; no retail or electricity datasets are "
    "downloaded, stored, or redistributed."
)
