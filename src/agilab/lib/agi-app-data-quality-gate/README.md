# agi-app-data-quality-gate

![Release artifact](https://img.shields.io/badge/release%20artifact-wheel%2Bsdist-blue)
![PyPI](https://img.shields.io/badge/PyPI-not%20promoted-lightgrey)
[![License: BSD 3-Clause](https://img.shields.io/badge/license-BSD%203--Clause-blue)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-data-quality-gate` packages the `data_quality_gate_project` AGILAB app.
It is a deterministic data contract, drift, leakage, and promotion-gate example
for teams that need a concrete proof before a candidate dataset reaches model
training or pilot promotion.

## Purpose

Use this package to show how AGILAB can turn a data-readiness review into
replayable evidence. The app generates a baseline dataset and a candidate
dataset, validates the expected columns, profiles quality, measures drift, and
writes a decision that can be reviewed before another system takes ownership.

## What You Learn

The packaged project demonstrates the same contract-first workflow without
requiring a source checkout. A first run shows the generated datasets, the
quality profiles, the drift table, the gate decision, and the manifest that ties
those artifacts together. It is intended to make a data promotion review easy to
rerun and easy to inspect from AGILAB.

## Installed Project

The distribution name is `agi-app-data-quality-gate`; the AGILAB project name is
`data_quality_gate_project`. The package exposes both `data_quality_gate` and
`data_quality_gate_project` through the `agilab.apps` entry point group, so
`AgiEnv(app="data_quality_gate_project")` resolves the project without a
monorepo checkout once this payload package is installed.

## Install

```bash
pip install agi-app-data-quality-gate
```

This is the stable package install shape once this distribution is promoted to
PyPI. For the current release artifact path, install the wheel directly:

```bash
pip install /path/to/agi_app_data_quality_gate-<version>-py3-none-any.whl
```

This app project is built as wheel and source-distribution artifacts in the
GitHub Release archive, but it is not promoted to PyPI in the current release
plan and is not pulled by the `agi-apps` umbrella. Install it directly only when
validating the data quality gate package from a release artifact or a locally
built wheel.

## Run In AGILAB

Select `data_quality_gate_project`, open `ORCHESTRATE`, then run `INSTALL` and
`EXECUTE`. Open `ANALYSIS` or inspect the exported evidence directory to review
the contract, drift metrics, gate decision, and artifact manifest.

## Expected Inputs

The default run generates deterministic synthetic baseline and candidate
datasets. It does not require private data, a model registry, a cloud account,
an LLM, or an external network service.

## Expected Outputs

The app writes baseline and candidate CSV files, JSON profiles, a data contract,
drift metrics, a gate decision, a Markdown evidence report, a run manifest, and
a data-quality summary with artifact hashes.

## Change One Thing

Change only `drift_strength`, then rerun the app. Lower values should move the
gate toward `promote`; higher values should move it toward `manual-review` or
`block`. Keep `seed=2026` when you want artifact deltas that remain easy to
explain.

## Troubleshooting

If the package resolves but custom data does not, rerun the default synthetic
case first. Then verify that CSV and JSON paths are AGILAB-share-relative and
that the candidate file contains every column required by the contract. A noisy
or unexpected `manual-review` decision usually means the drift threshold was
tighter than the candidate distribution, so inspect `drift_metrics.csv` before
loosening the gate.

## Scope

This is a compact data-quality gate example. It does not replace a full data
observability platform, feature store, enterprise governance workflow, or
production approval authority. Its purpose is to make one data-readiness review
portable, deterministic, and evidence-backed.
