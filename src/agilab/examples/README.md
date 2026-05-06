# AGILAB Packaged Examples

These examples are small Python entry points for public AGILAB workflows. The
app-specific `AGI_*.py` scripts are copied by the app installer into
`~/log/execute/<app>/`; the read-only previews stay in the package or source
checkout because they teach orchestration concepts without launching long-lived
or multi-app work.

## Learning Path

Start with the examples in this order. Each step adds one concept while keeping
the command shape stable.

| Order | Example | App | Main lesson |
|---:|---|---|---|
| 1 | `flight` | `flight_project` | First proof: install one app, run one file, inspect map-ready output. |
| 2 | `mycode` | `mycode_project` | Smallest worker template and execution smoke. |
| 3 | `meteo_forecast` | `meteo_forecast_project` | Turn a notebook-style forecast into a reproducible app run. |
| 4 | `notebook_migrations/skforecast_meteo_fr` | `meteo_forecast_project` | Packaged migration source: notebooks, artifacts, lab steps, and pipeline view. |
| 5 | `notebook_to_dask` | notebook import -> Dask pipeline | Read-only migration preview: code cells, artifact contracts, and a Dask pipeline view. |
| 6 | `data_io_2026` | `data_io_2026_project` | Deterministic mission-data decision run with richer artifacts. |
| 7 | `inter_project_dag` | `flight_project` -> `meteo_forecast_project` | Read-only DAG contract: app nodes, artifact handoff, and runner-state preview. |
| 8 | `service_mode` | `mycode_project` | Read-only service lifecycle preview: start, status, health, stop. |
| 9 | `mlflow_auto_tracking` | any pipeline app | Optional tracking preview: local evidence first, MLflow as the memory backend. |
| 10 | `resilience_failure_injection` | UAV relay scenario contract | Read-only resilience preview: inject a relay failure, compare fixed/replanned/search/policy responses. |

## What To Notice

- `AGI_install_*.py` prepares the app environment and worker runtime.
- `AGI_run_*.py` builds a `RunRequest` and calls `AGI.run`.
- `inter_project_dag/preview_inter_project_dag.py` plans a cross-project
  handoff without executing either app.
- `notebook_to_dask/preview_notebook_to_dask.py` shows how notebook cells become
  `lab_steps.toml`, a Dask solution slice, and an artifact contract.
- `tools/notebook_import_preflight.py` gives the same notebook import path a
  generic cleanup report plus artifact, pipeline-view, and app view-plan
  sidecars before you turn a notebook into a project.
- `notebook_migrations/skforecast_meteo_fr` keeps the weather-forecast source
  notebooks, exported artifacts, migrated `lab_steps.toml`, and conceptual
  pipeline view in the packaged examples tree.
- `service_mode/preview_service_mode.py` explains persistent-worker operations
  and health gates without starting a service.
- `mlflow_auto_tracking/preview_mlflow_auto_tracking.py` shows the intended
  tracker abstraction without creating a parallel AGILAB model registry.
- `resilience_failure_injection/preview_resilience_failure_injection.py` shows
  how a failure event and strategy comparison can be made explicit before a
  real trainer or simulator run.
- `data_in` and `data_out` are share-root relative paths, so examples stay
  portable across machines.
- Run modes use named AGI constants instead of magic numbers, and keep Cython
  off in packaged first-run examples so the demo is not tied to a compiled
  extension for a specific Python ABI.
- The examples are intentionally local-first: one scheduler, one worker, and
  deterministic public inputs.

## Typical Use

```bash
python ~/log/execute/flight/AGI_install_flight.py
python ~/log/execute/flight/AGI_run_flight.py
```

## How To Read An Example

1. Read the app README to understand the goal and expected output.
2. Open the install script and identify the app name and enabled modes.
3. Open the run script and find `RunRequest`.
4. Change one parameter only, rerun, and compare the output directory.

## When To Use These Scripts

Run `agilab first-proof --json` when you want the shortest packaged product
proof. Use these scripts when you want to inspect or adapt the generated
programmatic calls. Use `inter_project_dag` when you want to understand how
project-level app runs can be connected by explicit artifact contracts. Use
`notebook_to_dask` when you want to evaluate a notebook migration before
creating an app or running Dask. Use `service_mode` before enabling persistent
workers for an already-working app. Use `mlflow_auto_tracking` when you want
to show tracking as optional memory around AGILAB execution, not a competing
experiment system. Use `resilience_failure_injection` when you want to explain
fixed versus adaptive behavior on the same degraded scenario before training or
serving a policy.
