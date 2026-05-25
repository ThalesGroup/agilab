# Scikit-Learn Pipeline Proof Example

## Purpose

Shows how a normal scikit-learn training script can become an AGILAB-style proof:
a deterministic dataset, a fitted pipeline, row-level predictions, metrics, a
serialized model, and a hash manifest are written together under one output
directory.

This is a read-only preview. It does not install an app, start a worker, contact
a model registry, or require a cluster.

## What You Learn

- Keep familiar scikit-learn code while making the evidence explicit.
- Treat the model file, metrics, predictions, report, and manifest as one
  replayable proof bundle.
- Use deterministic seeds so reviewers can reproduce the same artifact hashes.
- Decide whether an experiment is a candidate or needs review from persisted
  metrics, not from notebook state.

## Install

Install AGILAB first. The base AGILAB runtime already carries scikit-learn
through the distributed execution stack. For a completely isolated one-command
preview, provide scikit-learn explicitly:

```bash
uv --preview-features extra-build-dependencies run --with scikit-learn --with joblib python src/agilab/examples/sklearn_pipeline_proof/preview_sklearn_pipeline_proof.py
```

## Run

From a source checkout:

```bash
uv --preview-features extra-build-dependencies run python src/agilab/examples/sklearn_pipeline_proof/preview_sklearn_pipeline_proof.py
```

From an installed AGILAB package, locate the packaged script:

```bash
python -c "from pathlib import Path; import agilab; print(Path(agilab.__file__).with_name('examples') / 'sklearn_pipeline_proof' / 'preview_sklearn_pipeline_proof.py')"
```

Then run it:

```bash
python preview_sklearn_pipeline_proof.py
```

## Expected Input

The preview generates a deterministic binary classification dataset with
`sklearn.datasets.make_classification`.

Default inputs:

- seed: `2026`
- sample count: `240`
- test split: `0.25`
- pipeline: `StandardScaler` followed by `LogisticRegression`
- regularization: `C=1.0`

## Expected Output

The script writes:

```text
~/log/execute/sklearn_pipeline_proof/metrics.json
~/log/execute/sklearn_pipeline_proof/predictions.csv
~/log/execute/sklearn_pipeline_proof/model.joblib
~/log/execute/sklearn_pipeline_proof/sklearn_report.md
~/log/execute/sklearn_pipeline_proof/run_manifest.json
~/log/execute/sklearn_pipeline_proof/sklearn_pipeline_preview.json
```

`run_manifest.json` records artifact hashes, metrics, input parameters, and a
simple promotion hint. The preview JSON points to the same evidence bundle for
automation.

## Expected Preview

| Field | Expected value | Meaning |
|---|---|---|
| `schema` | `agilab.example.sklearn_pipeline_proof.v1` | Stable preview contract. |
| `metrics.accuracy` | deterministic float | Main classification score. |
| `metrics.f1` | deterministic float | Balance-aware classification score. |
| `artifacts.model.path` | `model.joblib` | Serialized scikit-learn pipeline. |
| `artifacts.manifest.sha256` | hex digest | Manifest integrity check. |

## Read The Script

Open `preview_sklearn_pipeline_proof.py` and look for these functions first:

- `build_preview()` creates the dataset, trains the pipeline, and writes the
  evidence bundle.
- `_artifact()` records path, role, size, and SHA-256 for each output file.
- `main()` exposes only deterministic, low-risk knobs.

## Change One Thing

Run the preview with a different regularization strength and compare
`metrics.json` plus `run_manifest.json`:

```bash
uv --preview-features extra-build-dependencies run python src/agilab/examples/sklearn_pipeline_proof/preview_sklearn_pipeline_proof.py --regularization-c 0.5
```

Only change one parameter at a time so the metric and hash differences remain
easy to explain.

## Troubleshooting

- If `sklearn` is missing, rerun with
  `uv --preview-features extra-build-dependencies run --with scikit-learn --with joblib ...`.
- If the output changes unexpectedly, check `seed`, `sample_count`, and
  `regularization_c` in `run_manifest.json`.
- If `model.joblib` is not portable across environments, keep
  `metrics.json`, `predictions.csv`, and `run_manifest.json` as the audit
  evidence and retrain the model in the target environment.
- If you need MLflow, combine this preview with the `mlflow_auto_tracking`
  example instead of adding tracking calls directly to the proof script.
