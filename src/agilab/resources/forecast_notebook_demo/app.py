"""Promotion forecast lab — Chronos-2 Small on synthetic data."""

import os
import sys

import numpy as np
import pandas as pd
import altair as alt
import streamlit as st

# Import forecast_core (ordinary import; bootstrap path if needed)
_HERE = os.path.dirname(os.path.abspath(__file__))
if "forecast_core" not in sys.modules:
    _saved_path = sys.path[:]
    try:
        if _HERE not in sys.path:
            sys.path.insert(0, _HERE)
        import forecast_core
    finally:
        sys.path[:] = _saved_path
else:
    import forecast_core

make_fixture = forecast_core.make_fixture
predict = forecast_core.predict
run_analysis = forecast_core.run_analysis
MODEL_ID = forecast_core.MODEL_ID
MODEL_REVISION = forecast_core.MODEL_REVISION


# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------

def _build_context_chart(context):
    """Render the historical context series."""
    ctx_df = pd.DataFrame({"t": np.arange(len(context)), "sales": context})
    return (
        alt.Chart(ctx_df)
        .mark_line(color="#4a90d9")
        .encode(
            x=alt.X("t:Q", title="Time step"),
            y=alt.Y("sales:Q", title="Sales"),
        )
        .properties(width="container", height=200)
        .interactive()
    )


def _build_forecast_chart(result):
    """Build the main forecast chart using the nested result contract."""
    horizon = int(result["horizon"])
    context_len = int(result["context_length"])

    context = np.asarray(result["fixture"]["context"], dtype=float)
    actual = np.asarray(result["fixture"]["actual"], dtype=float)
    forecast = np.asarray(result["predictions"]["forecast"], dtype=float)
    lower = np.asarray(result["predictions"]["lower"], dtype=float)
    upper = np.asarray(result["predictions"]["upper"], dtype=float)
    baseline = np.asarray(result["baseline"], dtype=float)

    # Line series (long form)
    rows = []
    for i in range(context_len):
        rows.append({"t": i, "value": float(context[i]), "series": "Historical"})
    for i in range(horizon):
        t = context_len + i
        rows.append({"t": t, "value": float(actual[i]), "series": "Actual"})
        rows.append({"t": t, "value": float(forecast[i]), "series": "Chronos-2"})
        rows.append({"t": t, "value": float(baseline[i]), "series": "Seasonal-7"})

    line_df = pd.DataFrame(rows)

    color_map = {
        "Historical": "#4a90d9",
        "Actual": "#2e8b57",
        "Chronos-2": "#8b5cf6",
        "Seasonal-7": "#f59e0b",
    }

    line_chart = (
        alt.Chart(line_df)
        .mark_line()
        .encode(
            x=alt.X("t:Q", title="Time step"),
            y=alt.Y("value:Q", title="Sales"),
            color=alt.Color(
                "series:N",
                scale=alt.Scale(domain=list(color_map.keys()), range=list(color_map.values())),
            ),
        )
    )

    # Uncertainty band (p10–p90) on future days only
    band_df = pd.DataFrame({
        "t": context_len + np.arange(horizon),
        "lower": lower,
        "upper": upper,
    })
    band = (
        alt.Chart(band_df)
        .mark_area(opacity=0.2, color="#8b5cf6")
        .encode(
            x=alt.X("t:Q"),
            y="lower:Q",
            y2="upper:Q",
        )
    )

    # Train/test boundary
    vline = (
        alt.Chart(pd.DataFrame({"t": [context_len]}))
        .mark_rule(strokeDash=[4, 4], color="black", opacity=0.5)
        .encode(x=alt.X("t:Q"))
    )

    chart = (
        (band + line_chart + vline)
        .properties(width="container", height=320)
        .interactive()
    )
    return chart


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

