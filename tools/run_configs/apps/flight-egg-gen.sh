#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: flight_egg gen
cd /Users/agi/PycharmProjects/agilab/src/agilab/apps/flight_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/agi/PycharmProjects/agilab/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py --app-path /Users/agi/PycharmProjects/agilab/src/agilab/apps/flight_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d /Users/agi/wenv/flight_worker
