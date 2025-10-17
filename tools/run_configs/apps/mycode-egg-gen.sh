#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: mycode_egg gen
cd /Users/example/PycharmProjects/agilab/src/agilab/apps/mycode_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/example/PycharmProjects/agilab/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py --app-path /Users/example/PycharmProjects/agilab/src/agilab/apps/mycode_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d /Users/example/wenv/mycode_worker
