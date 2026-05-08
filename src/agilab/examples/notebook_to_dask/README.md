# Notebook To Dask Migration Example

## Purpose

Shows how a notebook-first data workflow can be imported into AGILAB as an
explicit Dask-backed pipeline plan instead of remaining a loose sequence of
cells.

## What You Learn

- How markdown and code cells become traceable `lab_stages.toml` entries.
- How Dask-oriented cells are separated from setup and analysis cells.
- How input and output files become an artifact contract.
- How a conceptual pipeline view explains the migration before any notebook is
  executed.

## Install

This is a read-only migration preview. No app install is required.

From a source checkout:

```bash
uv --preview-features extra-build-dependencies run python src/agilab/examples/notebook_to_dask/preview_notebook_to_dask.py
```

From an installed package, run the same script from the package's
`agilab/examples/notebook_to_dask` directory.

## Run

```bash
uv --preview-features extra-build-dependencies run python src/agilab/examples/notebook_to_dask/preview_notebook_to_dask.py --output /tmp/notebook_to_dask_preview.json
```

The command reads:

- `notebook_to_dask_sample.ipynb`
- `lab_stages.toml`
- `pipeline_view.json`

It writes a JSON migration preview and does not execute the notebook.

## Expected Input

The sample notebook references `data/orders.csv` as the source dataset. The file
does not need to exist for the preview because the importer is static and
side-effect free.

## Expected Output

The preview reports a Dask migration contract with these planned outputs:

- `artifacts/daily_orders.parquet`
- `artifacts/dask_summary.json`

Those artifacts are intended for a future `ANALYSIS` page or notebook-native
analysis cell.

## Read The Script

Open `preview_notebook_to_dask.py` and look for these functions first:

- `build_preview` calls AGILAB's notebook import model.
- `artifact_contract_from_import` separates notebook inputs from planned
  outputs.
- `dask_solution_from_import` identifies the imported cells that become the
  Dask-backed solution path.

## Change One Thing

After the preview works, edit `pipeline_view.json` to add another artifact
consumer node. Keep the notebook unchanged so you can see how the conceptual
view can evolve independently from the raw notebook source.

## Troubleshooting

- If the script cannot import `agilab.notebook_pipeline_import`, run it from the
  AGILAB source checkout with `uv --preview-features extra-build-dependencies`.
- If the sample `lab_stages.toml` no longer matches the generated preview, rerun
  the script and compare the reported `lab_stages_preview` section.
- If you want real execution, first turn the preview into a project with an
  explicit dataset path, Dask dependency policy, and an `ANALYSIS` page that
  reads the declared artifacts.
