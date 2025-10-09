#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: flight_trajectory_postinstall test
cd /Users/jpm/PycharmProjects/agilab/src/agilab/apps/flight_trajectory_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/jpm/wenv/flight_trajectory_worker/src/flight_trajectory_worker/post_install.py /Users/jpm/PycharmProjects/agilab/src/agilab/apps/flight_trajectory_project 1 /Users/jpm/data/flight_trajectory
