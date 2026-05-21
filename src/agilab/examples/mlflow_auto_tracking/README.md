# MLflow Auto-Tracking Example

## Purpose

Shows the intended AGILAB tracking posture:

```text
AGILAB executes the workflow -> tracker logs evidence -> MLflow stores memory
```

The example is a deterministic preview. It writes the same local evidence every
time, then optionally logs that evidence to MLflow when the `mlflow` package is
available. If MLflow is not installed, the preview records a clear `skipped`
status instead of inventing a parallel registry.

## What You Learn

- Keep experiment tracking optional and backend-driven.
- Use a small `tracker.log_param(...)`, `tracker.log_metric(...)`,
  `tracker.log_artifact(...)` abstraction in worker or pipeline code.
- Do not duplicate MLflow concepts such as runs, experiments, metrics, or model
  registry entries inside AGILAB.
- Preserve a local JSON evidence bundle even when the tracking backend is not
  installed.

## Install

There is no separate project install for this preview. Install AGILAB first.
MLflow is optional:

```bash
uv --preview-features extra-build-dependencies run --with mlflow python src/agilab/examples/mlflow_auto_tracking/preview_mlflow_auto_tracking.py
```

Without `--with mlflow`, the same command still produces local evidence and
marks tracking as skipped.

## Run

From a source checkout:

```bash
uv --preview-features extra-build-dependencies run python src/agilab/examples/mlflow_auto_tracking/preview_mlflow_auto_tracking.py
```

From an installed AGILAB package, locate the packaged script:

```bash
python -c "from pathlib import Path; import agilab; print(Path(agilab.__file__).with_name('examples') / 'mlflow_auto_tracking' / 'preview_mlflow_auto_tracking.py')"
```

Then run it:

```bash
python preview_mlflow_auto_tracking.py
```

## Expected Input

The script reads the built-in
`weather_forecast_project/tracking_templates/mlflow_auto_tracking_run_config.json`
contract with:

- app: `weather_forecast_project`
- pipeline: `notebook_migration_forecast`
- model family: `skforecast_baseline`
- deterministic metrics and artifact names

## Expected Output

The script writes:

```text
~/log/execute/mlflow_auto_tracking/artifacts/run_summary.json
~/log/execute/mlflow_auto_tracking/mlflow_tracking_preview.json
```

If MLflow is installed, it also creates or updates an MLflow experiment named
`AGILAB Preview` using the configured tracking URI. The preview JSON records
the MLflow run ID and artifact path. If MLflow is missing, the preview JSON
records `tracking.status = "skipped"` with an installation hint.

## Expected Preview

Read the output as a tracking contract:

| Field | Expected value | Meaning |
|---|---|---|
| `example` | `mlflow_auto_tracking` | This is a preview, not a real model registry. |
| `tracker_backend` | `mlflow` or `none` | Which backend handled the calls. |
| `tracking.status` | `logged`, `skipped`, or `failed` | Whether tracking reached MLflow. |
| `local_evidence.run_summary` | path | Local evidence is always written. |
| `logged_metrics` | deterministic keys | Metrics that would appear in MLflow. |

## Read The Script

Open `preview_mlflow_auto_tracking.py` and look for these functions first:

- `build_demo_evidence()` creates deterministic params, metrics, and a local
  artifact.
- `create_tracker()` chooses the optional backend.
- `MlflowTracker` is a thin adapter around MLflow, not an AGILAB registry.
- `run_preview()` uses only `tracker.log_*` style calls.

## Change One Thing

Copy the built-in tracking template, change `metrics.forecast_mae` so it is
slightly lower, rerun the preview with `--config <copy>.json`, and inspect both
`run_summary.json` and the tracking status. If MLflow is installed, open the
MLflow UI and compare the logged metric.

## Troubleshooting

- If tracking is skipped, install MLflow for this one command with
  `uv --preview-features extra-build-dependencies run --with mlflow ...`.
- If tracking fails, inspect `tracking.reason`; the local artifact is still
  written so the execution evidence is not lost.
- If you point `--tracking-uri` at a remote server, verify network access and
  authentication before blaming AGILAB.
- If you need a model registry, use MLflow's registry or your production MLOps
  platform. This example intentionally does not create an AGILAB registry.
