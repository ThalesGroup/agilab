# view_maps

![view_maps preview](apps-pages-gallery/view_maps.svg)

Package: `agi-page-geospatial-map`

Explores geolocated datasets with map, sampling, palette, and basemap controls.

## When To Use It

Use first when latitude/longitude data needs a quick spatial sanity check.

## Expected Inputs

- CSV or Parquet with latitude/longitude columns.
- Optional app page defaults for data path and column names.

Open it from `ANALYSIS` after selecting a project, or run it directly while developing:

```bash
uv --preview-features extra-build-dependencies run streamlit run src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py -- --active-app src/agilab/apps/builtin/flight_telemetry_project
```

## Quality Contract

This bundle has a local README, a source-controlled preview asset, direct test coverage, and uses the shared `agi_pages.runtime` page chrome.
