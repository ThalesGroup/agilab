# Service Mode Example

## Purpose

Shows how to reason about AGILAB service mode before starting persistent
workers. The example uses `mycode_project` as the smallest public target and
previews the operator lifecycle:

```text
START -> STATUS -> HEALTH -> STOP
```

It is intentionally read-only by default. It evaluates a sample
`agi.service.health.v1` payload and writes an operator preview, but it does not
call `AGI.serve` or launch a service.

## What You Learn

- Service mode is queue-backed persistent worker execution, not an interactive
  RPC session.
- `start` creates persistent worker loops for an already-installed app.
- `status` tells the operator whether the service is running, idle, degraded,
  stopped, or in error.
- `health` exports machine-readable health JSON and applies SLA gates.
- `stop` should be called before changing topology or ending the session.

## Install

There is no separate project install for this preview. Install AGILAB and the
public built-in apps first. Use `mycode_project` when you later want the
smallest real service target.

## Run

From a source checkout:

```bash
uv --preview-features extra-build-dependencies run python src/agilab/examples/service_mode/preview_service_mode.py
```

From an installed AGILAB package, locate the packaged script:

```bash
python -c "from pathlib import Path; import agilab; print(Path(agilab.__file__).with_name('examples') / 'service_mode' / 'preview_service_mode.py')"
```

Then run it:

```bash
python preview_service_mode.py
```

## Expected Input

The script reads the built-in
`mycode_project/service_templates/sample_health_running.json` health payload:

- app: `mycode_project`
- status: `running`
- running workers: `1`
- unhealthy workers: `0`
- restarted workers: `0`

## Expected Output

The script writes:

```text
~/log/execute/service_mode/service_operator_preview.json
```

and prints a JSON summary. The expected health gate result is `ok` because the
sample service is running, has no unhealthy worker, and has no restart-rate
breach.

## Expected Preview

Read the output as an operator checklist:

| Stage | What it means | Real call when you are ready |
|---|---|---|
| `start` | Start persistent worker loops. | `AGI.serve(env, action="start", mode=AGI.DASK_MODE)` |
| `status` | Inspect the runtime state. | `AGI.serve(env, action="status")` |
| `health` | Export health JSON and apply gates. | `AGI.serve(env, action="health")` |
| `stop` | Stop loops before changing topology. | `AGI.serve(env, action="stop", shutdown_on_stop=False)` |

The health-gate interpretation should be:

| Field | Expected value | Meaning |
|---|---:|---|
| `status` | `running` | The service is active. |
| `workers_running_count` | `1` | One worker is alive. |
| `workers_unhealthy_count` | `0` | No worker violates health rules. |
| `restart_rate` | `0.0` | No worker restarted in the sample window. |
| `health_gate.ok` | `true` | The configured SLA gate passes. |

## Preview Versus Real Service Mode

This preview does not replace `AGI.serve`. It teaches the service lifecycle and
health-gate logic without starting persistent loops. A real service run requires
an installed app, Dask mode, a usable scheduler/workers configuration, and a
writable AGILAB share.

Use this preview to understand the operator sequence. Use ORCHESTRATE or an
explicit `AGI.serve` script when you want to start a real service.

## Read The Script

Open `preview_service_mode.py` and look for these functions first:

- `service_action_sequence()` lists the lifecycle actions in operator order.
- `evaluate_health_gate()` explains the SLA decision from the health payload.
- `build_preview()` writes the preview JSON and marks
  `real_service_execution = false`.

## Change One Thing

Copy the built-in health template, change `workers_unhealthy_count` from `0` to
`1`, rerun the preview with `--health-payload <copy>.json`, and inspect
`health_gate.reason`. Restore the value before using the sample as a passing
baseline.

## Troubleshooting

- If the preview fails to read JSON, validate that the health template is still
  a JSON object.
- If `health_gate.ok` is `false`, inspect `health_gate.details` before changing
  thresholds.
- If a real service start fails, first confirm the normal `AGI_run_*.py` example
  works for the same app, then check Dask mode, scheduler/workers, and share
  paths.
