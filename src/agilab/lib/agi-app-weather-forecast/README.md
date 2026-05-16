# agi-app-weather-forecast

[![PyPI version](https://img.shields.io/pypi/v/agi-app-weather-forecast.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-weather-forecast/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-weather-forecast.svg)](https://pypi.org/project/agi-app-weather-forecast/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-weather-forecast)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-weather-forecast` publishes the `weather_forecast_project` AGILAB app
as a self-contained PyPI payload. It is the public notebook-migration example
for turning a forecasting notebook into an executable AGILAB project.

## Purpose

Use this package to validate the notebook-to-app path: a small Meteo-France
sample dataset is forecasted, metrics are exported, and analysis pages can
inspect the resulting predictions.

## Installed Project

The distribution name is `agi-app-weather-forecast`; the AGILAB project name is
`weather_forecast_project`. The package exposes both `weather_forecast` and
`weather_forecast_project` through the `agilab.apps` entry point group, so
`AgiEnv(app="weather_forecast_project")` works without a monorepo checkout.

## Install

```bash
pip install agi-app-weather-forecast
```

Most users get this package through `agi-apps`, `agilab[ui]`, or
`agilab[examples]`; direct installation is useful when validating one app
package in isolation.

## Run In AGILAB

Select `weather_forecast_project`, open `ORCHESTRATE`, then run `INSTALL` and
`EXECUTE`. Open `view_forecast_analysis` from `ANALYSIS`; use
`view_release_decision` when you want baseline-versus-candidate promotion
evidence.

## Expected Inputs

The default run uses a bundled sample weather CSV. No live Meteo-France call,
cloud account, private dataset, or API key is required.

## Expected Outputs

The run writes forecast metrics, prediction CSV files, reducer summaries, and
analysis-ready artifacts under the weather-forecast output paths.

## Change One Thing

Change the forecast horizon or input window, then rerun the app. The metrics
artifact should make the impact visible before you promote or reject the run.

## Scope

This is a migration and reproducibility demo. It does not claim production
forecast serving, live weather ingestion, drift monitoring, or model governance.
