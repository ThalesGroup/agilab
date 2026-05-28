# Parallel Stage Example

## Example Class

**Read-only preview.** The preview validates a partition contract and writes planning evidence. It does not start workers or install an AGILAB app project.


## Purpose

Shows the smallest AGILAB mental model for parallelizing code:

```text
function + split rule + reducer = parallel AGILAB stage
```

The preview focuses on the case where there are fewer files than available
cores. It shows why AGILAB should parallelize partitions, not raw file count.

## What You Learn

- A file is not always the right scheduling unit.
- Large files can be split into more partitions than the number of input files.
- Small unsplittable files should cap useful worker count to file count.
- `parallel_stage.toml` records intent; it does not launch workers by itself.
- The reducer contract must be clear before switching from local preview to
  pool or Dask execution.

## Install

This is a read-only planning preview. No app install or worker install is
required.

From a source checkout:

```bash
uv --preview-features extra-build-dependencies run python src/agilab/examples/parallel_stage/preview_parallel_stage.py
```

From an installed package, run the same script from the package's
`agilab/examples/parallel_stage` directory.

## Run

```bash
uv --preview-features extra-build-dependencies run python src/agilab/examples/parallel_stage/preview_parallel_stage.py --output /tmp/parallel_stage_preview.json
```

The command reads `parallel_stage.toml` and writes a JSON preview. It does not
start local workers, Dask, SSH, or a distributed scheduler.

## Runtime Modes

The same partition contract can be consumed by different runtimes:

| Mode | What happens |
| --- | --- |
| Contract / preview | Validates and plans partitions only. No workers or scheduler start. |
| Local single-run | Run one partition in one Python process to prove outputs and evidence. |
| Local parallel, Dask disabled | `agi_dispatcher` owns local process or thread pools. Work-plan partitions can run concurrently on one machine. |
| Dask / distributed | AGILAB uses the outer scheduler and configured worker slots. The Dask dashboard sees AGILAB work-plan tasks, not hidden nested threads inside one worker. |
| Service mode | Persistent workers pull the same kind of partition tasks across repeated runs with health checks. |
| Library-internal parallelism | Libraries such as Polars, NumPy, Cython, or OpenMP may use threads inside one worker. AGILAB does not count those inner threads as separate work-plan tasks. |

The practical rule is: AGILAB parallelizes partitions, not files. If files are
splittable, create more partitions than files. If files are unsplittable,
useful worker count is capped by the number of independent files.

## Expected Input

The example contract uses:

```toml
split = "files"
workers = "auto"
partition_strategy = "file-chunks"
target_partitions = 64
min_partitions_per_worker = 2
```

The preview simulates three files on an eight-core machine. The files are
assumed to be large enough to split into chunks for the first policy check.

## Expected Output

The preview writes:

```text
~/log/execute/parallel_stage/parallel_stage_preview.json
```

The JSON contains two policy outcomes:

- `splittable_large_files`: keeps eight useful workers and creates chunk
  partitions.
- `unsplittable_small_files`: caps useful workers to three because only three
  independent units exist.

The key preview values are:

```text
input_files: 3
available_cores: 8
splittable_large_files:
  effective_workers: 8
  planned_partitions: 64
unsplittable_small_files:
  effective_workers: 3
  planned_partitions: 3
```

That is the core rule: parallelize partitions, not raw file count.

## Read The Script

Open `preview_parallel_stage.py` and look for these functions first:

- `validate_contract()` checks the preview contract shape.
- `effective_workers()` caps workers only when files cannot be split.
- `planned_partitions()` creates enough partitions for chunkable large files.
- `build_preview()` writes the policy summary and evidence JSON.

## Change One Thing

Run the preview with a different file count:

```bash
uv --preview-features extra-build-dependencies run python src/agilab/examples/parallel_stage/preview_parallel_stage.py --file-count 2 --available-cores 16
```

Then edit `parallel_stage.toml` and change `target_partitions` from `64` to
`128`. The useful worker count should stay bounded by available cores, but the
planned partition count should increase for splittable files.

## Troubleshooting

- If `tomllib` is unavailable, use Python 3.11 or newer.
- If the preview says the contract is invalid, check that `schema`, `split`,
  `partition_strategy`, and `target_partitions` still match the README.
- If you want real execution, first wire the contract into an AGILAB app or
  WORKFLOW stage, run one partition locally, then switch the backend to `pool`
  or `dask`.
