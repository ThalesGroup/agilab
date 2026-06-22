# view_maps_network

![view_maps_network preview](apps-pages-gallery/view_maps_network.svg)

Package: `agi-page-network-map`

Synchronizes topology, routes, allocations, trajectories, and geographic views.

## When To Use It

Use for relay or satellite queue-analysis runs where route choice and link availability need visual inspection.

## Expected Inputs

- pipeline/topology.gml or routing edge exports.
- pipeline/allocations_steps.csv or equivalent allocation exports.
- Trajectory CSV/Parquet files.

Open it from `ANALYSIS` after selecting a project, or run it directly while developing:

```bash
uv --preview-features extra-build-dependencies run streamlit run src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py -- --active-app src/agilab/apps/builtin/uav_relay_queue_project
```

## Quality Contract

This bundle has a local README, a source-controlled preview asset, direct test coverage, and uses the shared `agi_pages.runtime` page chrome.
