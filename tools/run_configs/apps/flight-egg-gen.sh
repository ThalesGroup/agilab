#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: flight_egg gen
cd /Users/example/PycharmProjects/agilab/src/agilab/apps/flight_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run agi_node.agi_dispatcher.build --app-path /Users/example/PycharmProjects/agilab/src/agilab/apps/flight_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d /Users/example/wenv/flight_worker
