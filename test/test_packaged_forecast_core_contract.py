"""Contracts for shipped forecast adapters, using a deterministic model API double.

These tests exercise orchestration and arithmetic, not external model quality.
"""

from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

RESOURCES = Path(__file__).resolve().parents[1] / "src/agilab/demos/resources"


class ArrayTensor:
    def __init__(self, value):
        self.value = np.asarray(value, dtype=np.float32)

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.value


@pytest.fixture(params=["", "_astra", "_rtx"])
def forecast_bundle(request, monkeypatch):
    calls, loads = [], []
    pipeline = SimpleNamespace()

    def predict(inputs, **kwargs):
        calls.append((inputs, kwargs))
        horizon = kwargs["prediction_length"]
        point = np.arange(horizon, dtype=np.float32).reshape(1, -1) + 100
        quantiles = np.stack((point - 10, point, point + 10), axis=-1)
        return [ArrayTensor(quantiles)], [ArrayTensor(point)]

    pipeline.predict_quantiles = predict

    def load(source, **kwargs):
        loads.append((source, kwargs))
        return pipeline

    torch = ModuleType("torch")
    torch.float32 = "float32"
    torch.set_num_threads = lambda count: None
    torch.inference_mode = nullcontext
    chronos = ModuleType("chronos")
    chronos.Chronos2Pipeline = SimpleNamespace(from_pretrained=load)
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "chronos", chronos)
    path = RESOURCES / ("forecast_notebook_demo" + request.param) / "forecast_core.py"
    name = "_forecast_contract" + (request.param or "_base")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    getter = {"": "_get_pipeline", "_astra": "_load_pipeline", "_rtx": "load_pipeline"}[
        request.param
    ]
    monkeypatch.delenv("CHRONOS_MODEL_PATH", raising=False)
    return SimpleNamespace(
        module=module,
        pipeline=pipeline,
        calls=calls,
        loads=loads,
        getter=getter,
        chronos=chronos,
        cache_attr="_pipeline_cache" if request.param == "" else "_pipeline",
    )


@pytest.mark.parametrize(
    "start,days,expected", [(1, 2, [0, 1, 1, 0]), (9, 2, [0] * 4), (0, 0, [0] * 4)]
)
def test_fixture_is_deterministic_and_clips_future_promotion(
    forecast_bundle, start, days, expected
):
    core = forecast_bundle.module
    first = core.make_fixture(
        seed=7, horizon=4, promotion_start=start, promotion_days=days
    )
    second = core.make_fixture(
        seed=7, horizon=4, promotion_start=start, promotion_days=days
    )
    assert len(first["context"]) == 256
    assert first["future_promotion"].tolist() == expected
    for key in first:
        np.testing.assert_array_equal(first[key], second[key])


@pytest.mark.parametrize("use_covariates", [False, True])
def test_prediction_never_reads_held_out_targets(forecast_bundle, use_covariates):
    core = forecast_bundle.module
    data = core.make_fixture(horizon=4)
    data["actual"] = object()
    result = core.predict(data, use_covariates=use_covariates)
    inputs, options = forecast_bundle.calls[-1]
    assert options["prediction_length"] == 4
    assert options["quantile_levels"] == [0.1, 0.5, 0.9]
    assert set(inputs[0]) == (
        {"target", "past_covariates", "future_covariates"}
        if use_covariates
        else {"target"}
    )
    np.testing.assert_array_equal(inputs[0]["target"], data["context"])
    assert result["forecast"].tolist() == [100, 101, 102, 103]
    assert result["lower"].tolist() == [90, 91, 92, 93]
    assert result["upper"].tolist() == [110, 111, 112, 113]


def test_model_location_is_pinned_or_explicit_and_cached(
    forecast_bundle, monkeypatch, tmp_path
):
    core = forecast_bundle.module
    getter = getattr(core, forecast_bundle.getter)
    assert getter() is forecast_bundle.pipeline
    assert getter() is forecast_bundle.pipeline
    assert len(forecast_bundle.loads) == 1
    source, options = forecast_bundle.loads[0]
    assert source == core.MODEL_ID
    assert options["revision"] == core.MODEL_REVISION
    assert options["device_map"] == "cpu"
    setattr(core, forecast_bundle.cache_attr, None)
    monkeypatch.setenv("CHRONOS_MODEL_PATH", str(tmp_path))
    assert getter() is forecast_bundle.pipeline
    source, options = forecast_bundle.loads[-1]
    assert source == str(tmp_path)
    assert "revision" not in options


def test_model_load_failure_remains_actionable(forecast_bundle, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("incomplete local snapshot")

    monkeypatch.setattr(
        forecast_bundle.chronos.Chronos2Pipeline, "from_pretrained", unavailable
    )
    with pytest.raises((RuntimeError, OSError)):
        getattr(forecast_bundle.module, forecast_bundle.getter)()
    assert getattr(forecast_bundle.module, forecast_bundle.cache_attr) is None


def test_analysis_metrics_match_independent_arithmetic(forecast_bundle):
    result = forecast_bundle.module.run_analysis(seed=11, horizon=9)
    fixture = result.get("fixture", result)
    predictions = result.get("predictions", result)
    metrics = result.get("metrics", result)
    actual = np.asarray(fixture["actual"])
    predicted = np.asarray(predictions["forecast"])
    baseline = np.asarray(result["baseline"])
    np.testing.assert_allclose(baseline, np.resize(fixture["context"][-7:], 9))
    assert metrics["mae"] == pytest.approx(np.abs(actual - predicted).mean())
    assert metrics["baseline_mae"] == pytest.approx(np.abs(actual - baseline).mean())
    expected_coverage = np.mean(
        (actual >= predictions["lower"]) & (actual <= predictions["upper"])
    )
    assert metrics["coverage"] == pytest.approx(expected_coverage)
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("forecast_bundle", ["_astra"], indirect=True)
@pytest.mark.parametrize(
    "key,value",
    [
        ("context", [float("nan")] * 256),
        ("context", [0] * 255),
        ("future_promotion", []),
        ("future_weekday", [[1]]),
        ("past_weekday", [0] * 255),
    ],
)
def test_invalid_inputs_fail_before_model_execution(forecast_bundle, key, value):
    data = forecast_bundle.module.make_fixture()
    data[key] = value
    with pytest.raises(ValueError):
        forecast_bundle.module.predict(data)
    assert not forecast_bundle.calls
