Framework API
=============

The framework is organised as a small set of cooperating packages that expose
both web-interface primitives (pages, widgets, orchestration helpers) and the
worker-side orchestration logic. Start here when you need to automate project
setup, build new nodes, or integrate with the AGILab distributor.

Core and UI packages
--------------------

- ``agi_env`` maps the current project into an ``AgiEnv`` object and provides the
  headless environment utilities used by apps, workers, and installers.
- ``agi_gui`` is the UI/page helper package under ``src/agilab/lib/agi-gui``. It
  depends on ``agi_env`` and adds the Streamlit-facing imports used by AGILAB
  pages and page bundles.
- ``agi_core`` keeps the shared framework contracts intentionally thin; for now,
  the architecture page is more useful than autodoc because the top-level Python
  package exports only a minimal public surface.
- ``agi_node`` contains the base worker/node abstractions that run inside a
  cluster. Extend these classes when you need custom pipelines or want to add
  typed contracts around data exchange.
- ``agi-distributor`` is the orchestration layer implemented under
  ``agi_cluster.agi_distributor``. It handles app installation, distribution
  creation, and task delegation to remote workers.

The detailed API reference for each package is available below.

.. toctree::
   :maxdepth: 2

   agi-env
   agi-gui
   agi-node
   agi-distributor

Working with the API
--------------------

- Use ``agi_env.AgiEnv`` inside web pages or utility scripts to access the
  active project structure and configuration.
- Use ``agi_gui`` imports for Streamlit page helpers so UI dependencies stay
  outside worker-only runtimes.
- Derive from ``agi_node`` base classes to implement new DAG stages or worker
  behaviours that can be shipped with your app bundles.
- Call into ``agi_cluster.agi_distributor.agi_distributor.AGI`` for programmatic
  install / get_distrib / run flows; this is the same surface area surfaced in
  the Orchestrate page snippets.

App structure conventions
-------------------------

- Every app bundles a manager module under
  ``src/agilab/apps/<app>_project/src/<app>/<app>.py`` and a worker module under
  ``src/agilab/apps/<app>_project/src/<app>_worker/<app>_worker.py``.
- Test coverage mirrors that split: ``test/_test_<app>_manager.py`` drives the
  manager entry points, ``test/_test_<app>_worker.py`` exercises the worker, and
  ``app_test.py`` orchestrates the combined flow.
- Instantiate managers with their validated args models (for example ``FlightArgs``).
  The convenience constructor ``BaseWorker.from_toml`` remains the recommended entry
  point for configuration-driven flows.

For end-to-end examples, browse ``src/agilab/examples`` to see how the packages
fit together in real projects.
