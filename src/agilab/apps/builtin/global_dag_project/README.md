# Global DAG Project

`global_dag_project` is the built-in AGILAB example for cross-app workflow
contracts.

It does not compete with an app-local `lab_stages.toml`. Instead, it shows how a
global DAG connects independent built-in apps through explicit artifact
handoffs.

## What It Shows

- a built-in app-owned DAG template under `dag_templates/`
- a `flight_project` stage that produces `flight_reduce_summary`
- a `meteo_forecast_project` stage that consumes that summary
- a read-only runner-state preview before any app is executed

## Typical Flow

1. Select `global_dag_project` in `WORKFLOW`.
2. Open `Workflow graph`.
3. Choose `Multi-app DAG`, then select the bundled global DAG template.
4. Inspect the runnable and blocked stages before dispatching or adapting it.

## Outputs

The preview helper writes a runner-state JSON file to
`~/log/execute/global_dag/runner_state.json`. The bundled DAG template itself is
read-only and safe to inspect without running the downstream apps.

## Scope

Use this project to learn cross-app orchestration. Use `flight_project` or
`uav_queue_project` when you want a domain app that executes real worker code.

## Reducer Contract Status

`global_dag_project` is template-preview only. It intentionally does not ship a
reducer contract because it demonstrates cross-app DAG contracts and runner
state, not a concrete worker merge output.
