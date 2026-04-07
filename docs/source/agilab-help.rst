About AGILab
============

agilab.py is the main web interface entry point. It provides a single navigation
 surface for:

- **Core pages** (Project, Orchestrate, Pipeline, Analysis), and
- **Page bundles** (optional dashboards launched from Analysis).

Creator
-------

AGILAB was created by **Jean-Pierre Morard**.

Jean-Pierre Morard builds engineering tooling for reproducible AI workflows,
distributed execution, and operational experimentation. AGILAB reflects that
vision: turning AI applications from isolated scripts into structured,
testable, benchmarkable, and shareable workflows.

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

Core page tour
--------------

Every built-in page now exposes direct documentation access from the sidebar,
so you can reopen the relevant guide without navigating back to the landing
page first.

.. figure:: _static/page-shots/core-pages-overview.png
   :alt: Overview screenshot montage of the PROJECT, ORCHESTRATE, PIPELINE, and ANALYSIS Streamlit pages.
   :align: center
   :class: diagram-panel diagram-wide

   A compact visual tour of the four built-in Streamlit pages that structure the AGILAB workflow.

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
