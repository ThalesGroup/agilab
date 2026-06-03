# Execution Polars Project

`execution_polars_project` is the built-in AGILAB reference app for the
`PolarsWorker` path.

## Purpose

Use this app to compare the polars execution path with
`execution_pandas_project` without changing the workload shape. It generates the
same deterministic partitioned input, processes it with polars, and writes
reducer evidence that can be compared against the pandas app.

## What You Learn

- How AGILAB distributes a tabular workload across worker partitions.
- How a polars worker keeps the same evidence contract as the pandas path.
- How reducer summaries expose row counts, score metrics, and engine labels.
- How to compare execution engines without changing the input data.

## Run In AGILAB

1. Select `execution_polars_project` in `PROJECT`.
2. Open `ORCHESTRATE`.
3. Run `INSTALL`.
4. Run `EXECUTE` with the default settings.
5. Inspect generated CSV or Parquet outputs under `execution_polars/results`.

## Expected Inputs

No external data is required. The app creates deterministic CSV partitions on
the first run.

## Expected Outputs

Each worker writes an output file. The reducer writes a summary artifact with
row counts, score metrics, source files, and the `polars` execution label.

## Change One Thing

After the default run works, change only the partition count. The same logical
workload should produce a different distribution shape while keeping reducer
totals stable.

## Troubleshooting

If polars cannot be imported, run `INSTALL` again for this app instead of using
the root environment. If result files are stale, enable reset in the app args or
remove only the app-owned `execution_polars/results` directory.

## Scope

This app validates AGILAB execution behavior and worker parity. It is not a
domain-specific analytics demo.
