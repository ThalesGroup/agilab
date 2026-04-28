# Workflow Maintainability Patterns

Target date: 2026-04-28

This backlog captures the long-term maintainability work for AGILAB workflow
pages. The goal is to make PROJECT, ORCHESTRATE, PIPELINE, and service-control
pages easier to test and evolve by applying explicit design patterns instead
of adding more direct Streamlit state mutation.

## Design Patterns

Use these patterns as the default direction for future workflow-page changes.

- **Page State / ViewModel**: compute one plain state object before rendering.
  The page should render from this object instead of rediscovering files,
  locks, snippets, and selected apps in multiple widgets.
- **Ports and Adapters**: isolate filesystem, subprocess, MLflow, OpenAI,
  keyring, GitHub, and AGILAB runtime calls behind injected dependencies.
  Streamlit should remain a boundary adapter, not the domain model.
- **Command Result**: buttons such as `INSTALL`, `RUN`, `EXPORT`, `CLONE`,
  `START SERVICE`, and `CLEAR LOGS` should call command functions that return
  typed results such as `success`, `refused`, `stale`, `failed`, or `no-op`.
- **Explicit State Machine**: model workflow status directly when a page can be
  `empty`, `generated`, `stale`, `runnable`, `running`, `failed`, or
  `complete`.
- **Versioned Artifact Contracts**: new generated artifacts should carry schema
  metadata and a migration or refusal path. This applies to `lab_steps.toml`,
  snippets, exported notebooks, screenshots, app settings, and run manifests.
- **Facade Boundary**: pages should depend on `agi_gui` and page-support
  helpers. If a low-level `agi_env` or worker dependency is unavoidable,
  isolate it behind a page-local port.
- **Registry Pattern**: page bundles, widgets, snippet templates, and app
  templates should move toward typed registries instead of repeated discovery
  rules.

## Roadmap Item: Pattern-Gated Workflow Changes

Treat long-term workflow-page maintenance as an explicit design-pattern
adoption program, not a sequence of isolated Streamlit fixes.

Every non-trivial change to PROJECT, ORCHESTRATE, PIPELINE, or service-control
pages should declare which pattern it is advancing and should add or update the
nearest support-module test. If a change cannot fit one of the patterns above,
the implementation should either introduce the missing pattern deliberately or
explain why the page-local exception is temporary.

The next concrete slice is Pipeline-first:

- Add a minimal `PipelinePageState` / ViewModel builder.
- Move `RUN` and `CLEAR LOGS` behind typed command-result functions.
- Represent stale snippets, missing logs, and runnable labs as state instead of
  rediscovering them in individual widgets.
- Keep Streamlit as the rendering adapter; do not move page behavior into
  `agi-env` or worker internals.

## Current Status

- Page State / ViewModel: partially done. Some typed state and report objects
  exist, but Pipeline and Orchestrate still read and write Streamlit session
  state directly in multiple places.
- Ports and Adapters: partially done. `BootstrapPorts`, `Orchestrate*Deps`, and
  support modules exist, but not every external dependency is behind an
  injected adapter yet.
- Command Result: partially done. `ActionResult`, `ActionSpec`, and
  `run_streamlit_action` provide the first shared Streamlit command-result
  primitive, with PROJECT clone creation as the first adopter. Other workflow
  actions still need to move toward the same typed boundary.
- Explicit State Machine: partially done. Global pipeline state helpers exist,
  but Pipeline editor, Pipeline run flow, and service mode still need one
  explicit workflow-state model.
- Versioned Artifact Contracts: partially done. `AGILAB_SNIPPET_API` and run
  manifest schema support exist, but related artifacts are not all versioned
  with migration or refusal paths.
- Facade Boundary: improved but incomplete. The `agi-gui` split and shared
  page bootstrap reduce direct coupling, but pages still touch low-level
  internals and session state in places.
- Registry Pattern: mostly not done. Connector registries exist, but page
  bundles, widgets, snippet templates, and app templates still need typed
  registries.

## Recommended Sequence

1. Keep extending typed command-result actions from PROJECT clone creation to
   the next high-friction workflow buttons.
2. Add a minimal `PipelinePageState` / ViewModel builder.
3. Derive selected lab, visible steps, stale-snippet status, lock/run status,
   and available actions from that state.
4. Move `RUN` and `CLEAR LOGS` behind typed command functions.
5. Add an explicit Pipeline workflow-state enum covering `empty`, `generated`,
   `stale`, `runnable`, `running`, `failed`, and `complete`.
6. Add `lab_steps.toml` schema metadata for newly saved pipeline files and a
   clear refusal or refresh path for unsupported versions.
7. Apply the same pattern to Orchestrate service mode after Pipeline is stable.
8. Convert snippet templates and page widgets into typed registries once state
   and command boundaries are in place.

## First Slice Acceptance Criteria

- Pipeline page rendering can be driven from one plain state object.
- Log cleanup cannot make pipeline steps disappear from the visible state.
- Stale generated snippets are represented as state, not only as an execution
  error.
- At least one targeted test covers old snippets, missing logs, and a runnable
  lab with visible steps.
- The change does not reintroduce direct UI dependencies into `agi-env`.
