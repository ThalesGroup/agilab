#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: sat_trajectory_postinstall test
cd /Users/jpm/PycharmProjects/agilab/src/agilab/apps/sat_trajectory_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/jpm/wenv/sat_trajectory_worker/src/sat_trajectory_worker/post_install.py /Users/jpm/PycharmProjects/agilab/src/agilab/apps/sat_trajectory_project 1 /Users/jpm/data/sat_trajectory
