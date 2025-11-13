#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: flight_trajectory test worker
cd /Users/agi/PycharmProjects/agilab/src/agilab/apps/flight_trajectory_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/agi/PycharmProjects/agilab/src/agilab/apps/flight_trajectory_project/test/_test_flight_trajectory_worker.py
