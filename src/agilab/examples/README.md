# AGILAB Packaged Examples

These examples are small Python entry points copied by the app installer into
`~/log/execute/<app>/`. They are meant to be readable first-run snippets for the
public built-in apps, not a separate workflow engine.

## Learning Path

Start with the examples in this order. Each step adds one concept while keeping
the command shape stable.

| Order | Example | App | Main lesson |
|---:|---|---|---|
| 1 | `flight` | `flight_project` | First proof: install one app, run one file, inspect map-ready output. |
| 2 | `mycode` | `mycode_project` | Smallest worker template and execution smoke. |
| 3 | `meteo_forecast` | `meteo_forecast_project` | Turn a notebook-style forecast into a reproducible app run. |
| 4 | `data_io_2026` | `data_io_2026_project` | Deterministic mission-data decision run with richer artifacts. |

## What To Notice

- `AGI_install_*.py` prepares the app environment and worker runtime.
- `AGI_run_*.py` builds a `RunRequest` and calls `AGI.run`.
- `data_in` and `data_out` are share-root relative paths, so examples stay
  portable across machines.
- Run modes use named AGI constants instead of magic numbers.
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
programmatic calls.
