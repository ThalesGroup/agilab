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
- **Registry Pattern**: page bundles, widgets, app templates, and remaining
  snippet-template discovery should move toward typed registries instead of
  repeated discovery rules.

## Roadmap Item: Pattern-Gated Workflow Changes

Treat long-term workflow-page maintenance as an explicit design-pattern
adoption program, not a sequence of isolated Streamlit fixes.

Every non-trivial change to PROJECT, ORCHESTRATE, PIPELINE, or service-control
pages should declare which pattern it is advancing and should add or update the
nearest support-module test. If a change cannot fit one of the patterns above,
the implementation should either introduce the missing pattern deliberately or
explain why the page-local exception is temporary.

The Pipeline-first slice is now the reference implementation:

- Add a minimal `PipelinePageState` / ViewModel builder.
- Move `RUN` and `CLEAR LOGS` behind typed command-result functions.
- Represent stale snippets, missing logs, and runnable labs as state instead of
  rediscovering them in individual widgets.
- Stamp newly saved `lab_steps.toml` files with schema metadata and refuse
  unsupported future versions before editing.
- Keep Streamlit as the rendering adapter; do not move page behavior into
  `agi-env` or worker internals.

## Current Status

- Page State / ViewModel: partially done. Pipeline has a typed
  `PipelinePageState` / ViewModel for visible steps, selected lab, stale
  snippets, lock/run status, logs, and available actions. Orchestrate service
  mode now has typed service state for visible action/status/health/export
  flows. Broader Orchestrate install/distribute/run views still need the same
  level of consolidation.
- Ports and Adapters: partially done. `BootstrapPorts`, `Orchestrate*Deps`, and
  support modules exist, but not every external dependency is behind an
  injected adapter yet.
- Command Result: partially done. `ActionResult`, `ActionSpec`, and
  `run_streamlit_action` provide shared Streamlit command-result primitives.
  Pipeline run, clear-logs, delete, delete-all, and undo-delete flows now use
  typed command results. Orchestrate service start, status, health, export,
  and stop controls also return typed command results. Remaining workflow
  actions should follow that shape.
- Explicit State Machine: partially done. Pipeline has a
  `PipelineWorkflowStatus` enum covering `empty`, `generated`, `stale`,
  `runnable`, `running`, `failed`, and `complete`. Orchestrate service mode has
  a `ServiceWorkflowStatus` model for `disabled`, `idle`, `starting`,
  `running`, `unhealthy`, `failed`, and `stopping`. Broader Orchestrate views
  still need explicit workflow-state models.
- Versioned Artifact Contracts: partially done. `AGILAB_SNIPPET_API`, run
  manifest schema support, `lab_steps.toml` v1 metadata/refusal support,
  exported notebook metadata v1 support, and `app_settings.toml` v1
  write-time metadata/refusal support exist. Screenshot evidence now has a v1
  `screenshot_manifest.json` helper/CLI, and the maintained Playwright robot
  refreshes the manifest when it writes failure screenshots.
- Facade Boundary: improved but incomplete. The `agi-gui` split and shared
  page bootstrap reduce direct coupling, but pages still touch low-level
  internals and session state in places.
- Registry Pattern: partially done. Connector registries, page bundles,
  `agi_gui` widgets, and app templates have typed registries. Remaining
  snippet-template discovery should move behind the same registry shape.

## Recommended Sequence

1. Move remaining snippet-template discovery behind a typed registry.
2. Apply the ViewModel, command-result, and workflow-state pattern to broader
   Orchestrate install/distribute/run views.
3. Extend versioned contracts to remaining persisted UI artifacts.

## First Slice Acceptance Criteria

- Pipeline page rendering can be driven from one plain state object.
- Log cleanup cannot make pipeline steps disappear from the visible state.
- Stale generated snippets are represented as state, not only as an execution
  error.
- At least one targeted test covers old snippets, missing logs, and a runnable
  lab with visible steps.
- The change does not reintroduce direct UI dependencies into `agi-env`.
