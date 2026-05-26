# Scikit-Learn Pipeline Project

Built-in AGILAB app for a compact, reproducible scikit-learn classifier
workflow. It keeps the normal sklearn training code recognizable while turning
the run into an executable app with persisted arguments and audit artifacts.

## Purpose

Use this project when you want the smallest classic ML example that still
behaves like an AGILAB app: `ORCHESTRATE` persists the run parameters, `INSTALL`
prepares the manager and worker environments, and `RUN` writes a model,
metrics, predictions, and a hash manifest.

## Run In AGILAB

Select `sklearn_pipeline_project`, then open `ORCHESTRATE`. Keep the default
arguments for the first run, click `INSTALL`, then click `RUN`.

The default configuration generates a deterministic binary classification
dataset, trains a `StandardScaler` + `LogisticRegression` pipeline, and exports
evidence under `sklearn_pipeline/evidence`.

## Expected Inputs

The app generates its own synthetic dataset with
`sklearn.datasets.make_classification`. No external CSV file, API key, cloud
service, model registry, or notebook is required.

## Expected Outputs

The worker writes:

- `metrics.json`
- `predictions.csv`
- `model.joblib`
- `sklearn_report.md`
- `run_manifest.json`
- `sklearn_pipeline_summary.json`

The same evidence bundle is also mirrored under the app analysis export
directory so generic artifact readers can inspect it later.

## Change One Thing

After the default run works, change only `regularization_c` or `sample_count`.
Keep `seed=2026` so metric and artifact changes remain easy to explain.

## Scope

This is a reproducible sklearn app example, not a generic shared apps-page. The
sklearn-specific training code, arguments, and evidence writer live inside the
app. A future app-agnostic page should read common artifacts such as
`run_manifest.json`, `metrics.json`, and `predictions.csv` without carrying
sklearn naming or assumptions.
