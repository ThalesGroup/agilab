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

Looking for the PyTorch playground or loss landscape? Use the built-in
``pytorch_playground_project`` app. It is a reproducible app project, not a
generic app-agnostic analysis page. The loss-landscape projection belongs to
that app, not to a separate ``view_loss_landscape`` package.

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

This section summarizes every page bundle shipped under
``src/agilab/apps-pages``. Use :doc:`explore-help` to discover, configure, and
launch them from the UI.

``agi-pages`` is the provider/umbrella package for the default lightweight page
set. Heavier teaching or framework-specific pages can still be shipped as
standalone ``agi-page-*`` packages or source-checkout bundles without being
pulled by the umbrella dependency graph.

.. list-table::
   :header-rows: 1

   * - Module
     - Package
     - Purpose
     - Packaging status
   * - ``view_autoencoder_latentspace``
     - ``agi-page-latent-space``
     - TensorFlow/Keras latent-space projection and autoencoder exploration.
     - Source-checkout opt-in; intentionally outside ``agi-pages`` because it
       targets Python 3.12 and carries TensorFlow runtime constraints.
   * - ``view_barycentric``
     - ``agi-page-simplex-map``
     - Barycentric/simplex visualisation for proportion-style KPI features.
     - Included in ``agi-pages``.
   * - ``view_data_io_decision``
     - ``agi-page-decision-evidence``
     - Decision-evidence review for data ingestion and strategy selection.
     - Included in ``agi-pages``.
   * - ``view_forecast_analysis``
     - ``agi-page-timeseries-forecast``
     - Forecast metrics and prediction review for time-series workflows.
     - Included in ``agi-pages``.
   * - ``view_inference_analysis``
     - ``agi-page-inference-report``
     - Allocation and inference-result comparison across exported runs.
     - Included in ``agi-pages``.
   * - ``view_live_artifacts``
     - ``agi-page-live-artifacts``
     - Dynamic artifact, manifest, evidence, and log monitor for active apps.
     - Included in ``agi-pages``.
   * - ``view_app_ui``
     - ``agi-page-app-ui``
     - Bridge that displays an app-owned Streamlit UI from ANALYSIS.
     - Included in ``agi-pages``.
   * - ``view_maps``
     - ``agi-page-geospatial-map``
     - 2D map viewer for geolocated datasets.
     - Included in ``agi-pages``.
   * - ``view_maps_3d``
     - ``agi-page-geospatial-3d``
     - 3D cartography view with extrusion, color, and overlay controls.
     - Included in ``agi-pages``.
   * - ``view_maps_network``
     - ``agi-page-network-map``
     - Network-aware geospatial topology and route inspection.
     - Included in ``agi-pages``.
   * - ``view_routing_model_comparison``
     - ``agi-page-routing-model-comparison``
     - Routing-model allocation comparison for candidate/baseline decisions.
     - Included in ``agi-pages``.
   * - ``view_queue_resilience``
     - ``agi-page-queue-health``
     - Queue occupancy, delay, drop, route, and run-metadata evidence.
     - Included in ``agi-pages``.
   * - ``view_relay_resilience``
     - ``agi-page-relay-health``
     - Relay queue comparison across exported run directories.
     - Included in ``agi-pages``.
   * - ``view_release_decision``
     - ``agi-page-promotion-gate``
     - Evidence cockpit for baseline/candidate run review, gates, and handoff decisions.
     - Included in ``agi-pages``.
   * - ``view_scenario_cockpit``
     - ``agi-page-scenario-cockpit``
     - Scenario cockpit for baseline/candidate queue-analysis evidence.
     - Included in ``agi-pages``.
   * - ``view_shap_explanation``
     - ``agi-page-feature-attribution``
     - Local feature-attribution evidence review for SHAP-compatible outputs.
     - Included in ``agi-pages``.
   * - ``view_training_analysis``
     - ``agi-page-training-report``
     - Training run scalar browser for TensorBoard logs and AGILAB training-history CSV artifacts.
     - Included in ``agi-pages``.

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
- UI convention: the sidebar exposes a compact ``Data source`` expander for
  the full directory path, and the page header includes ``Back to ANALYSIS``.

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
- UI convention: the resolved data path is kept under ``Resolved data path`` so
  the normal sidebar stays focused on choices rather than long filesystem
  strings.

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
- Maintainer dogfooding is repeatable with
  ``tools/scenario_cockpit_evidence.py``. The checked-in public sample at
  ``docs/source/data/scenario_cockpit_uav_queue_sample.json`` is generated from
  two real ``uav_queue_project`` worker runs, not hand-written fixtures.
