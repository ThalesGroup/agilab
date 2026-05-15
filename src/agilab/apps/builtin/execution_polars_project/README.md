# Polars Execution Project

`execution_polars_project` is a built-in AGILAB execution playground for the
`PolarsWorker` path.

The app uses the same deterministic workload shape as
`execution_pandas_project`, then processes the partitions with polars so the two
execution paths can be compared without changing the benchmark input.

## What It Shows

- deterministic first-run dataset generation under shared storage
- worker distribution over multiple CSV partitions
- polars-based compute and aggregation through the AGILAB worker contract
- parity outputs for comparing execution modes, engines, and reducer behavior

## Typical Flow

1. Select `execution_polars_project` in `PROJECT`.
2. Run `INSTALL` from `ORCHESTRATE`.
3. Run `EXECUTE` with the default settings or adjusted partition counts.
4. Inspect generated CSV or Parquet outputs under `execution_polars/results`.

## Outputs

Each worker writes an output file under the run results directory. The reducer
also emits a summary artifact that records row counts, score metrics, source
files, and the execution engine label.

## Scope

This app is intentionally synthetic. It is useful for validating AGILAB
execution behavior and comparing worker paths, not for demonstrating a
domain-specific analytics workflow.
