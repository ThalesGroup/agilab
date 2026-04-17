# view_release_decision

Reusable Streamlit analysis page for baseline-vs-candidate promotion decisions.

Primary use:

- compare two exported metric bundles
- apply explicit artifact and KPI gates
- export `promotion_decision.json`

Default search root:

- `~/export/<app_target>`

For `meteo_forecast_project`, the page defaults to:

- metrics glob: `**/forecast_metrics.json`
- required artifact patterns:
  - `forecast_metrics.json`
  - `forecast_predictions.csv`

This is the first app-layer MVP for AGILAB's promotion / release decision workflow.
