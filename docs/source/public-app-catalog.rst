Public app catalog
==================

This catalog maps the public AGILAB app names users see in PROJECT to the
package or source status behind them. It is intentionally more exhaustive than
the README: the README stays focused on the shortest adoption path, while this
page is the reference for choosing an app.

Status legend:

- ``PyPI app package``: promoted by the current release plan and installable as
  a standalone ``agi-app-*`` payload.
- ``Release artifact``: built as an app payload artifact, but not currently
  promoted to PyPI by the release plan.
- ``Source built-in``: present in the public source checkout for development,
  examples, or compatibility, without a separate promoted payload package.

.. list-table::
   :header-rows: 1
   :widths: 24 26 18 32

   * - Project
     - Package
     - Status
     - When to use it
   * - ``flight_telemetry_project``
     - ``agi-app-flight-telemetry``
     - PyPI app package
     - First proof and compact end-to-end data ingestion with map/network
       analysis; also the real-world worker-only Cython example for a
       haversine speed kernel with reducer evidence.
   * - ``weather_forecast_project``
     - ``agi-app-weather-forecast``
     - PyPI app package
     - Notebook-to-app migration using a small weather forecast dataset,
       forecast metrics, and promotion evidence.
   * - ``sklearn_pipeline_project``
     - ``agi-app-sklearn-pipeline``
     - PyPI app package
     - Minimal classic ML app proof using scikit-learn: deterministic dataset,
       fitted pipeline, serialized model, predictions, metrics, and artifact
       hashes.
   * - ``mission_decision_project``
     - ``agi-app-mission-decision``
     - PyPI app package
     - Deterministic mission-decision evidence with scenario scoring,
       re-planning, and decision artifacts.
   * - ``execution_pandas_project``
     - ``agi-app-pandas-execution``
     - PyPI app package
     - Cython worker speedup demo for the Pandas path: typed contiguous
       ``float64`` kernel, Python/Cython runtime evidence, and reducer
       evidence.
   * - ``execution_polars_project``
     - ``agi-app-polars-execution``
     - PyPI app package
     - Synthetic worker execution playground for the Polars path, comparable
       with the Pandas app.
   * - ``multi_app_dag_project``
     - ``agi-app-multi-dag``
     - PyPI app package
     - Cross-app DAG template preview and artifact-handoff contract review.
   * - ``pytorch_playground_project``
     - ``agi-app-pytorch-playground``
     - PyPI app package
     - Reproducible PyTorch classifier playground with persisted controls and
       evidence artifacts.
   * - ``r_runtime_bridge_project``
     - None
     - Source built-in
     - Narrow R stage runtime proof: AGILAB stays the Python orchestrator while
       a worker executes ``Rscript`` through JSON input/output, captured logs,
       artifact directories, manifest hashes, and reducer evidence.
   * - ``tescia_diagnostic_project``
     - ``agi-app-tescia-diagnostic``
     - PyPI app package
     - Evidence-scored diagnostic and self-evaluation cases with 2026 math
       coverage, classroom batch intake, live teacher dashboard artifacts,
       better-fix selection, and regression-plan evidence.
   * - ``uav_relay_queue_project``
     - ``agi-app-uav-relay-queue``
     - PyPI app package
     - Compact UAV relay queue scenario with relay-health, scenario-cockpit,
       and network-map analysis.
   * - ``uav_queue_project``
     - ``agi-app-uav-queue``
     - Release artifact
     - Queue-policy proof generator and scenario-cockpit evidence source used
       by the advanced proof pack.
   * - ``minimal_app_project``
     - None
     - Source built-in
     - Minimal app structure reference for adapting manager, worker, settings,
       and app argument form code.
   * - ``weather_forecast_legacy_project``
     - None
     - Source built-in
     - Source-checkout weather migration reference kept beside the packaged
       ``weather_forecast_project`` path.

Recommended first choices
-------------------------

- Start with ``flight_telemetry_project`` when you want the shortest proof that
  AGILAB can install, execute, write evidence, and open analysis.
- Use ``weather_forecast_project`` when the question is notebook migration and
  reusable forecast artifacts.
- Use ``sklearn_pipeline_project`` when the question is classic ML
  reproducibility with a familiar scikit-learn pipeline.
- Use ``pytorch_playground_project`` when you want a more visual AI/ML demo
  with training evidence.
- Use ``uav_relay_queue_project`` or ``uav_queue_project`` only after the first
  proof, because they are better suited to advanced evidence and scenario
  comparison.

Package truth source
--------------------

The PyPI publication status comes from the generated release plan and the
package split contract, not from this page by hand. If the release plan changes,
update this catalog in the same documentation pass.

See also:

- :doc:`package-publishing-policy` for the package split and trusted publisher
  contract.
- :doc:`advanced-proof-pack` for the heavier evidence scenarios.
- :doc:`execution-playground` for the Pandas/Polars execution comparison.
