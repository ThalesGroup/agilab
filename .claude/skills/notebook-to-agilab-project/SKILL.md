---
name: notebook-to-agilab-project
description: Migrate or maintain a small local notebook workflow inside an AGILAB project. Use this skill when a user wants notebooks turned into a reproducible AGILAB project, project-owned notebooks exposed under ANALYSIS, WORKFLOW notebook import, lab_stages.toml, artifact contracts, and a conceptual workflow view.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-05-16
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

## Surface choice contract

- Choose an AGI page when the analysis is becoming part of the app contract:
  repeatable dashboard, review screen, demo, validation evidence, or
  `agi-page-*` package. This enables non-notebook users, stable demos,
  CI-backed artifact checks, and releaseable page packaging. The cost is that
  the page bundle, dependencies, and exported artifact contract must be
  maintained.
- Choose notebooks or AGI snippets when the work is still code-centric:
  exploration, debugging, cell reruns, migration from an existing notebook,
  reusable snippets, or technical handoff. Reuse depends on the
  snippet/notebook contract, runtime environment, and declared dependencies.
  The ANALYSIS Jupyter sidecar is only the local interactive launch path; it is
  not the only way notebooks or snippets can be reused.
- Use both when the product surface and investigation trail both matter: keep
  the AGI page as the stable result surface and keep notebooks or snippets as
  the technical trail behind that result.

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
   - `ANALYSIS`: one page that reads the exported artifacts when the result
     should be productized
   - project notebooks: reusable `.ipynb` files under `<app_project>/notebooks/`
   - AGI snippets: reusable code contracts when a notebook cell should become a
     smaller execution unit

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
- one explicit surface decision: AGI page, notebook/AGI snippets, or both
- one analysis page bundle or a concrete plan to create it when the result is
  productized

## Notebook Import And Launch Guardrails

Use these checks whenever a notebook migration touches WORKFLOW import or the
ANALYSIS notebook launcher:

- For first-proof notebook import, keep the packaged sample selected from the
  ABOUT wizard only. PROJECT Create may show the selected state, but it must
  not add a second packaged-sample selection or download button.
  Use explicit wording such as `Create from built-in notebook` in ABOUT, not a
  hidden or ambiguous `example` file reference; say that no file needs to be
  found or uploaded for AGILAB's packaged sample. Keep direct local notebook
  upload in PROJECT Create, not in the ABOUT wizard.
- The packaged notebook sample must carry AGILAB import metadata, especially the
  `recommended_template` and `project_name_hint`, so PROJECT can preselect the
  right base project and create a runnable imported project without guesswork.
- The first-proof packaged notebook should create
  `flight_telemetry_from_notebook_project` and remain installable/executable
  through the same `INSTALL` / `EXECUTE` proof path as the built-in
  `flight_telemetry_project`.
- Do not silently infer manager versus worker ownership for imported executable
  cells when the distinction changes generated project code. Preserve explicit
  cell metadata when present; otherwise review or ask cell-by-cell and tag the
  stage before generating project files.
- Keep the included-sample path separate from the user-upload path. Selecting
  the packaged sample should not require a browser file chooser; uploading a
  user notebook should still clear the packaged sample source.
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
- Do not describe notebooks or AGI snippets as local-runtime-only. Only the
  embedded ANALYSIS Jupyter sidecar is local interactive UI; exported notebooks
  and snippets can be reused wherever their runtime and dependencies are
  available.

## References

- Read `references/migration-checklist.md` for the migration checklist.
- Read `references/skforecast-meteo-fr.md` for the lightweight French
  forecasting pilot used in this repo.
