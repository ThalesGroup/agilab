# AGILab future work

This page tracks planned work only.

- For current shipped capabilities, see {doc}`../features`.
- For toolchain fit and framework comparison, see {doc}`../agilab-mlops-positioning`.

The goal here is to rank future work, not to restate the current feature set.

## Professionalization priority order

Use this order when the goal is to make AGILab feel professional, adoptable,
and maintainable rather than just richer in features.

### P0. Release and runtime integrity

Goal:

- every public release can be installed, launched, and validated from a clean
  public environment without relying on the developer checkout

Concrete items:

- keep the release guard as the mandatory pre-tag path: install smoke,
  first-proof, security check, docs mirror check, badge freshness, dependency
  policy, and trusted-publisher contract
- make imported-notebook projects part of the release smoke, not a separate
  best-effort demo path
- require each shipped notebook sample to create an installable and runnable app
  equivalent to its packaged example
- keep PyPI, GitHub release proof, public docs, and Hugging Face demo text
  aligned before publication
- fail fast on local-path, stale-worker, missing-share, or stale-app-repository
  states instead of silently degrading

Done means:

- a clean install can run the default first proof and at least one imported
  notebook project end to end
- release proof points to the exact version, commands, evidence, and known
  limitations
- no release badge, docs mirror, dependency-policy, or trusted-publisher guard
  is knowingly stale

### P1. First-run product experience

Goal:

- a new user understands what to click, what will happen, and how to recover if
  it fails

Concrete items:

- keep ABOUT focused on the first proof and remove redundant call-to-action
  clutter
- make every wizard action direct: install really installs, execute really runs,
  analysis opens the right result page, notebook import creates the project
  without asking the user to locate packaged files
- keep PROJECT sidebars and advanced controls out of the default path unless
  they are needed for the current task
- add deterministic error messages for install/run/delete/import flows and keep
  spinners scoped to the action that is still running
- keep examples small enough to finish locally before users attempt cluster,
  service mode, or external app repositories

Done means:

- a user can complete the built-in first proof or the notebook first proof
  without reading source code, finding hidden files, or guessing page actions

### P2. Notebook interop and no-lock-in

Goal:

- teams can enter AGILab from notebooks and leave AGILab back to notebooks
  without losing the useful work

Concrete items:

- provide one importable notebook for every public packaged example that is
  suitable for notebook import
- preserve explicit manager/worker role metadata while still requiring clear
  cell-by-cell review when metadata is missing or ambiguous
- name imported projects predictably, for example
  `flight-telemetry-from-notebook-project`
- keep notebook export positioned as the exit and handoff path, not just a
  convenience download
- round-trip the stage order, code, runtime hints, artifacts, and provenance
  enough for review and reuse outside the AGILab UI

Done means:

- import and export are documented as a reversible adoption bridge: notebooks
  can become AGILab projects, and AGILab work can be handed back as notebooks
  when the workbench is no longer needed

### P3. Security and supply-chain posture

Goal:

- AGILab is safe by default for controlled R&D and explicit about what remains
  outside the default threat model

Concrete items:

- keep public UI binding local by default and document the reverse-proxy,
  authentication, TLS, and network controls required for exposure
- treat apps, notebooks, generated snippets, and external repositories as
  executable code that needs review, allowlisting, and isolation
- keep secrets out of command lines, logs, committed files, generated notebooks,
  and release evidence
- regenerate SBOM and dependency audit evidence for the actual install profiles
  being adopted
- keep PyPI trusted publishing and action pinning as mandatory release gates

Done means:

- the docs do not imply production, multi-tenant, regulated-data, or public
  exposure readiness without the external controls required to make that true

### P4. Team and cluster operation

Goal:

- shared-team and cluster use is diagnosable, bounded, and repeatable

Concrete items:

- make cluster share setup explicit and refuse cluster mode when no usable
  shared path is configured
- keep SSH, SSHFS, LAN discovery, remote path, and share-sentinel diagnostics
  actionable from both CLI and UI
- provide a small validation matrix for local, bare-metal cluster, VM-based
  cluster, AI Lightning, Hugging Face, and cloud targets when evidence exists
- add service-health gates for long-running service mode: idle policy,
  unhealthy limit, restart-rate threshold, and machine-readable status
