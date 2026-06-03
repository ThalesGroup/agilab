# Weather Forecast Legacy Project

`weather_forecast_legacy_project` is the compatibility version of the
skforecast + Meteo-France notebook migration example.

## Purpose

Use this app to prove that an older notebook-shaped forecasting workflow can be
installed, executed, and analyzed as an AGILAB project while keeping legacy app
ids and paths available.

## What You Learn

- How a notebook flow becomes an explicit AGILAB app.
- How a sample dataset is seeded for deterministic first run.
- How forecast metrics and predictions are exported as stable artifacts.
- How `view_forecast_analysis` and `view_release_decision` read the outputs.
- How legacy project compatibility is maintained without hiding the modern app.

## Run In AGILAB

1. Select `weather_forecast_legacy_project` in `PROJECT`.
2. Open `ORCHESTRATE`.
3. Review paths and forecast parameters.
4. Run `INSTALL`, then `EXECUTE`.
5. Open `ANALYSIS` with `view_forecast_analysis` or `view_release_decision`.

## Expected Inputs

The default run uses a bundled compact weather CSV under the legacy forecast
dataset path.

## Expected Outputs

The app writes `forecast_metrics.json`, `forecast_predictions.csv`, analysis
artifacts, reducer summaries, and optional promotion-decision evidence.

## Change One Thing

After the default run works, replace only the weather CSV with a larger local
snapshot that preserves the expected columns. Metrics and predictions should
update while the analysis pages still load.

## Troubleshooting

If `skforecast` is missing, run the app in its own installed environment rather
than the root test environment. If release decision has no baseline, run one
candidate first and then compare against that exported bundle.

## Scope

This app exists for legacy compatibility and migration proof. New demos should
prefer `weather_forecast_project` unless they specifically need legacy ids.
