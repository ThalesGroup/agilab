# Mycode Example

## Purpose

Runs `mycode_project`, the smallest built-in template for checking that AGILAB
can install and execute a worker project.

## What You Learn

- The smallest app shape that can be installed and executed by AGILAB.
- How to run a worker without bringing a dataset into the first experiment.
- Why some examples disable Cython while still using the same `AGI.run` API.

## Install

```bash
python ~/log/execute/mycode/AGI_install_mycode.py
```

## Run

```bash
python ~/log/execute/mycode/AGI_run_mycode.py
```

## Expected Input

No external dataset is required for the default smoke run.

## Expected Output

The run returns the worker result and writes standard AGILAB execution logs under
`~/log/execute/mycode/`.

## Read The Script

Open `AGI_run_mycode.py` and look for these lines first:

- `APP = "mycode_project"` selects the minimal built-in app.
- `NO_CYTHON_RUN_MODES` keeps this template focused on Python-compatible modes.
- `RunRequest(...)` is intentionally small because the worker owns the default
  behavior.

## Change One Thing

Use this example when creating a new app skeleton. First change only `APP` to
your copied project name, then add parameters to `RunRequest` one at a time.

## Troubleshooting

- If install succeeds but run returns nothing useful, inspect the worker source
  inside `mycode_project`.
- If the command cannot import AGILAB packages, run the app installer again.
- If you need dataset handling, move to `flight` or `meteo_forecast` before
  adding custom data paths here.
