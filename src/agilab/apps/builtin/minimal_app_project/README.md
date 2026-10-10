# Minimal App Project

`minimal_app_project` is the smallest built-in AGILAB app template.

## Purpose

Use this project as the reference layout for a new app. It keeps the manager,
worker, settings seed, form, and compatibility alias small enough to inspect in
one sitting.

## What You Learn

- Which files an installable AGILAB app must provide.
- How `app_settings.toml`, `app_args_form.py`, and `pre_prompt.json` fit
  together.
- How a worker class is packaged for deployment.
- How to copy the shape before adding domain logic.

## Run In AGILAB

1. Select `minimal_app_project` in `PROJECT`.
2. Open `ORCHESTRATE`.
3. Run `Deploy scheduler & workers`.
4. Place a CSV or Parquet table in the configured input directory and run the workflow.
5. Use the working pass-through pipeline as a code reference before adding domain logic.

## Expected Inputs

Provide at least one CSV or Parquet table in the configured input directory.
The app prepares app-owned input and output paths. The default `nfile = 1`
selects the first matching table; set `nfile = 0` to dispatch all tables.

## Expected Outputs

The default worker preserves the input table values and columns, adds the
standard `worker_id` provenance column, and writes Parquet results such as
`0_output.parquet` in the configured output directory.
`nskip` skips input rows and positive `nread` limits the rows read per table.
The manager reports missing table inputs before dispatching work.

## Change One Thing

Copy the project, rename the manager and worker modules, and add one real input
field before changing the execution contract.

## Example Quality Plan

- Review artifact: Review the manager, worker, settings seed, and output artifact as the smallest complete AGILAB app contract.
- Practice change: Change one argument default in the form or settings seed and confirm the worker output reflects only that change.
- Quality check: A mature run remains the copy/paste reference for new app authors: small, deterministic, and easy to diff.

## Troubleshooting

If a copied app does not appear in `PROJECT`, check the project suffix, root
`pyproject.toml`, and `src/app_settings.toml`. If a worker import fails, confirm
the worker package name matches the app manifest.

Packaged app manifests resolve AGILAB dependencies from the configured package
index or trusted wheelhouse. They do not require local `core/` or `lib/` source
directories. Source checkouts retain their editable development dependencies.
The manager uses the `agi-core` runtime bundle for GUI-generated orchestration.
The worker keeps its `agi-node` base and dynamic Python/Cython loading contract;
it does not need the manager or UI packages.
For a wheel-based installation, use `IS_SOURCE_ENV=0` in the AGILAB environment
configuration. A source-development configuration (`IS_SOURCE_ENV=1`) expects
the corresponding local source projects during deployment.

## Scope

This is a template-quality app, not a user-facing domain workflow. Use the
flight, weather, mission, or UAV apps when you need a complete demo.
