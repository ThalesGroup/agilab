#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: sat_trajectory_postinstall test
cd /Users/agi/PycharmProjects/agilab/src/agilab/apps/sat_trajectory_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/agi/PycharmProjects/agilab/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py /Users/agi/PycharmProjects/agilab/src/agilab/apps/sat_trajectory_project /Users/agi/data/sat_trajectory
