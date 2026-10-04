# agi-app-minimal

## Purpose

Run a small Python-authored Polars pipeline through AGILAB's native interface.
This package provides a working manager and worker for reading tabular files
and writing their rows back as persisted artifacts. Use it as a starting point
when learning the application and notebook workflow.

## Installed Project

The distribution exposes minimal_app and minimal_app_project through the
agilab.apps provider group. AgiEnv(app="minimal_app_project") resolves its
embedded project without a source checkout. Python code, settings and the
worker remain available for inspection.

## Install

```bash
pip install agi-app-minimal==2026.10.4 --find-links /path/to/trusted-release-wheels
```

Download the matching official AGILAB GitHub Release wheels into that directory.
This payload is delivered as a wheel and source archive; it is not promoted
to PyPI. Install the matching AGILAB UI/notebook extras for those workflows.

## Run In AGILAB

Select minimal_app_project, configure the input and output locations, then
deploy and run from ORCHESTRATE. Inspect the persisted table in ANALYSIS or
export the application to a notebook with the native view helpers.

## Expected Inputs

Provide at least one CSV or Parquet file in the configured input directory.
The file pattern, file limit and row slicing settings control the selected data.
An empty matching input raises an explicit error.

## Expected Outputs

The worker writes a Parquet result containing the selected rows and worker
identity. It preserves the original data columns.

## Change One Thing

Reduce the row limit and rerun. Compare the persisted output row count with
the previous run before adding your own transformation.

## Scope

This example demonstrates file dispatch, Python worker execution and artifact
inspection. It does not train a model or provide application-specific analytics.
The native UI and notebook views do not require Streamlit.

License: BSD-3-Clause. See LICENSE.
