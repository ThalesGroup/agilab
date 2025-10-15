#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: flight_trajectory_preinstall test
cd /Users/jpm/PycharmProjects/agilab/src/agilab/apps/flight_trajectory_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/jpm/PycharmProjects/agilab/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py remove_decorators --verbose --worker_path /Users/jpm/wenv/flight_trajectory_worker/src/flight_trajectory_worker/flight_trajectory_worker.py
