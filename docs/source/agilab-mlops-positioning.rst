AGILab in the MLOps Toolchain
=============================

AGILab focuses on the early experimentation phase of AI projects—roughly
Technology Readiness Level 3 (TRL‑3), where teams validate concepts, explore
algorithms, and collaborate on data preparation. This page explains how AGILab
fits alongside the broader MLOps landscape.

Where AGILab helps
------------------

- **Rapid experimentation**: templates, web pages, and CLI mirrors reduce
  the friction of testing new ideas without scaffolding bespoke dashboards.
- **Multi-algorithm workflows**: built-in orchestration (``AGI.run`` /
  ``AGI.get_distrib``) lets engineers cycle through multiple models using the
  same datasets and environment setup.
- **Distributed execution without DevOps**: Dask-based scheduling, SSH helpers,
  and worker packaging (`agi_cluster`, `agi_env`) allow TRL‑3 teams to scale out
  experiments without managing Kubernetes or cloud stacks.
- **Offline productivity**: optional offline assistants (Mistral/GPT‑OSS paths, plus
  local documentation assets when configured) can keep experimentation usable in
  air-gapped environments once the dependencies and local model/runtime setup are
  installed.

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

The table below is deliberately practical: it focuses on where teams usually
start, what each tool is strongest at, and why AGILab is not simply a drop-in
replacement for them.

.. list-table:: AGILab compared with adjacent workflow tools
   :widths: 18 32 18 32
   :header-rows: 1

   * - Tool
     - Primary centre of gravity
     - Best fit
     - How AGILab differs
   * - Kedro
     - Code-first data/ML pipeline engineering with modular pipelines, a data
       catalog, hooks, runners, and Kedro-Viz.
     - Teams that want a structured Python project for reproducible pipelines
       and plan to plug orchestration and infrastructure in around it.
     - AGILab is less about a pipeline framework in isolation and more about a
       single operator-facing workspace: install, distribute, run, pipeline
       replay, MLflow-traced execution, and analysis in one product.
   * - Dagster
     - Asset-centric orchestration with integrated lineage, observability,
       automation, and testing.
     - Data platform teams treating orchestration and asset health as the
       backbone of the platform.
     - AGILab is earlier-phase and more experiment-centric. It provides
       managed runtimes, domain apps, and researcher/operator workflows rather
       than a full asset-orchestration control plane.
   * - Prefect
     - Python-native orchestration of flows, tasks, deployments, and dynamic
       execution patterns.
     - Teams that want orchestration logic to stay close to normal Python code
       with lightweight deployment options.
     - AGILab wraps more of the surrounding lifecycle directly in the product:
       environment bootstrapping, worker packaging, distribution planning,
       service mode, and analysis pages.
   * - Metaflow
     - Human-friendly Python library for taking data science workflows from
       local prototyping to scaled and production deployments.
     - Data science teams that want a unified Python API across local,
       scaled, and production-style execution.
     - AGILab is more UI- and operations-oriented. It emphasizes guided
       orchestration, explicit app packaging, and shared operator flows over a
       single Python library abstraction.
   * - Airflow
     - Batch workflow scheduling, monitoring, and broad system integration via
       DAGs, operators, hooks, and the web UI.
     - Platform or data engineering teams running recurring, scheduled,
       batch-oriented pipelines across many external systems.
     - AGILab is not a general-purpose batch scheduler. It is stronger when
       the problem is experiment packaging, managed execution environments,
       distributed research workloads, and app-centric user workflows.

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
  integration across external systems, not an experimentation workbench.

In practice, AGILab often complements these tools rather than replacing them:
teams can use AGILab during the experimentation and validation phase, then hand
off stabilized assets to a broader orchestration or production platform.

Suggested workflow
------------------

1. Use AGILab to prototype algorithms, reuse app templates, and validate data
   processing. Capture run history via ``~/log/execute/<app>/``.
2. Once an approach stabilises, prepare the project artefacts for your target
   environment and integrate it with your organisation’s deployment toolchain
   (MLflow, Kubeflow, internal devops stack). In a source checkout, this commonly
   uses ``tools/run_configs`` and ``src/agilab/apps/<app>``; in packaged
   installs, use the generated app package artifacts available from your installer.
3. Track long-running metrics and governance artifacts using your preferred
   MLOps platform; AGILab does not replace those systems.

See also
--------

- :doc:`architecture` for the full stack overview.
- :doc:`framework-api` for automation hooks (``AGI.run``, ``AGI.install``).
- :doc:`introduction` for background and terminology around TRL and AGI use
  cases.
