Advanced Proof Pack
===================

Use this route after the lightweight hosted demo or the local first proof.
It surfaces stronger AGILAB capabilities that are already packaged but are too
deep for the default Hugging Face first-run path.

The goal is not to make the first demo longer. The goal is to keep the newcomer
path clean while giving evaluators a second pack that proves richer behavior:
mission decisions, execution-model benchmarks, network simulations, service
health, app-to-app contracts, connector contracts, and release evidence.

What belongs here
-----------------

.. list-table::
   :header-rows: 1
   :widths: 24 34 42

   * - Proof route
     - What it proves
     - Where to start
   * - ``mission_decision_project``
     - Deterministic mission-data decision loop: ingest evidence, score routes,
       inject an event, re-plan, and export a decision bundle.
     - Select the built-in app, run ``ORCHESTRATE``, then open
       ``view_data_io_decision``.
   * - ``execution_pandas_project`` / ``execution_polars_project``
     - Execution-model benchmarking: AGILAB pool/Dask/Cython choices are
       measured separately from dataframe-library choice.
     - Use :doc:`execution-playground`.
   * - ``uav_queue_project`` / ``uav_relay_queue_project``
     - Network-style experiment analysis: queue buildup, packet drops, routing
       policy changes, topology, trajectories, and generic network map views.
     - Select the built-in app, run it, then open
       ``view_scenario_cockpit``, ``view_queue_resilience``,
       ``view_relay_resilience``, or ``view_maps_network``.
   * - ``inter_project_dag`` packaged preview
     - App-to-app artifact handoff without private infrastructure: one app
       produces an explicit artifact contract that another app can consume.
     - Run ``src/agilab/examples/inter_project_dag/preview_inter_project_dag.py``.
   * - ``mlflow_auto_tracking`` packaged preview
     - Optional experiment memory: AGILAB writes local evidence first, then logs
       params, metrics, and artifacts through MLflow when the backend is present.
     - Run ``src/agilab/examples/mlflow_auto_tracking/preview_mlflow_auto_tracking.py``.
   * - ``resilience_failure_injection`` packaged preview
     - Resilience comparison: inject one relay degradation event, then compare
       fixed, replanned, search-based, and active-policy responses on the same
       scenario contract.
     - Run ``src/agilab/examples/resilience_failure_injection/preview_resilience_failure_injection.py``.
   * - ``train_then_serve`` packaged preview
     - Service handoff: freeze the trained-policy artifact path, IO contract,
       prediction sample, and health gate before a serving stack is started.
     - Run ``src/agilab/examples/train_then_serve/preview_train_then_serve.py``.
   * - ``service_mode`` packaged preview
     - Persistent worker lifecycle and health gates: start, status, health,
       and stop are presented as explicit operator actions.
     - Run ``src/agilab/examples/service_mode/preview_service_mode.py`` and see
       :doc:`service-mode`.
   * - Data connector reports
     - Connector catalogs, local/cloud/search endpoint shapes, health planning,
       and credential-safe resolution reports without requiring live secrets.
     - See :doc:`data-connectors`.
   * - Release proof
     - Public trust evidence: PyPI package, GitHub release, CI guardrails,
       docs-source integrity, and hosted-demo evidence in one page.
     - See :doc:`release-proof`.
   * - Optional SB3 industrial optimization examples
     - Advanced app-repository routes for active mesh optimization, MLflow
       auto-tracking, multi-app DAGs, resilience/failure injection, and
       train-then-serve policy contracts.
     - See :doc:`industrial-optimization-examples` when
       ``sb3_trainer_project`` is installed.

Recommended order
-----------------

Run these in this order when you need a compact but convincing evaluation pass:

1. **Mission decision**: ``mission_decision_project``. This is the best product
   story because it shows an input-to-decision workflow, not only a data
   transform.
2. **Execution credibility**: :doc:`execution-playground`. This is the best
   technical story because it separates Pandas, Polars, pool, Dask, and Cython
   effects. The Cython proof is kernel-scoped and records its dtype contract.
3. **Network analysis**: ``uav_relay_queue_project``. This is the best visual
   story because the same run can feed queue analysis and generic network maps.
