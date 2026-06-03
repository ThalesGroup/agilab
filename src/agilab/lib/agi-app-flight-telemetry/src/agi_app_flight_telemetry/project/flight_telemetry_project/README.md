# Flight Telemetry Project

`flight_telemetry_project` is the public first-proof AGILAB app for turning raw
flight records into reusable evidence.

## Purpose

Use this app to see the full AGILAB loop on a concrete dataset: configure a
project, install the worker, execute ingestion, inspect the workflow, and open
analysis views over the produced flight dataframe.

## What You Learn

- How raw flight files become a structured dataframe artifact.
- How worker-only Cython acceleration can cover a real hot loop while the app
  remains readable Python.
- How `view_maps` and `view_maps_network` reuse the same run artifacts.
- How reducer summaries record row counts, source files, distance metrics,
  kernel runtime, dtype contracts, and checksums.
- How notebook-import view declarations point the generic importer at
  flight-specific analysis pages.

## Run In AGILAB

1. Select `flight_telemetry_project` in `PROJECT`.
2. Open `ORCHESTRATE` and review the input path.
3. Run `INSTALL`, then `EXECUTE`.
4. Open `WORKFLOW` to inspect or extend the generated recipe.
5. Open `ANALYSIS`, then use `view_maps` or `view_maps_network`.

## Expected Inputs

The app can seed a compact public flight sample for the first run. Custom runs
can point the input glob at local flight CSV files under shared storage.

## Expected Outputs

The run writes a flight dataframe dataset and a `ReduceArtifact` summary with
aircraft counts, source-file counts, trajectory distance/time-span fields,
written output files, speed-kernel metadata, and checksum evidence.

## Change One Thing

After the default run works, change only the file glob or one input sample. The
analysis views should update while the reducer contract remains the same.

## Troubleshooting

If `ANALYSIS` shows no map data, confirm that `EXECUTE` produced dataframe
artifacts before opening the page. If a notebook import does not suggest flight
views, check `notebook_import_views.toml` instead of hard-coding page names.

## Scope

This public app is intentionally narrow. It demonstrates ingestion, pipeline
reuse, visual exploration, and auditable speedup evidence; it does not claim
advanced trajectory reconstruction or production flight-study tooling.
