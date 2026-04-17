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
  - What is still missing is a first-class generic ``reduce`` contract.
    Today, most final merge semantics and aggregation artefacts are still
    defined by each app.
  - A shared framework-level reduce contract remains roadmap work.

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
