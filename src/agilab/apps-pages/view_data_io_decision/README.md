# Data IO Decision View

Streamlit analysis page for the public Data IO 2026 built-in demo.

Use this page after running `data_io_2026_project` from AGILAB:

1. `PROJECT` -> select `src/agilab/apps/builtin/data_io_2026_project`.
2. `ORCHESTRATE` -> `INSTALL`, then `EXECUTE`.
3. `ANALYSIS` -> open `view_data_io_decision`.

The page reads the artifacts exported by `data_io_2026_project` and displays:

- selected strategy
- latency, cost, and reliability deltas versus no re-plan
- generated pipeline stages
- route scoring table
- decision timeline
- input sensor stream and feature evidence
- deterministic FRED-compatible context evidence when present

Expected artifact root:

- `export/data_io_2026/data_io_decision`

Expected successful result:

- initial strategy: `direct_satcom`
- adapted strategy: `relay_mesh`
- latency and cost deltas are negative versus no re-plan
- reliability delta is positive versus no re-plan
