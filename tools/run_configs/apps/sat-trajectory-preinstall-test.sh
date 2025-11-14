#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: sat_trajectory_preinstall test
cd /Users/agi/PycharmProjects/agilab/src/agilab/apps/sat_trajectory_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/agi/PycharmProjects/agilab/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py remove_decorators --verbose --worker_path /Users/agi/wenv/sat_trajectory_worker/src/sat_trajectory_worker/sat_trajectory_worker.py
