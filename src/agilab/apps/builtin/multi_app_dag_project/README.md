# Multi-app DAG Project

`multi_app_dag_project` is the built-in read-only example for cross-app DAG
contracts.

## Purpose

Use this project to inspect how independent AGILAB apps can be connected through
explicit artifact handoffs before any app is executed.

## What You Learn

- How a DAG template can live with the app that teaches it.
- How `flight_telemetry_project` can produce a handoff consumed by a weather
  stage.
- How runner-state previews expose runnable and blocked units.
- Why cross-app orchestration should keep artifact contracts explicit.

## Run In AGILAB

1. Select `multi_app_dag_project` in `WORKFLOW`.
2. Open `Workflow graph`.
3. Choose `Multi-app DAG`.
4. Select the bundled flight-to-weather DAG template.
5. Inspect stage readiness and handoffs.

## Expected Inputs

The project ships DAG templates under `dag_templates/`. No live app execution is
required for the preview.

## Expected Outputs

The preview writes runner-state JSON under `~/log/execute/multi_app_dag/` and
reports app stages, artifact dependencies, and dispatch readiness.

## Change One Thing

After the default preview works, edit a copy of the DAG template and change one
artifact handoff. The preview should make the affected downstream stage blocked
or runnable based on that contract.

## Troubleshooting

If the preview cannot find built-in apps, run AGILAB once from the source or
installed checkout so `.agilab-path` points at the package. If packaged preview
layout setup fails, inspect `~/.cache/agilab/multi_app_dag_layout`.

## Scope

This is a DAG-contract preview. It intentionally does not ship a reducer
contract because it does not execute a concrete worker merge output.
