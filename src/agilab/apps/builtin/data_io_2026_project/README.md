# Data IO 2026 Project

Autonomous mission-data decision demo for AGILAB.

This built-in app turns a compact mission scenario into a repeatable decision loop:

1. Ingest mission data from simulated sensors, network status, and operational constraints.
2. Generate the pipeline stages required for the scenario.
3. Distribute scenario execution across AGILAB workers.
4. Score candidate routes with a deterministic optimization policy.
5. Inject a mission event and re-plan.
6. Export a final decision with latency, cost, and reliability deltas.

The app is intentionally deterministic so it can be used in public demos, automated tests,
and Hugging Face Spaces without private datasets or external services.

## Outputs

Each run writes artifacts under `data_io_2026/results` and mirrors the analysis-ready
bundle under `export/<target>/data_io_decision`:

- `*_summary_metrics.json`
- `*_mission_decision.json`
- `*_generated_pipeline.json`
- `*_sensor_stream.csv`
- `*_feature_table.csv`
- `*_candidate_routes.csv`
- `*_decision_timeline.csv`

Open `view_data_io_decision` from the ANALYSIS page to inspect the selected strategy,
the pre/post-failure metrics, and the adaptation timeline.
