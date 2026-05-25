# view_live_artifacts

`view_live_artifacts` is an app-agnostic AGILAB analysis page for watching an
active app's exported evidence while a run is still producing files.

It does not execute the app or interpret domain-specific outputs. It scans a
selected artifact root, shows manifest candidates, computes a stable signature
from file metadata, and previews safe file types such as JSON, logs, CSV text,
and images. The page uses Streamlit's native fragment refresh so the artifact
panel can update automatically without rerunning the whole app.

## Run

```bash
uv --preview-features extra-build-dependencies run streamlit run src/agilab/apps-pages/view_live_artifacts/src/view_live_artifacts/view_live_artifacts.py -- --active-app src/agilab/apps/builtin/flight_telemetry_project
```

## Artifact conventions

The page works with any file, but gives extra prominence to common evidence
manifests:

- `live_state.json`
- `analysis_manifest.json`
- `run_manifest.json`
- `manifest_index.json`

Apps that want a richer live view should write one of those manifest files under
their export or run directory. The page remains generic and only renders what the
active app has already exported.
