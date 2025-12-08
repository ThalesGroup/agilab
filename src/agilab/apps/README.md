installation:

- Linux/MacOS:<br>
  chmod +x ./install.sh<br>
  ./install

- Python

uv run -_project ..\agilab\cluster python .\install.py <module>

Example with uv run -_project ../agilab/cluster python ./install.py flight<br>
uv run -_project ..\agilab\cluster python .\install.py agilab\cluster python .\install.py /uv
run
-_project ../agilab/cluster/manager python ./install.py flight

## Example App service/priority hints

When running `example_app_project`, you can steer synthetic demand generation by
dropping a `service.json` next to your dataset (defaults to `data_in/service.json`
or set `services_conf`). Each entry can set `name`, optional `priority`, `latency_ms`,
`bandwidth_min`/`bandwidth_max`, and `weight` (selection bias). The generator uses
those values to fill `ilp_demands.json`, so ILP and training runs inherit your
service mix and priorities without code changes.

## Streams context (FCAS WP3.3.2.1.3)

This codebase focuses on **Stream 2 (AI decision engine)**; some **Stream 1
make-before-break** pieces are simulated (predictive path selection/contended
capacities) to decouple and accelerate AI-side development. Replace the sims
with real Stream 1 outputs when available.

## How the pieces fit together (time-stepped routing policy)

- **Trajectory generation (`example_app_project`):**
  - Exports time-aligned positions per node (flights/sats) under `example_app/dataframe/flight_simulation/*.parquet`.
  - Key columns: `time_s`, `latitude`, `longitude`, `alt_m`, etc., used to interpolate positions each timestep.
- **Topology + demands (`example_app_project`):**
  - Emits `example_app/dataframe/`: `ilp_topology.gml` (topology), `ilp_demands.json` (demands with src/dst/bw/latency/priority), `topology_summary.json`.
  - Can consume `service.json` to set per-service priority/latency/bandwidth hints.
- **Link-budget assets (`example_app` dataset):**
  - Under `example_app/dataset/`: `CloudMapIvdl.npz`, `CloudMapSat.npz` (cloud attenuation), `antenna_conf.json` (sensor configs), optional `service.json`.
- **Static allocation (`example_app_project`):**
  - Loads topology/demands from `data_in` (defaults to `example_app/dataframe`) and solves once; provides a deterministic baseline.
- **Time-stepped routing RL (`example_app_project` routing trainer):**
  - Inputs: demands (`example_app/dataframe/ilp_demands.json`), trajectories (`example_app/dataframe/flight_simulation/*.parquet`), link assets (`example_app/dataset` heatmaps + antennas).
  - Environment (TimeRoutingEnv): interpolates positions per step; computes per-demand capacities via LOS/link budget (falls back to FSPL if needed); action = per-demand allocation fractions; reward = delivered bandwidth with priority and latency penalties; predictive path selection (make-before-break) plus contention scaling to respect capacities.
  - Trainer: PPO acts over a fixed horizon; logs per-step allocations/capacities to `example_app/dataframe/trainer_routing/allocations_steps.{json,parquet}` (relative to `agi_share_path`).
- **Visualisation/verification:**
  - `view_maps_network` animates trajectories + per-step allocations.
  - `example_app_project/tools/verify_allocations.py` checks capacity/time-window violations.

### Workflow to train/evaluate

1. Run `example_app_project` to populate `example_app/dataframe/flight_simulation/*.parquet`.
2. Run `example_app_project` to produce `example_app/dataframe/ilp_topology.gml` and `ilp_demands.json` (optionally with `service.json`).
3. Ensure `example_app/dataset` contains `CloudMapIvdl.npz`, `CloudMapSat.npz`, and `antenna_conf.json`.
4. Run `example_app_project` with the routing trainer (defaults point to these locations).
5. Inspect per-step outputs in `example_app/dataframe/trainer_routing/allocations_steps.json/parquet`; view in `view_maps_network` or validate with the verifier.

### Covered on 24/11/2025

- Per-step LOS capacities (Link model when installed, FSPL fallback) with contention scaling and service/latency-aware rewards.
- Predictive (make-before-break) path selection via capacity smoothing.
- Priority/latency hints passed end-to-end from `service.json` → Example App → trainer/ILP.
- Per-step logging + visualisation (`view_maps_network`) and allocation verification tool.
- Stubs let trainer run even if `example_worker`/`example_worker` are not installed (install for full fidelity).
- Optional demand time windows: auto-assign start/end times to demands (or honor provided start/end) to simulate session lifetimes; exponential arrivals/durations supported.

### Current limitations / next work

- RL env still uses per-demand actions; no edge-level/GNN policy yet.
- Demands support start/end windows with exponential arrivals/durations; no richer arrival processes yet.
- Predictive smoothing is basic exponential; no learned forecaster/jamming model.
- ILP stepping exists for time-varying capacities, but the baseline single-shot flow remains; integrate deeper if you need full per-step MILP planning.
