# skforecast Meteo-France Migration Pilot

## Purpose

Show how a small weather-forecast notebook sequence can become an AGILAB
workflow with explicit stages, reusable artifacts, and a matching runnable app.

## Example Class

**Notebook import asset.** This folder contains notebooks, artifacts, `lab_stages.toml`, and a pipeline view for import or inspection. It is not an installed AGI project helper.


This folder is a lightweight, local-first migration example for showing how a
small notebook workflow can move into AGILAB without changing the core data
science story.

## What You Learn

- How notebook cells map to AGILAB stage metadata.
- How migrated artifacts feed an `ANALYSIS` page.
- How the pilot relates to the packaged weather forecast app.

## Install

No package install is required to inspect the migration assets. To run the
matching app, install AGILAB with examples enabled and select
`weather_forecast_project`.

## Run

Open the notebooks under `notebooks/` for the original workflow, or use
`PROJECT` and `ORCHESTRATE` with `weather_forecast_project` for the runnable
AGILAB app.

## Expected Input

- `data/meteo_fr_daily_sample.csv`: a compact Meteo-France-style daily weather
  sample.

## Expected Output

- `analysis_artifacts/forecast_metrics.json`
- `analysis_artifacts/forecast_predictions.csv`

## Read The Notebook

- `notebooks/01_prepare_meteo_series.ipynb`
- `notebooks/02_backtest_temperature_forecast.ipynb`
- `notebooks/03_compare_predictions.ipynb`

## Change One Thing

Change the target column or forecast horizon in the notebook, then mirror the
same parameter change in the AGILAB app to compare notebook and app outputs.

## Troubleshooting

- If a notebook dependency is missing, run it from an AGILAB examples
  environment rather than the lean base CLI environment.
- If the AGILAB app is not visible, install the examples extra or refresh the
  app catalog from `PROJECT`.

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
