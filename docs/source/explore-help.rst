ANALYSIS
===========

.. toctree::
   :hidden:

Introduction
------------
The **Analysis** page is the catalog for web views that belong to your
AGILab installation. It lets you pick which views should appear on the main
landing page and launch any of them in an isolated sidecar session for a richer
interactive experience.

Page snapshot
-------------

.. figure:: _static/page-shots/analysis-page.png
   :alt: Screenshot of the ANALYSIS page showing discovered views and per-project selection.
   :align: center
   :class: diagram-panel diagram-wide

   ANALYSIS exposes the available page bundles, stores the selected views per
   project, and launches them as sidecar dashboards.

What you should read from this screenshot
----------------------------------------

The screenshot intentionally shows one explicit flow:

1. **Discovery zone (left)**: AGILAB scans installed page bundles and lists
   every discoverable module under ``AGILAB_PAGES_ABS``.
2. **Configure zone (middle)**: choose per-project views by project context.
3. **Launch zone (right)**: each checked entry gets a launch button that opens the
   page as a sidecar dashboard.
4. **Project context banner (top)**: analysis selection is always tied to the
   active project (same path model as PROJECT/ORCHESTRATE/PIPELINE).
5. **Back control (sidecar header)**: returns you to Analysis after opening an
   external dashboard in the embedded frame.

If a view you expect is missing, follow the checks below before re-running
discovery.

Sidebar
-------
- ``Read Documentation`` opens this guide in the hosted public docs, and
  ``Open Local Documentation`` uses the locally generated docs build when
  available.
- Project selector that keeps the current application in sync with the rest of
  the suite.
- The currently selected project determines which views are stored inside its
  workspace ``app_settings.toml`` file under ``~/.agilab/apps/<project>/``
  in the ``[pages]`` section.

Main Content Area
-----------------
.. tab-set::

   .. tab-item:: Discover

      AGILab scans ``${AGILAB_PAGES_ABS}`` for installed page bundles and
      Python files that expose an entrypoint such as ``src/<module>/<module>.py``
      (or ``main.py`` / ``app.py``). The page grid lists every discovered bundle
      so you can preview what is available on disk.

   .. tab-item:: Configure

      Use the multi-select control to choose which pages are shown as quick-access
      shortcuts for analyzing the selected project. The selection is written to
      ``~/.agilab/apps/<project>/app_settings.toml`` in the ``[pages]`` section
      under ``view_module``. Only the names you choose are persisted for the
      active project; every project keeps its own list. The workspace file is
      seeded from the app's ``app_settings.toml`` source file (for example
      ``<project>/app_settings.toml`` or ``<project>/src/app_settings.toml``)
      the first time the app is loaded.

      You can also create a complete starter bundle directly from this page using
      **Create** in the ``Create from template`` tab. It creates a minimal
      pyproject and runnable Streamlit module so the page is immediately usable
      and ready to be customized.
      You can optionally clone an existing app page as a starting point from the
      same panel before clicking **Create**.

   .. tab-item:: Launch

      Each selected view appears as a button. Clicking it launches the bundle in
      a dedicated web process (one port per view, per session) using the
      nearest virtual environment (``.venv``/``venv`` in the bundle or the
      directories pointed to ``${AGILAB_VENVS_ABS}`` and
      ``${AGILAB_PAGES_VENVS_ABS}``). The child app is then embedded via iframe
      and a ``Back to Analysis`` control keeps navigation lightweight.

When a single screenshot is not enough
--------------------------------------

Use this exact sequence to move from config to visual result:

1. Keep project unchanged in the top selector.
2. Open ``Discover`` and confirm the expected bundle appears.
3. Switch to ``Configure`` and select only the views you need for this project.
4. Go to ``Launch`` and open one view.
5. Verify the sidecar frame shows the expected dashboard, then close it and return
   with ``Back to Analysis``.

Tips & Notes
------------
- Views are ordinary web projects. Bundles that expose a ``pyproject.toml``
  and a ``src/<module>/<module>.py`` entry point are automatically picked up.
- Built-in IDE pages (PROJECT, ORCHESTRATE, PIPELINE, ANALYSIS) always remain
  available; page bundles simply add extra entries to the Analysis catalogue when
  the project opts into them.
- ``uav_queue_project`` is a good reference setup: select both
  ``view_uav_queue_analysis`` and ``view_maps_network`` to inspect the same run
  through a dedicated queue dashboard and the generic topology map.
- AGILab caches the list per project, so the Analysis grid reflects the exact
  configuration stored in ``app_settings.toml``.
- If a view needs its own Python environment, place it alongside the page
  bundle (``.venv`` or ``venv``) or in the shared directories referenced by the
  ``AGILAB_VENVS_ABS`` / ``AGILAB_PAGES_VENVS_ABS`` environment variables.
  Analysis automatically picks the first interpreter that exists when spinning up
  the sidecar process.

Troubleshooting and checks
--------------------------

If analysis view discovery is unexpected, use these checks:

- If the list is empty, confirm the bundle folder contains ``pyproject.toml`` and
  ``src/<module>/<module>.py``.
- If a bundle is not launchable, verify that no syntax error blocks startup and
  that the bundle has either ``.venv``/``venv`` or a valid shared interpreter
  under ``${AGILAB_VENVS_ABS}`` / ``${AGILAB_PAGES_VENVS_ABS}``.
- If a launch opens a blank frame, confirm the web process starts on the expected port and
  that your browser blocks mixed local/remote content.
- If the selected bundle list is not saved, check write permission on
  ``~/.agilab/apps/<project>/app_settings.toml``.
- If ``view_maps_network`` opens but shows no UAV queue data, point the data
  directory to one run folder such as
  ``~/export/uav_queue/queue_analysis/<artifact_stem>/`` rather than the parent
  directory. The generic page expects one scenario run at a time.

See also
--------

- :doc:`agilab-help` to place Analysis in the full flow.
- :doc:`apps-pages` to understand page bundle requirements.