- separate single-user convenience from multi-user isolation, quotas, and
  account policy

Done means:

- a team can distinguish local failure, share failure, worker dependency
  failure, scheduler failure, and service-health failure without reading
  tracebacks first

### P5. Evidence-driven MLOps bridge

Goal:

- AGILab stays a workbench, but hands clean evidence to the MLOps and platform
  systems that own production

Concrete items:

- strengthen run evidence, release decisions, run diff, artifact provenance,
  and compatibility profiles as first-class outputs
- keep MLflow integration focused on tracking, artifacts, model registry
  handoff, and comparison rather than replacing AGILab execution
- define promotion-ready evidence bundles for apps, imported notebooks, and
  cluster runs
- add hooks for monitoring, drift, feature stores, orchestration engines, and
  serving platforms without claiming those systems are built into AGILab

Done means:

- an experiment can be reviewed, compared, promoted, or rejected from evidence
  that is versioned, portable, and honest about its execution environment

### P6. Extension architecture and maintainability

Goal:

- new apps, pages, connectors, and workflow features follow stable patterns
  instead of accumulating one-off glue

Concrete items:

- keep public APIs, app templates, page metadata, connector models, reducer
  contracts, and workflow stage contracts explicit and tested
- use design patterns to separate UI, orchestration, runtime execution,
  artifacts, and evidence generation
- add pattern-gated checks before new workflow or notebook-import behavior can
  bypass existing contracts
- keep strict typing and focused tests on shared helpers that affect many apps
- document deprecations with migration paths and removal dates

Done means:

- future features can be added by extending clear contracts, not by duplicating
  page-specific or app-specific behavior

### P7. Ecosystem and distribution

Goal:

- AGILab is easy to adopt incrementally through public packages, app packages,
  demos, and external repositories without locking users into one layout

Concrete items:

- keep PyPI packages for publishable apps small, named consistently, and backed
  by trusted publishing
- keep Hugging Face and public demos aligned with the same release evidence as
  the repository
- provide clear app repository update, install, rename, and migration behavior
  instead of compatibility aliases for stale local copies
- publish only examples that meet content-quality, install/run, README, and
  notebook-import criteria

Done means:

- users can adopt one app, one notebook import, one demo, or the full workbench
  without discovering different contracts for each path

## Professional execution backlog

Treat this as the delivery order. Lower-priority feature work should not
displace higher-priority adoption, release, and safety work unless there is an
explicit product decision.

### Priority 1. Clean release lane

Ship only when the public package, public docs, release proof, coverage badges,
trusted publishing, Hugging Face copy, and first-proof commands all describe the
same release.

Acceptance gate:

- `./dev release`, `./dev docs`, and the release proof report pass from a clean
  checkout
- the release proof names the exact version, validation routes, and known
  non-certified environments
- no manual release note, README, public docs page, or demo copy contradicts the
  package that was published

Why first:

- professional adoption starts by trusting the published artifact, not by
  trusting the developer machine

### Priority 2. Notebook import parity

Every public example that is advertised as importable from a notebook must ship
with a notebook sample, deterministic metadata, and an imported-project smoke
that proves `INSTALL` and `EXECUTE` behave like the original app.

Acceptance gate:

- each supported sample creates a predictably named
  `<example>-from-notebook-project`
- manager/worker cell roles are explicit or force review before project
  creation
- at least one imported notebook project is included in the release smoke

Why now:

- notebook import is a unique adoption bridge only if users can prove that the
  imported project still runs

### Priority 3. First-run wizard contract

The default UI path must be direct: buttons perform the action they promise, and
the next required user action is visible before navigation.

Acceptance gate:

- built-in first proof: select demo, install, execute, and analysis are all
  direct and recoverable
- notebook first proof: create from packaged notebook does not require the user
  to find a hidden file
- spinners, success messages, and failure messages are scoped to the action that
  actually ran

Why now:

- first-run confusion makes the product feel experimental even when the backend
  works

### Priority 4. Runtime failure diagnostics

Failures must classify themselves before showing raw tracebacks.

Acceptance gate:

- install/run/delete/import failures distinguish dependency, path, archive,
  project-state, cluster-share, worker-copy, and scheduler failures