def main():
    st.title("Promotion forecast lab")
    st.caption(
        f"{MODEL_ID} (rev {MODEL_REVISION[:12]}…) on **synthetic** data. "
        "All series are generated locally; no retail or electricity datasets are used."
    )

    # --- Form with uniquely scoped session keys ---
    with st.form("forecast_form", border=True):
        horizon = st.selectbox("Forecast horizon", [14, 28, 56], index=1,
                               help="Number of future steps to forecast.")
        seed = st.number_input("Random seed", min_value=0, max_value=100000, value=42, step=1)
        promotion_start = st.number_input("Promotion start (step within horizon)",
                                          min_value=0, max_value=55, value=7, step=1)
        promotion_days = st.number_input("Promotion duration (days)",
                                         min_value=0, max_value=56, value=7, step=1)
        submitted = st.form_submit_button("Run analysis")

    if submitted:
        st.session_state["fcst_submitted"] = True
        st.session_state["fcst_params"] = {
            "horizon": int(horizon),
            "seed": int(seed),
            "promotion_start": int(promotion_start),
            "promotion_days": int(promotion_days),
        }
        st.session_state.pop("fcst_result", None)
        st.session_state.pop("fcst_error", None)

    # --- Determine parameters (committed or defaults) ---
    if st.session_state.get("fcst_submitted"):
        params = st.session_state.get("fcst_params", {
            "horizon": 28, "seed": 42, "promotion_start": 7, "promotion_days": 7,
        })
    else:
        params = {"horizon": 28, "seed": 42, "promotion_start": 7, "promotion_days": 7}

    # --- Historical context chart (from committed params, not hardcoded seed) ---
    st.subheader("Historical context")
    _ctx = make_fixture(
        seed=params["seed"],
        horizon=params["horizon"],
        promotion_start=params["promotion_start"],
        promotion_days=params["promotion_days"],
    )
    st.altair_chart(_build_context_chart(_ctx["context"]), width="stretch")

    # --- Render committed results (outside the submitted conditional) ---
    if st.session_state.get("fcst_submitted"):
        if "fcst_result" not in st.session_state and "fcst_error" not in st.session_state:
            with st.spinner("Loading model and running inference…"):
                try:
                    result = run_analysis(
                        seed=params["seed"],
                        horizon=params["horizon"],
                        promotion_start=params["promotion_start"],
                        promotion_days=params["promotion_days"],
                    )
                    st.session_state["fcst_result"] = result
                except Exception as exc:
                    st.session_state["fcst_error"] = f"{type(exc).__name__}: {exc}"

        if st.session_state.get("fcst_error"):
            st.error(f"Analysis failed: {st.session_state['fcst_error']}")
        elif st.session_state.get("fcst_result") is not None:
            result = st.session_state["fcst_result"]

            st.subheader("Settings used")
            st.json(params)

            st.subheader("Forecast vs. actual")
            st.altair_chart(_build_forecast_chart(result), width="stretch")

            mae = float(result["metrics"]["mae"])
            baseline_mae = float(result["metrics"]["baseline_mae"])
            coverage = float(result["metrics"]["coverage"])

            c1, c2, c3 = st.columns(3)
            c1.metric("Chronos-2 MAE", f"{mae:.2f}")
            c2.metric("Seasonal-7 MAE", f"{baseline_mae:.2f}")
            c3.metric("p10–p90 coverage", f"{coverage:.1%}")

            st.caption(
                "Coverage is the fraction of held-out actual values inside the model's "
                "p10–p90 interval. The nominal 80% interval is **not calibrated** on this "
                "synthetic fixture; treat coverage as a diagnostic, not a calibrated probability."
            )

            st.subheader("Forecast details")
            _h = int(result["horizon"])
            _actual = np.asarray(result["fixture"]["actual"], dtype=float)
            _promo = np.asarray(result["fixture"]["future_promotion"], dtype=int)
            _fc = np.asarray(result["predictions"]["forecast"], dtype=float)
            _lo = np.asarray(result["predictions"]["lower"], dtype=float)
            _hi = np.asarray(result["predictions"]["upper"], dtype=float)
            _base = np.asarray(result["baseline"], dtype=float)
            _details = pd.DataFrame({
                "Day": np.arange(1, _h + 1),
                "Actual": _actual,
                "Forecast": _fc,
                "Lower (p10)": _lo,
                "Upper (p90)": _hi,
                "Seasonal-7": _base,
                "Promotion": ["On" if p else "Off" for p in _promo],
            })
            st.dataframe(_details, width="stretch", hide_index=True)


if __name__ == "__main__":
    main()
