#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Generated from PyCharm run configuration: builtin/flight run
cd "$REPO_ROOT/src/agilab/apps/builtin/flight_project"
export PYTHONUNBUFFERED="1"
export UV_NO_SYNC="1"
uv run python $HOME/log/execute/flight/AGI_run_flight.py
