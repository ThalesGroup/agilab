# agi-app-r-runtime-bridge

## Purpose

Execute an R script as an AGILAB stage while retaining Python application
authoring, settings and execution evidence. The bridge records process output
and lets the script produce JSON results and additional artifacts for analysis
or notebook handoff.

## Installed Project

The distribution exposes r_runtime_bridge and r_runtime_bridge_project through
the agilab.apps provider group. AgiEnv(app="r_runtime_bridge_project") resolves
the embedded manager, worker, settings and example R script without a source
checkout.

## Install

```bash
pip install agi-app-r-runtime-bridge==2026.10.4 --find-links /path/to/trusted-release-wheels
```

Download the matching official AGILAB GitHub Release wheels into that directory.
This payload is delivered as a wheel and source archive; it is not promoted
to PyPI. Install the matching AGILAB UI/notebook extras for those workflows.

Install R separately and provide a working Rscript executable. The bundled
example also requires the R package jsonlite. Installing this Python wheel
does not install R or its packages.

## Run In AGILAB

Select r_runtime_bridge_project and configure its rscript setting with an
executable name or absolute path. Deploy and run from ORCHESTRATE, then inspect
the results in ANALYSIS or export the application to a notebook.

## Expected Inputs

Provide the selected R script and its required R packages. Script arguments,
input files and output location follow the application's settings.

## Expected Outputs

The bridge captures stdout, stderr and process status, together with JSON
output and artifact evidence produced by the selected script.

## Change One Thing

Change an input value in the example script, rerun it, and compare the recorded
JSON summary and process output.

## Scope

The bridge executes operator-provided R code as a stage. It does not bundle R,
claim remote cluster validation, or require Streamlit for its native UI and
notebook views.

License: BSD-3-Clause. See LICENSE.
