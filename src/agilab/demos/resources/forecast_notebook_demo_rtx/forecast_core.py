"""Core analysis for the Promotion forecast lab (synthetic data).

Adapted from the official Chronos-2 quickstart notebook:

- repository: amazon-science/chronos-forecasting
- commit:     10afa9ebe016e514f9d7dc1aa873f66af57e116b
- notebook:   notebooks/chronos-2-quickstart.ipynb
  (https://github.com/amazon-science/chronos-forecasting/blob/10afa9ebe016e514f9d7dc1aa873f66af57e116b/notebooks/chronos-2-quickstart.ipynb)

The upstream notebook demonstrates covariate forecasting with Chronos-2 on the
Rossmann retail and electricity-price datasets downloaded from the web. This
module is an explicitly authorized adaptation: it replaces those datasets with
a small fully synthetic fixture (no retail or electricity data is downloaded,
stored, or redistributed) and runs the Apache-2.0 ``autogluon/chronos-2-small``
model on CPU in float32. The outputs are scenario forecasts on synthetic data:
not causal estimates and not production-accuracy claims.
"""
from __future__ import annotations

import os
import threading

import numpy as np
import torch

MODEL_ID = "autogluon/chronos-2-small"
MODEL_REVISION = "ddec01313e50b6bc58ebaa92ede81bc24a3d9f9a"
MODEL_LICENSE = "Apache-2.0"
CONTEXT_LENGTH = 256
QUANTILE_LEVELS = [0.1, 0.5, 0.9]

_pipeline = None
_pipeline_lock = threading.Lock()
_infer_lock = threading.Lock()


class ModelUnavailableError(RuntimeError):
    """Raised when the Chronos-2 pipeline cannot be loaded or run."""


def _model_location() -> tuple[str, str | None]:
    """Return (source, revision) for the pinned Chronos-2 Small model.

    Uses CHRONOS_MODEL_PATH (a local directory) when present in the
    environment; otherwise the public model ID with its exact revision.
    """
    env_path = os.environ.get("CHRONOS_MODEL_PATH")
    if env_path:
        return env_path, None
    return MODEL_ID, MODEL_REVISION


def load_pipeline():
    """Load the pinned Chronos-2 Small pipeline once, on CPU float32."""
    global _pipeline
    if _pipeline is None:
        with _pipeline_lock:
            if _pipeline is None:
                os.environ.setdefault("HF_HUB_OFFLINE", "1")
                torch.set_num_threads(4)
                try:
                    from chronos import Chronos2Pipeline
                except Exception as exc:  # pragma: no cover - environment issue
                    raise ModelUnavailableError(
                        "The chronos package is not importable in this "
                        "environment; install the chronos-forecasting "
                        "package and retry."
                    ) from exc
                source, revision = _model_location()
                kwargs = {"device_map": "cpu", "dtype": "float32"}
                if revision is not None:
                    kwargs["revision"] = revision
                try:
                    _pipeline = Chronos2Pipeline.from_pretrained(source, **kwargs)
                except Exception as exc:
                    raise ModelUnavailableError(
                        f"Could not load Chronos-2 Small ({source}, "
                        f"revision={revision}) on CPU float32. Ensure the "
                        "model cache is available under HF_HOME, or set "
                        "CHRONOS_MODEL_PATH to a local model directory. "
                        f"Underlying error: {exc}"
                    ) from exc
    return _pipeline


def make_fixture(seed=42, horizon=28, promotion_start=7, promotion_days=7):
    """Build a synthetic promotion-forecasting fixture.

    A single series of length CONTEXT_LENGTH + horizon is generated as
    trend + weekly seasonality + 28-day seasonality + promotion lift +
    noise. The historical promotion flag follows a 28-day cycle
    (``(t % 28) >= 7 and < 14``); the future promotion schedule is all
    false except the selected interval
    ``promotion_start : promotion_start + promotion_days`` (clipped to the
    horizon). The held-out ``actual`` is generated with that selected
    future schedule. All values are float32.
    """
    horizon = int(horizon)
    if horizon <= 0:
        raise ValueError("horizon must be a positive integer")
    rng = np.random.default_rng(int(seed))
    t = np.arange(CONTEXT_LENGTH + horizon)
    promotion = np.zeros(t.shape, dtype=bool)
    past_t = t[:CONTEXT_LENGTH]
    promotion[:CONTEXT_LENGTH] = (past_t % 28 >= 7) & (past_t % 28 < 14)
    start = int(promotion_start)
    stop = min(start + int(promotion_days), horizon)
    if 0 <= start < horizon and stop > start:
        promotion[CONTEXT_LENGTH + start : CONTEXT_LENGTH + stop] = True
    weekday = np.sin(2.0 * np.pi * t / 7.0)
    noise = rng.normal(0.0, 2.5, t.size)
    sales = (
        100.0
        + 0.04 * t
        + 12.0 * weekday
        + 6.0 * np.sin(2.0 * np.pi * t / 28.0)
        + 40.0 * promotion
        + noise
    ).astype(np.float32)
    return {
        "context": sales[:CONTEXT_LENGTH],
        "actual": sales[CONTEXT_LENGTH:],
        "past_promotion": promotion[:CONTEXT_LENGTH].astype(np.float32),
        "future_promotion": promotion[CONTEXT_LENGTH:].astype(np.float32),
        "past_weekday": weekday[:CONTEXT_LENGTH].astype(np.float32),
        "future_weekday": weekday[CONTEXT_LENGTH:].astype(np.float32),
    }


