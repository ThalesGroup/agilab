#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: link_sim_egg gen
cd /Users/jpm/PycharmProjects/agilab/src/agilab/apps/link_sim_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/jpm/PycharmProjects/agilab/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py --app-path /Users/jpm/PycharmProjects/agilab/src/agilab/apps/link_sim_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d /Users/jpm/wenv/link_sim_worker
