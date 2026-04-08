---
name: notebook-to-agilab-project
description: Migrate a small local notebook workflow into an AGILAB project. Use this skill when a user wants a sequence of notebooks turned into a reproducible AGILAB project with lab_steps.toml, explicit artifact contracts, a conceptual pipeline view, and an ANALYSIS page that shows why the migration is useful.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-04-08
---

# Notebook To AGILAB Project

Use this skill when the source material is a small set of local notebooks and the
goal is to turn them into an AGILAB-style workflow rather than keep a notebook-only
delivery.

## When to use

- 2-6 notebooks that already form a sequence
- local ML / data notebooks with explicit artifacts
- migration demos where the user wants to show what AGILAB adds
- examples that need `lab_steps.toml`, a conceptual pipeline view, and an
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
   - `PIPELINE`: explicit ordered steps in `lab_steps.toml`
   - `ANALYSIS`: one page that reads the exported artifacts

4. Make the migration value explicit.
   - Show what was implicit in notebooks.
   - Show what becomes reproducible, rerunnable, and comparable in AGILAB.

5. Keep the first migrated project small.
   - Prefer one dataset, one target variable, one analysis page.
   - Do not overbuild a full product app for the first example.

## Output checklist

- a small notebook set kept as source material
- a migration README that explains why AGILAB helps
- a sample `lab_steps.toml`
- a `pipeline_view.dot` or `pipeline_view.json`
- exported sample artifacts for ANALYSIS
- one analysis page bundle or a concrete plan to create it

## References

- Read `references/migration-checklist.md` for the migration checklist.
- Read `references/skforecast-meteo-fr.md` for the lightweight French
  forecasting pilot used in this repo.