- stale local app directories and stale worker environments produce actionable
  remediation
- corrupted archives and invalid imported notebooks fail fast with a concise
  cause and a safe next step

Why now:

- professional users can tolerate failures; they cannot tolerate unclear
  failures

### Priority 5. Security and shared-use hardening

Keep controlled local R&D easy, but make shared-team use conditional on explicit
controls.

Acceptance gate:

- public bind, external app repositories, notebook import, generated code,
  secrets, cluster accounts, and service mode each have an explicit guard or
  operator checklist
- security checks can emit machine-readable results for the selected install
  profile
- the docs continue to reject standalone production, public, multi-tenant, or
  regulated-data claims without external hardening

Why now:

- adoption grows only if the boundary between safe default use and hardened use
  stays explicit

### Priority 6. Cluster and team operation

Cluster mode should be a supported team workflow, not a best-effort advanced
demo.

Acceptance gate:

- cluster requests fail when no usable shared path exists
- SSH, SSHFS, LAN discovery, remote path, and share-sentinel checks are exposed
  through CLI and UI diagnostics
- validation evidence covers local, bare-metal cluster, VM cluster, AI
  Lightning, Hugging Face, and cloud targets only where each route has actually
  been tested

Why now:

- distributed execution is a core differentiator only when setup and failure
  modes are operationally clear

### Priority 7. Evidence and promotion workflow

AGILab should make it easy to decide whether a run, app, notebook import, or
cluster validation is ready to reuse, publish, or hand off.

Acceptance gate:

- run evidence, release decisions, compatibility reports, run diff, artifact
  provenance, and supply-chain evidence share stable schemas
- evidence bundles can be consumed outside AGILab by reviewers, CI, MLflow, or
  platform teams
- promotion decisions state what passed, what failed, and what is out of scope

Why now:

- this is the bridge between a useful workbench and professional engineering
  governance

### Priority 8. Connector-backed data access

Move data access from repeated path settings to declarative connectors.

Acceptance gate:

- SQL, OpenSearch/ELK, object storage, local paths, and simulation backends use
  connector definitions instead of page-specific path glue where practical
- connector health checks stay operator-triggered and do not leak credentials
- import/export provenance names the connector and artifact source

Why now:

- professional workflows fail when data paths are machine-specific or invisible

### Priority 9. Extension and design-pattern guardrails

New app, page, workflow, notebook, connector, and reducer behavior should extend
stable contracts instead of adding special cases.

Acceptance gate:

- public app templates, page metadata, pipeline stages, notebook import roles,
  reducers, connectors, and evidence reports have focused tests
- pattern-gated checks block new workflow behavior that bypasses the shared
  contracts
- deprecations include a migration path and removal target

Why now:

- long-term maintenance depends more on repeatable patterns than on another
  feature page

### Priority 10. Curated app ecosystem

Publish fewer apps, but make every published app useful, named well, documented,
installable, runnable, and importable when it claims notebook support.

Acceptance gate:

- app packages use consistent `agi-app-*` names, trusted publishing, and clean
  metadata
- example READMEs explain purpose, inputs, outputs, install/run path, notebook
  import status, and limitations
- app repository update behavior wins over stale local copies without hidden
  compatibility aliases

Why now:

- app quality is the most visible proof that the platform contract works

### Priority 11. Multi-app DAG productization

Productize multi-app orchestration only after the release, first-run, notebook,
diagnostic, and evidence layers are stable.

Acceptance gate:

- `WORKFLOW` can show, validate, and execute a product-level DAG with persisted
  operator-visible state
- retry, partial rerun, dependency visualization, and artifact handoff are
  visible in the same operator surface
- the shipped two-app executable DAG remains the regression baseline before
  broader DAG coverage is claimed

Why later:

- multi-app DAGs are high-value, but they amplify every weak contract beneath
  them

### Priority 12. Observability and MLOps handoff

Integrate with observability and MLOps platforms without claiming to replace
them.

Acceptance gate:

- MLflow remains the tracking and registry handoff path
- OpenSearch/Grafana/Superset-style integrations consume AGILab evidence and
  telemetry instead of duplicating app logic
- production serving, drift detection, feature stores, and enterprise
  governance are framed as external platform integrations

