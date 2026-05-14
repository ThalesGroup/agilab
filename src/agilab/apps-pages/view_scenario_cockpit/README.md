# view_scenario_cockpit

Streamlit evidence cockpit for comparing exported scenario runs and packaging the
selected baseline/candidate decision as JSON.

## What It Shows

- selected queue-analysis runs side by side
- baseline versus candidate deltas for PDR, delay, queue wait, and max queue
- a deterministic pass/fail promotion gate
- artifact hashes for the summary and peer files used as evidence

## Expected Inputs

The page reads exported queue-analysis artifacts, including:

- `*_summary_metrics.json`
- `*_queue_timeseries.csv`
- `*_packet_events.csv`
- `*_node_positions.csv`
- `*_routing_summary.csv`
- `pipeline/topology.gml`
- `pipeline/allocations_steps.csv`

Run a compatible app once from `ORCHESTRATE`, then open this page from
`ANALYSIS`.

## Development Run

```bash
uv --preview-features extra-build-dependencies run streamlit run src/agilab/apps-pages/view_scenario_cockpit/src/view_scenario_cockpit/view_scenario_cockpit.py -- --active-app src/agilab/apps/builtin/uav_relay_queue_project
```
