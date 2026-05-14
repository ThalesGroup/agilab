# UAV Relay Queue Project

`uav_queue_project` is the AGILAB install id for this built-in lightweight UAV
relay queue example.

It is intentionally small and Python-native. The current worker uses a
UavNetSim-inspired SimPy model so the AGILAB workflow is immediately usable
without introducing a heavier external simulator toolchain.

Origin note:

- this built-in example is conceptually inspired by the SimPy buffer-based
  queueing pattern described in
  [`UavNetSim`](https://github.com/Zihao-Felix-Zhou/UavNetSim)
  (MIT-licensed)
- it does not vendor or claim to adapt UavNetSim source code directly

What it demonstrates:

- a seeded UAV scenario file becomes a reproducible AGILAB project
- routing policy changes are captured as exported queue and packet artifacts
- queue buildup, drops, and route usage are visible directly in `ANALYSIS`
- baseline/candidate deltas can be exported from `view_scenario_cockpit` as a
  hashed scenario evidence bundle
- the same run also exports `pipeline/topology.gml`, `pipeline/allocations_steps.csv`,
  `_trajectory_summary.json`, and per-node trajectory CSVs for the generic
  `view_maps_network` page
- the artifact schema is stable enough to swap the internal simulator for a real
  UavNetSim adapter later

Default flow:

1. Select `uav_queue_project` in `PROJECT`.
2. Review paths and routing parameters in the app args form.
3. Run the app from `ORCHESTRATE`.
4. Open `view_scenario_cockpit` from `ANALYSIS` to compare baseline/candidate
   runs and export a reviewable evidence bundle.
5. Open `view_queue_resilience` from `ANALYSIS` for run-level queue details.
6. Open `view_maps_network` from `ANALYSIS` to reuse the same run as a generic
   topology/trajectory/allocation map.
7. Re-run with `routing_policy = "queue_aware"` to compare against the default
   queue hotspot created by `shortest_path`.

The seeded scenario is not meant to be a full UAV research benchmark. It is a
compact queueing demo shaped to make the AGILAB value obvious: configure,
reproduce, distribute, and analyze.
