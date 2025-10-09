#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: sat_trajectory_egg gen
cd /Users/jpm/PycharmProjects/agilab/src/agilab/apps/sat_trajectory_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run agi_node.agi_dispatcher.build --app-path /Users/jpm/PycharmProjects/agilab/src/agilab/apps/sat_trajectory_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d /Users/jpm/wenv/sat_trajectory_worker
