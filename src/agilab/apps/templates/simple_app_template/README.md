# Simple App Template

Use this template for an AGILAB app that does not need a worker, scheduler, or
distributed execution contract yet.

## What This Template Provides

- A local app package under `src/simple_app/`.
- Pydantic-backed runtime arguments in `simple_app_args.py`.
- A Streamlit argument form in `src/app_args_form.py`.
- Local artifact output wiring through AGILAB path/settings helpers.
- A small `run()` method that writes a deterministic manifest.

## When To Use It

Choose this template for:

- notebook-derived local tools
- interactive playgrounds
- reports and explainers
- apps that generate artifacts directly from the manager process

Choose a worker template instead when the app needs AGILAB `INSTALL`/`RUN`
worker deployment, Dask, worker-specific dependencies, or a distributed task
plan.

## Create A New App

1. Copy this directory to a new `<name>_project` directory.
2. Rename `your_simple_project` in `pyproject.toml`.
3. Rename the Python package from `simple_app` to the app package name.
4. Replace the placeholder arguments and `run()` implementation with the app
   contract.
5. Add focused tests for argument loading, artifact generation, and exported
   evidence.

## First Local Check

From the repository root, create the app from PROJECT, select it, then open the
app argument form:

```bash
uv --preview-features extra-build-dependencies run --extra ui streamlit run src/agilab/main_page.py
```

This template is intentionally workerless. Add a worker template only when the
app needs distributed execution.
