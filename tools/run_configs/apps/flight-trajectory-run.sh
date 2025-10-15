#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: flight_trajectory run
cd /Users/jpm/PycharmProjects/agilab/src/agilab/apps/flight_trajectory_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/jpm/PycharmProjects/agilab/src/agilab/examples/flight_trajectory/AGI_run_flight_trajectory.py
