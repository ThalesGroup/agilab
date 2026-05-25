# Scikit-Learn Pipeline Example

## Purpose

Runs `sklearn_pipeline_project`, a compact app example that turns a normal
scikit-learn training run into reproducible AGILAB evidence.

## What You Learn

- How a familiar `Pipeline(StandardScaler, LogisticRegression)` run becomes an
  executable AGILAB app.
- How model parameters are passed through `RunRequest.params`.
- How metrics, predictions, a serialized model, and hashes become one proof
  bundle.

## Install

```bash
python ~/log/execute/sklearn_pipeline/AGI_install_sklearn_pipeline.py
```

## Run

```bash
python ~/log/execute/sklearn_pipeline/AGI_run_sklearn_pipeline.py
```

## Expected Input

The app generates a deterministic binary classification dataset with
`sklearn.datasets.make_classification`.

## Expected Output

The run writes `metrics.json`, `predictions.csv`, `model.joblib`,
`sklearn_report.md`, `run_manifest.json`, and `sklearn_pipeline_summary.json`
under `sklearn_pipeline/evidence`.

## Read The Script

Open `AGI_run_sklearn_pipeline.py` and look for these lines first:

- `sample_count=240` controls the generated dataset size.
- `test_size=0.25` controls the evaluation split.
- `regularization_c=1.0` controls logistic-regression regularization.
- `reset_target=True` keeps the example output deterministic.

## Change One Thing

After the default run works, change only `regularization_c` to `0.5` or `2.0`.
Keep `seed=2026` so you can compare metric and artifact-hash changes without
adding random drift.

## Troubleshooting

- If sklearn is missing, run the install script again for
  `sklearn_pipeline_project`.
- If metrics look stale, keep `reset_target=True` and rerun.
- If no analysis artifact appears, inspect `sklearn_pipeline/evidence` and the
  app export directory for `run_manifest.json`.
