# agi-app-uav-relay-queue

[![PyPI version](https://img.shields.io/pypi/v/agi-app-uav-relay-queue.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-uav-relay-queue/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-uav-relay-queue.svg)](https://pypi.org/project/agi-app-uav-relay-queue/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-uav-relay-queue)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-uav-relay-queue` publishes the `uav_relay_queue_project` AGILAB app as
a self-contained PyPI payload. It demonstrates queue-aware relay selection with
analysis-ready routing artifacts.

## Purpose

Use this package to run a compact UAV relay scenario: one source, one sink, and
two relay choices with different delay and queue trade-offs. The run makes
relay choice, drops, packet delay, and queue depth visible in AGILAB.

## Installed Project

The distribution name is `agi-app-uav-relay-queue`; the AGILAB project name is
`uav_relay_queue_project`. The package exposes both `uav_relay_queue` and
`uav_relay_queue_project` through the `agilab.apps` entry point group, so
`AgiEnv(app="uav_relay_queue_project")` works without a monorepo checkout.

## Install

```bash
pip install agi-app-uav-relay-queue
```

Most users get this package through `agi-apps`, `agilab[ui]`, or
`agilab[examples]`; direct installation is useful when validating one app
package in isolation.

## Run In AGILAB

Select `uav_relay_queue_project`, open `ORCHESTRATE`, then run `INSTALL` and
`EXECUTE`. Inspect `view_relay_resilience`, `view_scenario_cockpit`, or
`view_maps_network` from `ANALYSIS`.

## Expected Inputs

The packaged project includes a small synthetic relay scenario. It does not
require a live network simulator, private telemetry, cluster, or cloud service
for the default proof.

## Expected Outputs

The run writes queue time series, packet events, relay routing summaries, node
positions, topology files, trajectory CSVs, reducer summaries, and hashed
baseline/candidate evidence bundles.

## Change One Thing

Adjust relay capacity or queue size, then rerun the app. The queue-resilience
view should show how delay, drops, and selected relay changed.

## Scope

This is a lightweight public demo. It does not implement a full external UAV
network simulator, production routing control traffic, or operational radio
modeling.
