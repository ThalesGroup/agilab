# PyTorch Playground Project

`pytorch_playground_project` is the built-in AGILAB app for reproducible
neural-network playground experiments.

## Purpose

Use this project to train a compact PyTorch classifier, watch the decision
boundary move with real play/pause controls, and export replayable evidence
without leaving the AGILAB app model.

## What You Learn

- How Streamlit controls map to persisted ORCHESTRATE arguments.
- How an app-owned ANALYSIS surface can show training curves, learning snapshots,
  neuron views, regularization effects, and loss landscape evidence.
- How the `[app_surface]` contract separates the app runtime/evidence files
  from the UI backend, so the same project can open locally or through a hosted
  surface.
- How live play/pause training differs from a deterministic full evidence run:
  live mode mutates one in-session model, while `Train / refresh` rebuilds the
  full reproducible artifact.
- How generated samples, history, grids, network metadata, and manifests become
  a deterministic evidence ZIP.
- How the UI isolates heavy PyTorch work from Streamlit while keeping typed JSON
  IPC at the subprocess boundary.

## Direct Launch

Use the app-managed environment so PyTorch, Plotly, and Streamlit are installed
in the right place:

```bash
agilab app surface pytorch_playground_project --list
agilab app surface pytorch_playground_project --ui streamlit
```

To open the hosted backend instead of a local app venv:

```bash
agilab app surface pytorch_playground_project --ui hf
```

`agilab pytorch-playground` and `agilab pytorch-playground --backend hf` are
convenience shortcuts for the same app. The generic `agilab app surface ...`
command is the reusable pattern for any app that declares `[app_surface]`. Set
`AGILAB_PYTORCH_PLAYGROUND_HF_URL` or pass `--hf-space owner/agilab` when you
maintain a different Hugging Face Space.

## Run In AGILAB

1. Select `pytorch_playground_project` in `PROJECT`.
2. Open `ANALYSIS` for the interactive playground surface.
3. Use the default clean-circles preset and either press `Train / refresh` for
   a full evidence run or switch `Training mode` to `Live play/pause`.
4. In live mode, press `Play`, `Pause`, or `Step` to watch the boundary and
   curves advance by bounded epoch ticks.
5. Open `Boundary lab` and change the `Boundary epoch` selector to see how the
   decision surface formed during training.
6. Open `Neuron lens` to read the network map, then change features, hidden
   layers, or regularization and refresh evidence again.
7. Open `ORCHESTRATE` when you want the reproducible install/run path.

## Expected Inputs

No external file is required. The app generates a deterministic synthetic
dataset from the selected preset, seed, feature set, and training parameters.

## Expected Outputs

The worker writes `playground_config.json`, samples, training history, decision
grid, boundary snapshots, network layers, hidden activation maps, optional loss landscape,
`run_summary.json`, `manifest.json`, and `pytorch_playground_evidence.zip`.

## Change One Thing

After the default run works, change only one learning control:

- Switch `Regularization` from `None` to `L2` and keep the rate small, for
  example `0.001`.
- For XOR, remove engineered features, refresh evidence, then add `x1_x2` back
  to see why feature toggles matter.
- Change only the hidden-layer tuple and compare the `Boundary epoch` snapshots.

The decision boundary and evidence manifest should update while the artifact
names stay stable.

## Troubleshooting

If PyTorch is unavailable, the app returns displayable `missing_torch` evidence
instead of crashing. If the isolated UI runner fails, inspect the displayed
diagnostic tail before changing model code.

## Scope

This is an educational PyTorch evidence app. It is not a model-serving platform
or a generic app-agnostic analysis page.
