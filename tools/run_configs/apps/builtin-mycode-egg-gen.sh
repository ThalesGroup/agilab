#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Generated from PyCharm run configuration: builtin/mycode_egg gen
cd "$REPO_ROOT/src/agilab/apps/builtin/mycode_project"
export PYTHONUNBUFFERED="1"
export UV_NO_SYNC="1"
uv run python $REPO_ROOT/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py --app-path $REPO_ROOT/src/agilab/apps/builtin/mycode_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $HOME/wenv/builtin/mycode_worker
