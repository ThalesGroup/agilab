#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: mycode_egg gen
cd /Users/jpm/PycharmProjects/agilab/src/agilab/apps/mycode_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run agi_node.agi_dispatcher.build --app-path /Users/jpm/PycharmProjects/agilab/src/agilab/apps/mycode_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d /Users/jpm/wenv/mycode_worker
