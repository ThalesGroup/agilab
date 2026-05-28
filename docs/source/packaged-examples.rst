Packaged Examples
=================

AGILAB ships small public examples that teach one workflow at a time. Some
examples install and run a built-in app through ``AGI_*`` helper scripts. Other
examples are read-only previews that write deterministic evidence without
starting workers, services, or private integrations.

This page is the Packaged example catalog for public examples.

Use the source catalog as the executable index:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python -m py_compile $(find src/agilab/examples -name '*.py' -print)

Learning path
-------------

.. list-table::
   :header-rows: 1
   :widths: 24 32 44

   * - Example
     - Class
     - Main lesson
   * - ``flight_telemetry``
     - Installed app helper
     - First proof: install one app, run one file, inspect map-ready output.
   * - ``mycode``
     - Installed app helper
     - Smallest worker template and execution smoke.
   * - ``weather_forecast``
     - Installed app helper
     - Turn a notebook-style forecast into a reproducible app run.
   * - ``notebook_migrations``
     - Migration source assets
     - Notebooks, artifacts, lab stages, and conceptual pipeline view, including ``notebook_migrations/skforecast_meteo_fr``.
   * - ``notebook_quickstart``
     - Notebook examples
     - First-run, Colab, Kaggle, benchmark, and worker-path notebook samples.
   * - ``notebook_to_dask``
     - Read-only preview
     - Notebook cells, artifact contracts, and a Dask pipeline view.
   * - ``parallel_stage``
     - Read-only preview
     - Plan parallelism from function, split rule, reducer, and partition count.
   * - ``excel_workbook_proof``
     - Read-only preview
     - Workbook output, refreshable CSVs, and evidence hashes.
   * - ``sqlite_connector_proof``
     - Read-only preview
     - Local database query, CSV result, and evidence hashes.
   * - ``voila_notebook_proof``
     - Read-only preview
     - Notebook dashboard handoff with widget-to-args hints.
   * - ``sklearn_pipeline``
     - Installed app helper
     - Deterministic ML pipeline, metrics, model artifact, and hashes.
   * - ``mission_decision``
     - Installed app helper
     - Deterministic mission-data decision run with richer artifacts.
   * - ``inter_project_dag``
     - Read-only preview
     - Cross-project DAG artifact handoff and runner-state preview.
   * - ``service_mode``
     - Read-only preview
     - Service lifecycle and health-gate planning.
   * - ``mlflow_auto_tracking``
     - Read-only preview
     - Optional MLflow memory around AGILAB evidence.
   * - ``resilience_failure_injection``
     - Read-only preview
     - Compare fixed, replanned, search, and policy responses.
   * - ``train_then_serve``
     - Read-only preview
     - Freeze a trained policy before serving.
   * - ``native_rust_worker``
     - Read-only preview
     - Keep AGILAB orchestration in Python while moving a typed hot kernel to Rust.

Parallel-stage example
----------------------

Use ``parallel_stage`` before enabling pool or Dask execution when file count is
lower than core count. It teaches the rule used by :doc:`parallel-stages`:

.. code-block:: text

   if files are large and splittable:
       create chunk partitions until workers have enough work
   else:
       cap useful workers to file_count

Run it from a source checkout:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python src/agilab/examples/parallel_stage/preview_parallel_stage.py

The preview writes ``~/log/execute/parallel_stage/parallel_stage_preview.json``
and does not start workers.

Where to edit
-------------

The source README at ``src/agilab/examples/README.md`` is the detailed catalog.
Each example directory also has its own ``README.md`` with purpose, input,
output, safe adaptation, and troubleshooting notes.
