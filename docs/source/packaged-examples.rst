Packaged Examples
=================

This page is the rendered public catalog for examples shipped under
``src/agilab/examples``. Use it when you need the full list in one place. Use
:doc:`demos` when you need a shorter route chooser.

The examples are split into executable app helpers, deterministic read-only
previews, and notebook migration assets. The read-only previews intentionally
avoid hidden services, private data, and long-lived workers.

Catalog
-------

.. list-table:: Packaged example catalog
   :header-rows: 1
   :widths: 24 24 52

   * - Example
     - Route
     - What it proves
   * - ``flight_telemetry``
     - Executable app helper
     - First proof for ``flight_telemetry_project``: install, run, and inspect
       map-ready telemetry output.
   * - ``mycode``
     - Executable app helper
     - Smallest worker template and local execution smoke.
   * - ``weather_forecast``
     - Executable app helper
     - Notebook-style forecast turned into a reproducible AGILAB app run.
   * - ``mission_decision``
     - Executable app helper
     - Deterministic mission-data decision run with richer artifacts.
   * - ``sklearn_pipeline``
     - Executable app helper
     - Classic ML proof with dataset generation, fitted pipeline, predictions,
       metrics, model artifact, and hash manifest.
   * - ``notebook_quickstart``
     - Notebook route
     - Colab, Kaggle, and local agi-core notebooks for the smallest runtime
       surface.
   * - ``notebook_migrations``
     - Notebook migration assets
     - Packaged migration source material such as notebooks, analysis
       artifacts, ``lab_stages.toml``, and pipeline views.
   * - ``notebook_to_dask``
     - Read-only preview
     - Notebook cells, artifact contracts, and Dask pipeline view before a real
       app conversion.
   * - ``excel_workbook_proof``
     - Read-only preview
     - Excel-shaped workbook output, Power Query-friendly CSVs, and evidence
       hashes.
   * - ``sqlite_connector_proof``
     - Read-only preview
     - Local SQLite schema, parameterized read-only query, CSV output, and
       database evidence.
   * - ``voila_notebook_proof``
     - Read-only preview
     - Voila-shaped notebook dashboard proof with widget-to-args migration hints
       and app-view plan.
   * - ``inter_project_dag``
     - Read-only preview
     - Cross-project DAG compatibility route using explicit artifact handoff.
   * - ``service_mode``
     - Read-only preview
     - Service lifecycle contract: start, status, health, and stop semantics
       without launching a persistent worker.
   * - ``mlflow_auto_tracking``
     - Read-only preview
     - Optional MLflow tracking around AGILAB execution evidence, not a parallel
       model registry.
   * - ``resilience_failure_injection``
     - Read-only preview
     - Controlled relay-failure scenario comparing fixed, replanned, search, and
       policy responses.
   * - ``train_then_serve``
     - Read-only preview
     - Handoff from trained policy artifact to service contract, prediction
       sample, and health gate.
   * - ``native_rust_worker``
     - Read-only preview
     - PyO3/maturin native-worker skeleton for moving only a measured hot kernel
       to Rust while orchestration stays in Python.

Execution Map
-------------

Use installed ``AGI_*.py`` helpers when you want to run a real built-in app from
``~/log/execute/<app>/`` after AGILAB has seeded the scripts. Use preview
scripts when you want deterministic evidence without starting services or
distributed workers.

.. code-block:: bash

   python ~/log/execute/flight_telemetry/AGI_install_flight_telemetry.py
   python ~/log/execute/flight_telemetry/AGI_run_flight_telemetry.py

Preview scripts are run from a source checkout through ``uv`` so dependencies
come from the checkout environment:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python src/agilab/examples/sqlite_connector_proof/preview_sqlite_connector_proof.py --output-dir /tmp/agilab-sqlite-proof
   uv --preview-features extra-build-dependencies run python src/agilab/examples/notebook_to_dask/preview_notebook_to_dask.py --output /tmp/notebook_to_dask_preview.json

Related Pages
-------------

- :doc:`quick-start` for the shortest local first proof.
- :doc:`demos` for a compact demo route chooser.
- :doc:`advanced-proof-pack` for the deeper proof routes.
- :doc:`notebook-quickstart` and :doc:`notebook-advanced` for notebook-first
  examples.
- :doc:`excel-users`, :doc:`voila-users`, and :doc:`data-connectors` for
  stakeholder-specific bridge examples.