Why later:

- observability is most useful after run evidence and operational status are
  already consistent

### Explicit non-priorities until the above is stable

- broad public OS, GPU, cloud, or network certification without matching run
  evidence
- production multi-tenant claims without external identity, isolation, quotas,
  secrets management, audit, and monitoring controls
- generic dashboards that are not tied to AGILab runs, artifacts, or decisions
- new app publishing when the app lacks a clear purpose, deterministic first
  run, README, evidence, and package metadata

## Feature sequencing after the professional baseline

If the goal is near-term product sequencing rather than broad idea collection,
use this order after the P0-P2 professionalization gates are under control:

1. **Multi-app DAG orchestration productization**
   - let `WORKFLOW` represent one orchestrated DAG across the full workflow,
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
     union-environment notebooks when stage environments are compatible
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
   - `flight_telemetry_project` now emits trajectory-summary reduce artefacts through
     that contract
   - `uav_queue_project` now emits the same `reduce_summary_worker_<id>.json`
     artifact shape for queue metrics
   - `uav_relay_queue_project` now emits that shared queue-metrics reduce
     artifact shape too
   - `weather_forecast_project` now emits forecast-metrics reduce artefacts
   - Release Decision now surfaces benchmark, flight, weather forecast, and UAV
     queue-family reduce artefacts as evidence
   - a repository guardrail now requires every non-template built-in app to
     expose a reducer contract
   - `mycode_project` and `global_dag_project` are the explicit template-only
     exemptions because they have no concrete merge output yet
   - future apps/templates must opt in when they produce durable worker
     summaries
5. **Intent-first operator mode**
   - valuable, but it benefits from the cleaner evidence, compatibility, and
     connector contracts above
6. **Elasticity and active mesh optimization**
   - keep the current public claim bounded: a compact Active Mesh Optimization
     teaching route exists, but it is centralized-policy evidence, not full
     decentralized MARL certification
   - harden the shipped route by comparing baseline versus adaptive-network
     outcomes, then extending the evidence to failure injection and
     train-then-serve handoff
   - use moving nodes such as aircraft, UAVs, or satellites as active agents
     that can adapt trajectory or routing behavior to improve network KPIs
   - avoid duplicating experiment tracking or model-registry concepts; the
     differentiator should be closed-loop execution and evidence, not another
     metrics UI

Why this order:

- turn the shipped manifest remediation baseline and CI artifact harvest
  contract into external evidence import and release indexes before broader
  onboarding automation
- build global orchestration on the shipped cross-app contract and read-only
  product graph plus pending execution plan instead of claiming runner behavior
  before it exists
- keep notebook interop after the orchestration state model is clearer
- stabilize contracts before standardizing distributed reduction
- keep operator refinements downstream of the proof/evidence layer
- keep any broader MARL claim downstream of reproducible execution,
  baseline/candidate comparison, failure-injection evidence, service-contract
  handoff, and the shared evidence contract

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

Current shipped baseline:

- `agilab.run_diff_evidence.v1` defines a first no-execution run-diff evidence
  contract for public review
- `tools/run_diff_evidence_report.py --compact` compares static
  baseline/candidate KPI checks, run manifests, and artifact rows, then emits
  counterfactual prompts for material deltas
- the KPI evidence bundle includes this as `run_diff_evidence_report_contract`
  and verifies zero command, live-execution, and network-probe counts
- `tools/revision_traceability_report.py --compact` validates
  `agilab.revision_traceability.v1` and fingerprints repository HEAD, AGI core
  package versions, and built-in app manifests without invoking git commands or
  querying networks
- `tools/public_certification_profile_report.py --compact` validates
  `agilab.public_certification_profile.v1` and turns the compatibility matrix
  into a `bounded_public_evidence` certification profile without production or
  third-party certification claims
- `tools/supply_chain_attestation_report.py --compact` validates
  `agilab.supply_chain_attestation.v1` and fingerprints package metadata,
  lockfile, license, bundled AGI core versions, and built-in app manifests
  without formal supply-chain attestation claims
- `tools/ci_artifact_harvest_report.py --compact` now defines the
  no-network external-machine attachment contract for run manifests, KPI
  bundles, compatibility reports, and promotion decisions
