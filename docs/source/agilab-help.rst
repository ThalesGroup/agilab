About AGILab
============

agilab.py is the main web interface entry point. It provides a single navigation
 surface for:

- **Core pages** (Project, Orchestrate, Pipeline, Analysis), and
- **Page bundles** (optional dashboards launched from Analysis).

How pages are presented
-----------------------

- Core pages and page bundles both appear as “pages” in the UI, with a consistent
  layout and navigation.
- The key difference is runtime: core pages run inside the main AGILab web
  interface, while page bundles run in a sidecar web process and are embedded
  back into the UI.

Core pages
----------

- :doc:`edit-help` — **PROJECT**: inspect and modify project sources and settings.
- :doc:`execute-help` — **ORCHESTRATE**: install workers, generate distributions, and run pipelines.
- :doc:`experiment-help` — **PIPELINE**: iterate in ``lab_steps.toml`` and run snippets against exported data.
- :doc:`explore-help` — **ANALYSIS**: discover, configure, and launch page bundles.

Page bundles (apps-pages)
-------------------------

Page bundles are optional dashboards stored under ``${AGILAB_PAGES_ABS}``
(default: ``src/agilab/apps-pages``). They are enabled per project via
``[pages].view_module`` in ``app_settings.toml``.

First-time navigation
---------------------

Use this flow the first time:

1. Open :doc:`edit-help` (Project) to inspect or select the target project.
2. Use :doc:`execute-help` (Orchestrate) to install dependencies, build
   distributions, and generate a run snippet.
3. Move to :doc:`experiment-help` (Pipeline) to run or iterate that step in
   ``lab_steps.toml``.
4. Open :doc:`explore-help` (Analysis) to configure and launch page bundles for
   deeper views.

See also
--------

- :doc:`architecture` for the end-to-end pipeline view.
- :doc:`apps-pages` for how page bundles work (and the built-in bundle catalog).
- :doc:`learning-workflows` for training vs inference (and optional continuous/federated patterns).
