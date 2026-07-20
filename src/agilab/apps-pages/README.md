# Apps-Pages: Streamlit Views

This folder contains Streamlit pages for visualising AGILab data and maps. Each page expects an
active app and its exported datasets.

Page projects depend on `agi-gui`, the shared UI package under `src/agilab/lib/agi-gui`.

Naming convention:

- `view_*` page bundles are the generic app-agnostic sidecars.
- `app_ui` and `autoencoder_latentspace` are visible exceptions with their own names because they are not generic sidecars.

Looking for the PyTorch playground or loss landscape? Use the built-in
`pytorch_playground_project`. It is a reproducible app project, not a generic
app-agnostic analysis page. The generic `app_ui` bridge lets ANALYSIS
display the app-owned playground UI without moving training logic into
apps-pages.

## Gallery

Every shipped view bundle has a local README, a source-controlled preview, direct tests, and shared AGILAB page chrome.

| View | View |
|---|---|
| [![app_ui preview](apps-pages-gallery/app_ui.svg)](app_ui)<br>**app_ui**<br>Launches app-owned interactive Streamlit surfaces from ANALYSIS. | [![autoencoder_latentspace preview](apps-pages-gallery/autoencoder_latentspace.svg)](autoencoder_latentspace)<br>**autoencoder_latentspace**<br>Opt-in playground exception for TensorFlow/Keras latent projections; it trains a small autoencoder in-page and is not a generic app-agnostic sidecar. |
| [![view_barycentric preview](apps-pages-gallery/view_barycentric.svg)](view_barycentric)<br>**view_barycentric**<br>Plots proportion-style KPI features on a barycentric/simplex surface. | [![view_data_io_decision preview](apps-pages-gallery/view_data_io_decision.svg)](view_data_io_decision)<br>**view_data_io_decision**<br>Reviews data-ingestion and strategy-selection evidence. |
| [![view_forecast_analysis preview](apps-pages-gallery/view_forecast_analysis.svg)](view_forecast_analysis)<br>**view_forecast_analysis**<br>Reviews forecast metrics and prediction tables for time-series workflows. | [![view_inference_analysis preview](apps-pages-gallery/view_inference_analysis.svg)](view_inference_analysis)<br>**view_inference_analysis**<br>Canonically compares allocation metrics, active demands, outcomes, failures, and flow matrices across exported runs. |
| [![view_live_artifacts preview](apps-pages-gallery/view_live_artifacts.svg)](view_live_artifacts)<br>**view_live_artifacts**<br>Watches exported evidence, manifests, logs, text, CSVs, and images while a run is active. | [![view_maps preview](apps-pages-gallery/view_maps.svg)](view_maps)<br>**view_maps**<br>Explores geolocated datasets with map, sampling, palette, and basemap controls. |
| [![view_maps_3d preview](apps-pages-gallery/view_maps_3d.svg)](view_maps_3d)<br>**view_maps_3d**<br>Shows geospatial data in Deck.gl with extrusion, color, and overlay controls. | [![view_maps_network preview](apps-pages-gallery/view_maps_network.svg)](view_maps_network)<br>**view_maps_network**<br>Synchronizes topology, routes, allocations, trajectories, and geographic views. |
| [![view_queue_resilience preview](apps-pages-gallery/view_queue_resilience.svg)](view_queue_resilience)<br>**view_queue_resilience**<br>Reviews queue occupancy, packet events, routing summaries, and run metadata. | [![view_relay_resilience preview](apps-pages-gallery/view_relay_resilience.svg)](view_relay_resilience)<br>**view_relay_resilience**<br>Compares relay queue health, route usage, and exported node motion traces. |
| [![view_release_decision preview](apps-pages-gallery/view_release_decision.svg)](view_release_decision)<br>**view_release_decision**<br>Builds an evidence cockpit for candidate/baseline review and promotion gates. | [![view_routing_model_comparison preview](apps-pages-gallery/view_routing_model_comparison.svg)](view_routing_model_comparison)<br>**view_routing_model_comparison**<br>Compatibility route backed by the canonical inference comparison page. |
| [![view_scenario_cockpit preview](apps-pages-gallery/view_scenario_cockpit.svg)](view_scenario_cockpit)<br>**view_scenario_cockpit**<br>Packages baseline/candidate scenario evidence and promotion-gate deltas. | [![view_shap_explanation preview](apps-pages-gallery/view_shap_explanation.svg)](view_shap_explanation)<br>**view_shap_explanation**<br>Displays local feature-attribution evidence without depending on a specific explainer runtime. |
| [![view_training_analysis preview](apps-pages-gallery/view_training_analysis.svg)](view_training_analysis)<br>**view_training_analysis**<br>Browses scalar training runs from TensorBoard logs or AGILAB training-history CSVs. |  |

Quick start (dev checkout):

- view_maps
  - uv run streamlit run src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py -- --active-app src/agilab/apps/builtin/flight_telemetry_project

- view_maps_3d
  - uv run streamlit run src/agilab/apps-pages/view_maps_3d/src/view_maps_3d/view_maps_3d.py -- --active-app src/agilab/apps/builtin/flight_telemetry_project

- view_maps_network
  - uv run streamlit run src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py -- --active-app src/agilab/apps/builtin/uav_relay_queue_project
  - Sidebar accepts an allocations file (JSON/Parquet) and an optional trajectory glob to animate per-timestep routes/capacities.

- view_barycentric
  - uv run streamlit run src/agilab/apps-pages/view_barycentric/src/view_barycentric/view_barycentric.py -- --active-app src/agilab/apps/builtin/flight_telemetry_project

