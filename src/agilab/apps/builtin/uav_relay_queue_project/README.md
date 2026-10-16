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
3. Run `Deploy scheduler & workers`, then `RUN`.
4. Open `ANALYSIS` and inspect relay, scenario, and network views.

## Expected Inputs

The app ships a small public relay scenario with one UAV source, one ground
sink, and two relay choices. No external simulator is required.

## Expected Outputs

Each run exports queue time series, packet events, relay routing summary, node
positions, `pipeline/topology.gml`, `pipeline/allocations_steps.csv`, trajectory
CSVs, and reducer summaries.

## Exact packet handoff from the queue

The authored queue-to-relay DAG sets `use_upstream_delivery_trace=true`.
Exact trace mode requires `nfile=1`, so one upstream cohort feeds one relay
scenario. Independent relay runs retain multi-scenario support.
AGILAB binds `upstream_queue_metrics` to the original producer artifact, including
its path, size and SHA-256 digest. The relay worker reads and verifies those bytes
itself. Missing, changed, malformed or oversized inputs fail closed.
Every participating worker must be able to read the original producer artifact
path; distributed use requires shared storage with that same path visibility.

The worker schedules each delivered source packet at its original, unrounded
timestamp in simulation seconds, retaining its upstream identity. It does not
draw new source-arrival times. Empty traces generate zero source packets.
Late deliveries extend the relay's source-arrival horizon; the normal relay
drain interval follows the last arrival. Background generation retains its
configured horizon.

The relay summary reports `source_arrival_mode=upstream_delivery_trace` and an
`upstream_queue_receipt` containing the verified input digest and the actual
scheduled packet identities and timestamps. A child-orchestrator read alone
does not establish worker consumption.

For an independent reference, run the relay without the handoff flag or context.
This preserves its original Poisson source, parameterized in packets per second.
Keep the scenario, routing policy, service capacities, background-rate parameters
and random seed explicit when comparing runs. A shared seed does not ensure
identical background realizations because source scheduling changes random-number
consumption. Packet counts and configured source rates are not measured receiver
throughput; the trace includes the upstream drain interval.

## Change One Thing

After the default run works, adjust one relay capacity or routing policy. Delay,
drops, or relay choice should change while the topology artifacts remain
readable by `view_maps_network`.

## Example Quality Plan

- Review artifact: Review relay choice, congestion, delay, and drop metrics together before comparing policies.
- Practice change: Change one relay capacity or packet rate and confirm the selected relay and queue metrics move together.
- Quality check: A mature run makes policy tradeoffs visible through artifacts instead of only through final route labels.

## Troubleshooting

If relay views show no data, confirm `RUN` completed and exported queue
analysis artifacts. If a copied scenario gives impossible routes, check node ids
and relay names before changing the worker.

## Scope

This is a public, lightweight relay queueing demo. It does not implement a full
external UAV network simulator, detailed radio stack, or production routing
control plane.
