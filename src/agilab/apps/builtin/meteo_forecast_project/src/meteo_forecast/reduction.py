"""Reduce-contract adoption for the built-in Meteo forecast app."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from agi_node.reduction import (
    ReduceArtifact,
    ReduceContract,
    ReducePartial,
    require_payload_keys,
)


REDUCE_ARTIFACT_FILENAME_TEMPLATE = "reduce_summary_worker_{worker_id}.json"
REDUCE_ARTIFACT_NAME = "meteo_forecast_reduce_summary"
REDUCER_NAME = "meteo_forecast.forecast-metrics.v1"

_REQUIRED_METRIC_KEYS = (
    "scenario",
    "station",
    "target",
    "model_name",
    "horizon_days",
    "validation_days",
    "lags",
    "train_end",
    "test_start",
    "test_end",
    "mae",
    "rmse",
    "mape",
    "prediction_rows",
    "backtest_rows",
    "forecast_rows",
    "source_files",
)
_REQUIRED_PAYLOAD_KEYS = (
    "forecast_run_count",
    "prediction_rows",
    "backtest_rows",
    "forecast_rows",
    "mae_weighted_sum",
    "rmse_squared_weighted_sum",
    "mape_weighted_sum",
    "mape_weight",
    "stations",
    "targets",
    "model_names",
    "source_files",
    "horizon_days",
    "validation_days",
    "lags",
    "train_end_dates",
    "test_start_dates",
    "test_end_dates",
)


def _as_int(metrics: Mapping[str, Any], key: str) -> int:
    return int(metrics.get(key, 0) or 0)


def _as_float(metrics: Mapping[str, Any], key: str) -> float:
    return float(metrics.get(key, 0.0) or 0.0)


def _optional_float(metrics: Mapping[str, Any], key: str) -> float | None:
    value = metrics.get(key)
    if value is None:
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _strings(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return sorted(str(item) for item in value if str(item))
    if value is None or value == "":
        return []
    return [str(value)]


def _sorted_strings(values: set[str]) -> list[str]:
    return sorted(value for value in values if value)


def _merge_meteo_forecast_partials(partials: Sequence[ReducePartial]) -> dict[str, Any]:
    stations: set[str] = set()
    targets: set[str] = set()
    model_names: set[str] = set()
    source_files: set[str] = set()
    horizon_days: set[str] = set()
    validation_days: set[str] = set()
    lags: set[str] = set()
    train_end_dates: set[str] = set()
    test_start_dates: set[str] = set()
    test_end_dates: set[str] = set()
    prediction_rows = 0
    backtest_rows = 0
    forecast_rows = 0
    mae_weighted_sum = 0.0
    rmse_squared_weighted_sum = 0.0
    mape_weighted_sum = 0.0
    mape_weight = 0

    for partial in partials:
        payload = partial.payload
        partial_backtest_rows = int(payload["backtest_rows"])
        prediction_rows += int(payload["prediction_rows"])
        backtest_rows += partial_backtest_rows
        forecast_rows += int(payload["forecast_rows"])
        mae_weighted_sum += float(payload["mae_weighted_sum"])
        rmse_squared_weighted_sum += float(payload["rmse_squared_weighted_sum"])
        mape_weighted_sum += float(payload["mape_weighted_sum"])
        mape_weight += int(payload["mape_weight"])
        stations.update(str(item) for item in payload["stations"])
        targets.update(str(item) for item in payload["targets"])
        model_names.update(str(item) for item in payload["model_names"])
        source_files.update(str(item) for item in payload["source_files"])
        horizon_days.update(str(item) for item in payload["horizon_days"])
        validation_days.update(str(item) for item in payload["validation_days"])
        lags.update(str(item) for item in payload["lags"])
        train_end_dates.update(str(item) for item in payload["train_end_dates"])
        test_start_dates.update(str(item) for item in payload["test_start_dates"])
        test_end_dates.update(str(item) for item in payload["test_end_dates"])

    rmse = math.sqrt(rmse_squared_weighted_sum / backtest_rows) if backtest_rows else 0.0
    return {
        "forecast_run_count": len(partials),
        "stations": _sorted_strings(stations),
        "targets": _sorted_strings(targets),
        "model_names": _sorted_strings(model_names),
        "source_files": _sorted_strings(source_files),
        "source_file_count": len(source_files),
        "horizon_days": _sorted_strings(horizon_days),
        "validation_days": _sorted_strings(validation_days),
        "lags": _sorted_strings(lags),
        "train_end_dates": _sorted_strings(train_end_dates),
        "test_start_dates": _sorted_strings(test_start_dates),
        "test_end_dates": _sorted_strings(test_end_dates),
        "prediction_rows": prediction_rows,
        "backtest_rows": backtest_rows,
        "forecast_rows": forecast_rows,
        "mae": round(mae_weighted_sum / backtest_rows, 4) if backtest_rows else 0.0,
        "rmse": round(rmse, 4),
        "mape": round(mape_weighted_sum / mape_weight, 4) if mape_weight else None,
    }


def _validate_meteo_forecast_artifact(artifact: ReduceArtifact) -> None:
    payload = artifact.payload
    if int(payload["forecast_run_count"]) <= 0:
        raise ValueError("meteo_forecast reducer produced no forecast runs")
    if int(payload["backtest_rows"]) <= 0:
        raise ValueError("meteo_forecast reducer produced no backtest rows")
    if not payload["stations"]:
        raise ValueError("meteo_forecast reducer produced no station metadata")


METEO_FORECAST_REDUCE_CONTRACT = ReduceContract(
    name=REDUCER_NAME,
    artifact_name=REDUCE_ARTIFACT_NAME,
    merge=_merge_meteo_forecast_partials,
    validate_partial=require_payload_keys(*_REQUIRED_PAYLOAD_KEYS),
    validate_artifact=_validate_meteo_forecast_artifact,
    metadata={
        "app": "meteo_forecast_project",
        "domain": "weather-forecast",
        "scope": "forecast-metrics",
    },
)


def reduce_artifact_path(output_dir: Path | str, worker_id: int | str) -> Path:
    filename = REDUCE_ARTIFACT_FILENAME_TEMPLATE.format(worker_id=worker_id)
    return Path(output_dir) / filename


def partial_from_forecast_metrics(
    metrics: Mapping[str, Any],
    *,
    partial_id: str,
    artifact_path: Path | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReducePartial:
    missing = [key for key in _REQUIRED_METRIC_KEYS if key not in metrics]
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"meteo_forecast metrics missing columns: {missing_text}")

    backtest_rows = _as_int(metrics, "backtest_rows")
    rmse = _as_float(metrics, "rmse")
    mape = _optional_float(metrics, "mape")
    payload = {
        "forecast_run_count": 1,
        "stations": _strings(metrics["station"]),
        "targets": _strings(metrics["target"]),
        "model_names": _strings(metrics["model_name"]),
        "source_files": _strings(metrics["source_files"]),
        "horizon_days": _strings(metrics["horizon_days"]),
        "validation_days": _strings(metrics["validation_days"]),
        "lags": _strings(metrics["lags"]),
        "train_end_dates": _strings(metrics["train_end"]),
        "test_start_dates": _strings(metrics["test_start"]),
        "test_end_dates": _strings(metrics["test_end"]),
        "prediction_rows": _as_int(metrics, "prediction_rows"),
        "backtest_rows": backtest_rows,
        "forecast_rows": _as_int(metrics, "forecast_rows"),
        "mae_weighted_sum": _as_float(metrics, "mae") * backtest_rows,
        "rmse_squared_weighted_sum": (rmse**2) * backtest_rows,
        "mape_weighted_sum": (mape * backtest_rows) if mape is not None else 0.0,
        "mape_weight": backtest_rows if mape is not None else 0,
    }
    return ReducePartial(
        partial_id=partial_id,
        payload=payload,
        metadata=metadata or {},
        artifact_path=str(artifact_path) if artifact_path else None,
    )


def build_reduce_artifact(partials: Sequence[ReducePartial]) -> ReduceArtifact:
    return METEO_FORECAST_REDUCE_CONTRACT.build_artifact(partials)


def write_reduce_artifact(
    metrics: Mapping[str, Any],
    output_dir: Path | str,
    *,
    worker_id: int | str,
) -> Path:
    output_path = reduce_artifact_path(output_dir, worker_id)
    partial = partial_from_forecast_metrics(
        metrics,
        partial_id=f"meteo_forecast_worker_{worker_id}",
        artifact_path=output_path,
        metadata={"worker_id": str(worker_id)},
    )
    artifact = build_reduce_artifact((partial,))
    output_path.write_text(
        json.dumps(artifact.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


__all__ = [
    "METEO_FORECAST_REDUCE_CONTRACT",
    "REDUCE_ARTIFACT_FILENAME_TEMPLATE",
    "REDUCE_ARTIFACT_NAME",
    "REDUCER_NAME",
    "build_reduce_artifact",
    "partial_from_forecast_metrics",
    "reduce_artifact_path",
    "write_reduce_artifact",
]
