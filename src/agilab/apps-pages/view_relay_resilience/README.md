# view_relay_resilience

Streamlit analysis page for relay queue telemetry exported by any app that
writes the AGILAB relay-resilience artifact contract.

## What It Shows

- queue occupancy over time
- packet delivery and delay
- relay route usage
- exported node motion traces

## Expected Inputs

The page reads exported queue-analysis artifacts, including:

- `*_summary_metrics.json`
- `*_queue_timeseries.csv`
- `*_packet_events.csv`
- `*_node_positions.csv`
- `*_routing_summary.csv`

Run a compatible app once from `ORCHESTRATE` before opening this page from
`ANALYSIS`. The command below uses the built-in relay demo as a local fixture.

## Development Run

```bash
uv --preview-features extra-build-dependencies run streamlit run src/agilab/apps-pages/view_relay_resilience/src/view_relay_resilience/view_relay_resilience.py -- --active-app src/agilab/apps/builtin/uav_relay_queue_project
```