- Use ``uav_queue_project`` for the compact two-policy proof generator. Use
  ``uav_relay_queue_project`` when you want the same queue-analysis artifact
  contract inside the relay-focused built-in app and UI story.

view_relay_resilience
^^^^^^^^^^^^^^^^^^^^^

Relay queue comparison page for producer-agnostic queue-analysis artifacts.

- Input: one or more run directories under
  ``~/export/<app_target>/queue_analysis/<artifact_stem>/``.
- Output: multi-run comparison tables, queue occupancy charts, per-packet delay
  and drop summaries, route usage, and run metadata for reproducibility checks.
- The same run directory also exposes generic ``pipeline/`` artifacts so you can
  open ``view_maps_network`` on the exact same result.

view_data_io_decision
^^^^^^^^^^^^^^^^^^^^^

Decision evidence view for app-agnostic data and strategy selection artifacts.

- Input: data-decision JSON/CSV artifacts emitted by a producer workflow.
- Output: selected strategy, alternatives, validation notes, and evidence
  summaries for audit/review.

view_forecast_analysis
^^^^^^^^^^^^^^^^^^^^^^

Forecast evidence page for time-series prediction workflows.

- Input: ``forecast_metrics.json`` and ``forecast_predictions.csv`` from the
  selected export directory.
- Output: metric summaries, forecast/prediction overlays, and run metadata.

view_inference_analysis
^^^^^^^^^^^^^^^^^^^^^^^

Inference and allocation comparison page for producer-agnostic result exports.

- Input: ``allocations_steps`` files in JSON, JSONL/NDJSON, CSV, or parquet
  form.
- Output: side-by-side run metrics, delivered-bandwidth aggregates, and
  allocation charts.

view_live_artifacts
^^^^^^^^^^^^^^^^^^^

Live evidence monitor for app-agnostic exported artifacts.

- Input: any active app export, run, or custom artifact directory.
- Output: auto-refreshing inventory of manifests, logs, JSON/CSV/text files,
  images, file sizes, timestamps, and a stable artifact signature.
- Use it for long-running local or distributed runs that write incremental
  evidence while the app remains responsible for execution.

view_app_ui
^^^^^^^^^^^

Generic bridge for app-owned interactive Streamlit UIs.

- Input: an active app with ``[pages.view_app_ui].entrypoint`` configured in
  ``app_settings.toml``.
- Output: the app-owned UI rendered inside ANALYSIS while the app keeps
  control of training, execution semantics, and evidence artifacts.

view_release_decision
^^^^^^^^^^^^^^^^^^^^^

Evidence cockpit for baseline/candidate run review and promotion gates.

- Input: candidate and baseline evidence directories.
- Output: cockpit summary, blocking-gate counts, indexed evidence history,
  handoff checklist, and downloadable ``promotion_decision.json`` evidence.

view_shap_explanation
^^^^^^^^^^^^^^^^^^^^^

Feature-attribution evidence page for SHAP-compatible model explanations.

- Input: local explanation artifacts from SHAPKit, ``shap``, or compatible
  custom explainers.
- Output: feature attribution summaries and per-record explanation views.

view_training_analysis
^^^^^^^^^^^^^^^^^^^^^^

Training evidence page for scalar logs and model-training runs.

- Input: TensorBoard-compatible scalar folders or ``data/training_history.csv``
  artifacts under an app export directory.
- Output: run selector, scalar trends, and training metadata for comparison.

view_autoencoder_latentspace
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

TensorFlow/Keras latent-space exploration page for Python 3.12 source-checkout
environments.

- Input: embeddings, labels, or autoencoder-ready tabular/image artifacts.
- Output: latent-space projections, clustering diagnostics, and reconstruction
  exploration.
- This page remains opt-in because TensorFlow constrains the supported Python
  range and would make the default page bundle set heavier.

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
