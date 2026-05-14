Architecture in 5 minutes
=========================

AGILAB is an anti-lock-in reproducibility workbench for AI/ML engineering
teams. It bridges local interactive development, distributed execution, and
result analysis while preserving an exit path: workflows can be exported back
to runnable notebooks if AGILAB stops being the right runtime for a project.

Use this page for the mental model before opening the detailed architecture
reference.

One control path
----------------

.. code-block:: text

   User
     |
     v
   Streamlit UI, CLI wrappers, or notebook entry points
     |
     v
   AgiEnv: settings, project selection, app paths, logs, local workspace
     |
     v
   AGI facade: install, get_distrib, run, service actions
     |
     v
   agi-node / agi-cluster: package workers, dispatch work, start local or SSH workers
     |
     v
   Dask back-plane and optional MLflow tracking
     |
     v
   Artifacts, run manifests, app pages, and ANALYSIS views

What each layer owns
--------------------

.. list-table::
   :header-rows: 1
   :widths: 22 48 30

   * - Layer
     - Responsibility
     - Proof to look for
   * - UI / CLI / notebook
     - Capture user intent and keep PROJECT, ORCHESTRATE, WORKFLOW, and
       ANALYSIS on one visible path.
     - ``agilab first-proof --json`` and the hosted Hugging Face demo.
   * - ``AgiEnv``
     - Resolve app paths, settings, logs, environment variables, and per-user
       workspace files.
     - ``run_manifest.json`` plus app settings under ``~/.agilab/apps``.
   * - ``AGI`` facade
     - Provide the public install, distribution, execution, and service actions
       used by both UI and examples.
     - Example scripts in ``src/agilab/examples``.
   * - worker packaging
     - Build and stage worker runtimes so manager code and worker code stay
       isolated.
     - Worker copies under ``~/wenv/<app>_worker``.
   * - Dask / MLflow
     - Dask is the worker dispatch back-plane; MLflow is an optional tracking
       system AGILAB can integrate with, not replace.
     - Dask logs, MLflow runs, artifacts, and ANALYSIS pages.

Boundary
--------

AGILAB does not replace MLflow, Kubeflow, cloud deployment platforms, security
gateways, or production rollback systems. It keeps the engineering experiment
path reproducible and visible, then exports evidence and artifacts that those
deployment-focused systems can consume.

Next pages
----------

- :doc:`quick-start` for the first proof.
- :doc:`architecture` for package and runtime details.
- :doc:`agilab-mlops-positioning` for the MLOps boundary.
- :doc:`compatibility-matrix` for validated and documented public routes.
