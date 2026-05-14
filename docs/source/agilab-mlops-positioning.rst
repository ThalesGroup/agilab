AGILab in the MLOps Toolchain
=============================

AGILab focuses on the early experimentation phase of AI projects—roughly
Technology Readiness Level 3 (TRL‑3), where teams validate concepts, explore
algorithms, and collaborate on data preparation. This page explains how AGILab
fits alongside the broader MLOps landscape.

This page is about positioning, not the detailed feature list or the roadmap.

- For current shipped capabilities, see :doc:`features`.
- For planned work, see :doc:`roadmap/agilab-future-work`.
- For the public strategic scorecard and score movement rule, see
  :doc:`strategic-potential`.

Executive review summary
------------------------

AGILab is best evaluated as an AI/ML experimentation workbench, not as
a production MLOps replacement. Its practical value is keeping project
setup, environment management, execution, and result analysis on one
coherent path.

For research teams, engineering labs, and prototype-heavy AI workflows,
AGILab is worth evaluating when fragmented notebooks, scripts,
environments, and dashboards are slowing iteration. For production model
serving, enterprise governance and audit, online monitoring, drift
detection, or large-scale operational deployment, it should still be
treated as early-stage tooling and paired with a hardened production
stack.

MLflow strategy
---------------

AGILab should not be positioned as an alternative experiment tracker, a second
model registry, or a replacement run format. MLflow remains the system of
record for runs, parameters, metrics, artifacts, models, and registry state.
AGILab adds the industrial execution context around that record: managed
environments, worker packaging, distributed execution, project structure,
dataset and artifact paths, and reproducibility metadata.

The intended split is simple:

- **AGILab owns execution**: environments, workers, clusters, packaging,
  reproducibility, and operator workflows.
- **MLflow owns memory**: tracking, artifacts, model registry, versions, and
  deployment aliases.

In code, AGILab uses a small tracker facade such as
``tracker.log_metric(...)`` and ``tracker.log_artifact(...)``. The default
backend is MLflow, so normal AGILab execution can track automatically without
asking users to hand-write MLflow boilerplate in every snippet or worker.

Best fit and limits
-------------------

.. list-table:: Best fit and limits
   :widths: 35 65
   :header-rows: 1

   * - Use case
     - Fit
   * - Industrial AI prototypes
     - Strong fit when the team needs a reproducible path from setup to
       execution and analysis.
   * - Simulation-heavy engineering workflows
     - Strong fit when experiments need managed environments, worker
       execution, and operator-facing results.
   * - Internal AI/ML labs
     - Strong fit when controlled pilots matter more than hardened
       production deployment.
   * - Notebook-to-application workflow consolidation
     - Strong fit when exploration needs to become a replayable app-shaped
       workflow.
   * - Production model serving
     - Weak fit; use deployment-focused serving infrastructure.
   * - Enterprise governance and audit
     - Weak fit; keep compliance, audit, and retraining policy in the
       production governance stack.
   * - Large-scale cloud-native MLOps
     - Weak to moderate fit; AGILab can help before handoff, not replace the
       full platform.

Research experimentation evidence
---------------------------------

AGILab's research experimentation value is strongest when teams need to turn
interactive exploration into a replayable, inspectable workflow:

- ``lab_stages.toml`` records experiment stages, prompts, selected model, runtime,
  and execution metadata
- supervisor notebook export keeps the saved pipeline runnable outside the UI
- the notebook-to-pipeline import report reads a checked-in ``.ipynb`` and
  preserves markdown context, code cells, import hints, execution-count
  metadata, artifact references, and richer ``lab_stages.toml`` preview output
  as ``not_executed_import`` pipeline-stage evidence
- the notebook round-trip report validates ``lab_stages.toml -> supervisor
  notebook -> import -> lab_stages preview`` so saved stage fields survive the
  non-executing bridge in both directions
- the notebook union-environment report allows a ``single-kernel union
  notebook`` only for compatible stages and keeps mixed-runtime pipelines on the
  supervisor notebook path
