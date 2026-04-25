# AGILab future work

This page tracks planned work only.

- For current shipped capabilities, see {doc}`../features`.
- For toolchain fit and framework comparison, see {doc}`../agilab-mlops-positioning`.

The goal here is to rank future work, not to restate the current feature set.

## Recommended near-term execution order

If the goal is near-term product sequencing rather than broad idea collection,
use this order:

1. **Global DAG runner dispatch and UI state**
   - let `PIPELINE` represent one orchestrated DAG across the full workflow,
     not just one app-local execution view
   - build on the shipped multi-app DAG contract, read-only global pipeline DAG
     report, pending execution-plan report, read-only runner state, and
     persisted dispatch-state proof plus the two-unit app dispatch smoke,
     operator-state report, dependency-view report, live-update payload report,
     operator-action execution report, and operator-UI report
2. **Bidirectional notebook interop**
   - build on the shipped supervisor-notebook export and analysis-page launcher
     metadata
   - add notebook-to-pipeline import maturity and optional single-kernel
     union-environment notebooks when step environments are compatible
3. **Data connector facility**
   - make SQL, ELK, object storage, and other external data sources first-class
     connector targets
   - build on the shipped data connector facility report for SQL, OpenSearch,
     and object-storage definitions plus the data connector resolution report
     for connector-aware app/page resolution
   - add the shipped data connector health report for operator-gated probe
     planning without live public network checks
   - add the shipped data connector health actions report for explicit
     operator-triggered health probe rows
   - add the shipped data connector runtime adapters report for credentialed
     runtime bindings without materializing secrets in public evidence
   - add the shipped data connector UI preview report for static connector
     state and provenance review
   - add the shipped data connector live UI report for Release Decision
     Streamlit integration without connector network probes
   - add the shipped data connector app catalogs report for app-local
     connector catalogs across every non-template built-in app
   - this turns connector work into a practical data-access layer, not just path
     cleanup
4. **Reduce contract adoption**
   - AGILab already has distributed work-plan execution and an initial shared
     reducer contract
   - the public reducer benchmark now validates 8 partials / 80,000 synthetic
     items in `0.003s` against a `5.0s` target
   - `execution_pandas_project` and `execution_polars_project` now emit named
     benchmark reduce artefacts through that contract
   - `flight_project` now emits trajectory-summary reduce artefacts through
     that contract
   - `uav_queue_project` now emits the same `reduce_summary_worker_<id>.json`
     artifact shape for queue metrics
   - `uav_relay_queue_project` now emits that shared queue-metrics reduce
     artifact shape too
   - `meteo_forecast_project` now emits forecast-metrics reduce artefacts
   - Release Decision now surfaces benchmark, flight, meteo forecast, and UAV
     queue-family reduce artefacts as evidence
   - a repository guardrail now requires every non-template built-in app to
     expose a reducer contract
   - `mycode_project` is the only explicit template-only exemption because it
     has no concrete merge output yet
   - future apps/templates must opt in when they produce durable worker
     summaries
5. **Intent-first operator mode**
   - valuable, but it benefits from the cleaner evidence, compatibility, and
     connector contracts above

Why this order:

- turn the shipped manifest remediation baseline into external evidence import
  and release indexes before broader onboarding automation
- build global orchestration on the shipped cross-app contract and read-only
  product graph plus pending execution plan instead of claiming runner behavior
  before it exists
- keep notebook interop after the orchestration state model is clearer
- stabilize contracts before standardizing distributed reduction
- keep operator refinements downstream of the proof/evidence layer

## Streamlit-inspired AGILab views

The most promising Streamlit-style view patterns for AGILab are not generic
gallery clones. They are focused application views that reinforce AGILab's core
value: orchestration, evidence, and domain-specific interaction.

### 1. Experiment Cockpit

Purpose:

- compare runs quickly
- inspect KPI summaries
- open artefacts and benchmark results from one page

Suggested layout:

- KPI cards on top
- run filters and selectors on the left
- comparison charts in the center
- run table and artefact links below

Why it matters:

- best value-to-effort ratio
- directly useful across many AGILab apps

### 2. Evidence / Release View

Purpose:

- decide whether a run, model, or artefact bundle is promotable

Suggested layout:

