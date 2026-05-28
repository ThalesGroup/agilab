# Notebook Quickstart Examples

## Example Class

**Notebook import asset.** This folder contains notebook-first AGILAB runtime
routes for local Jupyter, Colab, Kaggle, source-checkout, and PyPI-package
users. It is not an installed `AGI_*.py` helper and it does not install an
AGILAB app project by itself.

## Purpose

Shows the smallest notebook-first AGILAB proof:

```text
notebook -> AgiEnv -> RunRequest -> AGI.run -> run manifest
```

Use these notebooks when you want to stay in a notebook while still showing the
same AGILAB concepts that the UI and app helpers use.

## What You Learn

- How to create an `AgiEnv` in a notebook.
- How to build a `RunRequest` with explicit inputs, outputs, and run mode.
- How to call `AGI.run(...)` without hiding the flow behind a one-line wrapper.
- How local, Colab, Kaggle, source-checkout, and PyPI-package variants differ.

## Install

Choose the notebook variant that matches the environment:

- `agi_core_first_run.ipynb` for a local source or installed environment.
- `agi_core_colab_first_run.ipynb` for Google Colab.
- `agi_core_kaggle_first_run.ipynb` for Kaggle.
- `*_source.ipynb` variants when the notebook should point at a source checkout.
- `*_pypi.ipynb` variants when the notebook should use the published package.

## Run

Open the notebook in the matching environment and run cells from top to bottom.
The notebooks keep the important AGILAB steps visible: create `app_env`, create
a `RunRequest`, optionally check worker readiness, then call `AGI.run(...)`.

## Expected Input

The first-run notebooks use deterministic public sample inputs or generate the
smallest local files needed for the proof. They do not require private data,
cluster credentials, or a hosted AGILAB UI.

## Expected Output

The notebook run should produce a local run manifest and visible output paths
under the configured AGILAB log/share location. The exact output depends on the
selected notebook route, but the proof should always make the run request,
execution result, and artifact path visible in notebook cells.

## Read The Notebook

Start with `agi_core_first_run.ipynb` for the local path. Look for these cells:

- environment setup and import checks
- `AgiEnv` creation
- `RunRequest` creation
- optional install or worker-readiness check
- `AGI.run(...)`
- manifest or log-root inspection

## Change One Thing

After the default notebook runs once, change only the output directory or one
small request parameter. Rerun the notebook and compare the new manifest path
with the previous run.

## Troubleshooting

- If the notebook cannot import AGILAB, use the matching source or PyPI variant.
- If a worker-readiness cell reports a missing environment, run the install cell
  shown by the notebook before executing `AGI.run(...)`.
- If a path is confusing, print the log root and share root cells before
  changing the request.
