# agi-app-minimal

Built-in AGILAB minimal Polars manager and worker example. This provider packages the Python-authored `minimal_app_project` project and its worker for the native AGILAB interface and notebook exports, without Streamlit.

Initial delivery uses AGILAB release assets (wheel and source archive); this provider is not promoted to PyPI. Install the matching release wheel together with AGILAB 2026.10.04. The `agilab.apps` entry points resolve both `minimal_app` and `minimal_app_project`.

The project provides a minimal Polars pipeline. Install the app project's declared Python dependencies when deploying its manager and worker.

License: BSD-3-Clause. See `LICENSE`.
