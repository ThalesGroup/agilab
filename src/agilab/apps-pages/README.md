# Apps-Pages: Streamlit Views

This folder contains Streamlit pages for visualising AGILab data and maps. Each page expects an
active app and its exported datasets.

Page projects depend on `agi-gui`, the shared UI package under `src/agilab/lib/agi-gui`.

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

- view_autoencoder_latentspace
  - uv run streamlit run src/agilab/apps-pages/view_autoencoder_latenspace/src/view_autoencoder_latentspace/view_autoencoder_latentspace.py -- --active-app src/agilab/apps/builtin/flight_telemetry_project

- view_forecast_analysis
  - uv run streamlit run src/agilab/apps-pages/view_forecast_analysis/src/view_forecast_analysis/view_forecast_analysis.py -- --active-app src/agilab/apps/builtin/mycode_project
  - Designed for notebook-to-AGILAB forecasting migrations. Reads `forecast_metrics.json` and `forecast_predictions.csv` from the selected export directory.

- view_release_decision
  - uv run streamlit run src/agilab/apps-pages/view_release_decision/src/view_release_decision/view_release_decision.py -- --active-app src/agilab/apps/builtin/weather_forecast_project
  - Compares a candidate bundle against a baseline bundle, applies explicit evidence gates, and exports `promotion_decision.json`.

- view_shap_explanation
  - uv run streamlit run src/agilab/apps-pages/view_shap_explanation/src/view_shap_explanation/view_shap_explanation.py -- --active-app src/agilab/apps/builtin/mycode_project
  - Displays local feature-attribution evidence exported by SHAPKit, the modern `shap` package, or a compatible custom explainer.

- view_queue_resilience
  - uv run streamlit run src/agilab/apps-pages/view_queue_resilience/src/view_queue_resilience/view_queue_resilience.py -- --active-app src/agilab/apps/builtin/uav_queue_project
  - Generic queue telemetry analysis page. Reads `*_summary_metrics.json`, `*_queue_timeseries.csv`, `*_packet_events.csv`, `*_node_positions.csv`, and `*_routing_summary.csv`.

- view_relay_resilience
  - uv run streamlit run src/agilab/apps-pages/view_relay_resilience/src/view_relay_resilience/view_relay_resilience.py -- --active-app src/agilab/apps/builtin/uav_relay_queue_project
  - Generic relay queue comparison page. Reads `*_summary_metrics.json`, `*_queue_timeseries.csv`, `*_packet_events.csv`, `*_node_positions.csv`, and `*_routing_summary.csv`.
  - The same run also exports `pipeline/topology.gml`, `pipeline/allocations_steps.csv`, `_trajectory_summary.json`, and per-node trajectory CSVs so `view_maps_network` can reuse the scenario directly.

- view_training_analysis
  - uv run streamlit run src/agilab/apps-pages/view_training_analysis/src/view_training_analysis/view_training_analysis.py -- --active-app src/agilab/apps/builtin/flight_telemetry_project
  - Generic TensorBoard scalar browser for any app that exports trainer logs under a `tensorboard/` folder.

- view_inference_analysis
  - uv run streamlit run src/agilab/apps-pages/view_inference_analysis/src/view_inference_analysis/view_inference_analysis.py -- --active-app src/agilab/apps/builtin/flight_telemetry_project
  - Generic allocations comparison page for `allocations_steps.{json,jsonl,ndjson,csv,parquet}` exports. It can aggregate metrics such as mean `delivered_bandwidth` across multiple folders and plot them side by side.

Notes
- The `--active-app` points to a `*_project` folder (e.g., `src/agilab/apps/builtin/flight_telemetry_project`).
- Each page falls back to `APP_DEFAULT` env var, then tries a default `flight_telemetry_project` under the saved `~/.local/share/agilab/.agilab-path` if not provided.
- Data directory defaults to the app’s export folder (e.g. `~/export/<app>`); adjust in the sidebar if needed.
- AGILAB Analysis can scaffold new custom page bundles from the same panel:
  - Use **Create** to generate a minimal complete bundle.

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
