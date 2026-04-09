# view_uav_relay_queue_analysis

Streamlit analysis page for the built-in UAV relay queue example
(`uav_relay_queue_project` install id).

Use it to inspect:
- queue occupancy over time
- packet delivery and delay
- relay route usage
- exported node motion traces

Run directly during development:

- `uv run streamlit run src/agilab/apps-pages/view_uav_relay_queue_analysis/src/view_uav_relay_queue_analysis/view_uav_relay_queue_analysis.py -- --active-app src/agilab/apps/builtin/uav_relay_queue_project`
