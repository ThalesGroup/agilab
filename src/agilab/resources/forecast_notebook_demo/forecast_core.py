"""Pure core: synthetic fixture, Chronos-2 inference, seasonal baseline, metrics.

All data is synthetic. No retail or electricity datasets are downloaded or used.
"""

import os
import threading

import numpy as np

# ---------------------------------------------------------------------------
# Public model identity (pinned)
# ---------------------------------------------------------------------------

MODEL_ID = "autogluon/chronos-2-small"
MODEL_REVISION = "ddec01313e50b6bc58ebaa92ede81bc24a3d9f9a"

_pipeline_cache = None
_pipeline_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Model loading (cached, thread-safe, offline-only)
# ---------------------------------------------------------------------------

def _get_pipeline():
    """Load (or return cached) Chronos-2 Small pipeline on CPU float32."""
    global _pipeline_cache
    if _pipeline_cache is not None:
        return _pipeline_cache
    with _pipeline_lock:
        if _pipeline_cache is not None:
            return _pipeline_cache
        try:
            import torch
            torch.set_num_threads(4)
            from chronos import Chronos2Pipeline
        except ImportError as exc:
            raise RuntimeError(
                f"Required dependency not available: {exc}. "
                "Ensure chronos-forecasting and torch are installed."
            ) from exc

        model_path = os.environ.get("CHRONOS_MODEL_PATH")
        if model_path:
            pipeline = Chronos2Pipeline.from_pretrained(
                model_path,
                device_map="cpu",
                torch_dtype=torch.float32,
                local_files_only=True,
            )
        else:
            pipeline = Chronos2Pipeline.from_pretrained(
                MODEL_ID,
                revision=MODEL_REVISION,
                device_map="cpu",
                torch_dtype=torch.float32,
                local_files_only=True,
            )
        _pipeline_cache = pipeline
        return pipeline


# ---------------------------------------------------------------------------
# Synthetic fixture
# ---------------------------------------------------------------------------

def make_fixture(seed=42, horizon=28, promotion_start=7, promotion_days=7):
    """Generate a synthetic sales series with promotion and weekday covariates.

    The historical (context) sales use a recurring 28-day promotion cycle.
    The future (actual) sales use the user-selected promotion schedule.

    Returns a dict of numpy float32 arrays:
        context, actual, past_promotion, future_promotion, past_weekday, future_weekday
    """
    context_length = 256
    rng = np.random.default_rng(seed)
    total_len = context_length + horizon
    t = np.arange(total_len, dtype=np.float64)

    # Historical promotion: every 28-day cycle, days 7-13 (7 days)
    historical_promo = ((t % 28) >= 7) & ((t % 28) < 14)

    # Future promotion schedule: all False except selected interval
    future_promo = np.zeros(horizon, dtype=np.float64)
    start = max(0, min(promotion_start, horizon))
    end = max(0, min(promotion_start + promotion_days, horizon))
    future_promo[start:end] = 1.0

    # Weekday signal
    weekday = np.sin(2.0 * np.pi * t / 7.0)

    # Monthly (28-day) seasonality
    monthly = np.sin(2.0 * np.pi * t / 28.0)

    # Noise
    noise = rng.normal(0.0, 2.5, size=total_len)

    # Base signal components
    trend = 100.0 + 0.04 * t
    weekly = 12.0 * weekday
    monthly_sig = 6.0 * monthly

    # Context (historical) sales: use historical promotion pattern
    ctx_promo = historical_promo[:context_length].astype(np.float64)
    context = (
        trend[:context_length]
        + weekly[:context_length]
        + monthly_sig[:context_length]
        + 40.0 * ctx_promo
        + noise[:context_length]
    ).astype(np.float32)

    # Actual (future) sales: use the user-selected future promotion schedule
    act_promo = future_promo.astype(np.float64)
    actual = (
        trend[context_length:]
        + weekly[context_length:]
        + monthly_sig[context_length:]
        + 40.0 * act_promo
        + noise[context_length:]
    ).astype(np.float32)

    past_promotion = historical_promo[:context_length].astype(np.float32)
    past_weekday = weekday[:context_length].astype(np.float32)
    future_promotion = future_promo.astype(np.float32)
    future_weekday = weekday[context_length:].astype(np.float32)

    return {
        "context": context,
        "actual": actual,
        "past_promotion": past_promotion,
        "future_promotion": future_promotion,
        "past_weekday": past_weekday,
        "future_weekday": future_weekday,
    }


# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------

def predict(data, use_covariates=True):
    """Run Chronos-2 inference on the given fixture.

    Parameters
    ----------
    data : dict with keys context, past_promotion, future_promotion,
           past_weekday, future_weekday (and optionally actual, which is ignored).
    use_covariates : bool – include past/future covariates in the model input.

    Returns
    -------
    dict with keys forecast, lower, upper (numpy float32 arrays of length horizon).
    """
    import torch

    context = np.asarray(data["context"], dtype=np.float32)
    context_length = len(context)

    # Derive horizon from future covariates (never from actual)
    horizon = len(data["future_promotion"])

    pipeline = _get_pipeline()

    entry = {"target": context}
    if use_covariates:
        entry["past_covariates"] = {
            "promotion": np.asarray(data["past_promotion"], dtype=np.float32),
            "weekday": np.asarray(data["past_weekday"], dtype=np.float32),
        }
        entry["future_covariates"] = {
            "promotion": np.asarray(data["future_promotion"], dtype=np.float32),
            "weekday": np.asarray(data["future_weekday"], dtype=np.float32),
        }

    inputs = [entry]

    with _pipeline_lock:
        quantiles, point = pipeline.predict_quantiles(
            inputs,
            prediction_length=horizon,
            context_length=context_length,
            batch_size=8,
            quantile_levels=[0.1, 0.5, 0.9],
        )

    # quantiles: list of tensors [1, horizon, 3]
    # point: list of tensors [1, horizon]
    q = quantiles[0].detach().cpu().numpy().astype(np.float32)
    p = point[0].detach().cpu().numpy().astype(np.float32)

    lower = q[0, :, 0]    # p10
    upper = q[0, :, 2]    # p90
    forecast = p[0]       # point prediction

    return {
        "forecast": forecast,
        "lower": lower,
        "upper": upper,
    }


# ---------------------------------------------------------------------------
# Seasonal-7 baseline
# ---------------------------------------------------------------------------

def _seasonal7_baseline(context, horizon):
    """Repeat the last 7 observations of context for each step in the horizon."""
    last7 = np.asarray(context, dtype=np.float64)[-7:]
    baseline = np.resize(last7, horizon).astype(np.float32)
    return baseline


# ---------------------------------------------------------------------------
# Full analysis
# ---------------------------------------------------------------------------

def run_analysis(seed=42, horizon=28, promotion_start=7, promotion_days=7):
    """Run the full pipeline: fixture -> prediction -> baseline -> metrics.

    Returns a JSON-serializable dict.
    """
    data = make_fixture(
        seed=seed,
        horizon=horizon,
        promotion_start=promotion_start,
        promotion_days=promotion_days,
    )

    pred = predict(data, use_covariates=True)
    forecast = pred["forecast"]
    lower = pred["lower"]
    upper = pred["upper"]
    actual = np.asarray(data["actual"], dtype=np.float64)
    context = np.asarray(data["context"], dtype=np.float64)

    baseline = _seasonal7_baseline(context, horizon)

    mae = float(np.mean(np.abs(forecast - actual)))
    baseline_mae = float(np.mean(np.abs(baseline - actual)))
    coverage = float(np.mean((actual >= lower) & (actual <= upper)))

    return {
        "seed": int(seed),
        "horizon": int(horizon),
        "promotion_start": int(promotion_start),
        "promotion_days": int(promotion_days),
        "context_length": int(len(context)),
        "fixture": {
            "context": [float(x) for x in context],
            "actual": [float(x) for x in actual],
            "past_promotion": [float(x) for x in data["past_promotion"]],
            "future_promotion": [float(x) for x in data["future_promotion"]],
            "past_weekday": [float(x) for x in data["past_weekday"]],
            "future_weekday": [float(x) for x in data["future_weekday"]],
        },
        "predictions": {
            "forecast": [float(x) for x in forecast],
            "lower": [float(x) for x in lower],
            "upper": [float(x) for x in upper],
        },
        "baseline": [float(x) for x in baseline],
        "metrics": {
            "mae": mae,
            "baseline_mae": baseline_mae,
            "coverage": coverage,
        },
    }
