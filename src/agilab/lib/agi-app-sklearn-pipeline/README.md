# agi-app-sklearn-pipeline

[![PyPI version](https://img.shields.io/pypi/v/agi-app-sklearn-pipeline.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-sklearn-pipeline/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-sklearn-pipeline.svg)](https://pypi.org/project/agi-app-sklearn-pipeline/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-sklearn-pipeline)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-sklearn-pipeline` publishes the `sklearn_pipeline_project` AGILAB app
as a self-contained PyPI payload. It keeps a normal scikit-learn pipeline
workflow intact while making the executable app boundary, arguments, and
evidence artifacts explicit.

## Purpose

Use this package to run a compact classic ML proof: generate a deterministic
classification dataset, train a `StandardScaler` + `LogisticRegression`
pipeline, and persist the model, metrics, predictions, report, and run
manifest together.

## Installed Project

The distribution name is `agi-app-sklearn-pipeline`; the AGILAB project name is
`sklearn_pipeline_project`. The package exposes both `sklearn_pipeline` and
`sklearn_pipeline_project` through the `agilab.apps` entry point group, so
`AgiEnv(app="sklearn_pipeline_project")` resolves the project without a
monorepo checkout.

## Install

```bash
pip install agi-app-sklearn-pipeline
```

The app project installs scikit-learn when AGILAB prepares its project
environment. The payload package stays lightweight and only exposes the project
root.

## Run In AGILAB

Select `sklearn_pipeline_project`, then open `ORCHESTRATE`. Keep the defaults,
run `INSTALL`, then run `RUN`. The worker exports model quality evidence and a
manifest under `sklearn_pipeline/evidence`.

## Expected Inputs

The default run generates a synthetic dataset with
`sklearn.datasets.make_classification`. No external dataset, API key, notebook,
cloud service, or private model is required.

## Expected Outputs

The worker writes `metrics.json`, `predictions.csv`, `model.joblib`,
`sklearn_report.md`, `run_manifest.json`, and `sklearn_pipeline_summary.json`.

## Change One Thing

Change `regularization_c` from `1.0` to `0.5`, then rerun the app. The manifest
and metrics artifacts should make the changed behavior auditable.

## Scope

This is a reproducible scikit-learn app example. It is not a generic
apps-page, production model registry, or serving stack. Sklearn-specific logic
stays inside the app project; shared pages should only consume app-agnostic
artifact contracts such as metrics, predictions, and manifests.
