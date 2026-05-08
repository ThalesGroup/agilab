# skforecast + Meteo-France Pilot

This repo uses a lightweight French forecasting pilot to demonstrate notebook to
AGILAB migration.

## Source material

- local daily weather sample shaped like a Meteo-France daily export
- 3 notebooks:
  - prepare the series
  - backtest a forecaster
  - compare predictions and metrics

## Target AGILAB shape

- `lab_stages.toml`
  - `load_clean`
  - `build_features`
  - `backtest_forecaster`
  - `forecast_next_days`
- `pipeline_view.dot`
  - scenario inputs
  - feature engineering
  - forecast and backtest
  - analysis artifacts
- `view_forecast_analysis`
  - reads `forecast_metrics.json`
  - reads `forecast_predictions.csv`
  - renders stable analysis outside the notebooks

## Artifact contract

- `forecast_metrics.json`
  - model name
  - target name
  - station label
  - horizon
  - MAE / RMSE / MAPE
- `forecast_predictions.csv`
  - `date`
  - `y_true`
  - `y_pred`
  - optional split / station columns