- Release Decision can import `ci_artifact_harvest.json`, display harvested
  artifact status/checksum/provenance rows, block invalid harvests, and export
  `ci_artifact_harvest_summary` plus `ci_artifact_harvest_evidence` inside
  `promotion_decision.json`
- `tools/github_actions_artifact_index.py --archive` converts downloaded
  GitHub Actions artifact ZIPs into a harvest-compatible `artifact_index.json`,
  and its opt-in `--live-github` path can query/download workflow-run artifacts
  when credentials are available
- `tools/ci_provider_artifact_index.py --provider gitlab_ci --archive` converts
  downloaded GitLab CI or generic provider artifact ZIPs into the same
  harvest-compatible `artifact_index.json` without querying live provider APIs
- the same tool supports opt-in `--live-gitlab` for credentialed GitLab CI
  pipeline artifact queries/downloads
- `tools/compatibility_report.py --artifact-index` can derive per-release
  compatibility status from those downloaded artifact indexes or from
  `ci_artifact_harvest.json` summaries
- the `pypi-publish` release workflow includes a `release-evidence` job that
  uploads sample external evidence, retrieves it through the live GitHub
  Actions artifact API with `--live-github`, and validates the resulting
  artifact index through the harvest and compatibility reports before publish
  jobs proceed

Remaining scope:

- add richer domain-specific explanations for allocation, topology, and
  decision deltas
- run non-GitHub live provider API harvests in credentialed operator CI

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
- `docs/source/data/multi_app_dag_portfolio_sample.json` broadens the
  contract-only sample suite across `flight_telemetry_project`,
  `weather_forecast_project`, `execution_pandas_project`, and
  `execution_polars_project`
- `tools/multi_app_dag_report.py --compact` validates schema, checked-in app
  nodes, acyclic dependencies, docs references, artifact handoffs, and the
  two-sample DAG suite
- the KPI evidence bundle includes this as `multi_app_dag_report_contract`
- the global DAG report family now covers execution planning, persisted
  dispatch state, real two-app app-entry smoke execution, operator state,
  dependency views, live-update payloads, operator actions, and static operator
  UI proof for the checked-in `queue_baseline -> relay_followup` contract

Remaining scope:

- no open report-driven contract gap remains for the shipped two-app executable
  DAG baseline or the broader contract-only sample suite
- future work is broader app coverage, placement in the live product surface,
  external validation, and production hardening

Why it matters:

- the contract closes the first bridge between app-local execution and a
  product-wide orchestrated workflow
- the remaining work is scale and hardening rather than missing public evidence
  for the shipped two-app baseline

### 7. Multi-app DAG orchestration productization

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
  app nodes, app-local stage nodes, app-local edges, and execution order
- `tools/global_pipeline_execution_plan_report.py --compact` converts the graph
  into ordered runnable units in `pending/not_executed` state, marks
  `queue_baseline` ready, marks `relay_followup` blocked on `queue_metrics`,
  and records provenance for the DAG and each app-local pipeline view
- `tools/global_pipeline_runner_state_report.py --compact` projects the plan
  into read-only runner state, marks `queue_baseline` as `runnable`, marks
  `relay_followup` as `blocked`, and records transition, retry,
  partial-rerun, operator-message, and provenance metadata without executing
  apps
- the WORKFLOW page now includes an expanded `Workflow graph` surface that can
  choose project workflow or multi-app DAG scope, edit steps, created outputs,
  and used outputs through selector-driven workspace drafts and read-only
  summaries, validate the plan without hand-editing docs files, reset the
  persisted preview state, show readiness KPIs, optional graph and output
  details, and preview the next ready step without claiming live app execution
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
  per-stage runtime constraints

Current shipped baseline:

- `WORKFLOW` can already export a supervisor notebook that preserves stage
  provenance, runtime metadata, and per-stage execution context
- exported notebooks can include related analysis-page launcher helpers when an
  app declares them
- `tools/notebook_pipeline_import_report.py --compact` now validates the first
  notebook-to-pipeline import contract from a checked-in `.ipynb`; it preserves
  markdown context, code cells, import hints, execution-count metadata, and
  artifact references as `not_executed_import` pipeline-stage evidence, writes a
  richer `lab_stages.toml` preview, and feeds the existing `WORKFLOW` upload path
