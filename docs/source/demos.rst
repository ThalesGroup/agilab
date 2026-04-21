Demos
=====

.. toctree::
   :hidden:

   demo_capture_script

Use this page as the public entry point for runnable AGILAB demos when you do
not want to start with a local source checkout first.

Available demo paths
--------------------

- :doc:`notebook-quickstart` for the ``agi-core demo`` notebook path.
  Use this when you want a code-first demo in Colab or Kaggle without a local
  install on your machine.
- :doc:`quick-start` for the ``AGILAB demo`` hosted UI path.
  Use this when you want a browser-hosted Streamlit demo.
  Prefer self-hosting if viewers should not need any account.
  Lightning remains an optional managed operator path for the same launcher.

What to use first
-----------------

- Safest truthful first proof: :doc:`quick-start` with the built-in
  ``flight_project`` local path.
- Lightest browser-first path: :doc:`notebook-quickstart`.
- Hosted UI demo path: :doc:`quick-start` and the ``AGILAB demo`` section.
  For public viewers without accounts, prefer the self-hosted VM variant.

Core Tour
---------

- ``flight_project``: best first local proof of the AGILAB workflow
  (``PROJECT -> ORCHESTRATE -> ANALYSIS``).

.. figure:: _static/page-shots/core-pages-overview.png
   :alt: Overview screenshot montage of the PROJECT, ORCHESTRATE, PIPELINE, and ANALYSIS Streamlit pages.
   :align: center
   :class: diagram-panel diagram-wide

   The stable four-page flow used as the reference story for the main AGILAB intro.

See Also
--------

- :doc:`quick-start`
- :doc:`notebook-quickstart`
- :doc:`agilab-help` for the core page tour
- :doc:`apps-pages` for the page bundles used from ``ANALYSIS``
- `Video tutorial guide in the repository <https://github.com/ThalesGroup/agilab/blob/main/docs/source/demo_capture_script.md>`_
