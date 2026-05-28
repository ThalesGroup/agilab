# Notebook Quickstart Assets

## Example Class

**Notebook import asset.** This directory packages notebook-first onboarding
material. It is not seeded as an `AGI_*.py` execution helper.

## Purpose

Use these notebooks when a user wants to stay in a notebook while learning the
first AGILAB proof, worker paths, simple data DAGs, Colab, Kaggle, and benchmark
variants.

## What You Learn

- How the notebook-first path maps to AGILAB proof and evidence concepts.
- How local, Colab, and Kaggle notebooks differ without changing the core app
  boundary.
- How worker paths and data DAG notebooks introduce execution structure before a
  full app migration.

## Install

Install AGILAB normally, then open the notebook from the packaged examples tree
or copy it into a working notebook environment. The notebooks are source assets,
not installer-seeded run scripts.

## Run

Open one notebook and run its cells in order. Start with
`agi_core_first_run.ipynb` for a local source checkout, or the matching Colab or
Kaggle first-run notebook for hosted notebook environments.

## Expected Input

The notebooks use public, deterministic first-run inputs and AGILAB-managed
paths. No private dataset, API key, or cluster credential is required for the
first-run path.

## Expected Output

The first-run notebooks produce AGILAB proof/evidence artifacts in the configured
notebook or AGILAB output path. Worker-path and data-DAG notebooks show the
paths and execution contracts used by later app migration steps.

## Read The Script

Read the cells that create the app environment, construct the run request, and
call AGILAB execution helpers. Those cells are the notebook equivalent of the
seeded `AGI_run_*.py` examples.

## Change One Thing

After the default notebook works, change only the output label or one small
sample parameter. Keep the runtime local and deterministic until you have
compared the new evidence with the previous run.

## Troubleshooting

- If imports fail, confirm AGILAB is installed in the notebook kernel.
- If output paths are confusing, run the worker-path notebook before changing
  any directories.
- If hosted notebooks cannot access local files, use the Colab or Kaggle
  variant instead of a source-checkout notebook.
