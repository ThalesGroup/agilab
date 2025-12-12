# Apps-Pages: Streamlit Views

This folder contains Streamlit pages for visualising AGILab data and maps. Each page expects an
active app and its exported datasets.

Quick start (dev checkout):

- view_maps
  - uv run streamlit run src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py -- --active-app src/agilab/apps/builtin/flight_project

- view_maps_3d
  - uv run streamlit run src/agilab/apps-pages/view_maps_3d/src/view_maps_3d/view_maps_3d.py -- --active-app src/agilab/apps/builtin/flight_project

- view_maps_network
  - uv run streamlit run src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py -- --active-app src/agilab/apps/builtin/flight_project
  - Sidebar accepts an allocations file (JSON/Parquet) and an optional trajectory glob to animate per-timestep routes/capacities.

- view_barycentric
  - uv run streamlit run src/agilab/apps-pages/view_barycentric/src/view_barycentric/view_barycentric.py -- --active-app src/agilab/apps/builtin/flight_project

- view_autoencoder_latentspace
  - uv run streamlit run src/agilab/apps-pages/view_autoencoder_latenspace/src/view_autoencoder_latentspace/view_autoencoder_latentspace.py -- --active-app src/agilab/apps/builtin/flight_project

Notes
- The `--active-app` points to a `*_project` folder (e.g., `src/agilab/apps/builtin/flight_project`).
- Each page falls back to `AGILAB_APP` env var, then tries a default `flight_project` under the saved `~/.local/share/agilab/.agilab-path` if not provided.
- Data directory defaults to the app’s export folder (e.g. `~/export/<app>`); adjust in the sidebar if needed.

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