- release decision banner
- pass/fail gate checklist
- baseline vs candidate KPI comparison
- provenance and reproducibility panel
- evidence bundle table

Why it matters:

- strong differentiator for AGILab
- aligns with evidence-driven engineering and promotion workflows

### 3. Scenario Playback View

Purpose:

- replay a run over time
- inspect state, actions, and KPI evolution together

Suggested layout:

- run selector and time slider
- map or network panel
- current decision-state panel
- KPI timeline and event log

Why it matters:

- strong demonstration value
- good fit with existing AGILab map/network views

### 4. Realtime Analytical and Geospatial Views

Purpose:

- inspect dense live data without degrading interaction quality
- support higher-frequency analysis for KPI, maps, and network state

Recommended direction:

- use Plotly.js/WebGL first for analytical views such as KPI timelines, run
  comparison, monitoring, and large point clouds
- use deck.gl for dense geospatial and network overlays
- use Three.js only for specialized 3D mission views where depth is part of the
  meaning, such as orbital or spatial playback

Why it matters:

- gives AGILab a practical realtime analysis layer without committing to custom
  low-level WebGL infrastructure
- fits existing AGILab needs better than a generic “WebGL support” initiative
- opens a clear path for performance gains in monitoring and playback views

### 5. Run Diff / Counterfactual Analysis

Purpose:

- compare two runs and explain what changed in a way that is directly useful to
  engineers and reviewers
- turn raw deltas into defensible reasoning about outcomes

Suggested scope:

- input and configuration diff
- topology and artefact diff
- allocation and decision diff
- KPI delta summary
- candidate-vs-baseline narrative focused on the most material changes

Why it matters:

- high value for debugging, review, and evidence-driven engineering
- fits AGILab better than generic BI dashboards because it stays tied to runs,
  artefacts, and orchestration decisions
- creates a strong bridge between experimentation and promotion workflows

### 6. Multi-app DAG orchestration

Purpose:

- extend orchestration from one app flow to DAGs that span multiple apps
- make inter-app dependencies explicit instead of hiding them in manual glue

Current shipped baseline:

- `agilab.multi_app_dag.v1` defines the first portable cross-app DAG contract
- `docs/source/data/multi_app_dag_sample.json` links `uav_queue_project` to
  `uav_relay_queue_project` through the explicit `queue_metrics` handoff
- `tools/multi_app_dag_report.py --compact` validates schema, checked-in app
  nodes, acyclic dependencies, docs references, and artifact handoffs
- the KPI evidence bundle includes this as `multi_app_dag_report_contract`
- the global DAG report family now covers execution planning, persisted
  dispatch state, real two-app app-entry smoke execution, operator state,
  dependency views, live-update payloads, operator actions, and static operator
  UI proof for the checked-in `queue_baseline -> relay_followup` contract

Remaining scope:

- no open report-driven contract gap remains for the shipped two-app DAG
  baseline
- future work is broader app coverage, placement in the live product surface,
  external validation, and production hardening

Why it matters:

- the contract closes the first bridge between app-local execution and a
  product-wide orchestrated workflow
- the remaining work is scale and hardening rather than missing public evidence
  for the shipped two-app baseline

### 7. Global DAG runner dispatch and UI state

Purpose:

- turn the checked-in global DAG, execution plan, read-only runner state, and
  persisted dispatch-state proof into live app execution with persisted
  operator-visible status

Current shipped baseline:

- `tools/global_pipeline_dag_report.py --compact` assembles one read-only
  product-level graph from `docs/source/data/multi_app_dag_sample.json`
- the graph expands `uav_queue_project` and `uav_relay_queue_project` through
  their checked-in `pipeline_view.dot` files
- the graph preserves the cross-app `queue_metrics` artifact edge and reports
  app nodes, app-local step nodes, app-local edges, and execution order
- `tools/global_pipeline_execution_plan_report.py --compact` converts the graph
  into ordered runnable units in `pending/not_executed` state, marks
  `queue_baseline` ready, marks `relay_followup` blocked on `queue_metrics`,
  and records provenance for the DAG and each app-local pipeline view
- `tools/global_pipeline_runner_state_report.py --compact` projects the plan
  into read-only runner state, marks `queue_baseline` as `runnable`, marks
  `relay_followup` as `blocked`, and records transition, retry,
  partial-rerun, operator-message, and provenance metadata without executing
  apps
