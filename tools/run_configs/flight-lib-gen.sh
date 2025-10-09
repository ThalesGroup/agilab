#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: flight_lib gen
cd /Users/example/wenv/flight_worker
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run agi_node.agi_dispatcher.build --app-path /Users/example/wenv/flight_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b /Users/example/wenv/flight_worker