- view_forecast_analysis
  - uv run streamlit run src/agilab/apps-pages/view_forecast_analysis/src/view_forecast_analysis/view_forecast_analysis.py -- --active-app src/agilab/apps/builtin/weather_forecast_project
  - Designed for notebook-to-AGILAB forecasting migrations. Reads `forecast_metrics.json` and `forecast_predictions.csv` from the selected export directory.

- view_release_decision
  - uv run streamlit run src/agilab/apps-pages/view_release_decision/src/view_release_decision/view_release_decision.py -- --active-app src/agilab/apps/builtin/weather_forecast_project
  - Compares a candidate bundle against a baseline bundle, applies explicit evidence gates, and exports `promotion_decision.json`.

- view_shap_explanation
  - uv run streamlit run src/agilab/apps-pages/view_shap_explanation/src/view_shap_explanation/view_shap_explanation.py -- --active-app src/agilab/apps/builtin/minimal_app_project
  - Displays local feature-attribution evidence exported by SHAPKit, the modern `shap` package, or a compatible custom explainer.

- view_queue_resilience
  - uv run streamlit run src/agilab/apps-pages/view_queue_resilience/src/view_queue_resilience/view_queue_resilience.py -- --active-app src/agilab/apps/builtin/uav_queue_project
  - Generic queue telemetry analysis page. Reads `*_summary_metrics.json`, `*_queue_timeseries.csv`, `*_packet_events.csv`, `*_node_positions.csv`, and `*_routing_summary.csv`.

- view_scenario_cockpit
  - uv run streamlit run src/agilab/apps-pages/view_scenario_cockpit/src/view_scenario_cockpit/view_scenario_cockpit.py -- --active-app src/agilab/apps/builtin/uav_relay_queue_project
  - Baseline/candidate scenario evidence page. Compares exported queue-analysis runs and downloads a hashed JSON evidence bundle.

- view_relay_resilience
  - uv run streamlit run src/agilab/apps-pages/view_relay_resilience/src/view_relay_resilience/view_relay_resilience.py -- --active-app src/agilab/apps/builtin/uav_relay_queue_project
  - Generic relay queue comparison page. Reads `*_summary_metrics.json`, `*_queue_timeseries.csv`, `*_packet_events.csv`, `*_node_positions.csv`, and `*_routing_summary.csv`.
  - The same run also exports `pipeline/topology.gml`, `pipeline/allocations_steps.csv`, `_trajectory_summary.json`, and per-node trajectory CSVs so `view_maps_network` can reuse the scenario directly.

- view_training_analysis
  - uv run streamlit run src/agilab/apps-pages/view_training_analysis/src/view_training_analysis/view_training_analysis.py -- --active-app src/agilab/apps/builtin/flight_telemetry_project
  - Generic scalar browser for apps that export TensorBoard logs under `tensorboard/` or AGILAB training history under `data/training_history.csv`.

- view_inference_analysis
  - uv run streamlit run src/agilab/apps-pages/view_inference_analysis/src/view_inference_analysis/view_inference_analysis.py -- --active-app src/agilab/apps/builtin/flight_telemetry_project
  - Generic allocations comparison page for `allocations_steps.{json,jsonl,ndjson,csv,parquet}` exports. It can aggregate metrics such as mean `delivered_bandwidth` across multiple folders and plot them side by side.

- view_live_artifacts
  - uv run streamlit run src/agilab/apps-pages/view_live_artifacts/src/view_live_artifacts/view_live_artifacts.py -- --active-app src/agilab/apps/builtin/flight_telemetry_project
  - Generic live monitor for exported evidence, manifests, logs, JSON/CSV/text files, and images. Uses Streamlit fragment refresh to update the artifact panel without executing the app.

- app_ui
  - uv run streamlit run src/agilab/apps-pages/app_ui/src/app_ui/app_ui.py -- --active-app src/agilab/apps/builtin/pytorch_playground_project
  - Generic bridge for app-owned Streamlit UIs declared in `[pages.app_ui]`. The page stays app-agnostic; the active app owns the UI entrypoint, controls, execution semantics, and evidence artifacts.

Notes
- The `--active-app` points to a `*_project` folder (e.g., `src/agilab/apps/builtin/flight_telemetry_project`).
- Sidecar page launch commands require `--active-app`; AGILAB ANALYSIS passes it when opening a selected page from the UI.
- Data directory defaults to the app’s export folder (e.g. `~/export/<app>`); adjust in the sidebar if needed.
- AGILAB Analysis can scaffold new custom page bundles from the same panel:
  - Use **Create** to generate a minimal complete bundle.

Experimental and opt-in views:

- autoencoder_latentspace
  - uv run streamlit run src/agilab/apps-pages/autoencoder_latentspace/src/autoencoder_latentspace/main.py -- --active-app src/agilab/apps/builtin/flight_telemetry_project
  - Opt-in playground exception for Python 3.12 teaching sessions. It trains a small TensorFlow/Keras autoencoder in-page, so it is intentionally not part of the public `agi-pages` umbrella or the generic app-agnostic sidecar set.

## Repository Pages (optional)

- This repository ships with built-in pages under `src/agilab/apps-pages`.
- You can also point the installer to an external repository that contains additional pages using PowerShell:
  - `./install.ps1 -InstallApps -AppsRepository "C:\\path\\to\\your-apps-repo"`
  - The external repo must have either `apps-pages` or `src/agilab/apps-pages` at its root.
- Merge behavior when both built-in and external provide the same page name:
  - If the destination page folder already exists and is not a link, it is left untouched (built-in wins).
  - Otherwise, the installer creates a link/junction from `src/agilab/apps-pages/<name>` to the external repo.
- You can limit which built-in pages are considered via environment variables:
  - `BUILTIN_PAGES_OVERRIDE="page1,page2"` or `BUILTIN_PAGES="page1 page2"`.
