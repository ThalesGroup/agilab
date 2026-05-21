# agi-app-pytorch-playground

[![PyPI version](https://img.shields.io/pypi/v/agi-app-pytorch-playground.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-pytorch-playground/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-pytorch-playground.svg)](https://pypi.org/project/agi-app-pytorch-playground/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-pytorch-playground)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-pytorch-playground` publishes the `pytorch_playground_project` AGILAB
app as a self-contained PyPI payload. It turns an interactive neural-network
playground into an executable AGILAB app with persisted arguments, worker
execution, and deterministic evidence artifacts.

## Purpose

Use this package to train a small PyTorch classifier on generated visual
datasets, inspect the resulting boundary/layers/loss terrain, and keep the
configuration and artifacts replayable.

## Installed Project

The distribution name is `agi-app-pytorch-playground`; the AGILAB project name
is `pytorch_playground_project`. The package exposes both
`pytorch_playground` and `pytorch_playground_project` through the `agilab.apps`
entry point group, so `AgiEnv(app="pytorch_playground_project")` resolves the
project without a monorepo checkout.

## Install

```bash
pip install agi-app-pytorch-playground
```

The app project itself installs PyTorch when AGILAB prepares its project
environment. The payload package stays lightweight and only exposes the project
root.

## Run In AGILAB

Select `pytorch_playground_project`, open `ORCHESTRATE`, tune the sidebar
fields, then run `INSTALL` and `EXECUTE`. Enable loss-landscape computation
only when you want the heavier 3D projection in the evidence bundle.

## Expected Inputs

The default run generates a synthetic dataset. No external dataset, API key,
notebook, cloud service, or private model is required.

## Expected Outputs

The run writes the playground config, samples, training history, decision grid,
network-layer summary, activation maps, optional loss landscape, a manifest,
and a deterministic evidence ZIP.

## Change One Thing

Switch the dataset from circles to XOR or spiral, then rerun the app. The
manifest and training-history artifacts should make the changed behavior
auditable.

## Scope

This is an educational reproducibility app. It is not a production trainer,
model registry, serving stack, or generic app-agnostic analysis page.
