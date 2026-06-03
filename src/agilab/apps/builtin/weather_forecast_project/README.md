# Weather Forecast Project

`weather_forecast_project` is the built-in AGILAB app for the skforecast +
Meteo-France notebook migration storyline.

## Purpose

Use this app to show how a forecasting notebook becomes a reproducible AGILAB
project with installable dependencies, seeded data, forecast artifacts, analysis
views, and release-decision evidence.

## What You Learn

- How notebook migration becomes an explicit app and worker contract.
- How the first run seeds a compact public weather dataset.
- How forecast metrics and predictions are written for replay.
- How `view_forecast_analysis` reads time-series artifacts.
- How `view_release_decision` compares a candidate run against a baseline.

## Run In AGILAB

1. Select `weather_forecast_project` in `PROJECT`.
2. Open `ORCHESTRATE`.
3. Review paths and forecasting parameters.
4. Run `INSTALL`, then `EXECUTE`.
5. Open `ANALYSIS` with `view_forecast_analysis` or `view_release_decision`.

## Expected Inputs

The default run uses the bundled compact weather CSV under
`weather_forecast/dataset`. No API key or live Meteo-France call is required.

## Expected Outputs

The app writes `forecast_metrics.json`, `forecast_predictions.csv`, analysis
artifacts, reducer summaries, and optional `promotion_decision.json` evidence.

## Change One Thing

After the default run works, replace only the input weather CSV with a larger
local snapshot that preserves the expected columns. Forecast metrics should
change while artifact names remain stable.

## Troubleshooting

If `skforecast` is missing, run `INSTALL` for this app and test from the app
environment. If analysis pages are empty, confirm `EXECUTE` produced forecast
artifacts before opening `ANALYSIS`.

## Scope

This is a notebook-migration and forecast-evidence demo. It is not a live
weather service or production forecasting platform.
