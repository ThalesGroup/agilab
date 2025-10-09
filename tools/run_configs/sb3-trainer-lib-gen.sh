#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: sb3_trainer_lib gen
cd /Users/jpm/wenv/sb3_trainer_worker
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run agi_node.agi_dispatcher.build --app-path /Users/jpm/wenv/sb3_trainer_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b /Users/jpm/wenv/sb3_trainer_worker
