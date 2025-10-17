#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: agilab run (enduser)
cd /Users/example/PycharmProjects/agilab/../agi-space
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run streamlit run .venv/lib/python3.13/site-packages/agilab/AGILAB.py -- --openai-api-key "your-key"
