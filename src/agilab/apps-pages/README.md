# Apps-Pages: Streamlit Views

This folder contains Streamlit pages for visualising AGILab data and maps. Each page expects an
active app and its exported datasets.

Quick start (dev checkout):

- view_maps
  - uv run streamlit run src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py -- --active-app src/agilab/apps/flight_project

- view_maps_3d
  - uv run streamlit run src/agilab/apps-pages/view_maps_3d/src/view_maps_3d/view_maps_3d.py -- --active-app src/agilab/apps/flight_project

- view_maps_network
  - uv run streamlit run src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py -- --active-app src/agilab/apps/flight_project

- view_barycentric
  - uv run streamlit run src/agilab/apps-pages/view_barycentric/src/view_barycentric/view_barycentric.py -- --active-app src/agilab/apps/flight_project

- view_autoencoder_latentspace
  - uv run streamlit run src/agilab/apps-pages/view_autoencoder_latenspace/src/view_autoencoder_latentspace/view_autoencoder_latentspace.py -- --active-app src/agilab/apps/flight_project

Notes
- The `--active-app` points to a `*_project` folder (e.g., `src/agilab/apps/flight_project`).
- Each page falls back to `AGILAB_APP` env var, then tries a default `flight_project` under the saved `~/.local/share/agilab/.agilab-path` if not provided.
- Data directory defaults to the app’s export folder (e.g. `~/export/<app>`); adjust in the sidebar if needed.
