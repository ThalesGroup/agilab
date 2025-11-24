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

## NetworkSim service/priority hints

When running `network_sim_project`, you can steer synthetic demand generation by
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

- **Trajectory generation (`flight_trajectory_project`):**
  - Exports time-aligned positions per node (flights/sats) under `flight_trajectory/dataframe/flight_simulation/*.parquet`.
  - Key columns: `time_s`, `latitude`, `longitude`, `alt_m`, etc., used to interpolate positions each timestep.
- **Topology + demands (`network_sim_project`):**
  - Emits `network_sim/dataframe/`: `ilp_topology.gml` (topology), `ilp_demands.json` (demands with src/dst/bw/latency/priority), `topology_summary.json`.
  - Can consume `service.json` to set per-service priority/latency/bandwidth hints.
- **Link-budget assets (`link_sim` dataset):**
  - Under `link_sim/dataset/`: `CloudMapIvdl.npz`, `CloudMapSat.npz` (cloud attenuation), `antenna_conf.json` (sensor configs), optional `service.json`.
- **Static allocation (`ilp_project`):**
  - Loads topology/demands from `data_in` (defaults to `network_sim/dataframe`) and solves once; provides a deterministic baseline.
- **Time-stepped routing RL (`sb3_trainer_project` routing trainer):**
  - Inputs: demands (`network_sim/dataframe/ilp_demands.json`), trajectories (`flight_trajectory/dataframe/flight_simulation/*.parquet`), link assets (`link_sim/dataset` heatmaps + antennas).
  - Environment (TimeRoutingEnv): interpolates positions per step; computes per-demand capacities via LOS/link budget (falls back to FSPL if needed); action = per-demand allocation fractions; reward = delivered bandwidth with priority and latency penalties; predictive path selection (make-before-break) plus contention scaling to respect capacities.
  - Trainer: PPO acts over a fixed horizon; logs per-step allocations/capacities to `sb3_trainer/dataframe/trainer_routing/allocations_steps.{json,parquet}` (relative to `agi_share_dir`).
- **Visualisation/verification:**
  - `view_maps_network` animates trajectories + per-step allocations.
  - `sb3_trainer_project/tools/verify_allocations.py` checks capacity/time-window violations.

### Workflow to train/evaluate

1. Run `flight_trajectory_project` to populate `flight_trajectory/dataframe/flight_simulation/*.parquet`.
2. Run `network_sim_project` to produce `network_sim/dataframe/ilp_topology.gml` and `ilp_demands.json` (optionally with `service.json`).
3. Ensure `link_sim/dataset` contains `CloudMapIvdl.npz`, `CloudMapSat.npz`, and `antenna_conf.json`.
4. Run `sb3_trainer_project` with the routing trainer (defaults point to these locations).
5. Inspect per-step outputs in `sb3_trainer/dataframe/trainer_routing/allocations_steps.json/parquet`; view in `view_maps_network` or validate with the verifier.

### Covered on 24/11/2025

- Per-step LOS capacities (LinkSim when installed, FSPL fallback) with contention scaling and service/latency-aware rewards.
- Predictive (make-before-break) path selection via capacity smoothing.
- Priority/latency hints passed end-to-end from `service.json` → NetworkSim → trainer/ILP.
- Per-step logging + visualisation (`view_maps_network`) and allocation verification tool.
- Stubs let trainer run even if `link_sim_worker`/`ilp_worker` are not installed (install for full fidelity).
- Optional demand time windows: auto-assign start/end times to demands (or honor provided start/end) to simulate session lifetimes; exponential arrivals/durations supported.

### Current limitations / next work

- RL env still uses per-demand actions; no edge-level/GNN policy yet.
- Demands support start/end windows with exponential arrivals/durations; no richer arrival processes yet.
- Predictive smoothing is basic exponential; no learned forecaster/jamming model.
- ILP stepping exists for time-varying capacities, but the baseline single-shot flow remains; integrate deeper if you need full per-step MILP planning.
