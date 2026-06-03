# UAV Queue Project

`uav_queue_project` is the built-in lightweight UAV queueing example.

## Purpose

Use this app to see how a seeded UAV scenario becomes repeatable routing,
queue-health, topology, and trajectory evidence inside AGILAB.

## What You Learn

- How a SimPy-based queue model can be packaged as an app-owned worker.
- How routing policy changes affect queue buildup, drops, and route usage.
- How scenario artifacts feed `view_scenario_cockpit`,
  `view_queue_resilience`, and `view_maps_network`.
- How a compact artifact schema can later be swapped for a richer simulator
  adapter.

## Run In AGILAB

1. Select `uav_queue_project` in `PROJECT`.
2. Open `ORCHESTRATE`.
3. Review routing and path arguments.
4. Run `INSTALL`, then `EXECUTE`.
5. Open `ANALYSIS` and inspect scenario, queue, and network-map views.

## Expected Inputs

The default run uses a bundled scenario template. No external simulator is
required.

## Expected Outputs

The app writes queue time series, packet events, routing summaries, topology
GML, allocation steps, trajectory summaries, and per-node trajectory CSV files.

## Change One Thing

After the default run works, change only `routing_policy` from `shortest_path`
to `queue_aware`. Queue hotspots and drops should change while output schemas
stay stable.

## Troubleshooting

If analysis pages are empty, confirm the queue analysis bundle exists under the
app export path. If a custom scenario fails, validate the scenario JSON before
changing worker logic.

## Scope

This is a compact queueing demo inspired by public SimPy UAV-network patterns.
It does not vendor UavNetSim source code and is not a full radio, PHY, MAC, or
operational UAV-network benchmark.
