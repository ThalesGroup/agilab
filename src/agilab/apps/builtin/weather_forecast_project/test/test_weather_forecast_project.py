from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from agi_node.reduction import ReduceArtifact


APP_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = APP_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from weather_forecast import WeatherForecast, WeatherForecastArgs  # noqa: E402
from weather_forecast.reduction import (  # noqa: E402
    REDUCE_ARTIFACT_NAME,
    REDUCER_NAME,
    build_reduce_artifact,
    partial_from_forecast_metrics,
    reduce_artifact_path,
)
from weather_forecast_legacy import (  # noqa: E402
    WeatherForecastLegacy,
    WeatherForecastLegacyArgs,
)
from weather_forecast_legacy import reduction as legacy_reduction  # noqa: E402
from weather_forecast_legacy_worker import WeatherForecastLegacyWorker  # noqa: E402
from weather_forecast_worker import WeatherForecastWorker  # noqa: E402


def _make_env(tmp_path: Path) -> SimpleNamespace:
    share_root = tmp_path / "share"
    share_root.mkdir(parents=True, exist_ok=True)
    export_root = tmp_path / "export"
    export_root.mkdir(parents=True, exist_ok=True)

    def _resolve_share_path(path):
        candidate = Path(path)
        return candidate if candidate.is_absolute() else share_root / candidate

    return SimpleNamespace(
        verbose=0,
        resolve_share_path=_resolve_share_path,
        home_abs=tmp_path,
        _is_managed_pc=False,
        AGI_LOCAL_SHARE=str(share_root),
        AGILAB_EXPORT_ABS=export_root,
        target="weather_forecast",
    )


