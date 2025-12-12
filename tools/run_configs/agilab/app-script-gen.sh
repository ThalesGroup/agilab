#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Generated from PyCharm run configuration: app_script gen
export PYTHONUNBUFFERED="1"
export UV_NO_SYNC="1"
uv run python $REPO_ROOT/pycharm/gen_app_script.py $Prompt:Enter app manager name:flight$