- the data connector facility report validates first-class SQL, OpenSearch,
  and object-storage connector definitions without opening live network
  connections; see :doc:`data-connectors` for supported provider names,
  credential references, and runtime dependency boundaries
- the data connector resolution report validates connector-aware app/page
  resolution and keeps ``legacy_path_fallback`` rows available during migration
- the data connector health report plans opt-in connector health/status probes
  without executing network checks in public evidence
- the data connector health actions report exposes operator-triggered health
  probes while keeping public evidence network-free
- the data connector runtime adapters report binds credentialed connector
  adapters to runtime operations without materializing secrets in public
  evidence
- the data connector UI preview report renders connector state and
  connector-derived provenance as static JSON+HTML evidence
- the data connector live UI report wires connector state and
  connector-derived provenance into the Release Decision Streamlit page without
  running connector probes
- the data connector app catalogs report validates app-local connector catalogs
  for every non-template built-in app while preserving legacy path fallbacks
- MLflow tracking records one parent run and nested runs for executed stages
- the notebook-migration example shows how exploratory notebooks become reusable
  AGILab projects with stable artifacts and analysis views
- the initial first-class reduce contract in ``agi_node`` defines partial
  inputs, reducer merge semantics, and a standard reduce artefact schema
- ``execution_pandas_project`` and ``execution_polars_project`` emit named
  benchmark reduce artefacts through that shared contract,
  ``flight_telemetry_project`` emits trajectory-summary reduce artefacts,
  ``weather_forecast_project`` emits forecast-metrics reduce artefacts, and
  ``uav_queue_project`` plus ``uav_relay_queue_project`` emit the same
  ``reduce_summary_worker_<id>.json`` artifact shape for queue metrics
- the Release Decision evidence view surfaces those reducer artefacts,
  including flight row/aircraft/speed fields, weather forecast MAE/RMSE/MAPE
  fields, and UAV queue-family packet/PDR fields, and flags invalid reduce JSON
  without hiding the rest of the evidence page
- a repository guardrail requires every non-template built-in app to expose a
  reducer contract, while ``mycode_project`` and ``global_dag_project`` are
  explicitly template-only until a clone or concrete worker flow adds merge
  outputs
- the public reducer benchmark validates 8 partials / 80,000 synthetic items in
  ``0.003s`` against a ``5.0s`` target

That supports a ``Research experimentation`` score of ``4.0 / 5``. The compact
KPI evidence bundle now reports both the reducer adoption guardrail and the
first-proof ``run_manifest.json`` contract, and the release-decision view
consumes that manifest as promotion evidence; broader fresh-machine
reproducibility remains roadmap work. The remaining reducer rule is maintenance
discipline: future apps/templates must opt in when they produce concrete merge
outputs.

Engineering prototyping evidence
--------------------------------

AGILab's engineering prototyping value is strongest when a team needs to move
from a working idea to an app-shaped prototype without losing the experiment
history:

- app templates and isolated app/page environments keep prototypes reproducible
- ``lab_stages.toml`` and supervisor notebook export preserve the working
  sequence
- the notebook-to-pipeline import contract proves the reverse direction by
  turning code cells into pipeline-stage metadata and markdown cells into linked
  context blocks, then feeds the existing ``WORKFLOW`` upload path without
  running the notebook
- the notebook round-trip report checks that supervisor export metadata can be
  re-imported into ``lab_stages.toml`` preview fields without losing D/Q/M/C/R
  stage values
- the notebook union-environment report makes the single-kernel shortcut
  explicit and prevents mixed environments from being flattened accidentally
- the data connector facility report gives prototypes a plain-text connector
  catalog for external data systems while keeping credentials in environment
  references; the current object-storage contract covers AWS S3/S3-compatible
  stores, Azure Blob Storage, and Google Cloud Storage
- connector-aware app/page resolution lets prototypes reference those
  connectors from app settings without dropping legacy raw path fallbacks
- opt-in connector health planning gives prototypes a status boundary without
  claiming live connectivity in static public evidence
