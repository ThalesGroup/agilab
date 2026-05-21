#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Generated from PyCharm run configuration: agilab run (enduser)
cd "$REPO_ROOT/../agi-space"
export PYTHONUNBUFFERED="1"
export UV_NO_SYNC="1"
export STREAMLIT_CONFIG_FILE="$REPO_ROOT/../agi-space/.venv/lib/python3.13/site-packages/agilab/resources/config.toml"
export STREAMLIT_THEME_BASE="dark"
export STREAMLIT_THEME_PRIMARY_COLOR="#4A90E2"
export STREAMLIT_THEME_BACKGROUND_COLOR="#08111F"
export STREAMLIT_THEME_SECONDARY_BACKGROUND_COLOR="#102334"
export STREAMLIT_THEME_TEXT_COLOR="#F7F2E8"
# Let uv select the run-config project .venv instead of a stale activated shell.
unset VIRTUAL_ENV
uv run streamlit run .venv/lib/python3.13/site-packages/agilab/main_page.py -- --openai-api-key "your-key"
