# Inter-Project DAG Example

## Purpose

Shows how two AGILAB projects can be connected by a DAG contract without
inventing a second tracking or orchestration model. The example plans a
`flight_telemetry_project` to `weather_forecast_project` handoff and writes a read-only
runner-state preview.

## What You Learn

- A DAG node represents one project-level AGILAB run.
- A DAG edge represents an explicit artifact handoff between projects.
- Local `pipeline_view.dot` files still explain what happens inside each app.
- Runner state can show which project is runnable and which project is blocked
  before any real app execution happens.

## Install

There is no separate project install for this preview. Install AGILAB and the
public built-in apps, then run the script from the source checkout or from the
packaged examples. The DAG contract is owned by the built-in
`global_dag_project` app so UI users and script users share the same template.

## Run

From a source checkout:

```bash
python src/agilab/examples/inter_project_dag/preview_inter_project_dag.py
```

From an installed AGILAB package, copy the example path shown by your
environment or pass the source checkout explicitly:

```bash
python preview_inter_project_dag.py --repo-root /path/to/agilab
```

You can locate the packaged script with:

```bash
python -c "from pathlib import Path; import agilab; print(Path(agilab.__file__).with_name('examples') / 'inter_project_dag' / 'preview_inter_project_dag.py')"
```

## Expected Input

The script reads the built-in
`global_dag_project/dag_templates/flight_to_weather_global_dag.json` template.
The contract says:

- `flight_context` runs `flight_telemetry_project` and produces
  `flight_reduce_summary`.
- `weather_forecast_review` runs `weather_forecast_project` and consumes
  `flight_reduce_summary`.

## Expected Output

The script writes a runner-state preview to
`~/log/execute/inter_project_dag/runner_state.json` and prints a JSON summary.
The first project should be runnable, the second should be blocked until the
flight summary artifact exists.

## Expected Preview

Read the output as a planning table:

| Project node | App | Status before dispatch | Why |
|---|---|---|---|
| `flight_context` | `flight_telemetry_project` | `runnable` | It has no upstream artifact dependency. |
| `weather_forecast_review` | `weather_forecast_project` | `blocked` | It waits for `flight_reduce_summary` from `flight_context`. |

The important handoff is:

```text
flight_telemetry_project -> flight_reduce_summary -> weather_forecast_project
```

After the preview dispatches the first runnable unit, the runner state changes
only in metadata:

| Field | Expected value | Meaning |
|---|---|---|
| `after_first_dispatch.dispatched_unit_id` | `flight_context` | The first project would be launched first. |
| `after_first_dispatch.run_status` | `running` | The preview moved one unit into the running state. |
| `real_app_execution` | `false` | No AGILAB app was actually executed. |

## DAG Preview Versus AGI.run

This example does not replace `AGI.run`. A normal `AGI.run` call executes one
project with concrete parameters, workers, and output paths. This preview checks
the contract between projects before execution: which app should run first,
which artifact it must produce, and which downstream app is blocked until that
artifact exists.

Use this preview to design and review a multi-project workflow. Use the
app-specific `AGI_run_*.py` examples when you want to execute each project.

## Read The Script

Open `preview_inter_project_dag.py` and look for these functions first:

- `planning_repo_root()` locates the source or packaged app layout used for
  validation.
- `build_preview()` builds the execution plan, persists runner state, and
  previews the first dispatch.
- `_artifact_handoffs()` extracts the cross-project artifact dependency that
  makes the second project wait for the first.

## Change One Thing

After the preview works, copy
`src/agilab/apps/builtin/global_dag_project/dag_templates/flight_to_weather_global_dag.json`
to a scratch file, change only the artifact id, and rerun with
`--dag-path /path/to/scratch.json`. The validation should fail because the edge
no longer matches what the first node produces. Restore the id before adapting
the contract further.

## Troubleshooting

- If the script cannot find `.agilab-path`, run the AGILAB installer first or
  pass `--repo-root` from a source checkout.
- If validation says an app is missing, reinstall the public built-in apps.
- If a project is blocked, inspect `artifact_handoffs` in the printed JSON to
  see which upstream artifact is missing.