- operator-triggered health actions make the opt-in boundary actionable without
  executing connector probes in public evidence
- runtime connector adapter bindings define where SQL, OpenSearch, and
  object-storage probes execute once an operator supplies runtime credentials
- static connector UI preview makes connector cards, page bindings, legacy
  fallbacks, and probe boundaries reviewable before live UI integration
- Release Decision connector live UI integration makes the same connector
  provenance visible in an operator-facing page while keeping health probes
  opt-in
- app-local connector catalogs let mature built-in apps move connector
  definitions next to their ``app_settings.toml`` files
- conceptual ``pipeline_view`` files make the workflow readable outside the code
- analysis-page templates turn produced artifacts into a reusable operator view
- the in-product first-proof wizard now guides one validated ``flight_telemetry_project``
  source-checkout path, reads ``run_manifest.json``, and shows
  manifest-driven remediation with exact evidence commands
- the run-diff evidence report compares static baseline/candidate KPI checks,
  run manifests, and artifact rows, then emits counterfactual prompts without
  executing commands or network probes
- the CI artifact harvest report maps external-machine evidence attachments to
  a release status with SHA-256 and provenance checks without querying live CI
  providers
- Release Decision can import that ``ci_artifact_harvest.json`` output, display
  checksum/provenance rows, block invalid harvests, and export the harvest
  summary with ``promotion_decision.json``
- the multi-app DAG contract validates a first cross-app handoff from
  ``uav_queue_project`` to ``uav_relay_queue_project`` through
  ``tools/multi_app_dag_report.py --compact`` and the checked-in
  ``multi_app_dag_sample.json``
- the supplemental ``multi_app_dag_portfolio_sample.json`` expands the contract
  sample suite across flight, weather forecast, pandas execution, and polars
  execution apps without changing the executable UAV smoke baseline
- the global pipeline DAG report combines that handoff with each app-local
  ``pipeline_view.dot`` so reviewers can inspect one read-only product graph
  before runner and UI orchestration are claimed
- the global DAG execution plan report turns that product graph into ordered
  ``pending/not_executed`` runnable units with artifact dependencies and
  provenance, while still avoiding any app dispatch
- the global DAG runner state report projects that plan into read-only
  ``runnable/blocked`` dispatch state, retry and partial-rerun metadata, and
  operator-facing readiness messages without starting the apps
- the global DAG dispatch state report persists the first queue-to-relay
  state transition proof, records ``queue_baseline`` completion,
  ``queue_metrics`` availability, ``relay_followup`` unblocking, timestamps,
  retry counters, partial-rerun flags, operator messages, and provenance
  without claiming real app execution
- the global DAG app dispatch smoke report executes real ``queue_baseline`` and
  ``relay_followup`` app entries through ``uav_queue_project`` and
  ``uav_relay_queue_project``, persists ``queue_metrics``, ``relay_metrics``,
  and reducer artifacts into dispatch-state JSON, and stops short of claiming
  live operator UI
- the global DAG operator state report projects that persisted full-DAG state
  into operator-visible completed unit state, available artifact handoffs, and
  retry/partial-rerun action rows while still avoiding live UI claims
- the global DAG dependency view report turns that operator-state proof into
  cross-app upstream/downstream adjacency, the ``queue_baseline ->
  relay_followup`` ``queue_metrics`` edge, and artifact-flow rows without
  claiming live UI rendering
- the global DAG live state updates report turns the dependency view into
  ordered graph, unit, artifact, dependency, and action refresh payloads without
  claiming a runtime streaming service
- the global DAG operator actions report executes retry and partial-rerun
  operator requests through real queue and relay app-entry replays, then
  persists action outcomes and output artifacts without claiming UI controls
- the global DAG operator UI report renders persisted state into reusable
  status, unit-card, dependency, timeline, action-control, and artifact
  components with a static HTML proof

That supports an ``Engineering prototyping`` score of ``4.0 / 5``. It is not
scored higher yet because additional external replication and future
app/template reducer adoption remain maintenance discipline when new concrete
merge outputs appear.

