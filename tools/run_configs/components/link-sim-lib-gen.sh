#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: link_sim_lib gen
cd /Users/jpm/wenv/link_sim_worker
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python agi_node.agi_dispatcher.build --app-path /Users/jpm/wenv/link_sim_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b /Users/jpm/wenv/link_sim_worker
