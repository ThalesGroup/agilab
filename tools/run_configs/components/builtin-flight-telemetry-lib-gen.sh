#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Generated from PyCharm run configuration: builtin/flight_telemetry_lib gen
cd "$HOME/wenv/flight_worker"
export PYTHONUNBUFFERED="1"
export UV_NO_SYNC="1"
# Let uv select the run-config project .venv instead of a stale activated shell.
unset VIRTUAL_ENV
uv run python -m agi_node.agi_dispatcher.build --app-path $HOME/wenv/flight_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $HOME/wenv/flight_worker
