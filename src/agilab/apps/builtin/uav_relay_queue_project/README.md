# UAV Relay Queue Project

`uav_relay_queue_project` is the AGILAB install id for this built-in lightweight UAV
relay queue example.

The project demonstrates a compact routing-and-queueing simulation:
- one UAV source
- one ground sink
- two relay choices with different queue and delay trade-offs
- exported telemetry that can be inspected in AGILAB analysis pages

Origin note:

- this built-in example is conceptually inspired by the SimPy buffer-based
  queueing pattern described in
  [`UavNetSim`](https://github.com/Zihao-Felix-Zhou/UavNetSim)
  (MIT-licensed)
- it does not vendor or claim to adapt UavNetSim source code directly

## What it is good for

- a self-contained AGILAB demo app
- quick queue-aware routing experiments
- understanding how relay congestion changes packet delivery, delay, and queue depth

## What is not implemented in the public version

This public built-in example is intentionally lightweight. It does **not** implement:
- a full external UAV network simulator or emulator backend
- detailed radio, PHY, or MAC behavior
- large topology families or operational-scale routing stacks
- production-grade routing control traffic, interference, or energy models
- a complete research benchmark for UAV networking

The goal is to keep the public example easy to run while still making queue buildup,
relay choice, delay, and drops visible inside AGILAB.

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
3. Inspect scenario artifacts in `view_scenario_cockpit`.
4. Inspect relay resilience in `view_relay_resilience`.
5. Inspect topology and trajectories in `view_maps_network`.

## What this teases in AGILAB

The same framework can support richer network studies than this public demo shows.
With dedicated apps and pages, AGILAB can be used to:
- run larger scenario sweeps through `ORCHESTRATE` and `WORKFLOW`
- attach custom analysis pages to domain-specific artifacts
- compare routing variants across repeatable experiment runs
- distribute experiments across workers instead of keeping everything local
- evolve a lightweight demo into a more advanced simulator-backed workflow
