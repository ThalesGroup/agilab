# Data IO 2026 Project

Autonomous mission-data decision demo for AGILAB.

`data_io_2026_project` is the first-class public AGILAB demo for the Data IO
2026 storyline. It is a deterministic mission-decision app, not a media-only
storyboard.

## What It Shows

The app turns a compact mission scenario into a repeatable decision loop:

1. Ingest mission data from simulated sensors, network status, and operational constraints.
2. Generate the pipeline stages required for the scenario.
3. Distribute scenario execution across AGILAB workers.
4. Score candidate routes with a deterministic optimization policy.
5. Inject a mission event and re-plan.
6. Export a final decision with latency, cost, and reliability deltas.

The app is intentionally deterministic so it can be used in public demos, automated tests,
and Hugging Face Spaces without private datasets or external services.

It also includes an offline FRED-shaped public macro-context fixture. That proves
how an external public data source can feed the feature-evidence table without
requiring a live network call, API key, or `fredapi` dependency. Custom demos can
opt in to the public FRED CSV endpoint later through the app-local helper module.

## Quick Run

From the AGILAB UI:

1. `PROJECT` -> select `src/agilab/apps/builtin/data_io_2026_project`.
2. `ORCHESTRATE` -> `INSTALL`, then `EXECUTE`.
3. `ANALYSIS` -> open the default `view_data_io_decision` page.

Expected successful result:

- seeded scenario: `mission_decision_demo.json`
- initial strategy: `direct_satcom`
- adapted strategy: `relay_mesh`
- decision deltas are shown versus the no-replan outcome

## Outputs

Each run writes artifacts under `data_io_2026/results` and mirrors the
analysis-ready bundle under `export/data_io_2026/data_io_decision`:

- `*_summary_metrics.json`
- `*_mission_decision.json`
- `*_generated_pipeline.json`
- `*_sensor_stream.csv`
- `*_feature_table.csv`
- `*_candidate_routes.csv`
- `*_decision_timeline.csv`

Open `view_data_io_decision` from the ANALYSIS page to inspect the selected strategy,
the pre/post-failure metrics, and the adaptation timeline.

The feature table includes deterministic FRED-compatible fixture rows under the
`fred_fixture` source label. These rows are context evidence only; the default
route-scoring policy remains fully deterministic and mission-scenario driven.

## Scope

This demo uses a public synthetic scenario and deterministic scoring. It proves
AGILAB’s setup -> execution -> analysis path for an autonomous decision workflow.
It does not claim live production telemetry, production MLOps governance, or
first-class runtime expansion of arbitrary pipeline stages.
