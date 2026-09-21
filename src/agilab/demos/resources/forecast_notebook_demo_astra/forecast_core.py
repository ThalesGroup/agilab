"""Synthetic adaptation of Amazon Science's Chronos-2 covariate quickstart.

Source: source/provenance.json (commit 10afa9ebe016e514f9d7dc1aa873f66af57e116b).
Model: AutoGluon Chronos-2 Small, Apache-2.0. No upstream datasets are used.
"""

from __future__ import annotations

import os
import threading

import numpy as np

MODEL_ID = "autogluon/chronos-2-small"
MODEL_REVISION = "ddec01313e50b6bc58ebaa92ede81bc24a3d9f9a"
CONTEXT_LENGTH = 256
QUANTILES = [0.1, 0.5, 0.9]
_pipeline = None
_model_lock = threading.RLock()


class PrerequisiteError(RuntimeError):
    """An already-installed dependency or locally available model is missing."""


def make_fixture(seed=42, horizon=28, promotion_start=7, promotion_days=7):
    """Generate synthetic daily sales; promotion start is a zero-based offset."""
    for name, value in dict(seed=seed, horizon=horizon, promotion_start=promotion_start,
                            promotion_days=promotion_days).items():
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise ValueError(f"{name} must be an integer.")
    if seed < 0 or horizon < 1 or promotion_start < 0 or promotion_days < 0:
        raise ValueError("Use a nonnegative seed and promotion offsets, and a positive horizon.")
    rng = np.random.default_rng(seed)
    t = np.arange(CONTEXT_LENGTH + horizon)
    promotion = (t % 28 >= 7) & (t % 28 < 14)
    future_promotion = np.zeros(horizon, dtype=np.float32)
    start = min(promotion_start, horizon)
    stop = min(promotion_start + promotion_days, horizon)
    future_promotion[start:stop] = 1.0
    promotion[CONTEXT_LENGTH:] = future_promotion.astype(bool)
    weekday = np.sin(2 * np.pi * t / 7)
    sales = (100 + 0.04 * t + 12 * weekday + 6 * np.sin(2 * np.pi * t / 28)
             + 40 * promotion + rng.normal(0, 2.5, len(t))).astype(np.float32)
    return {
        "context": sales[:CONTEXT_LENGTH].copy(),
        "actual": sales[CONTEXT_LENGTH:].copy(),
        "past_promotion": promotion[:CONTEXT_LENGTH].astype(np.float32),
        "future_promotion": future_promotion,
        "past_weekday": weekday[:CONTEXT_LENGTH].astype(np.float32),
        "future_weekday": weekday[CONTEXT_LENGTH:].astype(np.float32),
    }


def _load_pipeline():
    """Called under the model lock; keep a single lazy CPU float32 pipeline."""
    global _pipeline
    if _pipeline is None:
        try:
            import torch
            from chronos import Chronos2Pipeline
        except ImportError as exc:
            raise PrerequisiteError(
                "Chronos inference dependencies are unavailable. Use the prepared Python "
                "environment with chronos-forecasting, torch and transformers<5."
            ) from exc
        torch.set_num_threads(4)
        model_path = os.environ.get("CHRONOS_MODEL_PATH")
        options = dict(device_map="cpu", dtype=torch.float32, local_files_only=True)
        if not model_path:
            options["revision"] = MODEL_REVISION
        try:
            _pipeline = Chronos2Pipeline.from_pretrained(model_path or MODEL_ID, **options)
        except (OSError, ValueError, ImportError) as exc:
            raise PrerequisiteError(
                "Cannot load the pinned Chronos-2 Small model locally. Set CHRONOS_MODEL_PATH "
                f"to the complete predownloaded {MODEL_ID} snapshot at {MODEL_REVISION}, "
                "or make that exact revision available in the Hugging Face cache. "
                "This workflow does not download models."
            ) from exc
    return _pipeline


def _array(data, key, length=None):
    value = np.asarray(data[key], dtype=np.float32)
    if value.ndim != 1 or not np.isfinite(value).all():
        raise ValueError(f"{key} must be a finite one-dimensional array.")
    if length is not None and len(value) != length:
        raise ValueError(f"{key} must contain {length} values.")
    return value


def predict(data, use_covariates=True):
    """Run real Chronos inference. Held-out actual is never read here."""
    context = _array(data, "context", CONTEXT_LENGTH)
    future_promotion = _array(data, "future_promotion")
    horizon = len(future_promotion)
    if horizon < 1:
        raise ValueError("The future schedule must contain at least one day.")
    item = {"target": context}
    if use_covariates:
        item["past_covariates"] = {
            "promotion": _array(data, "past_promotion", CONTEXT_LENGTH),
            "weekday": _array(data, "past_weekday", CONTEXT_LENGTH),
        }
        item["future_covariates"] = {
            "promotion": future_promotion,
            "weekday": _array(data, "future_weekday", horizon),
        }
    with _model_lock:
        pipeline = _load_pipeline()
        import torch

        with torch.inference_mode():
            quantiles, points = pipeline.predict_quantiles(
                [item], prediction_length=horizon, context_length=CONTEXT_LENGTH,
                batch_size=8, quantile_levels=QUANTILES,
            )
        q = quantiles[0].detach().cpu().numpy()
        point = points[0].detach().cpu().numpy()
    if q.shape != (1, horizon, 3) or point.shape != (1, horizon):
        raise RuntimeError(f"Unexpected Chronos output shapes: {q.shape}, {point.shape}.")
    result = {"forecast": point[0].copy(), "lower": q[0, :, 0].copy(),
              "upper": q[0, :, 2].copy()}
    if not all(np.isfinite(v).all() for v in result.values()):
        raise RuntimeError("Chronos returned non-finite predictions.")
    if np.any(result["lower"] > result["upper"]):
        raise RuntimeError("Chronos returned crossed uncertainty bounds.")
    return result


def seasonal_baseline(context, horizon):
    """Repeat the last seven observed historical targets, without future targets."""
    return np.resize(np.asarray(context, dtype=np.float32)[-7:], horizon)


def evaluate(actual, predictions, baseline):
    actual = np.asarray(actual, dtype=np.float32)
    return {
        "mae": float(np.mean(np.abs(actual - predictions["forecast"]))),
        "baseline_mae": float(np.mean(np.abs(actual - baseline))),
        "coverage": float(np.mean((actual >= predictions["lower"]) &
                                  (actual <= predictions["upper"]))),
    }


def assemble_results(data, predictions, baseline, parameters):
    """Create the same JSON-ready result for the notebook and the application."""
    return {
        "data_kind": "synthetic",
        "parameters": parameters,
        "model": {"id": MODEL_ID, "revision": MODEL_REVISION, "device": "cpu",
                  "dtype": "float32", "quantile_levels": QUANTILES, "license": "Apache-2.0"},
        "fixture": {name: values.tolist() for name, values in data.items()},
        "predictions": {name: values.tolist() for name, values in predictions.items()},
        "baseline": baseline.tolist(),
        "metrics": evaluate(data["actual"], predictions, baseline),
    }


def run_analysis(seed=42, horizon=28, promotion_start=7, promotion_days=7):
    parameters = dict(seed=seed, horizon=horizon, promotion_start=promotion_start,
                      promotion_days=promotion_days)
    data = make_fixture(**parameters)
    predictions = predict(data)
    baseline = seasonal_baseline(data["context"], horizon)
    return assemble_results(data, predictions, baseline, parameters)