def test_weather_forecast_manager_seeds_dataset_and_distribution(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    args = WeatherForecastArgs()
    manager = WeatherForecast(env, args=args)

    files = sorted(manager.args.data_in.glob("*.csv"))
    assert len(files) == 1
    assert files[0].name == "meteo_fr_daily_sample.csv"
    assert manager.analysis_artifact_dir == env.AGILAB_EXPORT_ABS / "weather_forecast" / "forecast_analysis"

    workers = {"127.0.0.1": 1}
    work_plan, metadata, partition_key, weights_key, unit = manager.build_distribution(workers)

    assert len(work_plan) == 1
    assert len(work_plan[0]) == 1
    assert len(work_plan[0][0]) == 1
    assert partition_key == "file"
    assert weights_key == "size_kb"
    assert unit == "KB"
    assert metadata[0][0]["file"] == "meteo_fr_daily_sample.csv"


def test_weather_forecast_worker_exports_analysis_artifacts(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    args = WeatherForecastArgs(reset_target=True)
    manager = WeatherForecast(env, args=args)
    source = sorted(manager.args.data_in.glob("*.csv"))[0]

    worker = WeatherForecastWorker()
    worker.env = env
    worker.args = manager.args.model_dump(mode="json")
    worker._worker_id = 0
    worker.worker_id = 0
    worker.verbose = 0
    worker.start()

    result = worker.work_pool(str(source))

    assert isinstance(result, pd.DataFrame)
    assert {"date", "station", "target", "y_true", "y_pred", "split"} <= set(result.columns)
    assert {"backtest", "forecast"} <= set(result["split"])

    worker.work_done(result)

    result_root = Path(worker.data_out)
    export_root = env.AGILAB_EXPORT_ABS / env.target / "forecast_analysis"
    for root in (result_root, export_root):
        assert (root / "forecast_predictions.csv").is_file()
        assert (root / "forecast_metrics.json").is_file()
        reduce_path = reduce_artifact_path(root, 0)
        assert reduce_path.is_file()
        artifact = ReduceArtifact.from_dict(json.loads(reduce_path.read_text(encoding="utf-8")))
        assert artifact.name == REDUCE_ARTIFACT_NAME
        assert artifact.reducer == REDUCER_NAME
        assert artifact.partial_count == 1
        assert artifact.payload["forecast_run_count"] == 1
        assert artifact.payload["stations"] == ["Paris-Montsouris"]

    metrics = json.loads((export_root / "forecast_metrics.json").read_text(encoding="utf-8"))
    predictions = pd.read_csv(export_root / "forecast_predictions.csv")

    assert metrics["station"] == "Paris-Montsouris"
    assert metrics["target"] == "tmax_c"
    assert metrics["horizon_days"] == 7
    assert metrics["prediction_rows"] == len(predictions)
    assert metrics["backtest_rows"] > 0
    assert metrics["forecast_rows"] == 7
    assert metrics["source_files"] == ["meteo_fr_daily_sample.csv"]
    assert {"date", "y_pred", "split"} <= set(predictions.columns)
    assert "forecast" in set(predictions["split"])


def test_weather_forecast_worker_uses_share_path_without_export_attr(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    args = WeatherForecastArgs(reset_target=True)
    manager = WeatherForecast(env, args=args)

    worker_env = SimpleNamespace(**vars(env))
    delattr(worker_env, "AGILAB_EXPORT_ABS")
    worker = WeatherForecastWorker()
    worker.env = worker_env
    worker.args = manager.args.model_dump(mode="json")
    worker._worker_id = 0
    worker.worker_id = 0
    worker.verbose = 0

    worker.start()

    assert worker.artifact_dir == Path(worker_env.AGI_LOCAL_SHARE) / worker_env.target / "forecast_analysis"


def test_weather_forecast_reduce_contract_merges_forecast_partials() -> None:
    base_metrics = {
        "scenario": "Notebook migration builtin weather forecast",
        "station": "Paris-Montsouris",
        "target": "tmax_c",
        "model_name": "ForecasterRecursive(RandomForestRegressor)",
        "horizon_days": 7,
        "validation_days": 21,
        "lags": 7,
        "train_end": "2025-03-31",
        "test_start": "2025-04-01",
        "test_end": "2025-04-08",
        "mae": 1.0,
        "rmse": 2.0,
        "mape": 10.0,
        "prediction_rows": 15,
        "backtest_rows": 8,
        "forecast_rows": 7,
        "source_files": ["meteo_fr_daily_sample.csv"],
    }
    variant_metrics = {
        **base_metrics,
        "station": "Lyon-Bron",
        "mae": 2.0,
        "rmse": 4.0,
        "mape": 20.0,
        "prediction_rows": 19,
        "backtest_rows": 12,
        "source_files": ["meteo_fr_daily_sample_b.csv"],
    }

    artifact = build_reduce_artifact(
        (
            partial_from_forecast_metrics(base_metrics, partial_id="base"),
            partial_from_forecast_metrics(variant_metrics, partial_id="variant"),
        )
    )

    assert artifact.name == REDUCE_ARTIFACT_NAME
    assert artifact.reducer == REDUCER_NAME
    assert artifact.partial_count == 2
    assert artifact.payload["forecast_run_count"] == 2
    assert artifact.payload["stations"] == ["Lyon-Bron", "Paris-Montsouris"]
    assert artifact.payload["targets"] == ["tmax_c"]
    assert artifact.payload["source_file_count"] == 2
    assert artifact.payload["prediction_rows"] == 34
    assert artifact.payload["backtest_rows"] == 20
    assert artifact.payload["forecast_rows"] == 14
    assert artifact.payload["mae"] == 1.6
    assert artifact.payload["rmse"] == 3.3466
    assert artifact.payload["mape"] == 16.0


def test_weather_forecast_legacy_imports_keep_defaults_and_module_identity(
    tmp_path: Path,
) -> None:
    env = _make_env(tmp_path)
    env.target = "weather_forecast_legacy"
    args = WeatherForecastLegacyArgs()
    assert args.data_in == Path("weather_forecast_legacy/dataset")
    assert args.data_out == Path("weather_forecast_legacy/results")

    manager = WeatherForecastLegacy(env, args=args)

    assert manager.__class__.__module__ == (
        "weather_forecast_legacy.weather_forecast_legacy"
    )
    assert WeatherForecastLegacyWorker.__module__ == (
        "weather_forecast_legacy_worker.weather_forecast_legacy_worker"
    )
    assert (
        WeatherForecastLegacyWorker.reduce_artifact_writer
        is legacy_reduction.write_reduce_artifact
    )


def test_weather_forecast_legacy_writer_preserves_historical_contract(
    tmp_path: Path,
) -> None:
    metrics = {
        "scenario": "Notebook migration builtin weather forecast",
        "station": "Paris-Montsouris",
        "target": "tmax_c",
        "model_name": "ForecasterRecursive(RandomForestRegressor)",
        "horizon_days": 7,
        "validation_days": 21,
        "lags": 7,
        "train_end": "2025-03-31",
        "test_start": "2025-04-01",
        "test_end": "2025-04-08",
        "mae": 1.0,
        "rmse": 2.0,
        "mape": 10.0,
        "prediction_rows": 15,
        "backtest_rows": 8,
        "forecast_rows": 7,
        "source_files": ["meteo_fr_daily_sample.csv"],
    }

    output_path = legacy_reduction.write_reduce_artifact(
        metrics,
        tmp_path,
        worker_id=3,
    )
    artifact = ReduceArtifact.from_dict(
        json.loads(output_path.read_text(encoding="utf-8"))
    )

    assert artifact.name == legacy_reduction.REDUCE_ARTIFACT_NAME
    assert artifact.reducer == legacy_reduction.REDUCER_NAME
    assert artifact.partial_ids == ("weather_forecast_legacy_worker_3",)
    assert artifact.metadata["app"] == "weather_forecast_legacy_project"


def test_weather_forecast_legacy_worker_emits_historical_reduce_identity(
    tmp_path: Path,
) -> None:
    env = _make_env(tmp_path)
    env.target = "weather_forecast_legacy"
    manager = WeatherForecastLegacy(env, args=WeatherForecastLegacyArgs(reset_target=True))
    worker = WeatherForecastLegacyWorker()
    worker.env = env
    worker.args = manager.args.model_dump(mode="json")
    worker._worker_id = 0
    worker.worker_id = 0
    worker.verbose = 0
    worker.start()
    result = pd.DataFrame(
        [
            {
                "date": "2026-01-01",
                "station": "Paris-Montsouris",
                "target": "tmax_c",
                "y_true": 10.0,
                "y_pred": 9.5,
                "split": "backtest",
                "source_file": "meteo_fr_daily_sample.csv",
            },
            {
                "date": "2026-01-02",
                "station": "Paris-Montsouris",
                "target": "tmax_c",
                "y_true": float("nan"),
                "y_pred": 11.0,
                "split": "forecast",
                "source_file": "meteo_fr_daily_sample.csv",
            },
        ]
    )

    worker.work_done(result)

    for root in (Path(worker.data_out), Path(worker.artifact_dir)):
        artifact_path = legacy_reduction.reduce_artifact_path(root, 0)
        artifact = ReduceArtifact.from_dict(
            json.loads(artifact_path.read_text(encoding="utf-8"))
        )
        assert artifact.name == legacy_reduction.REDUCE_ARTIFACT_NAME
        assert artifact.reducer == legacy_reduction.REDUCER_NAME
        assert artifact.partial_ids == ("weather_forecast_legacy_worker_0",)
