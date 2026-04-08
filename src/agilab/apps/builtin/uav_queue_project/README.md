# UAV Queue Project

`uav_queue_project` is a built-in AGILAB example for lightweight UAV routing and
queueing experiments.

It is intentionally small and Python-native. The current worker uses a
UavNetSim-inspired SimPy model so the AGILAB workflow is immediately usable
without introducing a heavier external simulator toolchain.

What it demonstrates:

- a seeded UAV scenario file becomes a reproducible AGILAB project
- routing policy changes are captured as exported queue and packet artifacts
- queue buildup, drops, and route usage are visible directly in `ANALYSIS`
- the same run also exports `pipeline/topology.gml`, `pipeline/allocations_steps.csv`,
  `_trajectory_summary.json`, and per-node trajectory CSVs for the generic
  `view_maps_network` page
- the artifact schema is stable enough to swap the internal simulator for a real
  UavNetSim adapter later

Default flow:

1. Select `uav_queue_project` in `PROJECT`.
2. Review paths and routing parameters in the app args form.
3. Run the app from `ORCHESTRATE`.
4. Open `view_uav_queue_analysis` from `ANALYSIS`.
5. Open `view_maps_network` from `ANALYSIS` to reuse the same run as a generic
   topology/trajectory/allocation map.
6. Re-run with `routing_policy = "queue_aware"` to compare against the default
   queue hotspot created by `shortest_path`.

The seeded scenario is not meant to be a full UAV research benchmark. It is a
compact queueing demo shaped to make the AGILAB value obvious: configure,
reproduce, distribute, and analyze.
