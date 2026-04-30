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
- **Registry Pattern**: page bundles, widgets, app templates, reusable snippet
  candidates, and future structured step templates should move toward typed
  registries instead of repeated discovery rules.

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

Maintenance baseline complete as of 2026-04-30. The original long-term
workflow-page rework has a tested support-module baseline for Pipeline,
Orchestrate one-shot execution, Orchestrate service mode, persisted artifacts,
and reusable registries.

- Page State / ViewModel: baseline complete. Pipeline has a typed
  `PipelinePageState` / ViewModel for visible steps, selected lab, stale
  snippets, lock/run status, logs, and available actions. Orchestrate service
  mode has typed service state for visible action/status/health/export flows.
  Broader Orchestrate now has typed run-mode state, INSTALL readiness, CHECK
  distribute readiness, EXECUTE/combo readiness, run-artifact state, and a
  combined INSTALL/CHECK/RUN phase model.
- Ports and Adapters: baseline complete for the workflow pages covered by this
  backlog. `BootstrapPorts`, `Orchestrate*Deps`, action helpers, support
  modules, and page-local ports keep the tested business decisions outside the
  Streamlit rendering path. Further extraction of incidental file or runtime
  calls is normal hardening, not a blocking roadmap item.
- Command Result: baseline complete. `ActionResult`, `ActionSpec`, and
  `run_streamlit_action` provide shared Streamlit command-result primitives.
  Pipeline run, clear-logs, delete, delete-all, and undo-delete flows use typed
  command results. Orchestrate install, check-distribute, apply-distribution,
  service start/status/health/export/stop, and run gating now route through
  typed readiness or typed action results.
- Explicit State Machine: baseline complete. Pipeline has a
  `PipelineWorkflowStatus` enum covering `empty`, `generated`, `stale`,
  `runnable`, `running`, `failed`, and `complete`. Orchestrate service mode has
  a `ServiceWorkflowStatus` model for `disabled`, `idle`, `starting`,
  `running`, `unhealthy`, `failed`, and `stopping`. Broader Orchestrate now has
  explicit execute/combo, run-artifact, and combined install/distribute/run
  workflow state.
- Versioned Artifact Contracts: baseline complete. `AGILAB_SNIPPET_API`, run
  manifest schema support, `lab_steps.toml` v1 metadata/refusal support,
  exported notebook metadata v1 support, `app_settings.toml` v1 write-time
  metadata/refusal support, Pipeline step-template metadata preservation in
  editor snapshot/restore flows, and screenshot evidence via
  `screenshot_manifest.json` v1 are in place. The maintained Playwright robot
  refreshes the screenshot manifest when it writes failure screenshots.
- Facade Boundary: baseline complete for the tested workflow decisions. The
  `agi-gui` split, shared page bootstrap, support modules, and injected deps
  keep low-level decisions testable without moving page behaviour into
  `agi-env` or worker internals.
- Registry Pattern: baseline complete. Connector registries, page bundles,
  `agi_gui` widgets, app templates, Pipeline reusable snippet candidates, and
  Pipeline step templates now have typed registries or classification helpers.
  The editor preserves those metadata fields instead of reducing steps back to
  raw Python-only records during undo/restore.

## Ongoing Discipline

These patterns are now the default guardrails for future workflow-page changes.
New non-trivial work should keep adding support-module tests, avoid silent
snippet rewrites, and preserve explicit artifact/schema refusal paths.

The structured pipeline-step template registry is now present. Replacing every
raw generated snippet with a fully structured `kind = "template"` runtime
representation remains a product evolution path, not a blocker for this
maintenance baseline.

## First Slice Acceptance Criteria

- Pipeline page rendering can be driven from one plain state object.
- Log cleanup cannot make pipeline steps disappear from the visible state.
- Stale generated snippets are represented as state, not only as an execution
  error.
- At least one targeted test covers old snippets, missing logs, and a runnable
  lab with visible steps.
- The change does not reintroduce direct UI dependencies into `agi-env`.
