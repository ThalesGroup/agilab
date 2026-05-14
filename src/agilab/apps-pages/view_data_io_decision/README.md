# Mission Decision View

Streamlit analysis page for the public Mission Decision built-in demo.

Use this page after running `mission_decision_project` from AGILAB:

1. `PROJECT` -> select `src/agilab/apps/builtin/mission_decision_project`.
2. `ORCHESTRATE` -> `INSTALL`, then `EXECUTE`.
3. `ANALYSIS` -> open `view_data_io_decision`.

The page reads the artifacts exported by `mission_decision_project` and displays:

- selected strategy
- latency, cost, and reliability deltas versus no re-plan
- generated pipeline stages
- route scoring table
- decision timeline
- input sensor stream and feature evidence
- deterministic FRED-compatible context evidence when present

Expected artifact root:

- `export/mission_decision/data_io_decision`

Expected successful result:

- initial strategy: `direct_satcom`
- adapted strategy: `relay_mesh`
- latency and cost deltas are negative versus no re-plan
- reliability delta is positive versus no re-plan