- `tools/notebook_roundtrip_report.py --compact` validates
  `lab_stages.toml -> supervisor notebook -> import -> lab_stages preview`
  preservation for saved stage description, prompt, model, code, runtime,
  import hints, and artifact references
- `tools/notebook_union_environment_report.py --compact` validates a
  `single-kernel union notebook` candidate only for compatible `runpy` /
  current-kernel stages and records `supervisor_notebook_required` for mixed
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
- stage latency
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
- lowers the gap between conceptual workflows and executable stages

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
- `tools/data_connector_live_endpoint_smoke_report.py --compact` adds the
  operator-gated live endpoint smoke contract and validates the execution path
  with a local SQLite endpoint
- `tools/data_connector_ui_preview_report.py --compact` renders connector
  state, page bindings, legacy fallbacks, and health-boundary provenance as
  static JSON+HTML evidence
- `tools/data_connector_live_ui_report.py --compact` wires connector state and
  connector-derived provenance into the Release Decision Streamlit page in
  `streamlit_render_contract_only` mode
- `tools/data_connector_view_surface_report.py --compact` verifies the
  connector-aware Release Decision panels for state/provenance, health
  boundary, import/export provenance, and external artifact traceability in
  `connector_view_surface_contract_only` mode
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

- run the opt-in smoke against real credentialed operator endpoints

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
- `execution_pandas_project`, `execution_polars_project`, `flight_telemetry_project`,
  `weather_forecast_project`, `uav_queue_project`, and
  `uav_relay_queue_project` write worker-scoped
  `reduce_summary_worker_<id>.json` artefacts through the shared contract
- Release Decision surfaces those reduce artefacts with schema validation,
  reducer name, partial count, artifact path, benchmark row/source/execution
  fields, flight row/aircraft/speed fields, weather forecast MAE/RMSE/MAPE
  fields, and UAV queue-family packet/PDR fields when present
- aggregation outside the migrated benchmark, flight, weather, and UAV
  queue-family apps is still mostly app-specific

Current guardrail:

- all non-template built-in apps now expose a reducer contract
- `mycode_project` is template-only and intentionally exempt because its worker
  hooks are placeholders with no concrete merge output
- `global_dag_project` is template-preview only and intentionally exempt because
  it demonstrates cross-app DAG contracts rather than a concrete worker merge
  output
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
- `flight_telemetry_project` now emits worker-scoped
  `reduce_summary_worker_<id>.json` `ReduceArtifact` files for trajectory
  summary metrics
- `uav_queue_project` now emits worker-scoped
  `reduce_summary_worker_<id>.json` `ReduceArtifact` files for queue summary
  metrics
- `uav_relay_queue_project` now emits worker-scoped
  `reduce_summary_worker_<id>.json` `ReduceArtifact` files for relay queue
  summary metrics
- `weather_forecast_project` now emits worker-scoped
  `reduce_summary_worker_<id>.json` `ReduceArtifact` files for forecast
  quality metrics
- Release Decision now discovers `reduce_summary_worker_*.json`, parses it with
  `ReduceArtifact.from_dict`, displays reducer evidence, and flags invalid JSON
- a repository guardrail now fails if a non-template built-in app lacks a
  reducer contract or worker-scoped artifact writer
- `mycode_project` and `global_dag_project` are documented as template-only
  rather than counted as reducer migration gaps

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
- `WORKFLOW` should remain unchanged in phase 1

Suggested implementation phases:

1. core connector model, parser, resolver, and validation
2. connector-aware default resolution in apps-pages
3. connector preview and navigation support in `PROJECT`
4. optional connector references in `WORKFLOW` only if needed later

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
  definitions with kind-specific required fields; the current object-storage
  contract covers AWS S3/S3-compatible stores, Azure Blob Storage, and Google
  Cloud Storage
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
- `tools/data_connector_live_endpoint_smoke_report.py --compact` validates
  `agilab.data_connector_live_endpoint_smoke.v1`, keeps default public evidence
  in `live_endpoint_smoke_plan_only` mode, and proves the opt-in execution path
  with a local SQLite endpoint without opening external networks
