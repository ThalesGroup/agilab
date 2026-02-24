#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Generated from PyCharm run configuration: apps-pages launcher
cd "$REPO_ROOT"
export PYTHONUNBUFFERED="1"
export UV_NO_SYNC="1"
uv run python $REPO_ROOT/tools/apps_pages_launcher.py --active-app $REPO_ROOT/src/agilab/apps/builtin/flight_project
