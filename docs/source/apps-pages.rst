:orphan:

Page Bundles (apps-pages)
=========================

AGILab can optionally launch **page bundles** (sometimes called “apps-pages”):
standalone dashboards that complement the built-in workflow pages.

In the UI, page bundles are presented the same way as core pages, but they run
in their own sidecar web process and are embedded back into the main app.

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

- Choose a page name in the Analysis ``Create from template`` panel and click
  ``Create``.
- The generator creates ``<page>/pyproject.toml`` and
  ``<page>/src/<page>/<page>.py`` so the page is immediately discoverable.
- The page title is derived from the page name.
- You can also duplicate an existing page bundle as a starting point with
  **Clone from existing apps-page**.
- Open the generated page and replace the sample logic with your own visuals.

Enabling bundles (per project)
------------------------------

Bundles are enabled per project by writing their module names into
the per-user workspace copy of ``app_settings.toml``:

.. code-block:: toml

   [pages]
   view_module = ["view_uav_relay_queue_analysis", "view_maps_network"]

The file lives at ``~/.agilab/apps/<project>/app_settings.toml`` and is seeded
from the app's versioned ``app_settings.toml`` source file (for example
``<project>/app_settings.toml`` or ``<project>/src/app_settings.toml``) on first
use. You can edit it manually (PROJECT → APP-SETTINGS) or use Analysis →
Configure, which writes the same list for you.

Included page bundles
---------------------

This page lists the page bundles shipped with the repository. You can discover
and launch them from :doc:`explore-help`.

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
- It can also reuse the built-in ``UAV Relay Queue`` exports (install id
  ``uav_relay_queue_project``) when a run provides ``pipeline/topology.gml``,
  ``pipeline/allocations_steps.csv``, and trajectory CSV files in the same run
  directory.

view_uav_relay_queue_analysis
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Dedicated analysis page for the built-in ``UAV Relay Queue`` example
(``uav_relay_queue_project`` install id).

- Input: one run directory under ``~/export/uav_relay_queue/queue_analysis/<artifact_stem>/``.
- Output: queue occupancy charts, per-packet delay and drop summaries, route
  usage, and a quick explanation of why the scenario is a good AGILAB demo.
- The same run directory also exposes generic ``pipeline/`` artifacts so you can
  open ``view_maps_network`` on the exact same result.

Notes for distributed runs
--------------------------

- The ``UAV Relay Queue`` demo (install id ``uav_relay_queue_project``) distributes
  one scenario JSON file per worker. One simulation is one work item; AGILAB
  does not split a single scenario across multiple workers.
- Each scenario now writes into its own
  ``~/export/uav_relay_queue/queue_analysis/<artifact_stem>/`` directory, so
  distributed runs with several scenario files do not overwrite each other's
  ``pipeline/`` artifacts.
