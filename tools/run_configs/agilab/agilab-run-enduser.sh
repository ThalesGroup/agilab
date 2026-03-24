#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Generated from PyCharm run configuration: agilab run (enduser)
cd "$REPO_ROOT/../agi-space"
export PYTHONUNBUFFERED="1"
export UV_NO_SYNC="1"
export OPENAI_API_KEY="your-key"
uv run streamlit run .venv/lib/python3.13/site-packages/agilab/About_agilab.py
