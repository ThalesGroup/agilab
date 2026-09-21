"""Native Streamlit lab; all displayed sales data are synthetic."""

import json

import streamlit as st

st.title("Promotion forecast lab")
st.caption("Chronos-2 Small · Synthetic daily sales · Known future promotion covariates")

try:
    import altair as alt
    import numpy as np
    import pandas as pd

    from forecast_core import (
        MODEL_ID, MODEL_REVISION, PrerequisiteError, make_fixture, run_analysis,
    )
except ImportError as exc:
    st.error(f"Missing analysis dependency: {exc}. Use the prepared Python environment "
             "with the dependencies declared in pyproject.toml.")
    st.stop()


def history_chart(data):
    frame = pd.DataFrame({
        "Day": np.arange(-256, 0), "Synthetic sales": data["context"],
        "Promotion": np.where(np.asarray(data["past_promotion"]) > 0, "On", "Off"),
    })
    base = alt.Chart(frame).encode(x=alt.X("Day:Q", title="Day relative to forecast start"))
    line = base.mark_line(color="#475569").encode(
        y=alt.Y("Synthetic sales:Q", scale=alt.Scale(zero=False)),
        tooltip=["Day:Q", alt.Tooltip("Synthetic sales:Q", format=".1f"), "Promotion:N"],
    )
    points = base.transform_filter(alt.datum.Promotion == "On").mark_circle(
        color="#d97706", size=18, opacity=0.65,
    ).encode(y="Synthetic sales:Q", tooltip=["Day:Q", "Promotion:N"])
    return (line + points).properties(height=210).interactive()


def forecast_chart(frame):
    base = alt.Chart(frame).encode(x=alt.X("Day:Q", title="Forecast day (zero-based)"))
    interval = base.mark_area(color="#2563eb", opacity=0.15).encode(
        y=alt.Y("p10:Q", title="Synthetic sales", scale=alt.Scale(zero=False)),
        y2="p90:Q",
        tooltip=["Day:Q", alt.Tooltip("p10:Q", format=".2f"),
                 alt.Tooltip("p90:Q", format=".2f")],
    )
    lines = base.transform_fold(
        ["Actual", "Chronos forecast", "Seasonal-7"], as_=["Series", "Sales"],
    ).mark_line(point=True).encode(
        y=alt.Y("Sales:Q", title="Synthetic sales", scale=alt.Scale(zero=False)),
        color=alt.Color("Series:N", scale=alt.Scale(
            domain=["Actual", "Chronos forecast", "Seasonal-7"],
            range=["#0f766e", "#2563eb", "#d97706"],
        ), legend=alt.Legend(title=None, orient="bottom")),
        strokeDash=alt.StrokeDash("Series:N", legend=None),
        tooltip=["Day:Q", "Series:N", alt.Tooltip("Sales:Q", format=".2f"), "Promotion:N"],
    )
    return (interval + lines).properties(height=350).interactive()


defaults = dict(seed=42, horizon=28, promotion_start=7, promotion_days=7)
if "committed_parameters" not in st.session_state:
    st.session_state.committed_parameters = defaults.copy()

with st.form("scenario"):
    st.subheader("Design a synthetic promotion")
    left, right = st.columns(2)
    with left:
        horizon = st.selectbox("Forecast horizon (days)", [14, 28, 56], index=1)
        seed = st.number_input("Synthetic data seed", min_value=0, max_value=2**32 - 1,
                               value=42, step=1)
    with right:
        start = st.number_input("Promotion start (day offset)", min_value=0,
                                max_value=56, value=7, step=1)
        duration = st.number_input("Promotion duration (days)", min_value=0,
                                   max_value=56, value=7, step=1)
    st.caption("Day 0 is the first forecast day. The promotion interval is clipped to the "
               "horizon; duration 0 means no future promotion. Changes apply on submit.")
    submitted = st.form_submit_button("Run analysis", type="primary", width="stretch")

if submitted:
    st.session_state.committed_parameters = dict(
        seed=int(seed), horizon=int(horizon), promotion_start=int(start),
        promotion_days=int(duration),
    )
    st.session_state.pop("analysis", None)
    st.session_state.pop("analysis_error", None)

