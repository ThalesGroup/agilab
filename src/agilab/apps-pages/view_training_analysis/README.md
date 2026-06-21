# view_training_analysis

![view_training_analysis preview](apps-pages-gallery/view_training_analysis.svg)

Package: `agi-page-training-report`

Browses scalar training runs from TensorBoard logs or AGILAB training-history CSVs.

## When To Use It

Use to compare trainers, tags, steps, and training curves before deeper model review.

## Expected Inputs

- tensorboard/ event logs.
- data/training_history.csv.

Open it from `ANALYSIS` after selecting a project, or run it directly while developing:

```bash
uv --preview-features extra-build-dependencies run streamlit run src/agilab/apps-pages/view_training_analysis/src/view_training_analysis/view_training_analysis.py -- --active-app src/agilab/apps/builtin/flight_telemetry_project
```

## Quality Contract

This bundle has a local README, a source-controlled preview asset, direct test coverage, and uses the shared `agi_pages.runtime` page chrome.
