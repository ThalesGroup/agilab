# AGILab future work

This page tracks planned work only.

- For current shipped capabilities, see {doc}`../features`.
- For toolchain fit and framework comparison, see {doc}`../agilab-mlops-positioning`.

The goal here is to rank future work, not to restate the current feature set.

## Recommended near-term execution order

If the goal is near-term product sequencing rather than broad idea collection,
use this order:

1. **Run manifest + evidence bundle**
   - establish one factual run record and one portable evidence surface
   - this is the dependency for promotion, compatibility automation, and the
     first-proof wizard
2. **Promotion / release decision workflow**
   - turn the evidence bundle into an explicit promotable / blocked decision
   - this is the first strong evidence-driven product surface
3. **First-proof wizard in product**
   - guide newcomers through one validated proof path in the UI
   - it should consume the same run/evidence model instead of inventing a
     separate onboarding proof contract
4. **Compatibility matrix automation**
   - replace the current manual compatibility page with workflow-backed status
   - this becomes much cleaner once run evidence is standardized
5. **Connector registry hardening**
   - stabilize path portability and artefact resolution across apps/pages
   - this reduces glue before deeper cross-app automation
6. **Multi-app DAG orchestration**
   - extend orchestration from one app flow to DAGs that span multiple apps
   - this is the contract needed before the pipeline can become a true
     cross-app orchestrated graph
7. **Global orchestrated pipeline DAG**
   - let `PIPELINE` represent one orchestrated DAG across the full workflow,
     not just one app-local execution view
   - this depends on clearer multi-app orchestration contracts
8. **Bidirectional notebook interop**
   - build on the shipped supervisor-notebook export and analysis-page launcher
     metadata
   - add notebook-to-pipeline import maturity and optional single-kernel
     union-environment notebooks when step environments are compatible
9. **Data connector facility**
   - make SQL, ELK, object storage, and other external data sources first-class
     connector targets
   - this turns connector work into a practical data-access layer, not just path
     cleanup
10. **First-class reduce contract**
   - AGILab already has distributed work-plan execution; the missing piece is a
     shared reducer contract
   - this should come after evidence and connector stabilization, not before
11. **Intent-first operator mode**
   - valuable, but it benefits from the cleaner evidence, compatibility, and
     connector contracts above

Why this order:

- start with evidence before decisions
- start with validated proof before broader onboarding automation
- stabilize cross-app orchestration before claiming a global orchestrated DAG
- keep notebook interop after the orchestration contract is clearer
- stabilize contracts before standardizing distributed reduction
- keep operator refinements downstream of the proof/evidence layer

## Streamlit-inspired AGILab views

The most promising Streamlit-style view patterns for AGILab are not generic
gallery clones. They are focused application views that reinforce AGILab's core
value: orchestration, evidence, and domain-specific interaction.

### 0. First-proof wizard

Purpose:

- guide a newcomer to one successful proof path inside the product
- reduce early branching into cluster, package, or notebook routes

Suggested layout:

- environment readiness check
- recommended proof path card
- one guided launch flow
- explicit success or failure evidence at the end

Why it matters:

- strongest adoption accelerator after evidence-backed runs
- reuses the same compatibility and proof contracts instead of inventing a
  separate tutorial-only path

### 0b. Run manifest + evidence bundle

Purpose:

- give every meaningful run one stable factual record and one exportable
  evidence bundle

Suggested contents:

- resolved inputs and settings
- output artefact references
- KPI summary
- provenance and execution context
- validation results
- human-reviewable evidence attachments

Why it matters:

- this is the base layer for promotion, compatibility automation, and
  onboarding proof
- without it, release and newcomer flows stay partly implicit

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

Suggested scope:

- app-to-app step dependencies
- explicit cross-app artefact handoff
- orchestration contracts for retries, partial reruns, and provenance
- one run record that still captures the whole multi-app execution

Why it matters:

- this is the missing bridge between app-local execution and a real product-wide
  orchestrated workflow
- it turns AGILab orchestration from “one app at a time” into a reusable
  workflow fabric

### 7. Global orchestrated pipeline DAG

Purpose:

- make `PIPELINE` the view of one global orchestrated DAG rather than a mainly
  app-local execution trace

Suggested scope:

- one graph that spans preparation, training, simulation, analysis, and export
- explicit upstream/downstream dependency visualization across apps
- orchestration-state visibility for the full DAG

Why it matters:

- this gives AGILab a clearer product story than isolated per-app pipelines
- it makes the orchestration layer visible to operators and reviewers

### 8. Bidirectional notebook interop

Purpose:

- complete the bridge between notebooks and AGILab pipelines without hiding
  per-step runtime constraints

Current shipped baseline:

- `PIPELINE` can already export a supervisor notebook that preserves step
  provenance, runtime metadata, and per-step execution context
- exported notebooks can include related analysis-page launcher helpers when an
  app declares them
- this is intentionally not the same thing as flattening a multi-venv pipeline
  into one notebook kernel

Suggested scope:

- import notebook logic into pipeline steps
- keep the supervisor-notebook export as the default for mixed-runtime or
  multi-venv pipelines
- generate an optional union notebook environment only when the pipeline step
  environments are actually compatible
- make notebook-native analysis surfaces or Voilà-style packaging possible
  without duplicating the current apps-pages logic blindly
- preserve enough provenance so the notebook remains explainable

Why it matters:

- reduces the gap between exploratory notebook work and reproducible product
  workflows
- gives teams a practical adoption bridge instead of a one-way migration story

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

## Distributed execution and reduction

AGILab already ships real distributed execution primitives, but the product
surface is not yet a first-class generic map/reduce layer.

Current state:

- apps can build explicit distribution plans
- workers execute partitioned plans locally or on Dask-backed clusters
- aggregation is still mostly app-specific

Current gap:

- docs can overstate the capability as a full generic map/reduce mechanism
- reducer semantics are not declared in shared core
- merge artefacts and aggregation summaries are not standardized across apps

### 1. First-class reduce contract

Purpose:

- promote the current distributed work-plan execution model into a clear,
  reusable aggregation contract

Focus areas:

- explicit reducer interface
- merge semantics for partial outputs
- standard aggregation artefacts
- validation hooks for reducer correctness
- user-visible evidence that a distributed run was merged successfully

Why it matters:

- makes the product claim honest and specific
- reduces repeated merge logic across apps
- improves reviewability of distributed results
- gives AGILab a clearer story than “Dask-backed execution exists somewhere in
  the stack”

Concrete change request:

- define a reducer contract in shared core with explicit inputs, partial
  outputs, merge operation, and final artefact schema
- expose the reducer result as a named run artefact instead of leaving it
  implicit in app-specific outputs
- ship one public benchmark/demo app that proves the end-to-end model

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

### 3. Connector-aware views

Purpose:

- expose connector state and connector-derived provenance directly in the UI

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
- choose **Multi-app DAG orchestration** if the next need is one orchestrated
  workflow that spans several apps with explicit dependencies
- choose **Global orchestrated pipeline DAG** if the next need is to expose that
  orchestration as a single product-visible graph in `PIPELINE`
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

- Run manifest + evidence bundle
- Promotion / release decision workflow
- First-proof wizard in product
- Compatibility matrix automation
- Connector registry hardening
- Multi-app DAG orchestration
- Global orchestrated pipeline DAG
- Bidirectional notebook interop
- Data connector facility
- First-class reduce contract
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