- `tools/global_pipeline_dispatch_state_report.py --compact` writes and reads
  back a persisted dispatch-state JSON proof, records `queue_baseline`
  completion, publishes `queue_metrics`, marks `relay_followup` runnable, and
  preserves timestamps, retry counters, partial-rerun flags, operator messages,
  and provenance without executing apps
- `tools/global_pipeline_app_dispatch_smoke_report.py --compact` executes
  `queue_baseline` and `relay_followup` through the real checked-in
  `uav_queue_project` and `uav_relay_queue_project` manager/worker entries,
  writes the actual `queue_metrics`, `relay_metrics`, and reducer artifacts,
  and persists them in dispatch-state JSON
- `tools/global_pipeline_operator_state_report.py --compact` reads that
  persisted full-DAG dispatch state and exposes completed unit state,
  queue-to-relay handoffs, available artifacts, and retry/partial-rerun action
  rows for future operator flows
- `tools/global_pipeline_dependency_view_report.py --compact` reads the
  operator-state proof and exposes upstream/downstream dependency visualization
  for `queue_baseline -> relay_followup`, including the `queue_metrics` edge,
  producer/consumer apps, adjacency lists, and artifact-flow rows
- `tools/global_pipeline_live_state_updates_report.py --compact` reads the
  dependency view and emits deterministic live orchestration-state updates for
  graph-ready, unit-state, artifact-state, dependency-state, and
  operator-action refresh payloads; this is an update contract, not a streaming
  service or UI renderer
- `tools/global_pipeline_operator_actions_report.py --compact` reads the
  live-update payloads, accepts `queue_baseline:retry` and
  `relay_followup:partial_rerun`, replays the corresponding queue and relay app
  entries, and persists action outcomes plus output artifacts
- `tools/global_pipeline_operator_ui_report.py --compact` reads the action
  outcomes and renders status, unit-card, dependency-graph, update-timeline,
  action-control, and artifact-table components into a static HTML proof
- the compact KPI bundle includes this as
  `global_pipeline_dag_report_contract`,
  `global_pipeline_execution_plan_report_contract`,
  `global_pipeline_runner_state_report_contract`, and
  `global_pipeline_dispatch_state_report_contract`, plus
  `global_pipeline_app_dispatch_smoke_report_contract` and
  `global_pipeline_operator_state_report_contract` and
  `global_pipeline_dependency_view_report_contract` and
  `global_pipeline_live_state_updates_report_contract` and
  `global_pipeline_operator_actions_report_contract` and
  `global_pipeline_operator_ui_report_contract`

Remaining scope for this item:

- no open report-driven contract gap remains for the global DAG runner/UI
  baseline; future work is product hardening, placement, and broader external
  validation

Why it matters:

- the report gives AGILab a clearer product story than isolated per-app
  pipelines without overclaiming execution
- live UI state is still needed before the orchestration layer is fully visible
  to operators and reviewers

### 8. Bidirectional notebook interop

Purpose:

- complete the bridge between notebooks and AGILab pipelines without hiding
  per-step runtime constraints

Current shipped baseline:

- `PIPELINE` can already export a supervisor notebook that preserves step
  provenance, runtime metadata, and per-step execution context
- exported notebooks can include related analysis-page launcher helpers when an
  app declares them
- `tools/notebook_pipeline_import_report.py --compact` now validates the first
  notebook-to-pipeline import contract from a checked-in `.ipynb`; it preserves
  markdown context, code cells, import hints, execution-count metadata, and
  artifact references as `not_executed_import` pipeline-step evidence, writes a
  richer `lab_steps.toml` preview, and feeds the existing `PIPELINE` upload path
- `tools/notebook_roundtrip_report.py --compact` validates
  `lab_steps.toml -> supervisor notebook -> import -> lab_steps preview`
  preservation for saved step description, prompt, model, code, runtime,
  import hints, and artifact references
- `tools/notebook_union_environment_report.py --compact` validates a
  `single-kernel union notebook` candidate only for compatible `runpy` /
  current-kernel steps and records `supervisor_notebook_required` for mixed
  runtime or mixed-environment pipelines
- this is intentionally not the same thing as flattening a multi-venv pipeline
  into one notebook kernel

Suggested scope:

