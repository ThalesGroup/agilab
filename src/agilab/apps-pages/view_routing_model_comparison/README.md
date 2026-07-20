# view_routing_model_comparison

![view_routing_model_comparison preview](apps-pages-gallery/view_routing_model_comparison.svg)

Package: `agi-page-routing-model-comparison`

Compatibility route for projects that still declare
`view_routing_model_comparison`. It delegates to the canonical,
settings-driven `view_inference_analysis` page, preserving existing launcher
and package contracts without maintaining a second allocation-comparison
implementation.

New app configurations should declare `view_inference_analysis` directly. The
canonical page supports arbitrary run counts and common allocation formats,
active-demand reconciliation, latency-target and failure diagnostics,
label-safe flow matrices, and workspace-persisted controls.

Open it from `ANALYSIS` after selecting a project, or run the compatibility
entrypoint directly while developing:

```bash
uv --preview-features extra-build-dependencies run streamlit run src/agilab/apps-pages/view_routing_model_comparison/src/view_routing_model_comparison/view_routing_model_comparison.py -- --active-app /path/to/app_project
```

## Quality Contract

This bundle retains its entry point, preview, and direct compatibility tests.
Behavioral coverage lives with `view_inference_analysis`.