Production readiness evidence
-----------------------------

AGILab's production-readiness story is strongest when it is judged as a
controlled pilot and handoff workbench, not as a production MLOps platform:

- release preflight tooling and workflow-parity profiles give maintainers local
  checks before packaging or publishing
- CI and component coverage workflows keep the public repository observable
- the compatibility matrix marks which public paths are validated versus only
  documented
- service health gates expose JSON and Prometheus-compatible operator checks
- the release-decision page gates on the first-proof ``run_manifest.json``,
  resolves artifact/log/export roots through the shared connector path registry,
  imports external manifest evidence, applies artifact and KPI gates, and
  exports ``promotion_decision.json`` plus ``manifest_index.json`` with connector
  registry paths, manifest summary, import summary, provenance-tagged attachment
  metadata, per-release evidence history, cross-release manifest comparison,
  cross-run evidence bundle comparison, and gate details
- the standalone run-diff/counterfactual report gives those comparison claims a
  no-execution JSON contract suitable for public evidence review
- the CI artifact harvest report gives external-machine replication a
  contract-only attachment model for manifest, KPI, compatibility, and
  promotion-decision evidence, and Release Decision can consume that model as
  promotion evidence
- ``SECURITY.md`` documents supported versions, disclosure expectations, and a
  deployment hardening checklist

That supports a ``Production readiness`` score of ``3.0 / 5``. It is not scored
higher because AGILab still does not provide production model serving, feature
stores, online monitoring, drift detection, enterprise governance, or broad
remote-topology certification.

Strategic potential evidence
----------------------------

AGILab's strategic potential is strongest where teams need a repeatable bridge
between research experiments and engineering validation:

- a clear TRL‑3 experimentation focus instead of an overclaimed production MLOps
  scope
- a public demo path and a guided, measurable local first-proof path
- a handoff model for stabilized assets into MLflow, Kubeflow, or internal
  deployment stacks
- a first multi-app DAG contract/report baseline that makes cross-app artifact
  handoffs explicit before runner integration
- a supplemental multi-app DAG portfolio sample that validates broader app
  coverage before live runner hardening
- a read-only global pipeline DAG report that ties app-local pipeline views to
  the cross-app handoff contract
- a runner-facing execution-plan report that defines dependency state before
  real dispatch is introduced
- a two-unit app dispatch smoke that executes ``queue_baseline`` and
  ``relay_followup`` for real while keeping live UI orchestration separate
- an operator-state report that exposes completed units, handoffs, and
  retry/partial-rerun actions before UI components are added
- a dependency-view report that makes the cross-app upstream/downstream
  relationship explicit before live UI rendering is added
- a live-update payload report that defines the operator refresh stream before
  UI components or runtime transport are added
- an operator-action execution report that proves retry and partial-rerun
  requests can replay the real app entries before UI controls are added
- an operator-UI report that makes the persisted state and supported actions
  renderable as reusable components
- a notebook-to-pipeline import report and ``WORKFLOW`` upload integration that
  close the first reverse-notebook bridge while preserving the non-execution
  boundary
- a notebook round-trip report that validates the first bidirectional
  ``lab_stages.toml`` and supervisor-notebook preservation path
- a notebook union-environment report that makes compatible single-kernel
  notebooks possible without weakening the supervisor fallback boundary
- a data connector facility report that starts the practical external-data
  access layer with SQL, OpenSearch, and object-storage targets
- a data connector resolution report that proves app/page connector references
  resolve against the catalog while preserving legacy path migration fallback
- a data connector health report that plans operator-gated connector probes
  without opening networks in public evidence
- a data connector health actions report that turns those planned probes into
  operator-trigger rows
- a data connector runtime adapters report that binds connector definitions to
  runtime operations and credential-deferral metadata
- a data connector UI preview report that turns connector provenance into a
  static review artifact
- a data connector live UI report that proves Release Decision renders that
  connector provenance through reusable Streamlit components
- a data connector app catalogs report that proves connector definitions can
  live with built-in apps instead of only in global samples
