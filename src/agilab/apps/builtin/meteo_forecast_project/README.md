# Meteo Forecast Project

`meteo_forecast_project` is a built-in AGILAB example that turns the
`skforecast + Meteo-France` notebook migration pilot into a real project.

What it demonstrates:

- the source notebook flow becomes an explicit AGILAB project
- the sample dataset is seeded automatically for the first local run
- `forecast_metrics.json` and `forecast_predictions.csv` are exported as stable artifacts
- `view_forecast_analysis` can read those artifacts directly from `ANALYSIS`
- `view_release_decision` can compare a candidate run against a baseline and export `promotion_decision.json`

Default flow:

1. Select `meteo_forecast_project` in `PROJECT`.
2. Review paths and forecasting parameters in the app args form.
3. Run the app from `ORCHESTRATE`.
4. Open `view_forecast_analysis` from `ANALYSIS`.
5. Open `view_release_decision` when you want a promotable / blocked baseline comparison.

The small bundled CSV is only meant to show the migration path cleanly. Replace
the dataset under `meteo_forecast/dataset` with a larger local weather snapshot
when you want to iterate on the same pipeline with real data.
