# view_queue_resilience

Streamlit analysis page for queue telemetry exported by any app that writes the
AGILAB queue-analysis artifact contract.

## What It Reads

- `*_summary_metrics.json`
- `*_queue_timeseries.csv`
- `*_packet_events.csv`
- `*_node_positions.csv`
- `*_routing_summary.csv`

Default artifact root:

- `~/export/<app_target>/queue_analysis`

Run a compatible app once from `ORCHESTRATE` before opening this page from
`ANALYSIS`. The command below uses the built-in queue demo as a local fixture.

## Development Run

```bash
uv --preview-features extra-build-dependencies run streamlit run src/agilab/apps-pages/view_queue_resilience/src/view_queue_resilience/view_queue_resilience.py -- --active-app src/agilab/apps/builtin/uav_queue_project
```
