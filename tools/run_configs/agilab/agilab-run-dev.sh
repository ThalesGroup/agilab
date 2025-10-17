#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: agilab run (dev)
cd /Users/example/PycharmProjects/agilab
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run streamlit run /Users/example/PycharmProjects/agilab/src/agilab/AGILAB.py -- --openai-api-key "your-key" --apps-dir /Users/example/PycharmProjects/agilab/src/agilab/apps