def _seasonal7_baseline(context: np.ndarray, horizon: int) -> np.ndarray:
    """Repeat the last seven historical observations."""
    last_week = np.asarray(context, dtype=np.float32)[-7:]
    repeats = (horizon + 6) // 7
    baseline = np.tile(last_week, repeats)[:horizon]
    return baseline.astype(np.float32)


def predict(data, use_covariates=True):
    """Run real Chronos-2 inference on the synthetic fixture.

    Only ``data["context"]`` is used as the input target; the held-out
    ``data["actual"]`` is never used for prediction. Returns a dictionary of
    numpy arrays: forecast (median), lower (p10) and upper (p90).
    """
    pipeline = load_pipeline()
    horizon = int(len(data["future_promotion"]))
    context = np.asarray(data["context"], dtype=np.float32)
    inputs = [{"target": context}]
    if use_covariates:
        inputs[0]["past_covariates"] = {
            "promotion": np.asarray(data["past_promotion"], dtype=np.float32),
            "weekday": np.asarray(data["past_weekday"], dtype=np.float32),
        }
        inputs[0]["future_covariates"] = {
            "promotion": np.asarray(data["future_promotion"], dtype=np.float32),
            "weekday": np.asarray(data["future_weekday"], dtype=np.float32),
        }
    with _infer_lock:
        try:
            quantiles, point = pipeline.predict_quantiles(
                inputs,
                prediction_length=horizon,
                context_length=CONTEXT_LENGTH,
                batch_size=8,
                quantile_levels=list(QUANTILE_LEVELS),
            )
        except ModelUnavailableError:
            raise
        except Exception as exc:
            raise ModelUnavailableError(
                "Chronos-2 inference failed in this environment. "
                f"Underlying error: {exc}"
            ) from exc
    quantile_arr = np.asarray(quantiles[0].detach().cpu().numpy(), dtype=np.float32)
    point_arr = np.asarray(point[0].detach().cpu().numpy(), dtype=np.float32)
    return {
        "forecast": point_arr[0],
        "lower": quantile_arr[0, :, 0],
        "upper": quantile_arr[0, :, 2],
    }


def run_analysis(seed=42, horizon=28, promotion_start=7, promotion_days=7):
    """Run the full scenario: fixture, Chronos-2, seasonal baseline, metrics.

    Returns a JSON-serializable dictionary (lists of floats) with the fixture
    arrays, the Chronos-2 prediction, the seasonal-7 baseline, and the
    metrics ``mae``, ``baseline_mae`` and ``coverage`` (the fraction of held-out
    points inside the p10-p90 interval).
    """
    data = make_fixture(
        seed=seed, horizon=horizon, promotion_start=promotion_start,
        promotion_days=promotion_days,
    )
    prediction = predict(data, use_covariates=True)
    actual = np.asarray(data["actual"], dtype=np.float64)
    forecast = np.asarray(prediction["forecast"], dtype=np.float64)
    lower = np.asarray(prediction["lower"], dtype=np.float64)
    upper = np.asarray(prediction["upper"], dtype=np.float64)
    baseline = _seasonal7_baseline(data["context"], horizon)
    mae = float(np.mean(np.abs(forecast - actual)))
    baseline_mae = float(np.mean(np.abs(baseline - actual)))
    coverage = float(np.mean((actual >= lower) & (actual <= upper)))
    return {
        "seed": int(seed),
        "horizon": int(horizon),
        "promotion_start": int(promotion_start),
        "promotion_days": int(promotion_days),
        "model": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "model_license": MODEL_LICENSE,
        "device": "cpu",
        "dtype": "float32",
        "quantile_levels": list(QUANTILE_LEVELS),
        "context": [float(x) for x in np.asarray(data["context"], dtype=np.float64)],
        "actual": [float(x) for x in actual],
        "past_promotion": [float(x) for x in np.asarray(data["past_promotion"], dtype=np.float64)],
        "future_promotion": [float(x) for x in np.asarray(data["future_promotion"], dtype=np.float64)],
        "past_weekday": [float(x) for x in np.asarray(data["past_weekday"], dtype=np.float64)],
        "future_weekday": [float(x) for x in np.asarray(data["future_weekday"], dtype=np.float64)],
        "forecast": [float(x) for x in forecast],
        "lower": [float(x) for x in lower],
        "upper": [float(x) for x in upper],
        "baseline": [float(x) for x in np.asarray(baseline, dtype=np.float64)],
        "mae": mae,
        "baseline_mae": baseline_mae,
        "coverage": coverage,
    }
