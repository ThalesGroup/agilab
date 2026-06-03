# Mission Decision Project

`mission_decision_project` is the deterministic public AGILAB demo for an
autonomous mission decision loop.

## Purpose

Use this app to show how mission data, candidate routes, operational
constraints, and a failure event become replayable decision evidence. It is
designed for public demos and tests, so the default run uses synthetic data and
does not require private services.

## What You Learn

- How AGILAB turns a mission scenario into pipeline stages and worker tasks.
- How route candidates are scored with deterministic evidence.
- How a mission event triggers re-planning and exposes before/after deltas.
- How public FRED-shaped context can be included as fixture evidence without a
  live API dependency or `fredapi` package.
- How `view_data_io_decision` reads the exported decision bundle.

## Run In AGILAB

1. Select `mission_decision_project` in `PROJECT`.
2. Open `ORCHESTRATE`.
3. Run `INSTALL`, then `EXECUTE`.
4. Open `ANALYSIS` and select `view_data_io_decision`.

## Expected Inputs

The default input is the seeded `mission_decision_demo.json` scenario plus
deterministic public macro-context fixture rows.

## Expected Outputs

The app writes artifacts under `mission_decision/results` and mirrors the
analysis bundle under `export/mission_decision/data_io_decision`, including
summary metrics, mission decision JSON, generated pipeline JSON, sensor stream,
feature table, candidate routes, and decision timeline CSV files.

## Change One Thing

After the default run works, adjust one route constraint or event severity. The
selected strategy and decision deltas should change without introducing
nondeterministic inputs.

## Troubleshooting

If the analysis page is empty, confirm the mirrored `data_io_decision` bundle
exists. If a route score looks surprising, inspect the candidate-routes CSV
before changing the deterministic policy.

## Scope

This app proves AGILAB setup, execution, and analysis for a mission decision
storyline. It does not claim live telemetry, production autonomy governance, or
runtime expansion of arbitrary pipeline stages.
