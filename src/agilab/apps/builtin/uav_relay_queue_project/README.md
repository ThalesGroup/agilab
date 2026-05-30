# UAV Relay Queue Project

`uav_relay_queue_project` is the built-in UAV relay queueing example.

## Purpose

Use this app to inspect how relay choice, congestion, packet delay, and drops
change when a UAV source can route through different relay paths.

## What You Learn

- How a compact routing-and-queueing simulation becomes AGILAB evidence.
- How relay congestion is exposed through queue and packet artifacts.
- How `view_relay_resilience`, `view_scenario_cockpit`, and
  `view_maps_network` read the same run outputs.
- How a lightweight demo can evolve into a simulator-backed workflow without
  changing the evidence contract.

## Run In AGILAB

1. Select `uav_relay_queue_project` in `PROJECT`.
2. Open `ORCHESTRATE`.
3. Run `INSTALL`, then `EXECUTE`.
4. Open `ANALYSIS` and inspect relay, scenario, and network views.

## Expected Inputs

The app ships a small public relay scenario with one UAV source, one ground
sink, and two relay choices. No external simulator is required.

## Expected Outputs

Each run exports queue time series, packet events, relay routing summary, node
positions, `pipeline/topology.gml`, `pipeline/allocations_steps.csv`, trajectory
CSVs, and reducer summaries.

## Change One Thing

After the default run works, adjust one relay capacity or routing policy. Delay,
drops, or relay choice should change while the topology artifacts remain
readable by `view_maps_network`.

## Troubleshooting

If relay views show no data, confirm `EXECUTE` completed and exported queue
analysis artifacts. If a copied scenario gives impossible routes, check node ids
and relay names before changing the worker.

## Scope

This is a public, lightweight relay queueing demo. It does not implement a full
external UAV network simulator, detailed radio stack, or production routing
control plane.
