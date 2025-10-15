#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: flight_trajectory_postinstall test
cd /Users/jpm/PycharmProjects/agilab/src/agilab/apps/flight_trajectory_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/jpm/PycharmProjects/agilab/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py /Users/jpm/PycharmProjects/agilab/src/agilab/apps/flight_trajectory_project /Users/jpm/data/flight_trajectory
