# Meteo Forecast Example

## Purpose

Runs `meteo_forecast_project`, a compact weather forecasting example migrated
from a notebook flow into a reproducible AGILAB project.

## What You Learn

- How a notebook-style forecasting workflow becomes a repeatable AGILAB run.
- How model parameters are passed through `RunRequest.params`.
- How forecast metrics and prediction files become analysis-page artifacts.

## Install

```bash
python ~/log/execute/meteo_forecast/AGI_install_meteo_forecast.py
```

## Run

```bash
python ~/log/execute/meteo_forecast/AGI_run_meteo_forecast.py
```

## Expected Input

The default run reads one CSV file from `meteo_forecast/dataset`.

## Expected Output

The run writes forecast metrics and predictions under `meteo_forecast/results`
for `view_forecast_analysis`.

## Read The Script

Open `AGI_run_meteo_forecast.py` and look for these lines first:

- `station = "Paris-Montsouris"` selects the public sample station.
- `target_column = "tmax_c"` defines the predicted signal.
- `lags`, `horizon_days`, and `validation_days` control the forecasting setup.
- `reset_target=True` makes the demo deterministic by replacing old results.

## Change One Thing

After the default run works, change `horizon_days` from `7` to a nearby value.
Keep `random_state=42` so you can compare forecast behavior without adding model
randomness.

## Troubleshooting

- If no CSV is found, confirm that `meteo_forecast/dataset` exists in shared
  storage.
- If metrics look stale, keep `reset_target=True` and rerun.
- If the analysis page has no chart, check that `meteo_forecast/results`
  contains both metrics and predictions.
