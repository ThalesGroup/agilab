# agi-app-r-runtime-bridge

Built-in AGILAB Rscript JSON and artifact stage bridge. This provider packages the Python-authored `r_runtime_bridge_project` project and its worker for the native AGILAB interface and notebook exports, without Streamlit.

Initial delivery uses AGILAB release assets (wheel and source archive); this provider is not promoted to PyPI. Install the matching release wheel together with AGILAB 2026.10.04. The `agilab.apps` entry points resolve both `r_runtime_bridge` and `r_runtime_bridge_project`.

R execution additionally requires an operator-installed R runtime with a working `Rscript` executable. Python package installation does not install R. Configure the app's `rscript` setting with its executable name or absolute path; the stage validates the script and captures stdout, stderr, JSON output and artifact evidence.

License: BSD-3-Clause. See `LICENSE`.
