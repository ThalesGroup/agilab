# UAV Relay Queue Project

`uav_relay_queue_project` is the AGILAB install id for this built-in lightweight UAV
relay queue example.

The project demonstrates a compact routing-and-queueing simulation:
- one UAV source
- one ground sink
- two relay choices with different queue and delay trade-offs
- exported telemetry that can be inspected in AGILAB analysis pages

## What it is good for

- a self-contained AGILAB demo app
- quick queue-aware routing experiments
- understanding how relay congestion changes packet delivery, delay, and queue depth

## Main outputs

Each run exports:
- queue time series
- packet events
- relay routing summary
- node positions
- `pipeline/topology.gml`
- `pipeline/allocations_steps.csv`
- trajectory CSVs for `view_maps_network`

## Typical flow

1. Select `uav_relay_queue_project` in `PROJECT`.
2. Run it from `ORCHESTRATE`.
3. Inspect queue artifacts in `view_uav_relay_queue_analysis`.
4. Inspect topology and trajectories in `view_maps_network`.