- a run-diff/counterfactual evidence report that turns baseline/candidate
  check, manifest, and artifact deltas into reviewable prompts
- a CI artifact harvest report that turns external-machine evidence attachments
  into validated release-status inputs
- Release Decision import/export support for those harvested attachment rows
- a roadmap ordered around run evidence, promotion decisions, compatibility
  automation, and cross-app orchestration

That supports a ``Strategic potential`` score of ``4.2 / 5``. It is not scored
higher yet because future app/template reducer adoption discipline and broader
fresh-install validation are still roadmap work. The public scorecard in
:doc:`strategic-potential` defines the evidence required before maintainers
should move that score to ``4.3 / 5`` or higher.

Together, the current public category scores round to an overall public
evaluation of ``3.8 / 5``. This is a compact experimentation-workbench snapshot,
not a production MLOps certification.

Where AGILab helps
------------------

- **Rapid experimentation**: one workspace for selecting a project, running it,
  and inspecting outputs.
- **Managed execution without heavy platform setup**: local and distributed
  execution stay accessible to small teams before they commit to a larger
  platform stack.
- **Application-oriented workflows**: AGILab is stronger when the problem is an
  end-to-end engineering workflow, not only a scheduler or a pipeline library.
- **Lower operational overhead during experimentation**: useful work can happen
  before a team invests in production-serving, governance, or platform-heavy
  tooling.
- **Controlled pilot handoff**: release preflight checks, compatibility
  evidence, service health gates, and promotion-decision exports make it easier
  to decide when an experiment is ready to leave AGILab for a hardened
  production stack.

What AGILab does *not* aim to cover
-----------------------------------

- **Production deployment** (TRL‑6+): model serving, CI/CD, feature stores,
  online monitoring, or model drift detection belong to the deployment-focused
  side of MLOps (tools such as Kubeflow, MLflow Serving, Sagemaker, etc.).
- **Enterprise governance**: compliance workflows, audit trails, or retraining
  policies are intentionally out of scope. AGILab’s strength is rapid iteration
  before promoting assets to hardened pipelines.

Positioning vs. other tools
---------------------------

.. list-table:: Positioning vs. other tools
   :widths: 20 40 40
   :header-rows: 1

   * - Phase
     - AGILab focus
     - Examples of complementary tools
   * - Ideation / TRL‑2
     - Not covered (use notebooks, small prototypes)
     - Whiteboards, notebooks, lightweight sandboxes
   * - Experimentation / TRL‑3
     - **Primary target** – templated projects, cluster automation
     - AGILab + data catalogues + experiment trackers
   * - Validation / TRL‑4
     - Hand off to deployment-stack as soon as requirements stabilise
     - MLflow, Weights & Biases, Seldon, Kubeflow
   * - Deployment / TRL‑6+
     - Out of scope
     - CI/CD, serving frameworks, APM, feature stores

Framework comparison
--------------------

The comparison below stays deliberately practical and avoids a wide table so it
renders cleanly on narrower viewports.

.. rubric:: AGILab

- **Primary centre of gravity**: integrated experimentation and execution
  workspace spanning managed environments, distributed workers, pipeline
  replay, service health, and analysis pages.
- **Best fit**: engineering or research teams that want one product to cover
  setup, execution, validation, and operator-facing workflows during the
  experimentation phase.
- **Positioning note**: strongest when the problem is not only defining a
  pipeline, but also operating reusable application workflows with managed
  runtimes, a lower operational footprint for experimentation, and a
  consistent UI/CLI control path.

.. rubric:: Kedro

- **Primary centre of gravity**: code-first data/ML pipeline engineering with
  modular pipelines, a data catalog, hooks, runners, and Kedro-Viz.
- **Best fit**: teams that want a structured Python project for reproducible
  pipelines and plan to plug orchestration and infrastructure in around it.
- **Positioning note**: AGILab is less about a pipeline framework in isolation
  and more about a single operator-facing workspace: install, distribute, run,
  pipeline replay, MLflow-traced execution, and analysis in one product.

.. rubric:: Dagster

