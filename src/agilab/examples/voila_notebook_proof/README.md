# Voila Notebook Proof Preview

## Purpose

Show how a notebook dashboard can become an AGILAB app adoption bridge without
requiring a Voila server, a notebook kernel, or ipywidgets during the preview.

## What You Learn

- how a notebook dashboard keeps a familiar stakeholder interface
- how stable widgets map to AGILAB app arguments
- where app-specific UI and worker code should live
- which evidence files make the bridge auditable

## Install

From a source checkout, install the normal AGILAB development dependencies. No
extra Voila dependency is required for this preview.

```bash
uv sync
```

## Run

```bash
uv --preview-features extra-build-dependencies run python src/agilab/examples/voila_notebook_proof/preview_voila_notebook_proof.py
```

Use a temporary output directory when testing:

```bash
uv --preview-features extra-build-dependencies run python src/agilab/examples/voila_notebook_proof/preview_voila_notebook_proof.py --output-dir /tmp/agilab-voila-proof --json
```

## Expected Input

No external input is required. The script creates a small dashboard notebook and
sidecar contracts from deterministic fixtures.

## Expected Output

The default output directory is:

```text
~/log/execute/voila_notebook_proof/
```

It contains:

```text
dashboard.ipynb
widget_to_args.json
hidden_code_manifest.json
agilab_app_view_plan.json
dashboard_app_preview.html
voila_notebook_evidence.json
```

## Expected Preview

Open `dashboard_app_preview.html` to inspect the static adoption plan. Open
`dashboard.ipynb` to see the notebook shape that a future Voila runtime could
serve.

## Read The Script

Start with `build_preview()`. It writes the notebook, widget-to-args contract,
hide-code manifest, app-view plan, and evidence hashes.

## Change One Thing

Add one field to `widget_to_args_contract()`, rerun the preview, and compare the
hashes in `voila_notebook_evidence.json`.

## Troubleshooting

- If `uv sync` is slow, run only the script with the checkout environment already
  created.
- If a generated path is not where you expect, pass `--output-dir`.
- If you need a real Voila server, treat this preview as the contract first; the
  optional runtime integration is still roadmap.
