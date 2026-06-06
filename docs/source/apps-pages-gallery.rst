Page Bundle Gallery
===================

This gallery is the visual front door for the reusable Streamlit page bundles
that AGILAB can launch from ANALYSIS. Each bundle has a local README, a
source-controlled preview asset, direct test coverage, and shared AGILAB page
chrome.

.. list-table::
   :widths: 34 66

   * - .. image:: _static/apps-pages-gallery/view_app_ui.svg
          :alt: view_app_ui preview
          :width: 260px
     - **view_app_ui**

       Launches app-owned interactive Streamlit surfaces from ANALYSIS.

       When to use: Use when the app owns live controls, training loops, or a custom UI that should stay outside generic page bundles.
   * - .. image:: _static/apps-pages-gallery/view_autoencoder_latentspace.svg
          :alt: view_autoencoder_latentspace preview
          :width: 260px
     - **view_autoencoder_latentspace**

       Opt-in playground exception for TensorFlow/Keras latent projections and
       reconstruction behavior.

       When to use: Use for heavier Python 3.12 teaching or exploration sessions where an in-page autoencoder training loop is intentional; keep reproducible training workflows in app projects.
   * - .. image:: _static/apps-pages-gallery/view_barycentric.svg
          :alt: view_barycentric preview
          :width: 260px
     - **view_barycentric**

       Plots proportion-style KPI features on a barycentric/simplex surface.

       When to use: Use when three or more normalized contributions need a visual balance map instead of a raw table.
   * - .. image:: _static/apps-pages-gallery/view_data_io_decision.svg
          :alt: view_data_io_decision preview
          :width: 260px
     - **view_data_io_decision**

       Reviews data-ingestion and strategy-selection evidence.

       When to use: Use after a decision producer exports strategy, route, latency, cost, and reliability artifacts.
   * - .. image:: _static/apps-pages-gallery/view_forecast_analysis.svg
          :alt: view_forecast_analysis preview
          :width: 260px
     - **view_forecast_analysis**

       Reviews forecast metrics and prediction tables for time-series workflows.

       When to use: Use for notebook-to-AGILAB migrations or apps exporting forecast_metrics.json and forecast_predictions.csv.
   * - .. image:: _static/apps-pages-gallery/view_inference_analysis.svg
          :alt: view_inference_analysis preview
          :width: 260px
     - **view_inference_analysis**

       Compares allocation and inference-result metrics across exported runs.

       When to use: Use when several allocation exports need side-by-side diagnostics for load, routing, latency, bearer mix, and flows.
   * - .. image:: _static/apps-pages-gallery/view_live_artifacts.svg
          :alt: view_live_artifacts preview
          :width: 260px
     - **view_live_artifacts**

       Watches exported evidence, manifests, logs, text, CSVs, and images while a run is active.

       When to use: Use when a producer is still writing files and the reviewer needs a safe live artifact monitor.
   * - .. image:: _static/apps-pages-gallery/view_maps.svg
          :alt: view_maps preview
          :width: 260px
     - **view_maps**

       Explores geolocated datasets with map, sampling, palette, and basemap controls.

       When to use: Use first when latitude/longitude data needs a quick spatial sanity check.
   * - .. image:: _static/apps-pages-gallery/view_maps_3d.svg
          :alt: view_maps_3d preview
          :width: 260px
     - **view_maps_3d**

       Shows geospatial data in Deck.gl with extrusion, color, and overlay controls.

       When to use: Use when altitude, density, or height-encoded metrics need a spatial 3D view.
   * - .. image:: _static/apps-pages-gallery/view_maps_network.svg
          :alt: view_maps_network preview
          :width: 260px
     - **view_maps_network**

       Synchronizes topology, routes, allocations, trajectories, and geographic views.

       When to use: Use for relay or satellite queue-analysis runs where route choice and link availability need visual inspection.
   * - .. image:: _static/apps-pages-gallery/view_queue_resilience.svg
          :alt: view_queue_resilience preview
          :width: 260px
     - **view_queue_resilience**

       Reviews queue occupancy, packet events, routing summaries, and run metadata.

       When to use: Use for compact queue-analysis artifacts from any producer writing the AGILAB queue contract.
   * - .. image:: _static/apps-pages-gallery/view_relay_resilience.svg
          :alt: view_relay_resilience preview
          :width: 260px
     - **view_relay_resilience**

       Compares relay queue health, route usage, and exported node motion traces.

       When to use: Use after relay-focused queue runs when packet delivery and relay behavior need side-by-side review.
   * - .. image:: _static/apps-pages-gallery/view_release_decision.svg
          :alt: view_release_decision preview
          :width: 260px
     - **view_release_decision**

       Builds an evidence cockpit for candidate/baseline review and promotion gates.

       When to use: Use before handoff when a run needs explicit gates, indexed evidence, and a promotion_decision.json export.
   * - .. image:: _static/apps-pages-gallery/view_routing_model_comparison.svg
          :alt: view_routing_model_comparison preview
          :width: 260px
     - **view_routing_model_comparison**

       Compares baseline and candidate routing allocation decisions.

       When to use: Use when routing models need allocation deltas, failure inspection, and side-by-side decision evidence.
   * - .. image:: _static/apps-pages-gallery/view_scenario_cockpit.svg
          :alt: view_scenario_cockpit preview
          :width: 260px
     - **view_scenario_cockpit**

       Packages baseline/candidate scenario evidence and promotion-gate deltas.

       When to use: Use before opening detailed queue or network maps when a compact scenario decision artifact is enough.
   * - .. image:: _static/apps-pages-gallery/view_shap_explanation.svg
          :alt: view_shap_explanation preview
          :width: 260px
     - **view_shap_explanation**

       Displays local feature-attribution evidence without depending on a specific explainer runtime.

       When to use: Use when producer workflows export SHAPKit, shap, or compatible attribution tables.
   * - .. image:: _static/apps-pages-gallery/view_training_analysis.svg
          :alt: view_training_analysis preview
          :width: 260px
     - **view_training_analysis**

       Browses scalar training runs from TensorBoard logs or AGILAB training-history CSVs.

       When to use: Use to compare trainers, tags, steps, and training curves before deeper model review.
