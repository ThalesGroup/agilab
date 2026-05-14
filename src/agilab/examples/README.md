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
| 1 | `flight_telemetry` | `flight_telemetry_project` | First proof: install one app, run one file, inspect map-ready output. |
| 2 | `mycode` | `mycode_project` | Smallest worker template and execution smoke. |
| 3 | `weather_forecast` | `weather_forecast_project` | Turn a notebook-style forecast into a reproducible app run. |
| 4 | `notebook_migrations/skforecast_meteo_fr` | `weather_forecast_project` | Packaged migration source: notebooks, artifacts, lab stages, and pipeline view. |
| 5 | `notebook_to_dask` | notebook import -> Dask pipeline | Read-only migration preview: code cells, artifact contracts, and a Dask pipeline view. |
| 6 | `mission_decision` | `mission_decision_project` | Deterministic mission-data decision run with richer artifacts. |
| 7 | `global_dag_project` | `flight_telemetry_project` -> `weather_forecast_project` | Built-in app-owned global DAG contract: app nodes, artifact handoff, and runner-state preview. |
| 8 | `inter_project_dag` | `flight_telemetry_project` -> `weather_forecast_project` | Standalone compatibility preview for the same cross-project DAG concept. |
| 9 | `service_mode` | `mycode_project` | Read-only service lifecycle preview: start, status, health, stop. |
| 10 | `mlflow_auto_tracking` | any pipeline app | Optional tracking preview: local evidence first, MLflow as the memory backend. |
| 11 | `resilience_failure_injection` | UAV relay scenario contract | Read-only resilience preview: inject a relay failure, compare fixed/replanned/search/policy responses. |
| 12 | `train_then_serve` | trained policy handoff contract | Read-only service handoff preview: model artifact, IO contract, prediction sample, and health gate. |

## Execution Map

Use this table before choosing a command. The examples intentionally split real
app execution from read-only contract previews.

| Class | Examples | What actually runs | Primary output |
|---|---|---|---|
| Installed `AGI_*.py` helpers | `flight_telemetry`, `mycode`, `weather_forecast`, `mission_decision` | Real `AGI.install` / `AGI.run` calls from `~/log/execute/<app>/` after the app installer seeds the scripts. | App artifacts in AGILAB share/export paths plus execution logs. |
| Source/package read-only previews | `notebook_to_dask`, `inter_project_dag`, `service_mode`, `mlflow_auto_tracking`, `resilience_failure_injection`, `train_then_serve` | Deterministic Python preview scripts. They write JSON evidence and do not launch long-lived workers or hidden multi-app runs. | Preview JSON under `~/log/execute/<example>/` or the `--output` path. |
| Notebook migration assets | `notebook_migrations/skforecast_meteo_fr` | Packaged notebooks, artifacts, `lab_stages.toml`, and pipeline view used as migration source material. | Files to inspect or import; no service or cluster run is started by reading them. |

Source-checkout commands use `uv --preview-features extra-build-dependencies run python ...`
so dependencies resolve through the checkout environment. Commands under
`~/log/execute/<app>/` are installed helper scripts and are normally run after
AGILAB has initialized the target app environment.

## What To Notice

- `AGI_install_*.py` prepares the app environment and worker runtime.
- `AGI_run_*.py` builds a `RunRequest` and calls `AGI.run`.
- `global_dag_project` owns the packaged global DAG template under
  `src/agilab/apps/builtin/global_dag_project/dag_templates/`.
- `inter_project_dag/preview_inter_project_dag.py` remains as the standalone
  compatibility preview, but it reads the built-in `global_dag_project` DAG
  template by default.
- `notebook_to_dask/preview_notebook_to_dask.py` shows how notebook cells become
  `lab_stages.toml`, a Dask solution slice, and an artifact contract.
- `tools/notebook_import_preflight.py` gives the same notebook import path a
  generic cleanup report plus artifact, pipeline-view, and app view-plan
  sidecars before you turn a notebook into a project.
- `notebook_migrations/skforecast_meteo_fr` keeps the weather-forecast source
  notebooks, exported artifacts, migrated `lab_stages.toml`, and conceptual
  pipeline view in the packaged examples tree.
- `service_mode/preview_service_mode.py` reads a `mycode_project` built-in
  service template and explains persistent-worker operations without starting a
  service.
- `mlflow_auto_tracking/preview_mlflow_auto_tracking.py` reads a
  `weather_forecast_project` built-in tracking template and shows the intended
  tracker abstraction without creating a parallel AGILAB model registry.
- `resilience_failure_injection/preview_resilience_failure_injection.py` reads
  a `uav_queue_project` built-in scenario template and makes failure events
  explicit before a real trainer or simulator run.
- `train_then_serve/preview_train_then_serve.py` reads a
  `uav_relay_queue_project` built-in service template and shows the handoff
  from a trained policy artifact to a service contract.
- `data_in` and `data_out` are share-root relative paths, so examples stay
  portable across machines.
- Run modes use named AGI constants instead of magic numbers, and keep Cython
  off in packaged first-run examples so the demo is not tied to a compiled
  extension for a specific Python ABI.
- The examples are intentionally local-first: one scheduler, one worker, and
  deterministic public inputs.

## Typical Use

```bash
python ~/log/execute/flight_telemetry/AGI_install_flight_telemetry.py
python ~/log/execute/flight_telemetry/AGI_run_flight_telemetry.py
```

## Validate The Examples

From a source checkout, run the documentation and packaging guardrails that
keep examples copy/paste-safe:

```bash
uv --preview-features extra-build-dependencies run python -m py_compile $(find src/agilab/examples -name '*.py' -print)
uv --preview-features extra-build-dependencies run pytest -q test/test_app_installer_packaging.py::test_packaged_example_catalog_is_documented test/test_app_installer_packaging.py::test_packaged_example_readmes_teach_safe_adaptation test/test_app_installer_packaging.py::test_packaged_preview_example_scripts_are_compile_safe
```

## How To Read An Example

1. Read the app README to understand the goal and expected output.
2. Open the install script and identify the app name and enabled modes.
3. Open the run script and find `RunRequest`.
4. Change one parameter only, rerun, and compare the output directory.

## When To Use These Scripts

Run `agilab first-proof --json` when you want the shortest packaged product
proof. Use these scripts when you want to inspect or adapt the generated
programmatic calls. Select `global_dag_project` in WORKFLOW when you want to
understand how project-level app runs can be connected by explicit artifact
contracts, and use `inter_project_dag` only when you need the standalone
compatibility preview path. Use
`notebook_to_dask` when you want to evaluate a notebook migration before
creating an app or running Dask. Use `service_mode` before enabling persistent
workers for an already-working app. Use `mlflow_auto_tracking` when you want
to show tracking as optional memory around AGILAB execution, not a competing
experiment system. Use `resilience_failure_injection` when you want to explain
fixed versus adaptive behavior on the same degraded scenario before training or
serving a policy. Use `train_then_serve` when you want to explain what must be
frozen after training before a policy becomes service-ready.
