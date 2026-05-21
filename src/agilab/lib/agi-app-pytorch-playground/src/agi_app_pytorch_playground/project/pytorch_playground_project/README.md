# PyTorch Playground Project

Built-in AGILAB app for reproducible PyTorch classifier playground experiments.
It generates a small synthetic dataset, trains a real PyTorch classifier, and
exports deterministic evidence artifacts that can be replayed or inspected.

## Purpose

Use this project when you want a compact neural-network teaching workflow that
still behaves like an AGILAB app: controls are persisted in `app_settings.toml`,
`ORCHESTRATE` executes the run, and the worker writes CSV/JSON evidence plus a
deterministic ZIP bundle.

## Run In AGILAB

Select `pytorch_playground_project`, then open `ANALYSIS` for the app-owned
PyTorch Playground surface. That single surface contains the interactive
controls, decision boundary, training curves, neuron/loss views, and evidence
download.

Open `ORCHESTRATE` when you want the reproducible AGILAB execution path:
adjust the sidebar fields, then run `INSTALL` and `RUN`. The default
configuration trains the clean-circles preset and exports evidence under
`pytorch_playground/evidence`.

The app also keeps a local Streamlit playground surface for interactive review:

```bash
uv run streamlit run src/agilab/apps/builtin/pytorch_playground_project/src/pytorch_playground/playground_ui.py -- --active-app src/agilab/apps/builtin/pytorch_playground_project
```

## Expected Inputs

The default run generates its own synthetic dataset. No external file, cloud
service, notebook, API key, or private model is required.

## Expected Outputs

The worker writes:

- `config/playground_config.json`
- `data/samples.csv`
- `data/training_history.csv`
- `data/decision_grid.csv`
- `model/network_layers.csv`
- `model/hidden_activation_maps.csv`
- `model/loss_landscape.csv`
- `summary/run_summary.json`
- `manifest.json`
- `pytorch_playground_evidence.zip`

## Scope

This is a reproducible educational app for neural-network behavior and loss
landscape inspection. It owns its PyTorch-specific UI inside the app project;
generic apps-pages are only optional artifact readers such as cross-run scalar
inspection. It is not a model-serving platform, production training pipeline,
or generic app-agnostic analysis page.
