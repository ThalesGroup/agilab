---
name: notebook-to-agilab-project
description: Migrate or maintain a small local notebook workflow inside an AGILAB project. Use this skill when a user wants notebooks turned into a reproducible AGILAB project, project-owned notebooks exposed under ANALYSIS, WORKFLOW notebook import, lab_stages.toml, artifact contracts, and a conceptual workflow view.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-05-14
---

# Notebook To AGILAB Project

Use this skill when the source material is a small set of local notebooks and the
goal is to turn them into an AGILAB-style workflow rather than keep a notebook-only
delivery.

## When to use

- 2-6 notebooks that already form a sequence
- local ML / data notebooks with explicit artifacts
- migration demos where the user wants to show what AGILAB adds
- examples that need `lab_stages.toml`, a conceptual workflow view, and an
  ANALYSIS page

## Do not use

- giant exploratory notebooks with no stable outputs
- cloud-first tutorials whose main value is vendor services
- notebooks that depend on interactive widgets as the primary UX

## Required workflow

1. Identify the notebook sequence.
   - Keep only the semantic stages.
   - Collapse notebook noise such as repeated plotting or ad hoc debug cells.

2. Define the artifact contract first.
   - Decide which files must survive the migration.
   - Prefer stable files such as CSV, Parquet, JSON, and PNG over notebook state.

3. Map the sequence into AGILAB.
   - `PROJECT`: args and dataset location
   - `WORKFLOW`: explicit ordered stages in `lab_stages.toml`
   - `ANALYSIS`: one page that reads the exported artifacts
   - project notebooks: reusable `.ipynb` files under `<app_project>/notebooks/`

4. Make the migration value explicit.
   - Show what was implicit in notebooks.
   - Show what becomes reproducible, rerunnable, and comparable in AGILAB.

5. Keep the first migrated project small.
   - Prefer one dataset, one target variable, one analysis page.
   - Do not overbuild a full product app for the first example.

## Output checklist

- a small notebook set kept as source material
- a migration README that explains why AGILAB helps
- a sample `lab_stages.toml`
- a `pipeline_view.dot` or `pipeline_view.json`
- exported sample artifacts for ANALYSIS
- one analysis page bundle or a concrete plan to create it

## Notebook Import And Launch Guardrails

Use these checks whenever a notebook migration touches WORKFLOW import or the
ANALYSIS notebook launcher:

- Keep project-owned notebooks under `<app_project>/notebooks/`.
- Keep generated WORKFLOW exports and import sidecars in the selected project
  export workspace, normally under `exported_notebooks/<project>/`.
- Do not create or maintain both `flight` and `flight_project` project roots.
  Pick the canonical project directory name and make aliases point to it only
  when an existing installer contract requires that.
- For WORKFLOW notebook import, separate the output directory from the manifest
  lookup directory:
  - output: `stages_file.parent`
  - manifest lookup: selected app project root, for example
    `src/agilab/apps/builtin/<project>/notebook_import_views.toml`
- Resolve manifest lookup from the selected project name first. Do not blindly
  reuse `env.active_app` when WORKFLOW can switch projects in the same session.
- Treat `preflight.safe_to_import` as a hard gate. If it is false, show the
  blocking preflight error and do not write `lab_stages.toml` or notebook import
  sidecars.
- Treat notebook parse, schema, preflight, and persistence failures as failed
  imports, not as zero-stage successes. A successful notebook with no runnable
  code cells may return `0` and warn; failed or blocked imports should use a
  distinct sentinel such as `None` and must not mark the WORKFLOW page dirty.
- Persist `lab_stages.toml` atomically. Write to a same-directory temporary file,
  replace the target only after TOML serialization succeeds, and clean up the
  temporary file on failure so stale or partial local stage contracts are not
  created.
- Do not report import success or update editor state until the stage contract
  has been written successfully. Regression coverage should include invalid
  notebook structure, TOML write failure, no false success/page-dirty state after
  failure, and the valid zero-code-cell warning path.
- For supervisor-exported notebooks, preserve each imported stage's
  `source_cell_index` so artifact role inference can classify inputs and outputs
  from the right source code.
- ANALYSIS should discover launchable notebooks from the app project notebooks
  directory and persist notebook selection alongside view selection.

## References

- Read `references/migration-checklist.md` for the migration checklist.
- Read `references/skforecast-meteo-fr.md` for the lightweight French
  forecasting pilot used in this repo.
