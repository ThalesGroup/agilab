# AGILAB UX Improvement Roadmap

This roadmap turns the current AGILAB UX discussion into an execution backlog.
The objective is not cosmetic polish first. The objective is to make AGILAB feel
deterministic, explain its own state, and reduce avoidable operator confusion.

## UX Principles

- Prefer explicit state over hidden conventions.
- Prefer classified failures over raw tracebacks.
- Prefer one clear happy path over many partially overlapping workflows.
- Prefer preview-first and progress-first behavior on heavy pages.
- Prefer shared UX primitives over page-by-page improvisation.

## Current Friction To Remove

- First-run setup depends on too much implicit environment knowledge.
- Users cannot always tell whether a value comes from defaults, workspace state, or current session overrides.
- Long-running actions often start without clear progress phases or next-step guidance.
- Heavy pages can feel blank or frozen before enough data is available to render.
- PROJECT and ORCHESTRATE still expose too much internal architecture and not enough user intent.

## UX Targets

- New users should be able to reach a successful `INSTALL -> PROJECT -> EXECUTE` path without consulting repo internals.
- Every failed action should answer what failed, why it failed, and what to do next.
- Every heavy page should expose loading state, data scope, and applied filters before rendering dense outputs.
- The main workflow pages should describe user intent first and internal run mode second.

## Quick Wins

Target horizon: `0-6 weeks`

- Add an `Environment Health` summary panel.
- Scope: app path resolution, share path validity, cluster share vs local share, API key presence, worker install availability, and app settings path provenance.
- Best starting surfaces: [AGENTS.md](/Users/agi/PycharmProjects/agilab/AGENTS.md), [PROJECT page](/Users/agi/PycharmProjects/agilab/src/agilab/pages/1_PROJECT.py), and [ORCHESTRATE page](/Users/agi/PycharmProjects/agilab/src/agilab/pages/2_ORCHESTRATE.py).

- Standardize long-action feedback across install, execute, service health, and project clone/rename.
- Every action should emit start, current step, success summary, classified failure, and next action.

- Make settings provenance visible.
- Show whether a field comes from seed defaults, workspace config, current session override, or a derived value.
- Best first targets: `app_args_form.py` pages with derived paths and project/app settings editors.

- Add page-level empty/loading states for heavy views.
- Show dataset detected, rows loaded, filters applied, and expensive step in progress.
- First targets: `view_maps_network`, `view_maps_3d`, `view_barycentric`, and `view_training_analysis`.

- Replace raw install and cluster failure dumps with classified actions.
- First error classes: dependency missing, worker manifest drift, cluster share invalid, SSH/auth failure, and service health failure.

## Medium Refactors

Target horizon: `1-3 months`

- Reframe PROJECT around environment intent.
- Users should see current project type, clone type, `.venv` status, and whether install is required before execute.
- Remove ambiguity between temporary clones and working clones.

- Reframe ORCHESTRATE around run intent.
- Primary choices should be run locally, run on cluster, benchmark modes, and start service.
- Numeric mode and internal flags should become secondary details.

- Build a shared action-execution model for Streamlit pages.
- Page actions should use a common helper for progress state, exception classification, result summary, and command reproduction.
- This reduces one-off action handling in pages and forms.

- Add cached summary layers for heavy pages.
  - Load compact summaries first.
  - Fetch dense detail only after user selection.
  - Keep interaction responsive when datasets are large.

## Shared UX Primitives To Build Once

- `EnvironmentHealthCard`
  - report config, shares, install state, and cluster availability

- `SettingProvenanceBadge`
  - mark seed/workspace/session/derived values

- `ActionProgressPanel`
  - shared start/progress/success/failure rendering for long actions

- `ClassifiedFailureBox`
  - map exception classes and known failure patterns to actionable guidance

- `DataLoadSummary`
  - show detected files, rows, filters, and cache status before rendering charts/maps

- `RunIntentSelector`
  - user-facing run choices mapped to internal execution modes

## Success Metrics

- Time to first successful local execute on a clean machine
- Number of actions that end in raw traceback exposure
- Number of pages with explicit loading and empty-state summaries
- Median startup/import time for heavy pages using [perf_smoke.py](/Users/agi/PycharmProjects/agilab/tools/perf_smoke.py)
- Number of settings screens that expose provenance explicitly
- Number of workflow pages using shared action-feedback primitives instead of custom ad hoc messaging

## Performance And UX Budgets

- Use [perf_smoke.py](/Users/agi/PycharmProjects/agilab/tools/perf_smoke.py) before and after maintainability refactors on:
- `orchestrate-execute-import`
- `pipeline-ai-import`
- `runtime-distribution-import`
- `base-worker-import`
- `agi-page-network-map-import`
- `agi-page-geospatial-3d-import`

- Add page-level UX budgets for heavy views:
- first visible progress state should appear immediately
- first summary render should happen before full dense render when possible
- heavy pages should avoid blank full-page waits

## Recommended Delivery Sequence

1. `Environment Health` panel on PROJECT and ORCHESTRATE.
2. Shared long-action feedback pattern.
3. Settings provenance component.
4. ORCHESTRATE intent-first mode selection.
5. PROJECT clone/install state clarification.
6. Heavy page preview/loading-state upgrades.
7. Shared classified failure component across install and run flows.

## First Concrete Backlog

- Add a repo issue/epic for `Environment Health`.
- Add a repo issue/epic for `ActionProgressPanel`.
- Add a repo issue/epic for `SettingProvenanceBadge`.
- Use `perf_smoke.py` to capture current startup baselines before the first UX refactor wave.
- After the first two primitives exist, migrate PROJECT, ORCHESTRATE, and one heavy view page.

## Non-Goals

- Do not start with a visual redesign detached from workflow clarity.
- Do not add more mode/config options before state and provenance are clearer.
- Do not treat raw benchmark throughput as UX success unless the user can also understand what the system is doing.
