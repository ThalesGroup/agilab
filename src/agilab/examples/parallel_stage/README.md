# Parallel Stage Example

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