- **Primary centre of gravity**: asset-centric orchestration with integrated
  lineage, observability, automation, and testing.
- **Best fit**: data platform teams treating orchestration and asset health as
  the backbone of the platform.
- **Positioning note**: AGILab is earlier-phase and more experiment-centric. It
  provides managed runtimes, domain apps, and researcher/operator workflows
  rather than a full asset-orchestration control plane.

.. rubric:: Prefect

- **Primary centre of gravity**: Python-native orchestration of flows, tasks,
  deployments, and dynamic execution patterns.
- **Best fit**: teams that want orchestration logic to stay close to normal
  Python code with lightweight deployment options.
- **Positioning note**: AGILab wraps more of the surrounding lifecycle directly
  in the product: environment bootstrapping, worker packaging, distribution
  planning, service mode, and analysis pages.

.. rubric:: Metaflow

- **Primary centre of gravity**: human-friendly Python library for taking data
  science workflows from local prototyping to scaled and production
  deployments.
- **Best fit**: data science teams that want a unified Python API across local,
  scaled, and production-style execution.
- **Positioning note**: AGILab is more UI- and operations-oriented. It
  emphasizes guided orchestration, explicit app packaging, and shared operator
  flows over a single Python library abstraction.

.. rubric:: Airflow

- **Primary centre of gravity**: batch workflow scheduling, monitoring, and
  broad system integration via DAGs, operators, hooks, and the web UI.
- **Best fit**: platform or data engineering teams running recurring,
  scheduled, batch-oriented pipelines across many external systems.
- **Positioning note**: modern Airflow already supports dynamic task mapping
  and dynamic DAG generation, so it remains stronger when the core need is
  task-level orchestration semantics inside a scheduler-first platform.
  AGILab can express dynamic behavior inside generated or custom Python stages,
  but it does not yet expose the same kind of first-class runtime pipeline-stage
  expansion in **WORKFLOW**. Its strength is elsewhere: experiment packaging,
  managed execution environments, distributed research workloads, and
  app-centric user workflows.

Selection guide
---------------

- Choose **AGILab** when you want one environment to cover setup, execution,
  service health, pipeline replay, and analysis for engineering or research
  applications.
- Choose **Kedro** when the main need is a clean, code-first pipeline project
  structure with modular reusable pipelines and a data catalog.
- Choose **Dagster** when orchestration, lineage, observability, and asset
  automation are the platform itself.
- Choose **Prefect** when you want dynamic Python orchestration with lighter
  ceremony around flows, tasks, and deployments.
- Choose **Metaflow** when the team prefers a single Python library that grows
  from notebook-era prototyping toward scaled and production execution.
- Choose **Airflow** when the problem is recurring batch scheduling and broad
  integration across external systems, especially if you need native
  scheduler-level dynamic task expansion rather than an experimentation
  workbench.

In practice, AGILab often complements these tools rather than replacing them:
teams can use AGILab during the experimentation and validation phase, then hand
off stabilized assets to a broader orchestration or production platform.

Suggested workflow
------------------

This is a handoff sketch, not a roadmap.

1. Use AGILab to prototype algorithms, reuse app templates, and validate data
   processing. Capture execution history through AGILab run logs and
   MLflow-backed tracking runs.
2. Once an approach stabilises, prepare the project artefacts for your target
   environment and integrate it with your organisation’s deployment toolchain
   (MLflow, Kubeflow, internal devops stack). In a source checkout, this commonly
   uses ``tools/run_configs`` and ``src/agilab/apps/<app>``; in packaged
   installs, use the generated app package artifacts available from your installer.
3. Track long-running metrics and governance artifacts using your preferred
   MLOps platform; AGILab does not replace those systems.

See also
--------

- :doc:`features` for the current capability list.
- :doc:`roadmap/agilab-future-work` for planned work.
- :doc:`architecture` for the full stack overview.
- :doc:`framework-api` for automation hooks (``AGI.run``, ``AGI.install``).
- :doc:`introduction` for background and terminology around TRL and AGI use
  cases.
