from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


APP_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = APP_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from meteo_forecast import MeteoForecast, MeteoForecastArgs
from meteo_forecast_worker import MeteoForecastWorker


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
        target="meteo_forecast",
    )


def test_meteo_forecast_manager_seeds_dataset_and_distribution(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    args = MeteoForecastArgs()
    manager = MeteoForecast(env, args=args)

    files = sorted(manager.args.data_in.glob("*.csv"))
    assert len(files) == 1
    assert files[0].name == "meteo_fr_daily_sample.csv"
    assert manager.analysis_artifact_dir == env.AGILAB_EXPORT_ABS / "meteo_forecast" / "forecast_analysis"

    workers = {"127.0.0.1": 1}
    work_plan, metadata, partition_key, weights_key, unit = manager.build_distribution(workers)

    assert len(work_plan) == 1
    assert len(work_plan[0]) == 1
    assert len(work_plan[0][0]) == 1
    assert partition_key == "file"
    assert weights_key == "size_kb"
    assert unit == "KB"
    assert metadata[0][0]["file"] == "meteo_fr_daily_sample.csv"


def test_meteo_forecast_worker_exports_analysis_artifacts(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    args = MeteoForecastArgs(reset_target=True)
    manager = MeteoForecast(env, args=args)
    source = sorted(manager.args.data_in.glob("*.csv"))[0]

    worker = MeteoForecastWorker()
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

    metrics = json.loads((export_root / "forecast_metrics.json").read_text(encoding="utf-8"))
    predictions = pd.read_csv(export_root / "forecast_predictions.csv")

    assert metrics["station"] == "Paris-Montsouris"
    assert metrics["target"] == "tmax_c"
    assert metrics["horizon_days"] == 7
    assert {"date", "y_pred", "split"} <= set(predictions.columns)
    assert "forecast" in set(predictions["split"])
