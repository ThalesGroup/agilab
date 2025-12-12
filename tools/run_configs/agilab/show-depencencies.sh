#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Generated from PyCharm run configuration: show depencencies
cd "$REPO_ROOT"
export PYTHONUNBUFFERED="1 PYDEVD_USE_FRAME_EVAL=NO"
export UV_NO_SYNC="1"
uv run python $REPO_ROOT/tools/show_dependencies.py --repo pypi