4. **Tracking memory**: ``mlflow_auto_tracking`` preview. This is the best
   MLOps story because AGILAB keeps execution evidence local and uses MLflow as
   the optional system of record instead of competing with it.
5. **Resilience comparison**: ``resilience_failure_injection`` preview. This is
   the best strategy-comparison story because fixed, ILP-style, GA-style, and
   PPO-style responses are scored against one injected event.
6. **Service handoff**: ``train_then_serve`` preview. This is the best
   prototype-to-operations story because the model artifact, IO contract,
   prediction sample, and health gate are explicit before a service is started.
7. **Operator path**: :doc:`service-mode` plus ``service_mode`` preview. This
   is the best operations story because it shows persistent workers and health
   thresholds without hiding lifecycle actions.
8. **Trust close-out**: :doc:`release-proof`. This is the best ending slide
   because it ties demo claims back to release, CI, package, and docs evidence.

How to demo it
--------------

Keep the story bounded. Do not switch apps randomly. Use one of these lanes:

**Decision lane**
  ``mission_decision_project`` -> ``ORCHESTRATE`` -> ``ANALYSIS`` ->
  ``view_data_io_decision``. Stop when the selected strategy, re-plan event,
  decision deltas, and exported artifacts are visible.

**Performance lane**
  :doc:`execution-playground`. Stop when the viewer understands that ``pool`` is
  AGILAB's external local fan-out, Pandas can benefit from process fan-out, and
  Polars may not because it already owns native internal parallelism.

**Network lane**
  ``uav_relay_queue_project`` -> ``ORCHESTRATE`` -> ``ANALYSIS`` ->
  ``view_scenario_cockpit`` -> ``view_relay_resilience`` plus
  ``view_maps_network``. Stop when the baseline/candidate evidence bundle,
  queue buildup, relay choice, drops, topology, and trajectories are visible
  from the same run artifacts.

**Operator lane**
  ``service_mode`` preview and :doc:`service-health-schema`. Stop when the
  lifecycle and health thresholds are explicit. Do not claim production service
  certification from the preview.

**Tracking lane**
  ``mlflow_auto_tracking`` preview. Stop when the local evidence bundle and the
  tracking status show the same params, metrics, and artifact path. If MLflow is
  not installed, the expected status is ``skipped`` with an installation hint.

**Resilience lane**
  ``resilience_failure_injection`` preview. Stop when the fixed route degrades,
  the post-failure route ranking is explicit, and the adaptive response wins
  without implying a certified MARL benchmark.

**Train-then-serve lane**
  ``train_then_serve`` preview. Stop when the service contract, prediction
  sample, and health payload are written without implying that AGILAB is a
  production serving platform.

**Industrial optimization lane**
  :doc:`industrial-optimization-examples`. Stop when the reviewer can see the
  active-mesh or queue-routing artifact contract, optional MLflow tracking
  status, resilience comparison, or service contract without confusing those
  examples with the default hosted first proof.

What not to claim
-----------------

- Do not present the Advanced Proof Pack as the default hosted demo.
- Do not claim live cloud validation unless the compatibility matrix says that
  route is validated.
- Do not claim Cython end-to-end speedup from the kernel-only benchmark; the
  full run still includes IO, grouping, artifacts, startup, and orchestration.
- Do not claim Polars should always benefit from AGILAB pool mode.
  Polars already manages native internal parallelism.
- Do not claim the UAV examples are full research simulators. They are compact
  public scenarios shaped to prove AGILAB workflow value.
- Do not claim the Active Mesh Optimization example is full decentralized
  MARL. It is a compact centralized-policy route that makes the agent/action
  contract visible for later hardening.
- Do not present ``mlflow_auto_tracking`` as an AGILAB model registry. It is an
  adapter proof that keeps MLflow as the tracking and registry system when used.

Related pages
-------------

- :doc:`demos`
- :doc:`agilab-demo`
- :doc:`execution-playground`
- :doc:`data-connectors`
- :doc:`industrial-optimization-examples`
- :doc:`service-mode`
- :doc:`release-proof`
- :doc:`compatibility-matrix`