- `tools/data_connector_ui_preview_report.py --compact` validates
  `agilab.data_connector_ui_preview.v1` and renders static connector state plus
  connector-derived provenance as JSON+HTML preview evidence
- `tools/data_connector_live_ui_report.py --compact` validates
  `agilab.data_connector_live_ui.v1` and wires connector state plus
  connector-derived provenance into the Release Decision Streamlit page without
  opening connector networks
- `tools/data_connector_view_surface_report.py --compact` validates
  `agilab.data_connector_view_surface.v1` and checks the Release Decision
  connector state/provenance panel, health/status boundary, import/export
  provenance panel, and external artifact traceability panel without opening
  connector networks
- `tools/data_connector_app_catalogs_report.py --compact` validates
  `agilab.data_connector_app_catalogs.v1` for app-local connector catalogs
  across every non-template built-in app

Remaining scope:

- run the opt-in smoke against real credentialed SQL/OpenSearch/object-storage
  endpoints in operator environments

### 3. Connector-aware views

Purpose:

- move the shipped static connector state and connector-derived provenance
  preview into the live UI pages

Typical views:

- import or export provenance panel
- connector health/status panel
- external artefact traceability panel

Current shipped baseline:

- `tools/data_connector_view_surface_report.py --compact` validates
  `agilab.data_connector_view_surface.v1` in
  `connector_view_surface_contract_only` mode
- the report verifies four Release Decision surfaces: connector
  state/provenance, connector health/status boundary, import/export
  provenance, and external artifact traceability
- the evidence reads local page source plus the connector live-UI render
  contract, uses the existing Streamlit recorder, and keeps command execution
  and network probes at zero
- the KPI evidence bundle includes this as
  `data_connector_view_surface_report_contract`

Remaining scope:

- move the same pattern beyond Release Decision as additional live UI pages
  need connector-aware panels
- run live connector health/status actions only in credentialed operator
  environments

Why it matters:

- makes integrations visible and debuggable
- gives users confidence about what data came from where

### 4. DeepWiki/Open-style repository knowledge layer

Purpose:

- make the AGILab codebase easier to explore, onboard, and explain
- provide a generated code wiki and Q&A layer across repositories

Recommended scope:

- start with controlled local deployments before publishing hosted search
- index each repository separately
- include code, docs source, runbooks, and `pyproject.toml`
- exclude generated artefacts, virtualenvs, `build/`, `dist/`, and runtime shares

Guardrail:

- treat the generated wiki as an exploration aid, not as the source of truth
- keep official product and operator documentation in versioned docs and runbooks

Current shipped baseline:

- `tools/repository_knowledge_report.py --compact` validates
  `agilab.repository_knowledge_index.v1` in
  `repository_knowledge_static_index` mode
- the report indexes local code, tools, official docs, root runbooks, and
  package/app manifests with SHA-256 fingerprints and lightweight outlines
- generated artifacts, virtualenvs, build outputs, and distributions are
  excluded by contract
- the report emits stable onboarding query seeds while explicitly keeping the
  generated index as an exploration aid and versioned docs as the source of
  truth
- the KPI evidence bundle includes this as
  `repository_knowledge_report_contract`

Remaining scope:

- connect this static index to a generated wiki or Q&A service in controlled
  deployments
- extend indexing to external app repositories under the same source-of-truth
  guardrail

Why it matters:

- reduces time spent rediscovering cross-cutting implementation details
- helps new contributors navigate AGILab's multi-repo, multi-app structure
- complements agent workflows with repository-level context and diagrams

## Decision guidance

Use this rule of thumb:

- if the goal is professionalization, use the ordered list from
  **Professionalization priority order** first
- if the professional baseline is already under control and the goal is feature
  sequencing, use **Feature sequencing after the professional baseline**

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
- choose **Multi-app DAG orchestration productization** if the next need is to
  execute the shipped product-visible graph in `WORKFLOW`
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

- P0 release and runtime integrity
- P1 first-run product experience
- P2 notebook interop and no-lock-in
- P3 security and supply-chain posture
- P4 team and cluster operation
- Multi-app DAG orchestration productization, once the professional baseline is
  stable
- Data connector facility and connector-aware views, once first-run and
  evidence paths are predictable

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
