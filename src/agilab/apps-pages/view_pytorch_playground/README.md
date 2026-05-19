# View PyTorch Playground

Standalone AGILAB analysis page for interactive PyTorch classifier experiments on
small synthetic datasets. It is inspired by the TensorFlow Playground workflow,
but it uses an original Streamlit implementation and trains an actual PyTorch
model.

Quick start:

- `uv run streamlit run src/agilab/apps-pages/view_pytorch_playground/src/view_pytorch_playground/view_pytorch_playground.py -- --active-app src/agilab/apps/builtin/flight_telemetry_project`

Packaging:

- This page is published as the standalone `agi-page-pytorch-playground` package.
- It is intentionally not part of the public `agi-pages` umbrella because `torch`
  is a heavy runtime dependency.
- When installed explicitly, AGILAB discovers it through the `agilab.pages`
  entry point.
