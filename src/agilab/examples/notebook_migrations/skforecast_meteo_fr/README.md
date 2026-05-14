# skforecast Meteo-France Migration Pilot

This folder is a lightweight, local-first migration example for showing how a
small notebook workflow can move into AGILAB without changing the core data
science story.

## Source notebooks

- `notebooks/01_prepare_meteo_series.ipynb`
- `notebooks/02_backtest_temperature_forecast.ipynb`
- `notebooks/03_compare_predictions.ipynb`

## Why migrate to AGILAB

Notebook-only workflow:

- hidden execution order
- parameters spread across cells
- outputs depend on the last interactive state
- no reusable analysis page for non-notebook users

AGILAB workflow:

- explicit pipeline stages in `migrated_project/lab_stages.toml`
- conceptual pipeline view in `migrated_project/pipeline_view.dot`
- stable exported artifacts under `analysis_artifacts/`
- reusable `ANALYSIS` page through `view_forecast_analysis`
- and now a real runnable builtin app in `src/agilab/apps/builtin/weather_forecast_project`

## Files

- `data/meteo_fr_daily_sample.csv`
  - small local weather sample shaped like a daily Meteo-France export
- `analysis_artifacts/forecast_metrics.json`
  - summary metrics and run metadata
- `analysis_artifacts/forecast_predictions.csv`
  - observed vs predicted values

## Migration story

The point of this pilot is not to replace notebooks immediately.
The point is to show that:

1. the notebook sequence can be preserved,
2. the pipeline semantics can be made explicit,
3. the exported artifacts can be reused in AGILAB ANALYSIS,
4. reruns can later become reproducible local or cluster runs.

## From pilot to project

The migration story now exists in three layers:

1. notebook source under `notebooks/`
2. conceptual AGILAB skeleton under `migrated_project/`
3. real builtin app under `src/agilab/apps/builtin/weather_forecast_project`

That third layer is the important proof point: the notebook example does not
stop at documentation. It now runs as an AGILAB project with `PROJECT`,
`ORCHESTRATE`, `WORKFLOW`, and `ANALYSIS`.
