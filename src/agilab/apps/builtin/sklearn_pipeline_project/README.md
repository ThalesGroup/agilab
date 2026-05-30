# Scikit-Learn Pipeline Project

`sklearn_pipeline_project` is the built-in AGILAB app for a compact, reproducible
classic-ML classifier workflow.

## Purpose

Use this app to see familiar scikit-learn training code wrapped as an AGILAB
project with persisted arguments, worker execution, metrics, model artifacts,
and a run manifest.

## What You Learn

- How a deterministic synthetic dataset becomes a packaged training app.
- How `StandardScaler` and `LogisticRegression` are executed behind the worker
  contract.
- How metrics, predictions, model files, and manifests are exported together.
- How generic artifact readers can inspect app-produced evidence.

## Run In AGILAB

1. Select `sklearn_pipeline_project` in `PROJECT`.
2. Open `ORCHESTRATE`.
3. Keep the default arguments.
4. Run `INSTALL`, then `RUN`.

## Expected Inputs

The app generates its own dataset with `sklearn.datasets.make_classification`.
No CSV file, API key, cloud service, model registry, or notebook is required.

## Expected Outputs

The worker writes `metrics.json`, `predictions.csv`, `model.joblib`,
`sklearn_report.md`, `run_manifest.json`, and
`sklearn_pipeline_summary.json`.

## Change One Thing

After the default run works, change only `regularization_c` or `sample_count`.
Keep `seed=2026` so differences remain easy to explain.

## Troubleshooting

If model artifacts are missing, confirm `RUN` completed after `INSTALL`. If
metrics change unexpectedly, check the seed and generated dataset settings
before changing estimator code.

## Scope

This is a reproducible sklearn app example. It is not an app-agnostic analysis
page or a production model registry.
