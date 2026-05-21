# agi-app-uav-queue-project

[![PyPI version](https://img.shields.io/pypi/v/agi-app-uav-queue-project.svg?cacheSeconds=300)](https://pypi.org/project/agi-app-uav-queue-project/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-app-uav-queue-project.svg)](https://pypi.org/project/agi-app-uav-queue-project/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-app-uav-queue-project)](https://opensource.org/licenses/BSD-3-Clause)

`agi-app-uav-queue-project` packages the `uav_queue_project` AGILAB app. It is
a lightweight UAV queue simulation example with scenario evidence and
network-map artifacts.

## Purpose

Use this package to run a deterministic queueing scenario and inspect how
routing policy changes affect drops, delay, queue buildup, and trajectory
artifacts.

## Installed Project

The distribution name is `agi-app-uav-queue-project`; the AGILAB project name is
`uav_queue_project`. The package exposes both `uav_queue` and
`uav_queue_project` through the `agilab.apps` entry point group, so
`AgiEnv(app="uav_queue_project")` resolves the project without a monorepo
checkout.

## Install

```bash
pip install agi-app-uav-queue-project
```

This package is not pulled by the `agi-apps` umbrella until it is promoted for a
release. Install it directly when validating the UAV queue app package from an
index or a locally built wheel.

## Run In AGILAB

Select `uav_queue_project`, open `ORCHESTRATE`, then run `INSTALL` and
`EXECUTE`. Open the scenario cockpit, queue-resilience view, or network-map view
from `ANALYSIS` to inspect the produced artifacts.

## Expected Inputs

The default run uses a bundled synthetic scenario. It does not require a live
simulator, private telemetry, cloud account, or external network service.

## Expected Outputs

The app writes queue summaries, packet events, topology files, allocation-step
CSVs, trajectory summaries, and hashed scenario evidence bundles.

## Change One Thing

Switch the routing policy from shortest-path behavior to queue-aware behavior,
then rerun the app. The evidence bundle should show whether queue depth,
delivery ratio, or delay changed.

## Scope

This is a compact simulation-shaped example. It does not claim radio/PHY/MAC
fidelity, operational routing control, or a full UAV-network research benchmark.
