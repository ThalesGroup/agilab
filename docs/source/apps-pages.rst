:orphan:

Page Bundles
============

This page explains the optional analysis dashboards that AGILab can launch from
the **ANALYSIS** page.

If you are new to AGILab, do not start here. Start with
:doc:`newcomer-guide`, then use :doc:`explore-help` when you are ready to add
custom or optional views.

Page bundles are standalone dashboards that complement the built-in workflow
pages. In the UI they appear alongside the main pages, but they run in their
own sidecar web process.

What is a page bundle?
----------------------

A page bundle is a small web bundle project stored on disk and launched on demand
in its own Python interpreter:

- It lives under ``${AGILAB_PAGES_ABS}`` (default: ``src/agilab/apps-pages``).
- It is discovered when it is a Python file directly under ``AGILAB_PAGES_ABS``
  or a directory exposing ``src/<module>/<module>.py`` (or ``main.py`` /
  ``app.py``).
- It can ship its own ``.venv`` (or ``venv``); otherwise Analysis will fall back
  to the shared locations referenced by ``AGILAB_VENVS_ABS`` and
  ``AGILAB_PAGES_VENVS_ABS``.

For fastest setup, AGILAB Analysis also exposes a **minimal template generator**:

- Choose a page name in the Analysis ``Create analysis view`` panel and click
  ``Create``.
- The generator creates ``<page>/pyproject.toml`` and
  ``<page>/src/<page>/<page>.py`` so the page is immediately discoverable.
- The page title is derived from the page name.
- You can also duplicate an existing page bundle as a starting point with
  **Starting point**.
- Open the generated page and replace the sample logic with your own visuals.

Tutorial: clone an existing page bundle
---------------------------------------

Use this when one public page bundle is already close to what you need and you
want a new copy to modify safely.

1. Open **ANALYSIS**.
2. Find the page-bundle creation area.
3. Enter the new page name you want to create.
4. In **Starting point**, choose the source bundle to duplicate.
5. Confirm the creation step.

AGILAB creates a new bundle under ``${AGILAB_PAGES_ABS}`` with its own
``pyproject.toml`` and ``src/<page>/<page>.py`` entrypoint.

What to do next:

- Open the new page bundle source on disk and replace the copied sample logic
  with your own visuals or tables.
- If the bundle needs extra dependencies, edit its local ``pyproject.toml``.
- Enable the new bundle for a project through the ``[pages]`` section in
  ``~/.agilab/apps/<project>/app_settings.toml`` or through Analysis →
  Choose analysis views.

Enabling bundles (per project)
------------------------------

Bundles are enabled per project by writing their module names into
the per-user workspace copy of ``app_settings.toml``:

.. code-block:: toml

   [pages]
   view_module = ["view_scenario_cockpit", "view_relay_resilience", "view_maps_network"]

The file lives at ``~/.agilab/apps/<project>/app_settings.toml`` and is seeded
from the app's versioned ``app_settings.toml`` source file (for example
``<project>/app_settings.toml`` or ``<project>/src/app_settings.toml``) on first
use. You can edit it manually (PROJECT → APP-SETTINGS) or use Analysis →
Choose analysis views, which writes the same list for you.

Included page bundles
---------------------

This section summarizes the public page bundles shipped with the repository.
Use :doc:`explore-help` to discover, configure, and launch them from the UI.

view_autoencoder_latentspace
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Autoencoder-powered dimensionality reduction.

- Input: exported dataframe (typically created in Orchestrate).
- Output: latent-space plots, with colouring and train/test controls.

view_barycentric
^^^^^^^^^^^^^^^^

Barycentric simplex visualisation for KPI-style features that sum to 1.

- Input: dataframe with aggregated proportion columns.
- Output: interactive simplex plot for relative contributions.

view_maps
^^^^^^^^^

2D map viewer for geolocated datasets.

- Input: CSV/parquet with latitude/longitude columns.
- Output: interactive map with sampling, palette, and basemap controls.

view_maps_3d
^^^^^^^^^^^^

3D cartography view (Deck.gl) with optional overlays.

- Input: one or more geolocated datasets.
- Output: 3D map with extrusion/colour controls and layer toggles.

view_maps_network
^^^^^^^^^^^^^^^^^

Network topology viewer synchronised with geographic views.

- Input: node positions + link definitions in the dataset.
- Output: map + graph views to inspect connectivity, link types, and snapshots.
- It can also reuse any queue-analysis run that provides
  ``pipeline/topology.gml``, ``pipeline/allocations_steps.csv``, and
  trajectory CSV files in the same run directory.

view_queue_resilience
^^^^^^^^^^^^^^^^^^^^^

Queue telemetry page for producer-agnostic queue-analysis artifacts.

- Input: one or more summary files under
  ``~/export/<app_target>/queue_analysis/<artifact_stem>/``.
- Output: queue occupancy charts, per-packet delay and drop summaries, route
  usage, and run metadata for reproducibility checks.

view_scenario_cockpit
^^^^^^^^^^^^^^^^^^^^^

Scenario evidence cockpit for producer-agnostic queue-analysis artifacts.

- Input: one or more run directories under
  ``~/export/<app_target>/queue_analysis/<artifact_stem>/``.
- Output: baseline/candidate deltas, a deterministic promotion gate, and a
  downloadable JSON evidence bundle with hashes for the selected summaries and
  peer artifacts.
- Use this first when you need a compact review artifact before opening the
  detailed queue or network maps.

view_relay_resilience
^^^^^^^^^^^^^^^^^^^^^

Relay queue comparison page for producer-agnostic queue-analysis artifacts.

- Input: one or more run directories under
  ``~/export/<app_target>/queue_analysis/<artifact_stem>/``.
- Output: multi-run comparison tables, queue occupancy charts, per-packet delay
  and drop summaries, route usage, and run metadata for reproducibility checks.
- The same run directory also exposes generic ``pipeline/`` artifacts so you can
  open ``view_maps_network`` on the exact same result.

Producer example for distributed runs
-------------------------------------

- A compatible queue-analysis producer should distribute one scenario or
  workload file per worker. One simulation remains one work item; AGILAB does
  not split a single scenario across multiple workers.
- Each workload should write into its own
  ``~/export/<app_target>/queue_analysis/<artifact_stem>/`` directory, so
  distributed runs with several workload files do not overwrite each other's
  ``pipeline/`` artifacts.

See also
--------

- :doc:`explore-help` for the ANALYSIS page workflow
- :doc:`agilab-help` for the built-in page map
