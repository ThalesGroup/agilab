# view_release_decision

Reusable Streamlit analysis page for baseline-vs-candidate promotion decisions.

Primary use:

- compare two exported metric bundles
- gate promotion on first-proof `run_manifest.json`
- apply explicit artifact and KPI gates
- export `promotion_decision.json`

Default search root:

- `~/export/<app_target>`

For `meteo_forecast_project`, the page defaults to:

- metrics glob: `**/forecast_metrics.json`
- required artifact patterns:
  - `forecast_metrics.json`
  - `forecast_predictions.csv`

The page also defaults to `~/log/execute/flight/run_manifest.json` for the
first-proof gate. Promotion is blocked unless that manifest has `status: pass`,
uses the `source-checkout-first-proof` path id, passes all recorded validations,
and completes within its target seconds.

This is the first app-layer MVP for AGILAB's promotion / release decision workflow.
