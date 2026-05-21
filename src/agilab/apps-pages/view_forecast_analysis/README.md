# view_forecast_analysis

Reusable Streamlit analysis page for forecast-style artifacts.

## Expected Inputs

- `forecast_metrics.json`
- `forecast_predictions.csv`

Default search root:

- `~/export/<app_target>/forecast_analysis`

The page is intended to support notebook-to-AGILAB migration demos as well as
small forecasting apps that export the same artifact contract.

Run a compatible project such as `weather_forecast_project` once from
`ORCHESTRATE` before opening this page from `ANALYSIS`.

## Development Run

```bash
uv --preview-features extra-build-dependencies run streamlit run src/agilab/apps-pages/view_forecast_analysis/src/view_forecast_analysis/view_forecast_analysis.py -- --active-app src/agilab/apps/builtin/weather_forecast_project
```
