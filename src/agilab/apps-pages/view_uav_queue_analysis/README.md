# view_uav_queue_analysis

Streamlit analysis page for the built-in UAV relay queue example (`uav_queue_project` install id).

What it reads:

- `*_summary_metrics.json`
- `*_queue_timeseries.csv`
- `*_packet_events.csv`
- `*_node_positions.csv`
- `*_routing_summary.csv`

Default artifact root:

- `~/export/<app_target>/queue_analysis`

Quick start:

- `uv run streamlit run src/agilab/apps-pages/view_uav_queue_analysis/src/view_uav_queue_analysis/view_uav_queue_analysis.py -- --active-app src/agilab/apps/builtin/uav_queue_project`
