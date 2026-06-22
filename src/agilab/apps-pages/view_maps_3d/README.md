# view_maps_3d

![view_maps_3d preview](apps-pages-gallery/view_maps_3d.svg)

Package: `agi-page-geospatial-3d`

Shows geospatial data in Deck.gl with extrusion, color, and overlay controls.

## When To Use It

Use when altitude, density, or height-encoded metrics need a spatial 3D view.

## Expected Inputs

- One or more geolocated datasets.
- Optional altitude or extrusion metric columns.

Open it from `ANALYSIS` after selecting a project, or run it directly while developing:

```bash
uv --preview-features extra-build-dependencies run streamlit run src/agilab/apps-pages/view_maps_3d/src/view_maps_3d/view_maps_3d.py -- --active-app src/agilab/apps/builtin/flight_telemetry_project
```

## Quality Contract

This bundle has a local README, a source-controlled preview asset, direct test coverage, and uses the shared `agi_pages.runtime` page chrome.
