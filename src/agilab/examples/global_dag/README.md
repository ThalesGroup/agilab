# Global DAG Example

## Purpose

Shows the same public cross-project DAG as `inter_project_dag`, but under the
name operators expect when using the PIPELINE global DAG runner. The example
plans a `flight_project` to `meteo_forecast_project` handoff, writes a
runner-state preview, and does not execute either app.

## What You Learn

- A global DAG coordinates several AGILAB app runs.
- Each DAG node names one project-level app stage.
- Each DAG edge names the artifact that makes a downstream app runnable.
- The runner-state preview explains what can run now and what is blocked.

## Install

There is no separate project install for this preview. Install AGILAB and the
public built-in apps, then run the script from the source checkout or packaged
examples.

## Run

From a source checkout:

```bash
python src/agilab/examples/global_dag/preview_global_dag.py
```

From an installed AGILAB package, copy the example path shown by your
environment or pass the source checkout explicitly:

```bash
python preview_global_dag.py --repo-root /path/to/agilab
```

You can locate the packaged script with:

```bash
python -c "from pathlib import Path; import agilab; print(Path(agilab.__file__).with_name('examples') / 'global_dag' / 'preview_global_dag.py')"
```

## Expected Input

The script reads `flight_to_meteo_global_dag.json`. The contract says:

- `flight_context` runs `flight_project` and produces
  `flight_reduce_summary`.
- `meteo_forecast_review` runs `meteo_forecast_project` and consumes
  `flight_reduce_summary`.

## Expected Output

The script writes a runner-state preview to
`~/log/execute/global_dag/runner_state.json` and prints a JSON summary. The
first project should be runnable, and the second should be blocked until the
flight summary artifact exists.

## Expected Preview

Read the output as a planning table:

| Project node | App | Status before dispatch | Why |
|---|---|---|---|
| `flight_context` | `flight_project` | `runnable` | It has no upstream artifact dependency. |
| `meteo_forecast_review` | `meteo_forecast_project` | `blocked` | It waits for `flight_reduce_summary` from `flight_context`. |

The important handoff is:

```text
flight_project -> flight_reduce_summary -> meteo_forecast_project
```

The preview dispatches only metadata:

| Field | Expected value | Meaning |
|---|---|---|
| `after_first_dispatch.dispatched_unit_id` | `flight_context` | The first project would be launched first. |
| `after_first_dispatch.run_status` | `running` | The preview moved one unit into the running state. |
| `real_app_execution` | `false` | No AGILAB app was actually executed. |

## Global DAG Versus Single-App Pipeline

A single app pipeline explains steps inside one project. A global DAG explains
how several projects exchange artifacts. Keep app-specific `pipeline_view.dot`
or `lab_steps.toml` files for the inner workflow, and use this global DAG
contract for the cross-app handoff.

## Read The Script

Open `preview_global_dag.py` and look for these functions first:

- `build_preview()` delegates to the maintained `inter_project_dag` preview and
  relabels the summary as `global_dag`.
- `main()` resolves the source or packaged layout, writes the runner-state
  preview, and prints JSON.

## Change One Thing

After the preview works, change only the artifact id in
`flight_to_meteo_global_dag.json` and run the script again. The validation
should fail because the edge no longer matches what the first node produces.
Restore the id before adapting the contract further.

## Troubleshooting

- If the script cannot find `.agilab-path`, run the AGILAB installer first or
  pass `--repo-root` from a source checkout.
- If validation says an app is missing, reinstall the public built-in apps.
- If a project is blocked, inspect `artifact_handoffs` in the printed JSON to
  see which upstream artifact is missing.