- harden notebook-to-pipeline import beyond the initial report and upload path,
  including broader edge cases for exported supervisor notebooks
- keep expanding notebook-native analysis surfaces or Voilà-style packaging
  without duplicating the current apps-pages logic blindly
- make notebook-native analysis surfaces or Voilà-style packaging possible
  without duplicating the current apps-pages logic blindly
- preserve enough provenance so the notebook remains explainable

Why it matters:

- reduces the gap between exploratory notebook work and reproducible product
  workflows
- gives teams a practical adoption bridge instead of a one-way migration story

## Logging modernization

Purpose:

- improve developer and operator logging without breaking compatibility across
  Streamlit, workers, subprocesses, and distributed services

Recommended direction:

- keep Python stdlib `logging` plus `AgiLogger` as the canonical runtime logging
  contract
- add real child logger support, structured JSON output, and stable context
  fields such as app id, host, worker, and run id
- keep the current colorized human console output as the default local
  developer mode
- treat `loguru` as an optional choice only for isolated helper scripts or
  local tools that do not need full stdlib logging interoperability
- do not plan a repo-wide migration to `loguru` unless stdlib logging becomes a
  demonstrated blocker for AGILAB runtime requirements

Why it matters:

- AGILAB already spans third-party libraries and multi-process surfaces that
  integrate naturally with stdlib logging
- the real missing capability is structured context and better logger
  hierarchy, not a new logging syntax
- this keeps the logging contract stable while still making observability
  stronger
## Backend observability and audit architecture

AGILab should keep application-specific interaction inside the product and move
generic observability, search, and fleet-level monitoring into tools designed
for that job.

### 1. Elastic or OpenSearch + Grafana

Best when:

- engineering operations and observability are the main priority

Good for:

- run health
- worker load
- step latency
- failures and alerts
- SLA-style monitoring

Why it matters:

- strongest near-term operational value
- clean split between AGILab interaction and backend observability

### 2. OpenSearch + OpenSearch Dashboards

Best when:

- auditability, search, and historical traceability are the main priority

Good for:

- log exploration
- artefact traceability
- historical run search
- saved audit dashboards

Why it matters:

- lowest friction for Kibana-like usage patterns

### 3. Postgres + Superset

Best when:

- structured KPI analytics and management reporting are the main priority

Good for:

- curated dashboards
- cross-project reporting
- evidence trend analysis
- management-facing analytics

Why it matters:

- stronger fit than Elastic-native tools for BI-style reporting

## Connectors and integration

Connectors should appear explicitly in the roadmap because they are not just
implementation detail. They determine how AGILab reaches external systems,
resolves artefacts, and keeps app workflows portable.

### 1. Connector framework hardening

Purpose:

- make connector-backed workflows more predictable and portable

Focus areas:

- path portability
- artefact resolution
- stable source and target contracts
- less app-specific path glue
- clearer connector diagnostics

Why it matters:

- reduces friction across apps
- makes automation more reusable
- lowers the gap between conceptual workflows and executable steps

#### Connector integration change request

The concrete change request behind this roadmap item is to replace repeated raw
path settings in `app_settings.toml` with references to reusable connector
definition files.

Current problem:

- pages such as `view_maps_network` rely on many low-level path keys
- the same path logic is repeated across settings files
- defaults are more machine-specific than they should be
- page code must interpret too many raw path parameters directly

Proposed direction:

- introduce a declarative `Connector` model
- store connector definitions in plain-text TOML files
- let `app_settings.toml` reference those connector files instead of embedding
  all path details inline

Completed baseline:

- `tools/data_connector_facility_report.py --compact` validates first-class
  SQL, OpenSearch, and object-storage connector definitions without network
  probes
- `tools/data_connector_resolution_report.py --compact` resolves connector IDs
  from an app-settings-style sample, validates connector-aware app/page
  resolution, and preserves `legacy_path_fallback` rows for migration
- `tools/data_connector_health_report.py --compact` plans SQL, OpenSearch, and
  object-storage health/status probes behind operator opt-in while keeping
  public evidence in `health_probe_plan_only` mode
- `tools/data_connector_health_actions_report.py --compact` exposes those
  probes as operator-triggered action rows in `operator_trigger_contract_only`
  mode
