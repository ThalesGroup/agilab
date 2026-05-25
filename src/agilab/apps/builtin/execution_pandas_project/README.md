# Execution Pandas Project

`execution_pandas_project` is the built-in AGILAB reference app for a
`PandasWorker` with an explicit Cython/C-speedup path.

The app generates a deterministic CSV workload, distributes file batches across
available workers, runs a pandas aggregation workload, and writes result files
plus a reduce artifact that AGILAB analysis pages can inspect. Its default
`typed_numeric` kernel converts hot columns to contiguous `float64` arrays.
The app enables Cython mode by default so AGILAB can compile a real typed loop
instead of only wrapping Pandas calls.

## What It Shows

- deterministic first-run dataset generation under shared storage
- worker distribution over multiple CSV partitions
- pandas-based compute and aggregation through the AGILAB worker contract
- a Cython-favorable typed numeric kernel with explicit dtype metadata
- a worker build manifest that declares Cython as a build requirement
- output parity artifacts for comparing execution modes and worker behavior

## Typical Flow

1. Select `execution_pandas_project` in `PROJECT`.
2. Run `INSTALL` from `ORCHESTRATE`.
3. Run `EXECUTE` with the default `typed_numeric` kernel or switch the kernel
   back to `dataframe` when you want the older Pandas-vectorized path.
4. Inspect generated CSV outputs under `execution_pandas/results`.

## Outputs

Each worker writes an output file under the run results directory. The reducer
also emits a summary artifact that records row counts, score metrics, source
files, kernel mode, kernel runtime, dtype contract, and the execution engine
label.

## Scope

This app is intentionally synthetic. It is useful for validating AGILAB
execution behavior and comparing worker paths, not for demonstrating a
domain-specific analytics workflow.
