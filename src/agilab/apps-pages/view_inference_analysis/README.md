# view_inference_analysis

Reusable AGILAB ANALYSIS page for comparing metrics exported in
`allocations_steps` artifacts across multiple folders.

What it does:

- scans one root for `allocations_steps.json` by default
- supports `json`, `jsonl`, `ndjson`, `csv`, and `parquet` allocation exports
- flattens nested step payloads with `allocations` lists
- compares selected runs with fixed diagnostics for load, routing, latency,
  bearer mix, and source-destination flow heatmaps
- includes an optional advanced custom metric profile for ad hoc inspection

## Quick Start

- Open it from `ANALYSIS` after selecting a project and AGILAB will pass
  `--active-app` automatically.
- Standalone dev run:

```bash
uv --preview-features extra-build-dependencies run streamlit run src/agilab/apps-pages/view_inference_analysis/src/view_inference_analysis/view_inference_analysis.py -- --active-app src/agilab/apps/builtin/flight_telemetry_project
```
