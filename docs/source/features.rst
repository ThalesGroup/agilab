Features
========

This page lists current shipped capabilities.

For toolchain fit, framework comparison, and when to choose AGILab, see
:doc:`agilab-mlops-positioning`.

For planned work, see :doc:`roadmap/agilab-future-work`.

AGILab currently exposes 2 main user interfaces:

 - ``agi-core``: an API interface callable directly from your Python program.
 - ``agilab``: a web interface that generates ``agi-core`` calls and can render generated snippets for execution.

Shared components include ``agi-env`` (environment setup), ``agi-node`` (runtime orchestration), and ``agi-cluster`` (multi-node execution support).

agi-core
--------

- **Automated Virtual Environment Setup:**

  - Automatically installs virtual environments for cluster nodes which are computers with multi-cores CPU, GPU and NPU.

- **Flexible Application Run Modes:**

  - **Process Management:**

    - Single Process
    - Multiple Processes

  - **Language Support:**

    - Pure Python (From python 3.11)
    - Cython (Ahead of execution compilation)

  - **Deployment Modes:**

    - Single Node with MacOS, Windows (from W11) or Linux (Ubuntu from ubuntu 24.04)
    - Cluster with heterogeneous os per node

- **Dynamic Node Capacity Calibration:**

  - Automatically calibrates the capacity of each node to optimize performance.

- **Static Load Balancing:**

  - Distributes workloads evenly across nodes to ensure efficient resource utilization.

- **Distributed Work-Plan Execution:**

  - Facilitates partitioned data processing, worker dispatch, and app-level
    aggregation.
  - AGILab currently standardizes the ``map`` side of the workflow: building
    distribution plans, dispatching partitions, and running them on local or
    cluster workers.
  - AGILab now exposes a shared ``agi_node`` reduce contract with explicit
    partial inputs, reducer merge semantics, and a standard reduce artefact
    schema.
  - ``execution_pandas_project`` and ``execution_polars_project`` emit named
    benchmark reduce artefacts through that shared contract; the user-facing
    ``meteo_forecast_project`` emits forecast-metrics reduce artefacts; and
    ``uav_queue_project`` plus ``uav_relay_queue_project`` emit the same
    ``reduce_summary_worker_<id>.json`` artifact shape for queue metrics.
  - The Release Decision evidence view discovers those artefacts, validates
    their schema, and displays reducer name, partial count, artifact path,
    benchmark row/source/execution fields, meteo forecast MAE/RMSE/MAPE fields,
    and UAV queue-family packet/PDR fields when present.
  - The public reducer benchmark validates 8 partials / 80,000 synthetic items
    in ``0.003s`` against a ``5.0s`` target.
  - Other existing apps still own their final merge semantics, so broader app
    migration beyond the benchmark pair and first three user-facing apps remains
    roadmap work.

- **Optimized Run-Mode Selection:**

  - Chooses the best run-mode from up to 16 combinations (8 base modes and an optional RAPIDS variant).


agilab
------

- **Notebook-like multi-venv execution:**

  - Coordinate runs through one interface while keeping isolated runtimes for
    project steps, workers, or page bundles.

- **agi-core API Generation:**

  - Automatically generates APIs to streamline development processes.

- **ChatGPT / Mistral Coding Assistant:**

  - Integrates with ChatGPT and Mistral to offer real-time code suggestions and support across preferred providers.

- **Embedded Dataframe Export:**

  - Easily export dataframes cross project.

- **5 Ways to Reuse Code:**

  - **Framework Instantiation:**

    - Inherit from agi-core ``AgentWorker | DagWorker | DataWorker`` classes.

  - **Project Templates:**

    - Clone existing code or create new project from templates.

  - **Q&A Snippets History:**

    - Utilize historical code snippets for quick integration.

  - **Collaborative Coding:**

    - Export / Import project to work together efficiently cross organisation.

  - **Views Creation:**

    - Share views seamlessly across multiple projects.

- **Project & Page Isolation:**

  - Create full AGILab *apps* from templates; each ships with its own
    ``pyproject.toml`` / ``uv_config.toml`` so ``uv`` provisions a dedicated
    virtual environment during Install.
  - Build additional **page bundles** (standalone dashboards) that
    live under ``src/agilab/apps-pages``. Every bundle carries its own
    ``pyproject.toml`` or embedded ``.venv`` so the Analysis launcher spins it up
    inside an isolated interpreter.

Engineering prototyping evidence
--------------------------------

AGILab is strongest for engineering prototypes that need more structure than a
single notebook but less ceremony than a production MLOps platform:

- app templates and cloned projects provide a repeatable manager/worker shape
- app and page bundles keep dependencies isolated through their own
  ``pyproject.toml`` / ``uv`` environments
- ``app_args_form.py`` and ``app_settings.toml`` give prototypes a typed,
  configurable UI surface instead of hard-coded script parameters
- ``lab_steps.toml`` and notebook import/export support let teams move between
  notebook exploration and reproducible pipeline snippets
- optional ``pipeline_view.dot`` / ``pipeline_view.json`` files give prototypes
  a conceptual architecture view alongside generated execution snippets
- the Analysis page can generate minimal page bundles so a prototype can gain a
  shareable dashboard without becoming a full product

That supports an ``Engineering prototyping`` score of ``4.0 / 5``. It is not
scored higher yet because the first-proof wizard, generic evidence bundle, and
broader reduce-contract app migration beyond the benchmark pair and first three
user-facing apps remain roadmap work.

Production-readiness controls
-----------------------------

AGILab ships a bounded set of controls for controlled pilots and handoff to a
production platform:

- ``tools/pypi_publish.py`` enforces release preflight checks before real PyPI
  publication
- workflow-parity profiles mirror selected GitHub Actions locally before a
  maintainer relies on CI
- the compatibility matrix separates validated public paths from documented
  routes that still need broader certification
- ``tools/service_health_check.py`` evaluates service status against SLA
  thresholds and can emit JSON or Prometheus-compatible output
- the release-decision analysis page compares baseline and candidate bundles,
  applies artifact/KPI gates, and exports ``promotion_decision.json``
- the same evidence view surfaces reducer artifacts from benchmark distributed
  runs, meteo forecast results, and UAV queue-family results, including
  invalid-artifact diagnostics when JSON cannot be parsed
- ``SECURITY.md`` provides the public vulnerability-reporting and deployment
  hardening baseline

That supports a ``Production readiness`` score of ``3.0 / 5``. It is not scored
higher because AGILab remains a research and engineering workbench rather than
a production serving, monitoring, governance, or certification platform.
