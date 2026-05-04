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
   * - ``data_io_2026_project``
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
       ``view_uav_queue_analysis``, ``view_uav_relay_queue_analysis``, or
       ``view_maps_network``.
   * - ``inter_project_dag`` packaged preview
     - App-to-app artifact handoff without private infrastructure: one app
       produces an explicit artifact contract that another app can consume.
     - Run ``src/agilab/examples/inter_project_dag/preview_inter_project_dag.py``.
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

Recommended order
-----------------

Run these in this order when you need a compact but convincing evaluation pass:

1. **Mission decision**: ``data_io_2026_project``. This is the best product
   story because it shows an input-to-decision workflow, not only a data
   transform.
2. **Execution credibility**: :doc:`execution-playground`. This is the best
   technical story because it separates Pandas, Polars, pool, Dask, and Cython
   effects. The Cython proof is kernel-scoped and records its dtype contract.
3. **Network analysis**: ``uav_relay_queue_project``. This is the best visual
   story because the same run can feed queue analysis and generic network maps.
4. **Operator path**: :doc:`service-mode` plus ``service_mode`` preview. This
   is the best operations story because it shows persistent workers and health
   thresholds without hiding lifecycle actions.
5. **Trust close-out**: :doc:`release-proof`. This is the best ending slide
   because it ties demo claims back to release, CI, package, and docs evidence.

How to demo it
--------------

Keep the story bounded. Do not switch apps randomly. Use one of these lanes:

**Decision lane**
  ``data_io_2026_project`` -> ``ORCHESTRATE`` -> ``ANALYSIS`` ->
  ``view_data_io_decision``. Stop when the selected strategy, re-plan event,
  decision deltas, and exported artifacts are visible.

**Performance lane**
  :doc:`execution-playground`. Stop when the viewer understands that ``pool`` is
  AGILAB's external local fan-out, Pandas can benefit from process fan-out, and
  Polars may not because it already owns native internal parallelism.

**Network lane**
  ``uav_relay_queue_project`` -> ``ORCHESTRATE`` -> ``ANALYSIS`` ->
  ``view_uav_relay_queue_analysis`` plus ``view_maps_network``. Stop when queue
  buildup, relay choice, drops, topology, and trajectories are visible from the
  same run artifacts.

**Operator lane**
  ``service_mode`` preview and :doc:`service-health-schema`. Stop when the
  lifecycle and health thresholds are explicit. Do not claim production service
  certification from the preview.

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

Related pages
-------------

- :doc:`demos`
- :doc:`agilab-demo`
- :doc:`execution-playground`
- :doc:`data-connectors`
- :doc:`service-mode`
- :doc:`release-proof`
- :doc:`compatibility-matrix`
