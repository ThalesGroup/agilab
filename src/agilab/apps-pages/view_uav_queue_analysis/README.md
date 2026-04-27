# view_uav_queue_analysis

Streamlit analysis page for the built-in lightweight UAV queue example
(`uav_queue_project` install id).

## What It Reads

- `*_summary_metrics.json`
- `*_queue_timeseries.csv`
- `*_packet_events.csv`
- `*_node_positions.csv`
- `*_routing_summary.csv`

Default artifact root:

- `~/export/<app_target>/queue_analysis`

Run `uav_queue_project` once from `ORCHESTRATE` before opening this page from
`ANALYSIS`.

## Development Run

```bash
uv --preview-features extra-build-dependencies run streamlit run src/agilab/apps-pages/view_uav_queue_analysis/src/view_uav_queue_analysis/view_uav_queue_analysis.py -- --active-app src/agilab/apps/builtin/uav_queue_project
```
