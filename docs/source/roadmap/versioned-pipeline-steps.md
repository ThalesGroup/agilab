# Feature: versioned pipeline step templates

This note captures a recurring product problem observed in AGILab pipeline
workflows: generated steps are still stored as Python snippets, even though the
orchestrator knows much more structure than the saved text reveals.

AGILab previously relied on targeted snippet migrations to keep some older labs
running. That approach has since been retired because it was too fragile and too
opaque: a saved step could change behaviour simply because the loader rewrote it.
The current product direction is better, but still incomplete:

- saved Python now remains exactly as written
- stale generated snippets must be regenerated or re-imported explicitly
- AGILab still lacks a structured, version-aware representation for generated
  pipeline steps

The proposed feature is to replace raw generated snippets with explicit,
versioned pipeline step templates whose identity belongs to the orchestration
layer rather than to any single application.

## Problem

Today, AGILab stores many generated steps as raw Python code in
``lab_steps.toml``. Even when a step originates from **ORCHESTRATE**, the saved
artifact is still a snippet, not a structured execution spec.

This has several drawbacks:

- the real source of truth is code text, not structured step data
- users cannot clearly see whether a step is current, stale, or app-owned custom code
- changes in app contracts still surface as snippet drift instead of schema drift
- regeneration paths are explicit but not first-class in the saved data model
- imports from orchestration and saved labs do not share a fully explicit lifecycle

## Current product stance

This proposal does **not** suggest reintroducing silent snippet migration.

The intended behaviour remains:

- no implicit Python rewrite when a lab is loaded
- no hidden repair pass during execution
- explicit regeneration or refresh whenever a generated snippet becomes stale

The missing piece is a better representation for generated steps, so AGILab can
detect and explain drift without mutating saved Python behind the user's back.

## Proposal

Introduce two explicit step kinds:

- ``template`` for AGILab-generated steps
- ``raw_python`` for fully custom snippets

For ``template`` steps, store a structured payload instead of Python as the
source of truth:

- ``template_id``
- ``template_version``
- ``app``
- ``action`` or ``task``
- ``engine``
- ``question``
- ``args``

Python code becomes a rendered view or export artifact, not the canonical
representation. This keeps execution inspectable while making the actual step
contract explicit and versionable.

The key design rule is that ``template_id`` must identify the structural shape
owned by AGILab orchestration, not the business meaning of one particular app
step. In other words:

- ``template_id`` says how the orchestrator should render, validate, and refresh
  the step
- ``app`` says which application is targeted
- ``action`` or ``task`` says what that application should do

That avoids reintroducing app-specific coupling under a different name.

## Example shape

```toml
[[pipeline]]
kind = "template"
template_id = "pipeline.agi_run.single_action"
template_version = 3
app = "example_project"
action = "reference_allocator"
engine = "agi.run"
question = "Compute reference allocations"

[pipeline.args]
data_in = "network_sim/pipeline"
data_out = "routing_reference/pipeline"
time_horizon = 16
trajectories_glob = "flight_trajectory/pipeline/*"
sat_trajectories_glob = "sat_trajectory/pipeline/Trajectory/*.csv"
```

In this model:

- ``template_id`` is generic and reusable across apps
- ``app`` and ``action`` carry the business-specific intent
- changing one app action does not require inventing a new template family

## Expected behaviour

When AGILab loads a ``template`` step:

- it compares the saved ``template_version`` with the current template registry
- if the versions match, the step renders and runs normally
- if the versions differ, AGILab does not silently rewrite the step
- instead, AGILab marks the step as outdated and offers an explicit
  ``refresh from template`` action

For ``raw_python`` steps:

- AGILab stores and runs the code as-is
- AGILab does not attempt implicit structural migration
- the user remains responsible for keeping the snippet aligned with the runtime

## Why this is better

- removes fragile text-rewrite migrations from the critical path
- makes step drift visible instead of hidden
- produces more readable ``lab_steps.toml`` diffs
- reduces regressions caused by legacy path or contract rewrites
- separates product-supported templates from user-owned custom code
- keeps orchestration concerns separate from app concerns

## Transition plan

### Phase 1

Add the structured fields for newly created steps while keeping support for
legacy code steps.

### Phase 2

Replace ad-hoc legacy repair logic with explicit stale-step detection for
structured steps. Existing raw Python remains untouched.

### Phase 3

Provide a one-shot converter for older labs:

- convert known generated snippets into ``template`` steps
- keep unknown snippets as ``raw_python``

### Phase 4

Retire the remaining compatibility helpers once the majority of active labs have
been converted and the refresh workflow is well established.

## Non-goals

- banning custom Python snippets entirely
- parsing arbitrary Python into structured steps
- guaranteeing automated conversion for every hand-edited snippet
- encoding app-specific meaning directly into ``template_id``

## Product impact

This feature improves trust in AGILab pipeline execution. Instead of forcing the
user to reason about raw Python drift, AGILab would tell them exactly which
steps are current, which are stale, and which are fully custom.

That is a cleaner contract for both end users and developers, and it reduces the
maintenance burden of keeping generated steps aligned with changing application
interfaces.

It also gives AGILab a clearer ownership boundary: orchestration owns template
families and their versions, while applications only provide the runtime target
and business action invoked by the step.
