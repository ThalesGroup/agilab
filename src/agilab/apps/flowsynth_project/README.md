# FlowSynth Project

Tools and notebooks for turning the flight/link telemetry into concrete
traffic flows. FlowSynth reads the same flight trajectories that LinkSim
consumes, builds per-route stream definitions, and emits the packets that later
feed the ILP demand builder.

## Role in the ILP pipeline

1. **Inputs**: `flowsynth_legacy/tests/traffic-gen.ipynb` expects the
   `flight_trajectory_project` exports (`dataframe/…`) plus the topology hints
   produced by LinkSim.
2. **Outputs**: running the notebook creates:
   - `flows/nodes_ip.json` and `flows/topology.json` (node labels/IPs; number of
     nodes = aircraft + satellites that LinkSim discovered);
   - `flows/traffic_df/RouteID=*/*.parquet` (per-flow samples with `FlowID`,
     `SrcID`, `DstID`, bandwidth, latency);
   - reference PCAPs under `log/flowsynth`.
3. **Consumers**: `network_sim_project` loads those artefacts to aggregate the
   24-flow demand set that ILP expects.

## Quick start

1. Make sure the flight and link simulation steps already populated
   `~/network_sim/dataset`.
2. Open the notebook:

   ```bash
   cd src/agilab/apps/flowsynth_project/flowsynth_legacy/tests
   uv run jupyter notebook traffic-gen.ipynb
   ```

3. Set the `run` variable to your export directory (for example `run = 'run1'`)
   and execute every cell. Once finished, confirm that:

   ```text
   ~/network_sim/dataset/flows/nodes_ip.json
   ~/network_sim/dataset/flows/topology.json
   ~/network_sim/dataset/flows/traffic_df/RouteID=0/*.parquet
   ```

   all exist.

Those files are all `network_sim_project` needs to build the ILP-ready
`ilp_demands.json`.
