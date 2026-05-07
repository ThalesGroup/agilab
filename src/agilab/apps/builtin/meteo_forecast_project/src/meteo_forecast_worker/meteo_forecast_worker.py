"""Pandas-based worker for the built-in Meteo forecast project."""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from skforecast.model_selection import TimeSeriesFold, backtesting_forecaster
from skforecast.recursive import ForecasterRecursive

from agi_node.pandas_worker import PandasWorker
from meteo_forecast.reduction import write_reduce_artifact

logger = logging.getLogger(__name__)
_runtime: dict[str, object] = {}


def _artifact_dir(env: object, leaf: str) -> Path:
    export_root = getattr(env, "AGILAB_EXPORT_ABS", None)
    target = str(getattr(env, "target", "") or "")
    relative = Path(target) / leaf if target else Path(leaf)
    if export_root is not None:
        return Path(export_root) / relative
    resolve_share_path = getattr(env, "resolve_share_path", None)
    if callable(resolve_share_path):
        return Path(resolve_share_path(relative))
    return Path.home() / "export" / relative


class MeteoForecastWorker(PandasWorker):
    """Execute the weather forecasting workflow and export stable analysis artifacts."""

    pool_vars: dict[str, object] = {}

    def start(self):
        global _runtime
        if isinstance(self.args, dict):
            self.args = SimpleNamespace(**self.args)
        elif not isinstance(self.args, SimpleNamespace):
            self.args = SimpleNamespace(**vars(self.args))

        data_paths = self.setup_data_directories(
            source_path=self.args.data_in,
            target_path=self.args.data_out,
            target_subdir="results",
            reset_target=bool(getattr(self.args, "reset_target", False)),
        )
        self.args.data_in = data_paths.normalized_input
        self.args.data_out = data_paths.normalized_output
        self.data_out = data_paths.output_path
        self.artifact_dir = _artifact_dir(self.env, "forecast_analysis")
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.pool_vars = {"args": self.args}
        _runtime = self.pool_vars

    def pool_init(self, worker_vars):
        global _runtime
        _runtime = worker_vars

    def _current_args(self) -> SimpleNamespace:
        args = _runtime.get("args", self.args)
        if isinstance(args, dict):
            return SimpleNamespace(**args)
        return args

    def work_init(self) -> None:
        return None

    def _load_station_frame(self, file_path: str | Path) -> pd.DataFrame:
        args = self._current_args()
        source = Path(str(file_path)).expanduser()
        df = pd.read_csv(source, parse_dates=["date"]).sort_values("date")
        required = {"date", "station", args.target_column}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Missing required columns in {source.name}: {sorted(missing)}")

        station_df = df.loc[df["station"] == args.station, ["date", "station", args.target_column]].copy()
        if station_df.empty:
            available = sorted({str(v) for v in df["station"].dropna().unique().tolist()})
            raise ValueError(
                f"Station {args.station!r} not found in {source.name}. Available stations: {available}"
            )
        if len(station_df) <= args.validation_days + args.lags:
            raise ValueError(
                "Need more rows than validation_days + lags to run the forecast "
                f"(got {len(station_df)}, need > {args.validation_days + args.lags})."
            )
        return station_df.reset_index(drop=True)

    def work_pool(self, file_path):
        args = self._current_args()
        station_df = self._load_station_frame(file_path)

        y = station_df[args.target_column].astype(float)
        dates = pd.to_datetime(station_df["date"], errors="coerce")

        initial_train_size = len(station_df) - int(args.validation_days)
        if initial_train_size <= int(args.lags):
            raise ValueError(
                f"initial_train_size={initial_train_size} must be greater than lags={args.lags}"
            )

        forecaster = ForecasterRecursive(
            estimator=RandomForestRegressor(
                random_state=int(args.random_state),
                n_estimators=int(args.n_estimators),
            ),
            lags=int(args.lags),
        )
        cv = TimeSeriesFold(
            steps=int(args.horizon_days),
            initial_train_size=initial_train_size,
            refit=False,
            fixed_train_size=True,
            allow_incomplete_fold=True,
            verbose=False,
        )
        _, predictions = backtesting_forecaster(
            forecaster=forecaster,
            y=y,
            cv=cv,
            metric=[
                "mean_absolute_error",
                "mean_squared_error",
                "mean_absolute_percentage_error",
            ],
            verbose=False,
            show_progress=False,
        )

        prediction_index = predictions.index.to_list()
        backtest = pd.DataFrame(
            {
                "date": dates.iloc[prediction_index].reset_index(drop=True),
                "station": args.station,
                "target": args.target_column,
                "y_true": y.iloc[prediction_index].reset_index(drop=True),
                "y_pred": predictions["pred"].reset_index(drop=True),
                "split": "backtest",
            }
        )

        forecaster.fit(y=y)
        future_predictions = forecaster.predict(steps=int(args.horizon_days))
        future_dates = pd.date_range(
            start=dates.iloc[-1] + pd.Timedelta(days=1),
            periods=int(args.horizon_days),
            freq="D",
        )
        forecast = pd.DataFrame(
            {
                "date": future_dates,
                "station": args.station,
                "target": args.target_column,
                "y_true": pd.Series([float("nan")] * len(future_predictions), dtype="float64"),
                "y_pred": list(future_predictions),
                "split": "forecast",
            }
        )
        result = pd.concat([backtest, forecast], ignore_index=True)
        result["source_file"] = Path(str(file_path)).name
        result["model_name"] = "ForecasterRecursive(RandomForestRegressor)"
        return result

    def _metrics_payload(self, df: pd.DataFrame) -> dict[str, object]:
        args = self._current_args()
        backtest = df.loc[df["split"] == "backtest"].copy()
        errors = backtest["y_true"] - backtest["y_pred"]
        mae = float(errors.abs().mean())
        rmse = float(math.sqrt((errors**2).mean()))
        non_zero = backtest["y_true"].replace(0, pd.NA)
        mape_series = (errors.abs() / non_zero.abs()).dropna()
        mape = float(mape_series.mean() * 100.0) if not mape_series.empty else None

        first_test_day = pd.to_datetime(backtest["date"].min())
        train_end = first_test_day - pd.Timedelta(days=1)
        last_test_day = pd.to_datetime(backtest["date"].max())

        return {
            "scenario": "Notebook migration builtin weather forecast",
            "station": str(args.station),
            "target": str(args.target_column),
            "model_name": "ForecasterRecursive(RandomForestRegressor)",
            "horizon_days": int(args.horizon_days),
            "validation_days": int(args.validation_days),
            "lags": int(args.lags),
            "train_end": train_end.strftime("%Y-%m-%d"),
            "test_start": first_test_day.strftime("%Y-%m-%d"),
            "test_end": last_test_day.strftime("%Y-%m-%d"),
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "mape": round(mape, 4) if mape is not None else None,
            "prediction_rows": int(len(df)),
            "backtest_rows": int(len(backtest)),
            "forecast_rows": int((df["split"] == "forecast").sum()),
            "source_files": sorted(str(item) for item in df["source_file"].dropna().unique().tolist()),
            "notes": (
                "Built-in AGILAB forecast app migrated from the skforecast + Meteo-France "
                "notebook sequence."
            ),
        }

    def work_done(self, df: pd.DataFrame | None = None) -> None:
        if df is None or df.empty:
            return

        predictions = df.copy()
        predictions["date"] = pd.to_datetime(predictions["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        metrics = self._metrics_payload(predictions)

        destinations = [Path(self.data_out), Path(self.artifact_dir)]
        for root in destinations:
            root.mkdir(parents=True, exist_ok=True)
            (root / "forecast_predictions.csv").write_text(
                predictions.to_csv(index=False),
                encoding="utf-8",
            )
            (root / "forecast_metrics.json").write_text(
                json.dumps(metrics, indent=2),
                encoding="utf-8",
            )
            write_reduce_artifact(
                metrics,
                root,
                worker_id=getattr(self, "_worker_id", 0),
            )

        logger.info("Saved forecast artifacts to %s and %s", self.data_out, self.artifact_dir)
