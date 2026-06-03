# Minimal App Project

`minimal_app_project` is the smallest built-in AGILAB app template.

## Purpose

Use this project as the reference layout for a new app. It keeps the manager,
worker, settings seed, form, and compatibility alias small enough to inspect in
one sitting.

## What You Learn

- Which files an installable AGILAB app must provide.
- How `app_settings.toml`, `app_args_form.py`, and `pre_prompt.json` fit
  together.
- How a worker class is packaged for deployment.
- How to copy the shape before adding domain logic.

## Run In AGILAB

1. Select `minimal_app_project` in `PROJECT`.
2. Open `ORCHESTRATE`.
3. Run `INSTALL`.
4. Use it as a code reference before adapting a real app.

## Expected Inputs

No domain input is required. The app prepares app-owned input and output paths.

## Expected Outputs

The default worker writes minimal placeholder evidence and proves the packaging
contract. It is intentionally small.

## Change One Thing

Copy the project, rename the manager and worker modules, and add one real input
field before changing the execution contract.

## Troubleshooting

If a copied app does not appear in `PROJECT`, check the project suffix, root
`pyproject.toml`, and `src/app_settings.toml`. If a worker import fails, confirm
the worker package name matches the app manifest.

## Scope

This is a template-quality app, not a user-facing domain workflow. Use the
flight, weather, mission, or UAV apps when you need a complete demo.