- `tools/data_connector_runtime_adapters_report.py --compact` binds SQL,
  OpenSearch, and object-storage connectors to runtime adapter operations while
  deferring credential values to the operator runtime
- `tools/data_connector_ui_preview_report.py --compact` renders connector
  state, page bindings, legacy fallbacks, and health-boundary provenance as
  static JSON+HTML evidence
- `tools/data_connector_live_ui_report.py --compact` wires connector state and
  connector-derived provenance into the Release Decision Streamlit page in
  `streamlit_render_contract_only` mode
- `tools/data_connector_app_catalogs_report.py --compact` validates app-local
  connector catalogs referenced from built-in `app_settings.toml` files

First connector model:

- `id`
- `kind`
- `label`
- `description`
- `base`
- `subpath`
- `globs`
- `preferred_file_ext`
- `metadata`

Recommended file placement:

- next to the app settings
- for example `src/connectors/*.toml`

Recommended resolution rule:

1. explicit query parameters
2. current session-state widget values
3. explicit page-level overrides in `app_settings.toml`
4. connector references in `app_settings.toml`
5. legacy raw path keys
6. code-level defaults

Compatibility rule:

- keep legacy raw path keys working in phase 1
- let connector references win when both are defined

Expected impact:

- `view_maps_network` is the primary beneficiary

Remaining scope:

- add live endpoint smoke evidence for credentialed operator environments

## Distributed execution and reduction

AGILab already ships real distributed execution primitives, but the product
surface is not yet a fully migrated generic map/reduce layer.

Current state:

- apps can build explicit distribution plans
- workers execute partitioned plans locally or on Dask-backed clusters
- `agi_node.reduction` defines a shared reducer contract with partial inputs,
  merge semantics, validation hooks, and a standard reduce artefact schema
- `tools/reduce_contract_benchmark.py --json` validates 8 partials / 80,000
  synthetic items in `0.003s` against a `5.0s` target
- `execution_pandas_project`, `execution_polars_project`, `flight_project`,
  `meteo_forecast_project`, `uav_queue_project`, and
  `uav_relay_queue_project` write worker-scoped
  `reduce_summary_worker_<id>.json` artefacts through the shared contract
- Release Decision surfaces those reduce artefacts with schema validation,
  reducer name, partial count, artifact path, benchmark row/source/execution
  fields, flight row/aircraft/speed fields, meteo forecast MAE/RMSE/MAPE
  fields, and UAV queue-family packet/PDR fields when present
- aggregation outside the migrated benchmark, flight, meteo, and UAV
  queue-family apps is still mostly app-specific

Current guardrail:

- all non-template built-in apps now expose a reducer contract
- `mycode_project` is template-only and intentionally exempt because its worker
  hooks are placeholders with no concrete merge output
- future apps/templates must add `reduction.py`, emit
  `reduce_summary_worker_<id>.json`, and export a `*_REDUCE_CONTRACT` once they
  produce durable worker summaries
- docs should avoid describing AGILab as a full generic map/reduce mechanism
  beyond the explicit contract and migrated apps

### 1. Reduce contract adoption

Purpose:

- move the current distributed work-plan execution model onto the shared
  reusable aggregation contract

Focus areas:

- reducer adoption in public apps
- user-visible reduce artefacts in analysis views
- user-visible evidence that a distributed run was merged successfully

Why it matters:

- makes the product claim honest and specific
- reduces repeated merge logic across apps
- improves reviewability of distributed results
- gives AGILab a clearer story than “Dask-backed execution exists somewhere in
  the stack”

Completed slices:

- `execution_pandas_project` and `execution_polars_project` now emit named
  `reduce_summary_worker_<id>.json` `ReduceArtifact` files from worker results
- `flight_project` now emits worker-scoped
  `reduce_summary_worker_<id>.json` `ReduceArtifact` files for trajectory
  summary metrics
- `uav_queue_project` now emits worker-scoped
  `reduce_summary_worker_<id>.json` `ReduceArtifact` files for queue summary
  metrics
- `uav_relay_queue_project` now emits worker-scoped
  `reduce_summary_worker_<id>.json` `ReduceArtifact` files for relay queue
  summary metrics
- `meteo_forecast_project` now emits worker-scoped
  `reduce_summary_worker_<id>.json` `ReduceArtifact` files for forecast
  quality metrics
