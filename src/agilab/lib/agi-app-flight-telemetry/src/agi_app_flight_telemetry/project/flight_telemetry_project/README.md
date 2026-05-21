# Flight-Telemetry Project

`flight_telemetry_project` is the AGILAB install id for this built-in public flight-telemetry example.

The project focuses on a simple but useful workflow:
- ingest flight data from files under shared storage
- turn that input into a dataframe dataset under shared storage
- inspect the result in the default AGILAB `view_maps` page and the optional
  `view_maps_network` page

## What it is good for

- a compact end-to-end AGILAB demo around real-world flight data
- validating the `PROJECT -> ORCHESTRATE -> WORKFLOW -> ANALYSIS` flow in one
  packaged public app
- showing how a raw data source becomes a reusable dataset for visual exploration

## What is not implemented in the public version

This public built-in example is intentionally narrow. It does **not** implement:
- search-index ingestion inside this app; use an external app for that connector path
- richer trajectory-centric study workflows
- multi-stage trajectory reconstruction or scenario stitching
- dedicated cross-run comparison views for complex flight studies
- advanced trajectory replay, alignment, or domain-specific experiment dashboards

The public version is meant to stay approachable: one small app that demonstrates
data ingestion, pipeline reuse, and visual exploration without exposing a larger
specialized workflow.

## Main outputs

Each run produces a structured flight dataframe dataset that can then be reused by
analysis pages and downstream pipeline stages.

Workers also emit a `reduce_summary_worker_<id>.json` `ReduceArtifact` beside
the dataframe outputs. That summary records the reducer name, row count,
aircraft/source-file counts, written output files, and trajectory distance/time-span
fields so Release Decision can surface the flight run as first-class evidence.

## Typical flow

1. Select `flight_telemetry_project` in `PROJECT`.
2. Configure the input source in `ORCHESTRATE`.
3. Run the ingestion step.
4. Inspect or extend the generated recipe in `WORKFLOW`.
5. Explore the resulting dataset in `view_maps`, then open `view_maps_network`
   when you want the network-style analysis route.

Notebook imports do not try to infer flight UI intent from arbitrary code cells.
The app declares compatible import views in `notebook_import_views.toml`, so the
generic notebook importer can write a `notebook_import_view_plan.json` sidecar
that matches declared flight views to produced artifacts.

## What this teases in AGILAB

This public example is only the entry point. The same framework can also support:
- trajectory-focused studies with custom app logic and dedicated pages
- replayable experiment pipelines built from generated or saved steps
- richer domain-specific overlays on top of processed flight artifacts
- distributed preprocessing and repeatable multi-run comparisons
- domain-specific workflows that go beyond a generic dataframe export
