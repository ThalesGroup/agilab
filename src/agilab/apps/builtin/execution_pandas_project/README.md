# Execution Pandas Project

`execution_pandas_project` is the built-in AGILAB reference app for the
`PandasWorker` path and its Cython-friendly numeric kernel.

## Purpose

Use this app to prove that AGILAB can generate deterministic tabular input,
distribute CSV partitions, run a pandas workload, and reduce worker outputs into
repeatable evidence. The default `typed_numeric` kernel keeps the hot path
explicit so Cython runs can be audited instead of treated as a black box.

## What You Learn

- How first-run data seeding works under shared storage.
- How a manager creates a distribution plan over multiple CSV partitions.
- How worker outputs and reducer summaries become analysis evidence.
- How to compare Python, Cython, and worker execution modes with one workload.
- How dtype and checksum fields make speedup claims reproducible.

## Run In AGILAB

1. Select `execution_pandas_project` in `PROJECT`.
2. Open `ORCHESTRATE`.
3. Run `INSTALL`.
4. Run `EXECUTE` with the default `typed_numeric` kernel.
5. Inspect the result files under `execution_pandas/results`.

## Expected Inputs

No external data is required. The first run creates deterministic CSV partitions
from the app settings and records the generated input contract.

## Expected Outputs

Each worker writes a partition result. The reducer writes a summary with row
counts, score metrics, source files, kernel mode, kernel runtime, dtype contract,
distance/checksum fields, and the execution engine label.

## Change One Thing

After the default run works, change only the partition count or switch
`kernel_mode` from `typed_numeric` to `dataframe`. The output row counts should
stay stable while the runtime and kernel metadata change.

## Troubleshooting

If `INSTALL` fails, rerun the app-local install from `ORCHESTRATE` before
changing code. If outputs are missing, check that shared storage is writable and
that `execution_pandas/results` was not deleted by a stale run cleanup.

## Scope

This is a synthetic execution benchmark for AGILAB worker behavior. It is not a
domain analytics workflow and should not be presented as one.