- Release Decision now discovers `reduce_summary_worker_*.json`, parses it with
  `ReduceArtifact.from_dict`, displays reducer evidence, and flags invalid JSON
- a repository guardrail now fails if a non-template built-in app lacks a
  reducer contract or worker-scoped artifact writer
- `mycode_project` is documented as template-only rather than counted as a
  reducer migration gap

Next concrete change request:

- keep future public apps/templates aligned with the shared reducer contract as
  they gain concrete merge semantics
- extend the surfaced reducer evidence as more non-benchmark apps adopt the
  same artifact contract

Compatibility rule:

- keep current app-owned aggregation working in phase 1
- let apps opt into the shared reducer contract incrementally

Expected impact:

- cleaner public positioning for distributed execution
- easier regression testing of distributed apps
- a better foundation for future run-diff and evidence views
- `PROJECT` must expose connector references clearly enough to stay debuggable
- `PIPELINE` should remain unchanged in phase 1

Suggested implementation phases:

1. core connector model, parser, resolver, and validation
2. connector-aware default resolution in apps-pages
3. connector preview and navigation support in `PROJECT`
4. optional connector references in `PIPELINE` only if needed later

Acceptance target:

- connectors can replace path groups in `app_settings.toml`
- existing apps still work without migration
- connector definitions remain plain-text and git-friendly

### 2. Data connector facility

Purpose:

- connect AGILab cleanly to external data systems and storage backends

Typical targets:

- SQL databases
- Elasticsearch or OpenSearch
- ELK-backed data sources
- object storage
- GitHub or GitLab
- simulation backends
- shared data repositories

Why it matters:

- expands AGILab beyond local file-driven workflows
- makes observability, reporting, and traceability easier to industrialize

Current shipped baseline:

- `tools/data_connector_facility_report.py --compact` validates
  `agilab.data_connector_facility.v1` against
  `docs/source/data/data_connectors_sample.toml`
- the sample covers SQL, OpenSearch/ELK, and object-storage connector
  definitions with kind-specific required fields
- remote credentials are represented as `env:` references and the report runs
  in `contract_validation_only` mode without live network probes
- `tools/data_connector_resolution_report.py --compact` validates
  `agilab.data_connector_resolution.v1` against
  `docs/source/data/data_connector_app_settings_sample.toml`
- connector-aware app/page resolution now resolves catalog IDs from app
  settings while preserving `legacy_path_fallback` rows for raw-path migration
- `tools/data_connector_health_report.py --compact` validates
  `agilab.data_connector_health.v1` and plans connector health/status probes
  behind operator opt-in without executing network checks
- `tools/data_connector_health_actions_report.py --compact` validates
  `agilab.data_connector_health_actions.v1` and exposes operator-triggered
  health probe action rows without executing network checks
- `tools/data_connector_runtime_adapters_report.py --compact` validates
  `agilab.data_connector_runtime_adapters.v1` and binds credentialed connector
  adapters to runtime operations while deferring credential values
- `tools/data_connector_ui_preview_report.py --compact` validates
  `agilab.data_connector_ui_preview.v1` and renders static connector state plus
  connector-derived provenance as JSON+HTML preview evidence
- `tools/data_connector_live_ui_report.py --compact` validates
  `agilab.data_connector_live_ui.v1` and wires connector state plus
  connector-derived provenance into the Release Decision Streamlit page without
  opening connector networks
- `tools/data_connector_app_catalogs_report.py --compact` validates
  `agilab.data_connector_app_catalogs.v1` for app-local connector catalogs
  across every non-template built-in app

Remaining scope:

- live endpoint smoke evidence for credentialed operator environments

### 3. Connector-aware views

Purpose:

- move the shipped static connector state and connector-derived provenance
  preview into the live UI pages

Typical views:

- import or export provenance panel
- connector health/status panel
- external artefact traceability panel

Why it matters:

- makes integrations visible and debuggable
- gives users confidence about what data came from where

### 4. DeepWiki/Open-style repository knowledge layer

Purpose:

- make the AGILab codebase easier to explore, onboard, and explain
- provide a generated code wiki and Q&A layer across repositories

Recommended scope:

- internal deployment first
- index `agilab` and private app repositories separately
- include code, docs source, runbooks, and `pyproject.toml`
- exclude generated artefacts, virtualenvs, `build/`, `dist/`, and runtime shares

