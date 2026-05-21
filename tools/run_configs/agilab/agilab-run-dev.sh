#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Generated from PyCharm run configuration: agilab run (dev)
cd "$REPO_ROOT"
export PYTHONUNBUFFERED="1"
export UV_NO_SYNC="1"
export IS_SOURCE_ENV="1"
export STREAMLIT_CONFIG_FILE="$REPO_ROOT/src/agilab/resources/config.toml"
export STREAMLIT_THEME_BASE="dark"
export STREAMLIT_THEME_PRIMARY_COLOR="#4A90E2"
export STREAMLIT_THEME_BACKGROUND_COLOR="#08111F"
export STREAMLIT_THEME_SECONDARY_BACKGROUND_COLOR="#102334"
export STREAMLIT_THEME_TEXT_COLOR="#F7F2E8"
# Let uv select the run-config project .venv instead of a stale activated shell.
unset VIRTUAL_ENV
uv run python $REPO_ROOT/tools/launch_agilab_streamlit.py --openai-api-key "your-key" --apps-path $REPO_ROOT/src/agilab/apps
