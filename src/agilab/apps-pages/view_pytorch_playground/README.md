# View PyTorch Playground

Source-only AGILAB analysis page for interactive PyTorch classifier experiments on
small synthetic datasets. It is inspired by the TensorFlow Playground workflow,
but it uses an original Streamlit implementation and trains an actual PyTorch
model.

Quick start:

- `uv run streamlit run src/agilab/apps-pages/view_pytorch_playground/src/view_pytorch_playground/view_pytorch_playground.py -- --active-app src/agilab/apps/builtin/flight_telemetry_project`

Packaging:

- This page is intentionally not part of the public `agi-pages` umbrella because
  `torch` is a heavy runtime dependency.
- Keep it source-only unless AGILAB introduces an explicit heavy/teaching page
  extra.
