AGILab in the MLOps Toolchain
=============================

AGILab focuses on the early experimentation phase of AI projects—roughly
Technology Readiness Level 3 (TRL‑3), where teams validate concepts, explore
algorithms, and collaborate on data preparation. This page explains how AGILab
fits alongside the broader MLOps landscape.

Where AGILab helps
------------------

- **Rapid experimentation**: templates, Streamlit pages, and CLI mirrors reduce
  the friction of testing new ideas without scaffolding bespoke dashboards.
- **Multi-algorithm workflows**: built-in orchestration (``AGI.run`` /
  ``AGI.get_distrib``) lets engineers cycle through multiple models using the
  same datasets and environment setup.
- **Distributed execution without DevOps**: Dask-based scheduling, SSH helpers,
  and worker packaging (`agi_cluster`, `agi_env`) allow TRL‑3 teams to scale out
  experiments without managing Kubernetes or cloud stacks.
- **Offline productivity**: bundled Mistral/GPT‑OSS assistants and cached
  datasets keep experimentation running even on air-gapped networks.

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

==================  ==============================  ================================================
Phase               AGILab focus                      Examples of complementary tools
==================  ==============================  ================================================
Ideation / TRL‑2    Not covered (use notebooks,      Whiteboards, notebooks, lightweight sandboxes
                    small prototypes)
Experimentation /   **Primary target** – templated    AGILab + data catalogues + experiment trackers
TRL‑3               projects, cluster automation
Validation / TRL‑4  Hand off to deployment-stack as   MLflow, Weights & Biases, Seldon, Kubeflow
                    soon as requirements stabilise
Deployment / TRL‑6+ Out of scope                      CI/CD, serving frameworks, APM, feature stores
==================  ==============================  ================================================

Suggested workflow
------------------

1. Use AGILab to prototype algorithms, reuse app templates, and validate data
   processing. Capture run history via ``~/log/execute/<app>/``.
2. Once an approach stabilises, export the project (``tools/run_configs`` and
   ``src/agilab/apps/<app>``) and integrate it with your organisation’s
   deployment toolchain (MLflow, Kubeflow, internal devops stack).
3. Track long-running metrics and governance artifacts using your preferred
   MLOps platform; AGILab does not replace those systems.

See also
--------

- :doc:`architecture` for the full stack overview.
- :doc:`framework-api` for automation hooks (``AGI.run``, ``AGI.install``).
- :doc:`introduction` for background and terminology around TRL and AGI use
  cases.