params = st.session_state.committed_parameters
preview = make_fixture(**params)
st.subheader("Synthetic history")
st.caption(f"256 observed days · Seed {params['seed']} · Orange points mark historical promotions")
st.altair_chart(history_chart(preview), width="stretch")

active_days = np.flatnonzero(preview["future_promotion"])
schedule = (f"days {active_days[0]}–{active_days[-1]} ({len(active_days)} days)"
            if active_days.size else "none")
st.markdown(f"**Submitted scenario:** {params['horizon']} forecast days · Promotion: {schedule}")

if submitted:
    with st.spinner("Running Chronos-2 Small on CPU…"):
        try:
            st.session_state.analysis = run_analysis(**params)
        except PrerequisiteError as exc:
            st.session_state.analysis_error = str(exc)
        except Exception as exc:
            st.session_state.analysis_error = (
                f"Analysis failed ({type(exc).__name__}): {exc}. "
                "Check the submitted inputs and the model/environment compatibility, then retry."
            )

if st.session_state.get("analysis_error"):
    st.error(st.session_state.analysis_error)
elif "analysis" in st.session_state:
    result = st.session_state.analysis
    metrics = result["metrics"]
    st.subheader("Forecast against synthetic holdout")
    with st.container(horizontal=True):
        st.metric("Chronos MAE", f"{metrics['mae']:.2f}", border=True,
                  help="Mean absolute error in synthetic sales units; lower is better.")
        st.metric("Seasonal-7 MAE", f"{metrics['baseline_mae']:.2f}", border=True,
                  help="Repeats the last seven historical observations.")
        st.metric("Observed p10–p90 coverage", f"{metrics['coverage']:.1%}", border=True,
                  help="Fraction of this synthetic holdout inside the model's p10–p90 interval.")
    frame = pd.DataFrame({
        "Day": np.arange(params["horizon"]),
        "Actual": result["fixture"]["actual"],
        "Chronos forecast": result["predictions"]["forecast"],
        "Seasonal-7": result["baseline"],
        "p10": result["predictions"]["lower"],
        "p90": result["predictions"]["upper"],
        "Promotion": np.where(preview["future_promotion"] > 0, "On", "Off"),
    })
    st.altair_chart(forecast_chart(frame), width="stretch")
    st.caption("Blue shading: model p10–p90 bounds. Scroll to zoom and drag to pan; "
               "hover for values. All series share the same forecast-day axis.")
    st.info("The interval is nominally 80%; it is not calibrated on this fixture. "
            "Observed coverage is measured only on the selected synthetic holdout.")
    with st.expander("Inspect daily results"):
        st.dataframe(frame, hide_index=True, width="stretch")
    st.download_button("Download synthetic results", json.dumps({"results": result},
                       allow_nan=False, indent=2), file_name="results.json",
                       mime="application/json", on_click="ignore")
else:
    st.info("Choose a scenario and select Run analysis to load the model and forecast. "
            "The history above is available before inference.")

with st.expander("Method, model and source credit"):
    st.markdown(
        "All sales, promotion schedules and weekday features are **synthetic**. "
        "Chronos receives 256 historical sales observations, past promotion and weekday "
        "features, and the known future promotion and weekday features. Held-out sales "
        "are used only for evaluation. This is a scenario forecast, not a causal estimate "
        "or a production-accuracy claim.\n\n"
        "Adapted from **Amazon Science / the Chronos authors**, "
        "[Getting Started with Chronos-2](https://github.com/amazon-science/chronos-forecasting/"
        "blob/10afa9ebe016e514f9d7dc1aa873f66af57e116b/notebooks/chronos-2-quickstart.ipynb), "
        "specifically retail covariates and the NumPy/torch API. No retail or electricity "
        "datasets are downloaded or redistributed. Original source and provenance are "
        "preserved in source/. The supplied provenance does not specify a notebook license.\n\n"
        f"Model: [{MODEL_ID}](https://huggingface.co/{MODEL_ID}), **Apache-2.0**, "
        f"revision `{MODEL_REVISION}`. CPU float32, four threads; quantiles 0.1, 0.5, 0.9. "
        "The model is loaded only from predownloaded local files."
    )
