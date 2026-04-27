# view_uav_relay_queue_analysis

Streamlit analysis page for the built-in UAV relay queue example
(`uav_relay_queue_project` install id).

## What It Shows

- queue occupancy over time
- packet delivery and delay
- relay route usage
- exported node motion traces

## Expected Inputs

The page reads artifacts exported by `uav_relay_queue_project`, including:

- `*_summary_metrics.json`
- `*_queue_timeseries.csv`
- `*_packet_events.csv`
- `*_node_positions.csv`
- `*_routing_summary.csv`

Run the app once from `ORCHESTRATE` before opening this page from `ANALYSIS`.

## Development Run

```bash
uv --preview-features extra-build-dependencies run streamlit run src/agilab/apps-pages/view_uav_relay_queue_analysis/src/view_uav_relay_queue_analysis/view_uav_relay_queue_analysis.py -- --active-app src/agilab/apps/builtin/uav_relay_queue_project
```
