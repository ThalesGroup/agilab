#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Generated from PyCharm run configuration: agilab run (dev)
cd "$REPO_ROOT"
export PYTHONUNBUFFERED="1"
export UV_NO_SYNC="1"
export IS_SOURCE_ENV="1"
uv run streamlit run $REPO_ROOT/src/agilab/AGILAB.py -- --openai-api-key "your-key" --apps-dir $REPO_ROOT/src/agilab/apps