Guardrail:

- treat the generated wiki as an exploration aid, not as the source of truth
- keep official product and operator documentation in versioned docs and runbooks

Why it matters:

- reduces time spent rediscovering cross-cutting implementation details
- helps new contributors navigate AGILab's multi-repo, multi-app structure
- complements agent workflows with repository-level context and diagrams

## Decision guidance

Use this rule of thumb:

- if the goal is near-term execution order rather than thematic discussion, use
  the ordered list from **Recommended near-term execution order** first

- choose **Experiment Cockpit** if the next need is better daily usability for
  engineers comparing runs
- choose **Evidence / Release View** if the next need is promotion readiness and
  defensible evidence
- choose **Scenario Playback View** if the next need is time-based explanation
  and demonstration
- choose **Realtime Analytical and Geospatial Views** if the next need is
  denser live analysis, faster interaction, and higher-volume visual playback
- choose **Run Diff / Counterfactual Analysis** if the next need is faster
  debugging, clearer run review, and defensible explanation of KPI changes
- choose **Multi-app DAG orchestration** if the next need is broader app
  coverage beyond the shipped two-app dependency contract
- choose **Global DAG runner dispatch and UI state** if the next need is to
  execute the shipped product-visible graph in `PIPELINE`
- choose **Bidirectional notebook interop** if the next need is a stronger bridge
  between exploratory notebooks and AGILab-managed workflows
- choose **Elastic/OpenSearch + Grafana** if the next need is operations and
  observability
- choose **OpenSearch + OpenSearch Dashboards** if the next need is audit and
  historical search
- choose **Postgres + Superset** if the next need is curated KPI analytics
- choose **Connector framework hardening and the data connector facility** if the
  next need is portability, SQL/ELK/data-system access, and reliable artefact flow
- choose **DeepWiki/Open-style repository knowledge layer** if the next need is
  faster codebase onboarding, architecture discovery, and repository Q&A without
  turning generated content into official docs

## Final consolidated poll

Use both paths, because they serve different purposes:

1. Quick popularity signal in GitHub Discussions
   - Create or answer a poll: <https://github.com/ThalesGroup/agilab/discussions/new?category=polls>
   - Browse existing poll discussions: <https://github.com/ThalesGroup/agilab/discussions/categories/polls>
2. Structured roadmap vote in GitHub Issues
   - Submit a vote: <https://github.com/ThalesGroup/agilab/issues/new?template=roadmap-vote.yml>
   - Browse submitted votes: <https://github.com/ThalesGroup/agilab/issues?q=is%3Aissue+in%3Atitle+%22%5BRoadmap+vote%5D%22>
3. Open roadmap discussion in Issues
   - Central roadmap thread: <https://github.com/ThalesGroup/agilab/issues/2>
   - Use this thread if you want visible engineering discussion in the normal issue workflow.

### Comment template for `issues/2`

```text
Vote: <one option>
Why: <why this matters now>
Expected value: <product / engineering / user impact>
Constraints or dependencies: <blocking items, staffing, sequencing>
```

### Current candidate priorities

- Global DAG runner dispatch and UI state
- Bidirectional notebook interop
- Data connector facility
- Reduce contract adoption
- Intent-first operator mode

If the `roadmap` label is not visible yet in GitHub, the issue form still
works. The repository workflow will create or update that label on the next
successful run.

## Reference URLs

- Streamlit gallery: <https://streamlit.io/gallery>
- `st.metric`: <https://docs.streamlit.io/develop/api-reference/data/st.metric>
- `st.fragment`: <https://docs.streamlit.io/develop/api-reference/execution-flow/st.fragment>
- `st.pydeck_chart`: <https://docs.streamlit.io/develop/api-reference/charts/st.pydeck_chart>
- OpenSearch FAQ: <https://docs.opensearch.org/faq/>
- AWS OpenSearch background: <https://docs.aws.amazon.com/opensearch-service/latest/developerguide/rename.html>
- Grafana Elasticsearch datasource: <https://grafana.com/docs/grafana/latest/datasources/elasticsearch/>
- Superset Elasticsearch support: <https://superset.apache.org/docs/databases/supported/elasticsearch/>
- Metabase data sources: <https://www.metabase.com/data-sources/>
